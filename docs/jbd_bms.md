# JBD BMS

## Authentication flow

| Message| Header | Cmd | Length | Data | Checksum
|---|---|---|---|---|---|
| Cmd | ff aa | 15 | 06 | 30 30 30 30 30 30 | 3b
| ACK | ff aa | 15 | 01 | 00 | 16
| NACK | ff aa | 15 | 01 | 01 | 17

Checksum is the 8-Bit sum of `Cmd, Length, Data` fields.
Default password is "000000".


## Protection status (`problem_code`)

On basic info (`0x03`), aiobmsble maps a 16-bit little-endian field at data offset 20 to `problem_code` (`BMSDp("problem_code", 20, 2, False)`).

That word is the JBD **protection status** bitfield from the public UART/BLE protocol (same layout as Overkill Solar EEPROM register `0x10` "Current errors"). Bit = 1 means the protection is active.

| Bit | Mask | Meaning |
|---|---|---|
| 0 | `0x0001` | Cell overvoltage |
| 1 | `0x0002` | Cell undervoltage |
| 2 | `0x0004` | Pack overvoltage |
| 3 | `0x0008` | Pack undervoltage |
| 4 | `0x0010` | Charge over-temperature |
| 5 | `0x0020` | Charge under-temperature |
| 6 | `0x0040` | Discharge over-temperature |
| 7 | `0x0080` | Discharge under-temperature |
| 8 | `0x0100` | Charge overcurrent |
| 9 | `0x0200` | Discharge overcurrent |
| 10 | `0x0400` | Short circuit |
| 11 | `0x0800` | Frontend IC error |
| 12 | `0x1000` | Software lock MOS |
| 13-15 | | Reserved |

### Cell OV release hysteresis

Cell overvoltage (bit 0) is not a separate sticky latch register. Trip and clear use EEPROM thresholds `COVP` and `COVP_REL` (Overkill `0x24` / `0x25`).

With typical factory-style thresholds (e.g. `COVP=3650 mV`, `COVP_REL=3550 mV`):

- Bit 0 sets when any cell reaches the trip threshold.
- Bit 0 can remain set while any cell is still **above** `COVP_REL`, even if every cell is already **below** `COVP`.
- The bit clears only after all cells fall below the release threshold (and related delay settings elapse).

So `problem_code & 0x1` during / after top-of-charge can mean "still in the OV release band", not necessarily "still above trip" or "hard faulted". Useful when correlating `problem_code` with live cell voltages in logging or integrations. Behavior may vary with firmware and EEPROM settings.

References: JBD Smart BMS protocol (protection status note), [Overkill Solar JBD register map](https://gitlab.com/Overkill-Solar-LLC/overkill-solar-bms-tools/-/blob/master/JBD_REGISTER_MAP.md) (`0x10`, `0x24`, `0x25`).

## Chins Extended Fields

### Overview

Chins JBD batteries (matched by OUI `A4:C1:38`, `10:A5:62`, etc.) return
a longer 0x03 info response than standard JBD devices. The standard frame
has `data_len=0x1D` (29 bytes); the Chins frame has `data_len=0x22`
(34 bytes). The extra 7 bytes appear after the temperature sensor data.

The standard JBD parsing ignores these bytes — all core fields (voltage,
current, SOC, temperature, cell voltages, MOSFET states, problem codes)
parse correctly from the standard offsets. For simplicity and
maintainability, the decision was made not to parse the extended fields
at this time. This document preserves the protocol details and a
reference implementation in case they need to be added in the future.

### Extended Field Layout

The extended fields begin at offset `27 + (temp_sensors * 2)` in the
response frame:

| Offset (from ext_start) | Size | Field | Notes |
|---|---|---|---|
| +0 | 1 | humidity | Not used by aiobmsble |
| +1 | 2 | alter | Big-endian, purpose unclear |
| +3 | 2 | learnCapacity | Big-endian, units: 10 mAh |
| +5 | 2 | balanceCurrent | Big-endian, units: 10 mA |

The frame ends with CRC (2 bytes) + tail (`0x77`) after the extended data.

### Echo Behavior on Current Firmware

On observed Chins JBD firmware (12V 300Ah, hw_version `J-12300-241118-069`,
captured via BLE on Cerbo GX from device `A4:C1:38:33:41:24`), the extended
fields echo values from the standard fields rather than providing
independent data:

- `learnCapacity` echoes `design_capacity` (bytes 10–11)
- `balanceCurrent` echoes `cycle_charge` / remaining capacity (bytes 8–9)

This produces a spurious `balance_current` reading of ~196 A on a 300 Ah
battery if parsed without validation, because the remaining capacity
raw value (19630 = 196.30 Ah) is interpreted as current (196.30 A).

### Example Frame

Chins 0x03 response (1 temp sensor, `data_len=0x22`):

```
dd 03 00 22                         # header: resp, cmd, status, data_len=34
05 32                               # voltage: 13.30 V
00 00                               # current: 0.00 A
4c ae                               # cycle_charge: 196.30 Ah (remaining)
75 30                               # design_capacity: 300 Ah
00 1b                               # cycles: 27
31 2c                               # production date
00 00                               # balance status low
00 00                               # balance status high
00 00                               # problem_code: 0
29                                  # misc
41                                  # battery_level: 65%
03                                  # MOSFET status
04                                  # cell count: 4
01                                  # temp_sensors: 1
0b 3d                               # temp[0]: 14.6 °C (raw 2877 - 2731)
-- extended fields start here --
00                                  # humidity: 0
00 00                               # alter: 0
75 30                               # learnCapacity: 300 Ah (echoes design_capacity)
4c ae                               # balanceCurrent: 196.30 (echoes cycle_charge)
-- end extended fields --
fb 37                               # CRC
77                                  # tail
```

### Safe Parsing

If the extended fields need to be parsed in the future (e.g., if Chins
firmware begins populating them with independent data), the echo must be
detected to avoid reporting spurious values:

```python
ext_start: int = 27 + data.get("temp_sensors", 0) * 2
if len(self._msg) >= ext_start + 7 + 3:  # +3 for CRC (2) + tail (1)
    learn_cap = int.from_bytes(self._msg[ext_start + 3 : ext_start + 5], "big")
    bal_cur = int.from_bytes(self._msg[ext_start + 5 : ext_start + 7], "big")
    design_raw = int.from_bytes(self._msg[10:12], "big")
    remain_raw = int.from_bytes(self._msg[8:10], "big")
    if learn_cap != design_raw or bal_cur != remain_raw:
        data["balance_current"] = bal_cur / 100
```

This compares `learnCapacity` against `design_capacity` and
`balanceCurrent` against `cycle_charge`. If both pairs match, the values
are treated as echoes and discarded. If either differs, `balance_current`
is reported as a real value.
