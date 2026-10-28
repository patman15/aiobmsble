# Rolls VB-series LFP battery (RD-RJ8S150A internal BMS)

> **Note:** This document, the accompanying plugin, and its tests were
> drafted with AI assistance (Kiro), based on protocol analysis of two
> real BLE packet captures (Apple PacketLogger) of the vendor's own app
> connecting to a Rolls VB24-150LFP. All register decodes described below
> were cross-checked against raw capture bytes and, where noted, against
> the vendor app's own displayed values — but the write-up itself should
> be read with that in mind, and reviewers are encouraged to verify
> claims against the referenced capture data rather than taking the
> prose at face value.

## Hardware / protocol overview

The Rolls VB-series 24 V LiFePO4 "drop-in" batteries (e.g. VB24-150LFP,
24 V nominal, 150 Ah, 8S) use an internal BMS marked `RD-RJ8S150A` on the
PCB. It advertises over BLE with a local name of `RD` followed by its own
MAC address with colons stripped (e.g. `RDAC233F000000` for MAC
`AC:23:3F:00:00:00`, the last three bytes anonymized), and only becomes
BLE-reachable once a charger or
load drawing more than roughly 1 A is connected (per Rolls' own
installation guide — the BLE radio is otherwise asleep).

The vendor app ("Rolls LFP Connect") talks to the battery over a generic
serial-over-BLE bridge: GATT service `0xFFF0`, with notify characteristic
`0xFFF1` and write characteristic `0xFFF2` — the common cheap
HM-10/JDY-08/CC41-A UART-bridge pattern. The traffic carried over that
bridge is plain **MODBUS RTU** (slave address `0xD2`, function `0x03`,
Read Holding Registers, CRC-16/MODBUS), confirmed byte-for-byte against
two live captures (Apple PacketLogger on macOS/iOS, decoded with
`tshark`) of the vendor app connecting to a real VB24-150LFP.

The vendor app reads several register ranges per update cycle. This library
reads three blocks of 16 registers each, which together cover everything it
decodes:

| Register | Contents |
|---|---|
| `0x0000`–`0x000F` | Cell voltages, mV, padded to 16 slots for packs with fewer than 16 cells (the VB24-150LFP is an 8S pack; the remaining 8 registers read as zero) |
| `0x0020`–`0x0024` | Temperatures, raw value is °C + 40, unused sensors read as zero (this battery has two sensors) |
| `0x0028` | Pack voltage, ×0.1 V |
| `0x0029` | Current (see below) |
| `0x002A` | State of charge, ×0.1 % |
| `0x0030` | Remaining charge, ×0.1 Ah |
| `0x0031`–`0x0033` | Cell count, temperature sensor count, cycle count |

The register positions match the Modbus layout implemented in `daly_bms.py`
(same slave address `0xD2`, temperatures from `0x0020` with an offset of 40,
voltage/current/state of charge from `0x0028`, cell count/sensor count/cycles
from `0x0031`), which is how the blocks were identified. They were then
verified on the real battery:

- Temperature: raw values `59, 59` while the vendor app showed 19.0 °C.
- Cycles: raw value `2` in `0x0033` while the app showed 2.0 cycles (it read
  `1` in earlier captures).
- Remaining charge: `0x0030` read `1171` (117.1 Ah) while the state of charge
  was 78.1 %, which matches 78.1 % of the rated 150 Ah.
- Cross-checks between registers: `0x002B`/`0x002C` equal the highest and
  lowest cell voltage, `0x0037` is close to the mean cell voltage, and `0x0038`
  is close to the spread between the highest and lowest cell in mV (it is read a
  moment after the cell block, so it can differ by a mV or two while the cells
  are moving). `0x002D`/`0x002E` read the same as the two temperatures
  (probably the highest and lowest temperature, but both sensors read alike, so
  this is not distinguishable yet).
- While charging at about 25 A: current was positive (raw values below 30000),
  remaining charge and state of charge rose together (117.8 Ah at 78.5 %), and
  `0x0039` read the charging power in W (672 W against 672 W from voltage times
  current). The register at `0x002F` read 1 while charging and 0 when idle.

