# Changfa / RBT BMS

Protocol notes for Changfa (Huizhou Changfa Electronic Technology) BMS devices
sold under the "RBT BMS" app, supported by `aiobmsble/bms/rbt_bms.py`. The
devices advertise as `CF_BMS_<id>`. Details were derived from a BLE capture
(btsnoop) and a vendor-app screenshot reported in
[issue #338](https://github.com/patman15/aiobmsble/issues/338).

## BLE Characteristics

| Role | UUID |
|------|------|
| Service | `00002734-08c2-11e1-9073-0e8ac72e1001` |
| Notifications (RX) | `00002734-08c2-11e1-9073-0e8ac72e0002` |
| Commands (TX) | `00002734-08c2-11e1-9073-0e8ac72e0001` |

## Frame Format

Requests and responses share this layout:

```text
[HEAD, CMD, 0x01, REGISTER, LENGTH, DATA..., CHECKSUM]
```

| Offset | Size | Meaning |
|--------|------|---------|
| 0 | 2 | Header. Requests use `3a 9d`, responses use `3b 9d`. |
| 2 | 1 | Command. Read requests use `21`. |
| 3 | 1 | Always `01` in captured traffic. |
| 4 | 1 | Register block (`41` = telemetry). |
| 5 | 1 | Length of the data field. |
| 6 | n | Data. |
| 6+n | 1 | Checksum: `(sum(frame[:-1]) + 0x20) & 0xFF`. |

The telemetry request is `3a 9d 21 01 41 00 5a`. The device answers with a
73-byte frame in register `41` (66 data bytes). The checksum was verified on
all captured frames.

## Telemetry Register `0x41`

Offsets are within the data field (frame offset minus 6). All multi-byte values
are little-endian.

| Data offset | Size | Field | Scaling | Verified |
|-------------|------|-------|---------|----------|
| 1 | 1 | `battery_level` (SoC) | 1 % | Yes (19 %) |
| 4 | 2 | `cycles` | 1 | Yes (2) |
| 6 | 2 | `design_capacity` | /100 Ah | Yes (30 Ah) |
| 12 | 2 | `voltage` | /100 V | Yes (12.85 V) |
| 14 | 2 | `current` (signed magnitude, sent as discharge) | /100 A | Partly (-1.1 A) |
| 32, 34, 36, 38 | 2 each | Temperature: Chip, T1, T2, T3 | (raw - 2731) / 10 °C | Mostly (6.3, 5.6–5.7, 5.6, 23.7 °C) |
| 40–47 | 2 each | Cell voltages (4 cells) | /1000 V | Partly, not decoded |

The temperature offsets match the app's Chip, T1, T2 and T3 readings in that
order. Offset 34 reads 5.6 °C in some frames and 5.7 °C in others, so it is
not fully consistent with the single screenshot. The sign of `current` is not
confirmed by a charging capture: the captured current magnitude is always
positive in the trace (103–130, i.e. 1.03–1.30 A) while the app shows -1.1 A
while discharging, and the plugin reports it as negative. Offset 30 toggles
between `0x0301` and `0x0302` but no charging sample confirms its meaning. Cell voltages are present in the frame but not decoded, as
the mapping of the cell offsets is not yet confirmed.

## Open Points

- Current direction while charging (needs a charging capture).
- Cell voltage offsets and the meaning of the remaining status bytes.
