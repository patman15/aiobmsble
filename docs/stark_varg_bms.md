# Stark VARG

The Stark VARG exposes battery telemetry through proprietary BLE GATT services
whose UUIDs share the suffix `-5374-6172-4b20-467574757265`. This plugin
subscribes only to the Bike authentication characteristic and the read-only
Charger and Battery telemetry characteristics.

## Authentication

The vehicle must be bonded/encrypted by the Bluetooth platform when required.
The plugin then authenticates on `00001001`: it enables notifications, reads a
32-byte nonce, writes the V2 response, and waits for a result notification whose
first byte must be `0x01`. Protected telemetry subscriptions are started only
after authentication succeeds.

Set `BMSConfig.secret` to the 32-character hexadecimal representation of the
16-byte derived V2 key. The protocol notes describe the response hash but do not
publish the complete local key-derivation rule. Derive or obtain this key through
an authorized process; do not log or share it. Bluetooth PIN/bonding setup is
handled by the host platform, not this plugin.

## Battery data

Notifications are keyed by their characteristic UUID and contain little-endian
payloads without an additional frame envelope. The plugin maps:

| Characteristic | BMSSample fields |
| --- | --- |
| `5001` | `current` and `battery_charging` while the charger is enabled. This is charger-side current, not a discharge or traction-current measurement. |
| `6003` | `cell_count` from the observed series-count field. Raw capacity and parallel count are not converted because their mapping/units are unvalidated. |
| `6004` | `battery_level`, nonzero `battery_health`, and `voltage` from the DC bus. |
| `6005` | `temp_sensors` and masked `temp_values`. |
| `6007` | 100 cell-group voltages and, when `6003` is unavailable, `cell_count`. |
| `6008` | `balancer` as a little-endian bit mask for the first 100 cell groups. |

The plugin waits for fresh `6004`, `6005`, and `6007` notifications before
returning a sample. Charger data, topology, and balancing remain optional. It
does not infer battery discharge current from charger telemetry.

The public protocol references supplied for this implementation document field
layouts but do not include a real, anonymized advertisement or captured
notifications. No fabricated BLE capture is included. Add sanitized captures
from a real VARG before claiming recorded-device test coverage.