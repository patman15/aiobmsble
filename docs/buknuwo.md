# Buknuwo BMS

Could be a modified PACE BMS, as the first 0xf registers look very similar.
BMS sends frames in 20 bytes chunks

## Register Map

| Address |  Length | Description |
|---------|---------|-------------|
| `0x0000`| 2 Bytes | current 0.01 A |
| `0x0001`| 2 Bytes | voltage 0.01 V |
| `0x0002`| 2 Bytes | SoC |
| `0x0003`| 2 Bytes | SoH |
| `0x0004`| 2 Bytes | cycle charge  0.01 Ah |
| `0x0005`| 2 Bytes | cycle capacity  0.01 Ah |
| `0x0006`| 2 Bytes | design capacity 0.01 Ah |
| `0x0007`| 2 Bytes | cycles |
| `0x0008`| 2 Bytes | unknown |
| `0x0009`| 4 Bytes | error flags |
| `0x000b`| 2 Bytes | 0x800 discharge, 0x400 charge MOSFET |
| `0x000c`| 4 Bytes | unknown |
| `0x002e`| 2 Bytes | temperature sensors |
| `0x002f`| 20 Bytes | temperature values (max 10) |
| `0x0039`| 2 Bytes | MOS temp |
| `0x0053`| 32 Bytes | unknown |
| `0x0063`| 16 Bytes | unknown |
| `0x006b`| 42 Bytes | unknown |
| `0x0080`| 20 Bytes | unknown |
| `0x00a2`| 2 Bytes | design capacity 0.01 Ah |