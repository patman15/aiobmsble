# C4S100-family generic Modbus-over-BLE Smart BMS

## Hardware / protocol overview

Derived from a 4S/100A LiFePO4 BMS sold under the local BLE name
`C4S100IEnnnnn` (companion app: **E-BMS**). The hardware is built around a
generic RC6621A module (ShenZhen RF Crazy Technology, Onmicro HS6621CM
chip), a transparent BLE-UART bridge — the app's traffic over the Nordic
UART Service is a raw passthrough of the BMS's native **Modbus RTU**
protocol (slave id `0x02`, function `0x03`, Read Holding Registers).

A single request for the 70 holding registers starting at address
`0x0000` returns the full telemetry set: pack voltage, signed current,
SOC, cell voltages/count, remaining/nominal capacity, cycle count, SOH,
cell voltage delta, and temperature.

## Relation to VatrerBMS

This device shares its exact register table with `VatrerBMS`: voltage,
current, SOC, cycle_charge, cycles, delta_voltage, cell_count and
cell_voltages all decode correctly using Vatrer's field offsets and
scaling, verified byte-for-byte against real captured data.

What differs is the **query pattern**. `VatrerBMS` reads the table via
three separate partial requests: `(0x0,0x14)`, `(0x34,0x12)`,
`(0x15,0x1F)`. This device does not respond to any of them — verified
live against real hardware via `bluetoothctl` (notify enabled, all three
requests sent in sequence): no notification arrived for any of the three.
It only answers a single combined read of all 70 registers, `(0x0,
0x46)`.

Because of this, `C4SBMS` is implemented as `BMS(VatrerBMS)`, reusing the
transport layer as-is (`uuid_services`, `uuid_rx`, `uuid_tx`,
`_notification_handler`, `_HEAD`, `_FRAME_LEN`, `__init__`) and
overriding only the register field map and the query/parsing method.

## Register map

| Register | Field | Encoding |
|---|---|---|
| reg0 | `voltage` | ×0.01 V |
| reg1 (hi) + reg2 (lo) | `current` | signed 32-bit, ×0.01 A; positive = charging, negative = discharging |
| reg3 | `battery_level` (SOC) | % |
| reg4 | `cycle_charge` | ×0.01 Ah |
| reg5 | `design_capacity` | ×0.01 Ah (100.00 Ah on the reference unit) |
| reg6 | `cycles` | count |
| reg7 | `battery_health` (SOH) | % |
| reg13 | `delta_voltage` | mV, ÷1000 |
| reg16 | MOS_T temperature | °C |
| reg17 | ENV_T temperature | °C |
| reg21 | `cell_count` | count (4 on the reference unit) |
| reg22–25 | cell voltages | mV |

The `(0x023D, 20)` request (not used by this implementation) decodes as
ASCII `"EQ.V01.0.04"` — the firmware version string.

## Temperature duplication

The E-BMS app displays four temperature readings, but the device only has
**two** physical sensors. Registers 16/17 (`MOS_T`/`ENV_T`) reappear a
second time at registers 52–54 and 57–58 under different app labels
(`TCell1`/`TCell2`), mirroring the same physical values. Only the first
copy (reg16/17) is used by this implementation.

## Known gaps

- The status bits `chrg_mosfet`/`dischrg_mosfet`/`balancer`/`problem`
  that `VatrerBMS` derives from its `(0x34,0x12)` block have no confirmed
  ground truth on this device (never observed toggling in testing) and
  are intentionally not reported, to avoid presenting unverified data as
  real sensor state.
- The status bitmask register for `CHGMOS`/`DSGMOS`/`Balancing`/`Fully`/
  `Empty`/`Heating`/`LimitCurrent` shown in the app has not been located.
  Locating it would require capturing a moment where one of those states
  actually toggles.
