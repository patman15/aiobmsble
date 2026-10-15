# Dyness Junior Box BMS

Support for the Dyness Junior Box (1.6 kWh LiFePO4 home battery). The device
advertises with a BLE name starting with `R07` (e.g. `R07E8546681A00F9`) and
does **not** advertise its services; they appear only after connecting.

Reference: https://github.com/patman15/BMS_BLE-HA/issues/633

## BLE services and characteristics

| Purpose        | UUID   | Properties                     |
| -------------- | ------ | ------------------------------ |
| Service        | `fe00` | vendor specific                |
| Write (TX)     | `fe01` | write, write-without-response  |
| Notify (RX)    | `fe02` | notify (read not permitted)    |
| Additional     | `fed5` | write                          |

## Transport: Espressif BluFi

The battery uses the Espressif **BluFi** transport rather than a plain BMS
protocol. Each frame has the layout:

```
| Type (1B) | Frame Control (1B) | Sequence (1B) | Data Length (1B) | Data | CRC16 (2B) |
```

* **Type** – lower two bits select control (`0b00`) or data (`0b01`) frames;
  the upper six bits are the subtype (control `0x01` = set security mode,
  data `0x13` = custom application data).
* **Frame Control** flags used here: `0x01` encrypted data, `0x02` trailing
  CRC16 (CCITT/XMODEM over `sequence + length + data`), `0x10` more fragments
  follow (first two data bytes hold the remaining content length).

### Encryption

Data frames are AES-128-CBC encrypted with PKCS7 padding. The key and IV are
identical and derived deterministically from the device serial number (the BLE
name):

```
key = ("214028" + serial[:15]).encode("ascii")[:16]   # default "1111111111111111" if empty
```

A fixed HMAC-SHA256 key (`75cb83eb7066a944085c0b157831d1b9`) derives the
fallback `sign` value when no explicit device password is configured.

## Application protocol

After the BluFi session is secured, a small JSON protocol runs inside the
encrypted custom-data frames:

1. Authenticate: `{"req": "bleauth", "sign": "<password>"}`
2. Request data: `{"req": "fdbg", "data": "<modbus-hex>"}` → the reply carries a
   Modbus RTU frame (optionally wrapped in `{"data": "<hex>"}`).

## Open items (provisional)

The following could **not** be validated against a decrypted capture and must be
confirmed with real device traffic:

* the exact BluFi frame/encryption layering and the `bleauth` success criteria,
* the device password source (cloud-provided; the SN/HMAC fallback is unconfirmed),
* the Modbus request command and register map used to decode voltage, current
  and state of charge.
