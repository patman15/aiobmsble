# 123SmartBMS

Protocol details based on the official UART protocol documentation (v3.3.11) and a
BLE advertisement capture of a gen3 battery.

## Device Discovery

The BMS is not directly BLE-addressable; it is accessed via a BLE UART bridge
(Nordic UART Service, e.g. the Raytac/Alice nRF52810 module, advertising string
`nRF52810 UART AT Command`).

| Attribute | Value |
|-----------|-------|
| Local name | `123\SmartBMS` (also `123BMS-BLE*` after rename) |
| Service UUID | `6e400001-b5a3-f393-e0a9-e50e24dcca9e` |
| RX (notify) | `6e400003-b5a3-f393-e0a9-e50e24dcca9e` |
| TX (write) | `6e400002-b5a3-f393-e0a9-e50e24dcca9e` |
| Manufacturer data | `0x2330: 0x060d02` (gen3 capture) |

The bridge additionally advertises Battery Service (`180f`), Tx Power (`1804`/`2a07`)
and Device Information (`180a`).

## Protocol

The BMS pushes one 58 byte status frame per second, big-endian. The last byte is
the 8-bit checksum: `frame[57] = sum(frame[:57]) & 0xFF`. There is no frame
header; the driver resynchronizes on any byte position until the checksum matches.

## Frame Format

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0 | 3 | battery voltage | Pack voltage, 5 mV/bit |
| 3 | 1+2 | charge current | ASCII sign byte (`+`/`-`/`X`) + magnitude, 125 mA/bit |
| 6 | 1+2 | discharge current | ASCII sign byte + magnitude, 125 mA/bit |
| 9 | 1+2 | total current | ASCII sign byte + magnitude, 125 mA/bit |
| 12 | 2 | V-min | Minimum cell voltage, 5 mV/bit |
| 14 | 1 | V-min cell number | 1-based cell index |
| 15 | 2 | V-max | Maximum cell voltage, 5 mV/bit |
| 17 | 1 | V-max cell number | 1-based cell index |
| 18 | 2 | T-min | Minimum cell temperature, 1 °C/bit, offset `0x0114` |
| 20 | 1 | T-min cell number | 1-based cell index |
| 21 | 2 | T-max | Maximum cell temperature, 1 °C/bit, offset `0x0114` |
| 23 | 1 | T-max cell number | 1-based cell index |
| 24 | 1 | cell number | Number of the cell whose data is transferred (rotating) |
| 25 | 1 | cell count | Total number of cells |
| 26 | 2 | cell voltage | Voltage of the cell from offset 24, 5 mV/bit |
| 28 | 2 | cell temperature | Temperature of the cell from offset 24, offset `0x0114` |
| 30 | 1 | status byte 1 | See below |
| 34 | 3 | stored energy | Energy stored in Wh |
| 40 | 1 | SoC | State of charge in % |
| 47 | 2 | key/value pair | Rotating data, see below |
| 49 | 2 | capacity | Battery capacity, 0.1 kWh/bit |
| 51 | 6 | settings | V-balance/min/max settings (not parsed) |
| 57 | 1 | checksum | `sum(frame[:57]) & 0xFF` |

### Status byte 1 (offset 30)

| Bit | Meaning |
|-----|---------|
| 0 | Charge FET allowed (chrg_mosfet) |
| 1 | Discharge FET allowed (dischrg_mosfet) |
| 2 | Communication error |
| 3–6 | Voltage/temperature exceeded (problem_code, bits 0–3) |
| 7 | SoC not calibrated |

### Rotating cell data

The specific cell information (offsets 24–29) rotates through all cells, one per
frame. The driver collects `(voltage, temperature)` per cell number and only
reports `cell_voltages` / per-cell temperatures once the complete set has been
received.

### Key/value pairs (offset 47: key, offset 48: value)

The key is stored with an offset of 25 (raw key 25 = key 0). One pair is
transmitted per frame, rotating, so the full cycle takes roughly 20 s.

| Key | Bytes | Field |
|-----|-------|-------|
| 0 | 1 | SoH in % |
| 1 | 1 | Charge efficiency |
| 2–3 | 2 | V-low setting |
| 4–5 | 2 | Nominal cell voltage, 5 mV/bit |
| 6–7 | 2 | Firmware version (nibbles) |
| 8–9 | 2 | Charge cycles |
| 10–12 | 3 | Charged energy in Wh |
| 13–15 | 3 | Discharged energy in Wh |
| 16 | 1 | Status byte 2 (see below) |
| 17–18 | 2 | V-full setting |

### Status byte 2 (key 16)

| Bit | Meaning |
|-----|---------|
| 1 | Early warning |
| 2 | T-min discharge exceeded |
| 3 | T-min charge exceeded |
| 4 | Relay charge |
| 5 | Relay load |

Bits 1–3 are ORed into `problem_code` (`0x0E` mask).

## Notes

- Temperature decode follows the official documentation: `°C = raw - 0x0114`
  (`0x0114` = 0 °C, `0x0128` = 20 °C). The Victron Venus driver uses a different
  scaling (`round(raw * 0.857 - 232)`); this still needs live validation.
- `design_capacity` is derived from the configured capacity and nominal cell
  voltage: `capacity_kWh * 1000 / (nominal_V * cell_count)`.
- `cycle_capacity` is taken from the stored energy field (Wh).
- SoC byte interpretation (plain vs. /2) still needs live validation.