Read size: reads of 16 registers at `0x0000`, `0x0020` and `0x0030`, of 32
registers at `0x0000` and `0x0020`, and of 40 registers at `0x0000` all work.
The 16 and 32 register replies (37 and 69 bytes) each arrived as a single BLE
notification. A request for 48 or 62 registers gets no response at all, so the
limit lies between 40 and 48 registers.

## Current encoding

The current register uses the same zero-offset convention as the
`DalyBMS` protocol family (`register value`, centred on `30000`, in
0.1 A steps) — strong circumstantial evidence that the `RD-RJ8S150A`
board is a Daly-protocol-family clone with its own register map, not an
independently designed protocol. However, the **sign is inverted**
relative to Daly: Daly's formula is `(x - 30000) / 10` with a positive
result meaning charging, whereas on this device a raw value *below*
30000 means charging. This library therefore decodes it as
`(30000 - x) / 10`.

This was confirmed, not assumed: two captures were taken around a real
charge/discharge transition (0.9 A tapering to 0 A), and the vendor app's
own displayed charge/discharge direction was cross-checked against the
raw register value for the non-zero reading. A raw value of `29991`
(10 below the 30000 centre point) was displayed by the app as **charging
at +0.9 A**.

## Troubleshooting

Two issues were hit (and resolved) while bringing this plugin up against
real hardware for the first time, both worth checking before assuming
the plugin itself is broken:

**Device never appears, even unmatched, in Home Assistant's Bluetooth
scanner.** This battery's BMS only supports one BLE central connection
at a time, like most cheap serial-bridge modules of this type, and
appears to stop advertising entirely while something else is connected
to it. If the vendor's own "Rolls LFP Connect" app is open (even just
backgrounded, not force-quit) on a phone, it may be holding the
connection open, which makes the device invisible to any other scanner,
including Home Assistant's — independent of signal strength or BLE
proxy placement. Force-quitting the app (not just leaving it
backgrounded) frees the connection and the device starts advertising
again within a few seconds. "Forget this device" in the phone's OS-level
Bluetooth settings does **not** help here, since this class of device is
not OS-paired — the app holds its own internal connection.

**`BleakCharacteristicNotFoundError: Characteristic fff1 was not
found!` on every connection attempt, even though the service (`0xFFF0`)
resolves correctly.** This is a known BlueZ/bleak GATT-attribute-caching
issue (see e.g.
[hbldh/bleak#882](https://github.com/hbldh/bleak/issues/882) and
[hbldh/bleak#1358](https://github.com/hbldh/bleak/issues/1358)), not
specific to this plugin: if an earlier connection to the device was torn
down before characteristic discovery completed — easy to trigger during
initial setup/testing with repeated connect/disconnect attempts — BlueZ
can cache that incomplete attribute table and keep returning it on every
subsequent connection, even once the real device's full table is
available. The integration's own retry loop will keep hitting the same
cached, incomplete result and never recover on its own.
`bleak_retry_connector.clear_cache(address)` is the targeted fix, but
needs to run inside the same process holding the dbus session (i.e. the
Home Assistant Core container), which isn't reachable from the
Terminal & SSH add-on's shell. In practice, a full **Home Assistant Core
restart** (not just reloading the integration) was sufficient to clear
this and get a clean reconnect. A physical unplug/replug of the BLE
adapter is reported elsewhere as an alternative fix for the same
underlying BlueZ behaviour.

## Known gaps

- `design_capacity` is not read from the BMS. Remaining charge and state of
  charge are consistent with 150 Ah, but the rated capacity itself was not
  found in any register.
- Registers `0x0034`–`0x0036` read `0, 1, 1` both while idle and while charging
  at 25 A. In the Daly layout these are the balancer state and the charge and
  discharge MOSFET states, and the values are plausible, but they have not been
  seen to change and are not decoded.
- Register `0x003A` (4 registers, always zero so far) is the problem/alarm code
  in the Daly layout, but no non-zero value has been seen, so it is not decoded.
- A one-time burst of reads at register `0x0050`/`0x0051` was observed
  only at the start of a connection (an apparent event-log dump, 18
  entries) and is unrelated to steady-state telemetry; not decoded.
- Only verified against a single VB24-150LFP unit. Other VB-series
  capacities/voltages (12 V, 36 V, 48 V variants) are assumed to share
  the same protocol and register map but this has not been confirmed.
