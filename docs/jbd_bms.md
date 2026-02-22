# JBD BMS – Chins Extended Fields

## Overview

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

## Extended Field Layout

The extended fields begin at offset `27 + (temp_sensors * 2)` in the
response frame:

| Offset (from ext_start) | Size | Field | Notes |
|---|---|---|---|
| +0 | 1 | humidity | Not used by aiobmsble |
| +1 | 2 | alter | Big-endian, purpose unclear |
| +3 | 2 | learnCapacity | Big-endian, units: 10 mAh |
| +5 | 2 | balanceCurrent | Big-endian, units: 10 mA |

The frame ends with CRC (2 bytes) + tail (`0x77`) after the extended data.

## Echo Behavior on Current Firmware

On observed Chins JBD firmware (12V 300Ah, hw_version `J-12300-241118-069`,
captured via BLE on Cerbo GX from device `A4:C1:38:33:41:24`), the extended
fields echo values from the standard fields rather than providing
independent data:

- `learnCapacity` echoes `design_capacity` (bytes 10–11)
- `balanceCurrent` echoes `cycle_charge` / remaining capacity (bytes 8–9)

This produces a spurious `balance_current` reading of ~196 A on a 300 Ah
battery if parsed without validation, because the remaining capacity
raw value (19630 = 196.30 Ah) is interpreted as current (196.30 A).

## Example Frame

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

## Safe Parsing

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
