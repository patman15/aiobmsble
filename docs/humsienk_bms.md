# Humsienk BMS

Protocol details confirmed via live device testing.

## Frame Format

```
[0xAA, CMD, LEN, DATA..., CHK_LO, CHK_HI]
```

Checksum: 16-bit LE sum of bytes from CMD through end of DATA.

## Read Commands

| Cmd    | Description |
|--------|-------------|
| `0x00` | Handshake/init |
| `0x11` | Device model (ASCII string) |
| `0x20` | Operating status (FETs, alarms, runtime, balance, disconnect) |
| `0x21` | Battery info (voltage, current, SOC, SOH, capacity, cycles, temps) |
| `0x22` | Cell voltages (up to 24 cells, 2 bytes each, millivolts LE) |
| `0x23` | Current info, redundant to 0x21 |
| `0x40` | Battery chemistry type — single byte at data offset 13 indicating pack composition (e.g. 0=NMC/ternary, 1=LiFePO4). Could be exposed via BMSInfo once a "chemistry" field exists in the schema (see [#136](https://github.com/patman15/aiobmsble/issues/136)) |
| `0x58` | Configuration (protection thresholds, capacity, cell count) |
| `0xF5` | Firmware/hardware version (ASCII string) |

## Write Commands (not implemented)

| Cmd    | Description |
|--------|-------------|
| `0x50` | Charge FET control (data: `[0x00]`=off, `[0x01]`=on) |
| `0x51` | Discharge FET control (data: `[0x00]`=off, `[0x01]`=on) |
| `0x52` | Balance control (data: `[0x00]`=off, `[0x01]`=on) |
| `0x53` | Clear error/protection status |

## 0x21 — Battery Info (26 data bytes)

| Offset | Size | Type | Field | Description |
|--------|------|------|-------|-------------|
| 0 | 4 | u32 LE | voltage | Pack voltage in mV |
| 4 | 4 | s32 LE | current | Current in mA (positive = charging) |
| 8 | 1 | u8 | SOC | State of Charge % |
| 9 | 1 | u8 | SOH | State of Health % |
| 10 | 4 | u32 LE | capacity | Remaining capacity in mAh |
| 14 | 4 | u32 LE | allCapacity | Total/design capacity in mAh |
| 18 | 2 | u16 LE | cycles | Charge cycle count |
| 20 | 1 | s8 | temp1 | Cell temperature 1 in °C |
| 21 | 1 | s8 | temp2 | Cell temperature 2 in °C |
| 22 | 1 | s8 | temp3 | Cell temperature 3 in °C |
| 23 | 1 | s8 | temp4 | Cell temperature 4 in °C |
| 24 | 1 | s8 | MOS temp | MOSFET temperature in °C |
| 25 | 1 | s8 | env temp | Environment temperature in °C |

## 0x20 — Operating Status (14–15 data bytes)

| Offset | Size | Type | Field | Description |
|--------|------|------|-------|-------------|
| 0 | 2 | u16 LE | runtime days | Device uptime days |
| 2 | 1 | u8 | runtime hours | Device uptime hours |
| 3 | 1 | u8 | runtime minutes | Device uptime minutes |
| 4 | 4 | u32 LE | operation_status | Alarm/protection/FET flags (see below) |
| 8 | 3 | u24 LE | cell_balance | Bitmap of cells being balanced |
| 11 | 3 | u24 LE | cell_disconnect | Bitmap of disconnected cells |

> **Note:** Uptime fields (bytes 0–3) are not parsed by the driver. The framework's
> `runtime` field means "time remaining until empty" (derived from `cycle_charge / current`),
> which is a different concept from device uptime.

### operation_status bit definitions

| Bit | Meaning |
|-----|---------|
| 0 | Charge overcurrent protection |
| 1 | Charge over-temperature protection |
| 2 | Charge under-temperature protection |
| 4 | Pack overvoltage protection |
| 7 | Charge FET status (1 = on) |
| 8 | Charge overcurrent warning |
| 9 | Charge over-temperature warning |
| 10 | Charge under-temperature warning |
| 12 | Pack overvoltage warning |
| 15 | Balance active (1 = yes) |
| 16 | Discharge overcurrent protection |
| 17 | Discharge over-temperature protection |
| 18 | Discharge under-temperature protection |
| 20 | Short circuit protection |
| 21 | Pack undervoltage protection |
| 23 | Discharge FET status (1 = on) |
| 24 | Discharge overcurrent warning |
| 25 | Discharge over-temperature warning |
| 26 | Discharge under-temperature warning |
| 28 | Pack undervoltage warning |
| 29 | MOS over-temperature warning |
| 30 | MOS over-temperature protection |

### cell_balance / cell_disconnect bitmaps

Each is a 24-bit bitmap where bit 0 = cell 1, bit 1 = cell 2, etc.

- **cell_balance**: a set bit means that cell is actively being balanced.
  Exposed as a scalar `balancer` bool.
- **cell_disconnect**: a set bit indicates a physically disconnected cell
  (broken wire, faulty connection). Any non-zero value triggers `problem=True`
  in the driver.

## 0x22 — Cell Voltages

Up to 24 cells, 2 bytes each (unsigned 16-bit LE, millivolts).

## 0x58 — Configuration (44 data bytes)

All fields are 2-byte unsigned LE unless noted.

| Offset | Field | Description |
|--------|-------|-------------|
| 0 | cell_count | Number of cells in series |
| 2 | rated_capacity | Rated capacity in 0.01 Ah |
| 4 | cell_ovp | Cell overvoltage protection threshold (mV) |
| 6 | cell_ovp_recovery | Cell OVP recovery voltage (mV) |
| 8 | ovp_delay | OVP trigger delay (seconds) |
| 10 | cell_uvp | Cell undervoltage protection threshold (mV) |
| 12 | cell_uvp_recovery | Cell UVP recovery voltage (mV) |
| 14 | uvp_delay | UVP trigger delay (seconds) |
| 16 | charge_ocp | Charge overcurrent protection (0.1 A) |
| 18 | charge_ocp_delay | Charge OCP delay (seconds) |
| 20 | discharge_ocp1 | Discharge overcurrent level 1 (0.1 A) |
| 22 | discharge_ocp1_delay | Discharge OCP1 delay (seconds) |
| 24 | discharge_ocp2 | Discharge overcurrent level 2 (0.1 A) |
| 26 | discharge_ocp2_delay | Discharge OCP2 delay (seconds) |
| 28 | charge_high_temp | Charge high temp threshold (deciKelvin) |
| 30 | charge_high_temp_recovery | Charge high temp recovery |
| 32 | charge_low_temp | Charge low temp threshold (deciKelvin) |
| 34 | charge_low_temp_recovery | Charge low temp recovery |
| 36 | discharge_high_temp | Discharge high temp threshold (deciKelvin) |
| 38 | discharge_high_temp_recovery | Discharge high temp recovery |
| 40 | discharge_low_temp | Discharge low temp threshold (deciKelvin) |
| 42 | discharge_low_temp_recovery | Discharge low temp recovery |

Temperature conversion: `°C = (raw - 2731) / 10`
