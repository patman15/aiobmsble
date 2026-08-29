# PaceEX BMS

Each pack provides a separate Bluetooth device.

## Main Data
The system level query(0x0a00) is answered only by the pack acting as main pack in a parallel stack, all others reply with an all-zero payload.
Queried using the command `9a 00 00 0a 00 00 00 00 19 51 9d`
| Value | Offset | Length | Conversion |
|-------|--------|--------|------------|
| pack_count | 0 | 1 | - |
| current | 1 | 4 | /100 |
| voltage | 5 | 4 | /100 |
| cycle_charge | 9 | 4 | /100 |
| design_capacity | 13 | 4 | /100 |
| battery_level | 21 | 1 | - |
| battery_health | 22 | 1 | - |
| cycles | 23 | 4 | - |

## Pack Data
pack level query, answered by every pack
Queried using the command `9a 00 00 0a 01 00 00 02 01 01 1b 9c 9d`
| Value            | Offset | Length | Conversion |
|------------------|--------|--------|------------|
| current          | 1      | 2      | /100       |
| voltage          | 3      | 2      | /100       |
| cycle_charge     | 5      | 2      | /100       |
| design_capacity  | 9      | 2      | /100       |
| battery_level    | 11     | 1      | -          |
| battery_health   | 12     | 1      | -          |
| cycles           | 13     | 2      | -          |


