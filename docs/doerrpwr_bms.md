# Dörr Power BMS

## Protocol
Same E&J Technology family protocol/frame format as PowerBoozt
(:015150000EFE~ single-frame query, same field offsets, same
checksum), but different BLE advertisement (manufacturer ID) and
different GATT characteristic (FFF6 instead of FFF1/FFF2).

# Current Field
The raw `current` field (4 bytes at offset 54) is not a plain
signed integer like PowerBoozt assumes - it's a charging flag (bit
31, i.e. bit 7 of the first byte) plus an unsigned magnitude in the
lower 16 bits (mA). Verified against three captures: idle (0x00000000
-> 0.0A), discharging (0x000003B6 -> -0.95A, app showed -2.7A at a
different moment so only the sign/order of magnitude was cross-
checked), and charging (0x800009D8 -> +2.52A, matches
battery_charging=True).