# V-TAC TBESS

This plugin supports the two-pack TBESS datastream recorded in
`BMS-6233bc_last_ANONYMIZED.txt`. The advertisement matcher uses service UUID
`0000e0ff-0000-1000-8000-00805f9b34fb`, supplied for this device. The
notification capture discovers GATT service `FFF0` and characteristic `FFF1`.
The device publishes telemetry without a command; `FFF1` is therefore used
for RX and the unused TX characteristic identifier.

## Frame format

Notifications form a byte stream. Frames begin with `EF`, contain pack address
`01` or `02`, a command, a command-specific tag at byte offsets 22–23, and
terminate with `16`. Several frames can be concatenated or split across BLE
notifications.

| Command | Bytes in capture | Tag | Use |
| --- | ---: | --- | --- |
| `73` | 112 | `00 55` | System status, pack count, and main-sample fields |
| `DB` | 124 | `00 61` | Pack details and measurements |
| `DC` | 72 | `00 2D` | Configuration/status; ignored |
| `D0` | 163 | `00 88` | Metadata; ignored |

The reverse-engineering note lists `D0` as 162 bytes; the complete captured
frames are 163 bytes, including the terminator.

The two bytes immediately before the terminator are not a recognized checksum.
The plugin checks the observed frame size, start marker, pack address, tag, and
terminator, but does not claim to verify frame integrity. The device must not
be used as a safety-control signal.

## System status frame

The first `73` frame starts each update. Its parallel-count field determines
how many `DB` pack frames are collected. System values are decoded directly
from this frame into the main `BMSSample`; pack measurements are kept only
inside `packs` and are not averaged or summed into the main sample.

Offsets are zero-based from the `EF` start marker:

| Offset | Bytes | Field | Conversion |
| ---: | ---: | --- | --- |
| 26 | 1 | Pack count | unsigned integer |
| 28–29 | 2 | System voltage | raw / 100 = V |
| 30–31 | 2 | System current | signed raw / 10 = A |
| 32–33 | 2 | Design capacity | unsigned integer, Ah |
| 38–39 | 2 | Battery level | raw / 100 = % |
| 40–41 | 2 | Battery health | raw / 100 = % |
| 82–83 | 2 | Cycle count | unsigned integer |
| 101–104 | 4 | Accumulated charge | unsigned integer, `cycle_charge` |
| 105–108 | 4 | Accumulated discharge | unsigned integer, `total_charge` |

The recorded status frame reports a design capacity of 5600 Ah and two packs.

## Detail frame fields

Offsets are zero-based from the `EF` start marker. Multi-byte fields are
big-endian. The capture and app screenshots support these mappings:

| Offset | Bytes | Field | Conversion |
| ---: | ---: | --- | --- |
| 25–26 | 2 | Pack voltage | raw / 100 = V |
| 27–28 | 2 | Pack current | signed raw / 100 = A |
| 29–30 | 2 | Pack SOC | raw / 10 = % |
| 34–65 | 32 | 16 cell voltages | unsigned mV / 1000 = V |
| 68, 70, 72, 74 | 1 each | Four cell temperatures | unsigned byte / 10 = °C |
| 76 | 1 | MOS temperature | unsigned byte / 10 = °C |
| 78 | 1 | Ambient temperature | unsigned byte / 10 = °C |
| 79–80 | 2 | Cycle count | unsigned integer |
| 81–82 | 2 | Accumulated discharge | unsigned integer, summed across packs and returned as `total_charge` |
| 83–84 | 2 | Accumulated charge | unsigned integer, returned as `cycle_charge` |
| 91–92 | 2 | SOH | raw / 10 = % |

The pack-detail values remain available in `packs`, without top-level
aggregation. The main sample's voltage, current, SOC, and capacity fields come
from the system status frame. The accumulated counters are not per-cycle
capacity measurements. For that reason, the plugin does not derive
`cycle_capacity` or `runtime` from them.

The current register interpretation is supported by the captured pack-1 value
of −6.43 A, which matches the app screenshot. The app and capture are not
perfectly time-aligned, so other instantaneous currents can differ. The exact
checksum and several unrelated status fields remain unknown and are not
exposed.

## Recorded detail frames

These complete frames are from the supplied capture. The first is pack 1 at
00:42:14.551; the second is pack 2 at 00:42:35.399.

```text
\xEF\x01\xDB\x35\x31\x34\x31\x31\x30\x39\x32\x32\x36\x30\x35\x30
\x31\x30\x30\x35\x38\x34\x00\x61\x00\x14\xAC\xFD\x7D\x02\xBB\x4E
\x46\x10\x0C\xEC\x0C\xEB\x0C\xEC\x0C\xEC\x0C\xEB\x0C\xED\x0C\xEA
\x0C\xEC\x0C\xEB\x0C\xEC\x0C\xEE\x0C\xEC\x0C\xEA\x0C\xEC\x0C\xEC
\x0C\xEB\x04\x00\xE7\x00\xE9\x00\xE7\x00\xE7\x00\xFD\x00\xF7\x00
\x1B\x18\x6F\x18\xD6\x07\x4D\x00\x00\x00\x00\x03\xE8\x6F\xF2\x6D
\x60\x0C\xEE\x0B\x0C\xEA\x07\x00\x04\x00\xE9\x02\x00\xE7\x01\x00
\x02\x00\x00\x18\xD6\x00\x00\x18\x6F\xD8\x04\x16
```

```text
\xEF\x02\xDB\x35\x31\x34\x31\x31\x30\x39\x32\x32\x36\x30\x35\x30
\x31\x30\x31\x32\x33\x32\x00\x61\x00\x14\xAC\xFC\xF4\x02\xC4\x4E
\xFD\x10\x0C\xEC\x0C\xEA\x0C\xED\x0C\xED\x0C\xEA\x0C\xEC\x0C\xEA
\x0C\xED\x0C\xEA\x0C\xEB\x0C\xEE\x0C\xEC\x0C\xEA\x0C\xEC\x0C\xED
\x0C\xEA\x04\x00\xE5\x00\xE6\x00\xE4\x00\xE2\x00\xFE\x00\xF2\x00
\x1A\x17\x91\x18\x25\x06\x13\x00\x00\x00\x00\x03\xE8\x6F\x7D\x6D
\x60\x0C\xEE\x0B\x0C\xEA\x02\x00\x04\x00\xE6\x02\x00\xE2\x04\x00
\x04\x00\x00\x18\x25\x00\x00\x17\x91\xD8\xC2\x16
```
