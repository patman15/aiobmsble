# TDT BMS

Register and protocol notes for TDT smart BMS devices supported by
`aiobmsble/bms/tdt_bms.py`. Devices identified by the plugin include Humsienk
and WattCycle packs.

The protocol does not use conventional Modbus registers. The maps below are
byte offsets in response frames. Field positions that depend on the number of
cells or temperature sensors are expressed as formulas. The core fields and
offsets are confirmed by the implementation and recorded test frames. Additional
warning and analog fields are documented from the vendor-app analysis reported
in [issue #296](https://github.com/patman15/aiobmsble/issues/296); where the
issue does not provide bit definitions, those are explicitly left unknown.

## BLE Characteristics

| Role | UUID |
|------|------|
| Service | `0xFFF0` |
| Notifications (RX) | `0xFFF1` |
| Commands (TX) | `0xFFF2` |
| Optional unlock characteristic | `0xFFFA` |

The connection setup writes ASCII `HiLink` to `0xFFFA` and reads back a status
byte when that characteristic is present. A non-`1` value is logged; a missing
characteristic is ignored.

## Frame Format

Commands and responses use this layout:

```text
[HEAD, VERSION, 0x01, 0x03, ERROR, COMMAND, LENGTH_HI, LENGTH_LO,
 DATA..., CRC_HI, CRC_LO, 0x0D]
```

| Frame offset | Size | Meaning |
|--------------|------|---------|
| 0 | 1 | Header. Commands use `0x7E` or the alternate `0x1E`; recorded responses use `0x7E`. |
| 1 | 1 | Version. Responses with `0x00` and `0x04` are accepted. |
| 2 | 1 | Constant `0x01`. |
| 3 | 1 | Constant `0x03`. |
| 4 | 1 | Error code; accepted responses have `0x00`. |
| 5 | 1 | Command/response identifier. |
| 6-7 | 2 | Data length, unsigned big-endian. |
| 8 onward | variable | Command-specific data. |
| Final 3 bytes | 2 + 1 | CRC-16/MODBUS, stored big-endian, followed by `0x0D`. |

Frame length is `11 + data_length` bytes. The CRC is calculated over all frame
bytes before the CRC and terminator. The implementation has a compatibility
exception for `0x8D` responses from devices that appear to send a truncated
CRC; on detecting it, CRC validation is disabled for subsequent `0x8D` frames
on that connection.

The read commands used by the plugin are `0x8C`, `0x8D`, and `0x92`. Replies
must match the outstanding command identifier.

## `0x8C` — Cell and Analog Data

### WattCycle Payload (Start Address 140)

Offsets are zero-based relative to `frame.getData()[0]`; the frame header is
excluded. Multi-byte values are big-endian.

Let `N = cellCount`, `T = temperatureCount`, `K = ceil(N / 8)`, and
`C = 2N + 2T + 2`. `C` is the current field’s offset. For absolute offsets in
the full frame, add 8.

| Payload offset | Length | Field | Decoding |
|---|---:|---|---|
| `0` | 1 byte | Cell count `N` | `u8`, raw count |
| `1 + 2i` | 2 bytes each | Cell voltage `i`, `i = 0..N-1` | `u16_BE / 1000` V |
| `1 + 2N` | 1 byte | Temperature count `T` | `u8` |
| `2 + 2N` | 2 bytes | MOS temperature | `(u16_BE - 2730) / 10` °C |
| `4 + 2N` | 2 bytes | PCB temperature | `(u16_BE - 2730) / 10` °C |
| `6 + 2N + 2j` | 2 bytes each | Cell temperature `j`, `j = 0..T-3` | `(u16_BE - 2730) / 10` °C; reads `T-2` values |
| `C` | 2 bytes | Current | See signed-current encoding below; result in A |
| `C + 2` | 2 bytes | Module voltage | `u16_BE / 100` V |
| `C + 4` | 2 bytes | Remaining capacity | `u16_BE / 10` Ah |
| `C + 6` | 2 bytes | Total capacity | `u16_BE / 10` Ah |
| `C + 8` | 2 bytes | Cycle count | `u16_BE`, integer |
| `C + 10` | 2 bytes | Design capacity | `u16_BE / 10` Ah |
| `C + 12` | 2 bytes | SOC | `u16_BE`, percent |
| `C + 14` | 2 bytes | SOH | `u16_BE`, percent; defaults to `0` if unavailable |
| `C + 16` | 4 bytes | Accumulated capacity | Unsigned `u32_BE / 10` Ah |
| `C + 20` | 4 bytes | Remaining time | `getInt()` without scaling, minutes |
| `C + 24` | 2 bytes | Time until sleep | `u16_BE`, minutes |
| `C + 26` | 2 bytes | Protection-record count | `u16_BE` |
| `C + 28` | 2 bytes | Emergency time | `u16_BE`, minutes |
| `C + 30` | 2 bytes | Balance current | Same signed-current decoding; result in A |
| `C + 32 + 2k` | 2 bytes each | Balance sample `k`, `k = 0…K-1` | `u16_BE / 1000` V |
| `C + 32 + 2K` | 1 byte each | Total cell count, total temperature count, cell start index, temperature start index | Four raw `u8` values |

For each 2-byte current value, the first byte contains flags: bit 7 indicates
negative, bit 6 indicates scaling by 10. The magnitude is
`((byte0 & 0x3F) << 8) | byte1`; divide it by 10 when bit 6 is set, then
negate it when bit 7 is set.

**Note:** different firmware versions seem to still use different scaling factors for `design capacity` and `cycle charge` independent of the `current` flag. The implementation therefore sticks to firmware version detection.

Fields after SOC are guarded by available-byte checks; missing optional fields
default to zero.

## `0x8D` - Warning and Status Data

Let `n` be the cell count, `t` the temperature-sensor count, and `k = n + t`.
Offsets below are relative to frame offset 8, the cell-count byte. Single-byte
fields follow the variable-length cell and temperature state arrays.

| Relative offset | Size | Field | Meaning / decoding |
|-----------------|------|-------|-------------------|
| 0 | 1 | Cell count | Number of cell-state bytes and cells. |
| 1 through `n` | `n` | Cell states | One byte per cell; individual bit meanings are not specified. |
| `n + 1` | 1 | Temperature sensor count | Number of following temperature-state bytes. |
| `n + 2` through `n + t + 1` | `t` | Temperature states | One byte per sensor; individual bit meanings are not specified. |
| `k + 2` | 1 | Charge current state | Meaning/bit definitions unknown. |
| `k + 3` | 1 | Module voltage state | Meaning/bit definitions unknown. |
| `k + 4` | 1 | Discharge current state | Meaning/bit definitions unknown. |
| `k + 5` | 1 | Battery mode | Meaning/encoding unknown. |
| `k + 6` | 1 | Status 1: protections | High byte of the `problem_code` decoded by the plugin. Individual flags are not documented. |
| `k + 7` | 1 | Status 2 | Low byte of the `problem_code`; individual flags are not documented. |
| `k + 8` | 1 | Status 3: FETs | Bit `0x02` indicates charge MOSFET enabled; bit `0x04` indicates discharge MOSFET enabled. Other bits are unknown. |
| `k + 9` | 1 | Status 4 | Meaning unknown. |
| `k + 10` | 1 | Status 5 | Meaning unknown. |
| `k + 11` | 1 | Status 6 | Meaning unknown. |
| `k + 12` | 1 | Status 7 | Meaning unknown. |
| `k + 13` | 1 | Warning 1 | Meaning/bit definitions unknown. |
| `k + 14` | 1 | Warning 2 | Meaning/bit definitions unknown. |
| `k + 15` through `k + 14 + ceil(n / 8)` | `ceil(n / 8)` | Cell balance bitmap | Bit `i` of byte `q` represents cell `8q + i + 1`; bytes form a little-endian bit mask. Set means the cell is balancing. |

The current decoder exposes `problem_code` as the two-byte big-endian value
formed by Status 1 and Status 2. It decodes the two FET flags from Status 3.
The bitmap offset and bit order are reported in issue #296; the current plugin
does not yet expose this bitmap as `balancer`.

## `0x92` - Device Information

The plugin reads three fixed-width 20-byte text fields from the response data.
Text is decoded up to its first NUL byte.

| Frame offset | Size | Field |
|--------------|------|-------|
| 8-27 | 20 | Software version |
| 28-47 | 20 | Manufacturer |
| 48-67 | 20 | Serial number |
