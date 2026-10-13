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
MAC address with colons stripped (e.g. `RDAC233FAF8312` for MAC
`AC:23:3F:AF:83:12`), and only becomes BLE-reachable once a charger or
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

The app issues three separate read requests per update cycle (there is no
single combined read of all fields, unlike some other Modbus-over-BLE
BMS protocols in this library):

| Register | Count | Contents |
|---|---|---|
| `0x0000` | 16 | Cell voltages, mV, padded to 16 slots for packs with fewer than 16 cells (the VB24-150LFP is an 8S pack; the remaining 8 registers read as zero) |
| `0x0028` | 2 | Pack voltage (×0.1 V) and current (see below) |
| `0x002A` | 1 | State of charge, ×0.1 % |

A fourth read range (`0x0031`, 3 registers; `0x003A`, 4 registers;
`0x0020`, 5 registers) is also issued by the app but was not needed to
satisfy this library's minimum required fields and is not yet decoded —
see "Known gaps" below.

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

## Known gaps

- `design_capacity` is not available from any register read observed so
  far, so `cycle_charge`/`cycle_capacity` cannot be derived.
- Registers `0x0031`, `0x003A`, and `0x0020` are read by the app each
  cycle but not yet decoded. `0x003A` (4 registers, observed constant at
  all zero) is suspected to be an alarm/fault bitfield; `0x0020` (5
  registers, observed constant `60, 60, 0, 0, 0`) is suspected to be
  temperature-related but unconfirmed; `0x0031` (3 registers, observed
  constant `8, 2, 1`) may include the cell count (`8`, matching the
  known 8S pack) plus two unidentified static fields.
- A one-time burst of reads at register `0x0050`/`0x0051` was observed
  only at the start of a connection (an apparent event-log dump, 18
  entries) and is unrelated to steady-state telemetry; not decoded.
- Only verified against a single VB24-150LFP unit. Other VB-series
  capacities/voltages (12 V, 36 V, 48 V variants) are assumed to share
  the same protocol and register map but this has not been confirmed.
