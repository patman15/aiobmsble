# BASEN GREEN 0x84 Reply: Status Bytes (Payload Offset 8–15)

## Field Layout

| Payload Bytes | Field | Width | Notes |
|---|---|---|---|
| 8–9 | Voltage status | 16-bit | Bit 15 (byte 8, bit 7) = sleep, not a fault |
| 10–11 | Current status | 16-bit | Bits 0/1 of byte 11 = charge/discharge FET state |
| 12–13 | Temperature status | 16-bit | Low byte = protections, high byte = warnings |
| 14–15 | Alarms | 16-bit | Hardware/fault flags |

Bit numbering is per 16-bit field, with bit 0 = LSB of the low byte.

## Voltage Status (bytes 8–9)

| Bit | Meaning | Type |
|---|---|---|
| 0 | Cell OVP | Protection |
| 1 | Cell UVP | Protection |
| 2 | Pack OVP | Protection |
| 3 | Pack UVP | Protection |
| 4 | Cell high warning | Warning |
| 5 | Cell low warning | Warning |
| 6 | Pack high warning | Warning |
| 7 | Pack low warning | Warning |
| 8 | Cell diff warning | Warning |
| 15 | Sleep | **Status (not a fault)** |

## Current Status (bytes 10–11)

| Bit | Meaning | Type |
|---|---|---|
| 0 | Charge FET on | **Status (not a fault)** |
| 1 | Discharge FET on | **Status (not a fault)** |
| 2 | Charge OCP | Protection |
| 3 | Short circuit | Protection |
| 4 | Discharge OCP1 | Protection |
| 5 | Discharge OCP2 | Protection |
| 6 | Charge current warning | Warning |
| 7 | Discharge current warning | Warning |
| 14 | Anti-theft lock (gyro) | Protection/lock |

## Temperature Status (bytes 12–13)

| Bits | Category | Order (same for both groups) |
|---|---|---|
| 0–7 | Protections | Charge high (cell), charge low (cell), discharge high (cell), discharge low (cell), ambient high, ambient low, MOSFET high, MOSFET low |
| 8–15 | Warnings | Same order as protections |

## Alarms (bytes 14–15)

| Bit | Meaning |
|---|---|
| 0 | Cell diff |
| 1 | Charge FET damaged |
| 2 | SD card |
| 3 | SPI |
| 4 | EEPROM |
| 5 | LED |
| 6 | Buzzer |
| 7 | Low SOC |
| 8 | MOS over-temp protect |
| 9 | MOS over-temp warn |
| 10 | Current limiter board |
| 11 | Sampling |
| 12 | Cell fault |
| 13 | NTC fault |
| 14 | Charge MOS fault |
| 15 | Discharge MOS fault |

## Interpreting the 8-byte value as one number

| Raw value | Meaning |
|---|---|
| `0x200000000` | Discharge FET enabled only (normal) |
| `0x100000000` | Charge FET enabled (charging) |
| `0x300000000` | Charge and discharge FETs both enabled |
