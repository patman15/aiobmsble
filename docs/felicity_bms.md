# Felicity Solar BMS Documentation

## Overview

Felicity Solar LiFePo4 batteries (ESS units advertise as `F10…`, FLB rack batteries as
`F07…`) expose their BMS data over BLE as JSON text. Multiple packs can be connected in
parallel; each pack is a separate BLE device, but every pack also knows the aggregated
values of the whole parallel stack (reported by the master over the inter-pack bus).

## Device Identification

- **Local Name**: `F07*` or `F10*`
- **Service UUID**: `6e6f736a-4643-4d44-8fa9-0fafd005e455`
- **Notification Characteristic**: `49535458-8341-43f4-a9d4-ec0e34729bb3` (notify)
- **Write Characteristic**: `49535258-184d-4bd9-bc61-20c647249616` (write)

## Protocol

Commands are ASCII strings prefixed with `wifilocalMonitor:`, e.g.
`wifilocalMonitor:get dev real infor` for real-time data. <!-- codespell:ignore infor -->
The response is a JSON
document (`{` … `}`) streamed in chunks over the notification characteristic.

Example real-time response (16S FLB48314TG1-H pack, 3 packs in parallel, during charge):

```json
{"CommVer": 1, "wifiSN": "F075704831426030796", "modID": 3, "date": "20260813120925",
 "DevSN": "075704831426030796", "Type": 112, "SubType": 7353,
 "Estate": 9152, "Bfault": 0, "Bwarn": 0, "Bstate": 9152,
 "Batt": [[54100], [1977], [null]],
 "Batsoc": [[7860, 943, 1050000]],
 "BattList": [[54070, 65535], [647, -1]],
 "BatsocList": [[7800, 1000, 350000]],
 "BatcelList": [[3378, 3380, 3379, 3380, 3379, 3380, 3380, 3382, 3389, 3381, 3380, 3381, 3380, 3380, 3379, 3380],
                [65535, 65535, 65535, 65535, 65535, 65535, 65535, 65535, 65535, 65535, 65535, 65535, 65535, 65535, 65535, 65535]],
 "BMaxMin": [[3389, 3378], [8, 0]],
 "BtemList": [[340, 340, 340, 340, 32767, 32767, 32767, 32767]]}
```

## Stack (fleet) vs. individual pack keys

**Important**: the plain keys report aggregates of the *whole parallel stack*, while the
`…List` keys report the values of the *individual pack* being queried:

| Stack aggregate | Per-pack     | Content |
|-----------------|--------------|---------|
| `Batt`          | `BattList`   | `[[voltage mV], [current dA]]` |
| `Batsoc`        | `BatsocList` | `[[SoC ‱, SoH ‱, capacity mAh]]` |
| `BTemp`         | `BtemList`   | temperatures (d°C) |
| —               | `BatcelList` | cell voltages (mV) |

This was verified on a 3-pack stack: `Batt` current equals the sum of the three packs'
`BattList` currents (e.g. 197.7 A vs. 71.8 + 62.7 + 64.4 A) and is identical on all three
devices at any instant, and `Batsoc` capacity equals 3 × the `BatsocList` capacity
(1 050 000 mAh vs. 350 000 mAh). Since every BLE device represents a single pack, the
plugin reads voltage, current, SoC, cells, and temperatures from the `…List` keys.

## Scaling and filler values

- voltage: mV (`/1000`), current: dA (`/10`, positive = charging), SoC: ‱ (`/100`),
  cell voltages: mV (`/1000`), temperatures: d°C (`/10`)
- Unused slots are filled with `65535` (`0xFFFF`), `32767` (`0x7FFF`), `-1`, or `null`;
  the second inner array of `BattList`/`BatcelList`/`Templist` belongs to a second
  module slot and is all filler on single-module packs.
