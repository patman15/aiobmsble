# Saihang BMS (Anenji) Documentation

## Overview

The Saihang BMS (often branded as Anenji) uses a custom Bluetooth Low Energy protocol that is heavily based on Modbus RTU, but wrapped in a proprietary frame starting with `A5 A5`. 
The BMS returns a large, contiguous block of registers containing real-time telemetry and battery parameters. Additional protection settings exist later in the register map, but are currently documented only for future extension.

## Device Identification

- **Local Name**: `SH*` (e.g., SH-BMS)
- **Service UUID**: `0000fffa-0000-1000-8000-00805f9b34fb` (Short: `fffa`)
- **Notification Characteristic**: `0000fffc-0000-1000-8000-00805f9b34fb` (read/notify)
- **Write Characteristic**: `0000fffb-0000-1000-8000-00805f9b34fb` (write)

### Device Discovery

The Saihang BMS is detected using:
- A local name matching the prefix `SH`
- Service UUID `fffa`
- The device must be connectable.

## Protocol Mechanics

### The Polling Command

Unlike some BMS devices that push data automatically, the Saihang BMS requires an active polling command to stream telemetry. The driver periodically writes a Modbus `Read Holding Registers` (0x03) command to the `fffb` characteristic.

The polling command structure currently used by the driver is:
`A5 A5 01 03 00 00 00 48 [CRC16]`

- `A5 A5`: Start of Frame (SOF)
- `01`: Device ID
- `03`: Modbus Function (Read Holding Registers)
- `00 00`: Starting Register (Address 0)
- `00 48`: Number of registers to read (72 registers = 144 bytes of data)
- `CRC16`: Standard Modbus CRC-16

The `0x48` request covers all currently supported telemetry fields, including cell voltages, temperatures, MOSFET state, balancer state, MOSFET temperature, and ambient temperature.

Additional voltage protection settings exist later in the register map. Requesting `0x53` registers would include more of that block, but those values are currently not exposed by the driver and are documented only for future extension.

### Response Fragmentation

The BLE MTU size is typically smaller than the requested payload. The BMS may split the response across multiple BLE notification frames. The `aiobmsble` driver accumulates these frames until the total length matches the expected length defined in the 5th byte of the response header (`data[4]`).

### Temperatures
The telemetry block contains up to 4 standard cell NTC sensors starting at byte offset 87. However, the payload contains two additional dedicated sensors:
- **MOSFET Temperature**: Located at byte offset 107.
- **Ambient Temperature**: Located at byte offset 109.
These are now appended dynamically to the `temp_values` array so that Home Assistant can track the internal transistor and ambient case temperatures independently.

### Hardware Switch States
The 16-bit word at offset 37 represents the `Fault & Switch Status Bitmask`. 
- **Bit 9 (`0x0200`)**: Charge MOSFET state
- **Bit 10 (`0x0400`)**: Discharge MOSFET state
- **Bit 13 (`0x2000`)**: AC IN state

### Supported Telemetry Memory Map

The following table documents the currently supported part of the Saihang BMS response payload. Offsets are byte offsets in the complete response frame, including the `A5 A5` frame header.

The current driver request (`0x48` registers) returns a 144-byte data block, which is sufficient for all supported runtime telemetry fields.

| **Field** | **Byte Offset** | **Length (bytes)** | **Hexadecimal** | **Decoded Value** | **Description** |
| --- | --- | --- | --- | --- | --- |
| **Frame Header** | 0 | 2 | a5a5 | – | Frame Header (SOF) |
| **Device ID** | 2 | 1 | 01 | 1 | Device ID |
| **Function Code** | 3 | 1 | 03 | 3 | Modbus Function Code (03 = Read Holding Registers) |
| **Payload Length** | 4 | 1 | 90 | 144 | Payload Data Length (144 bytes / 72 registers) |
| **Current** | 5 | 4 | fffffe54 | -4.28 A | Current (screenshot shows -4.40 A) |
| **Total Voltage** | 9 | 4 | 000014d6 | 53.34 V | Total Voltage (screenshot: 53.39 V) |
| **SOC** | 13 | 2 | 0063 | 99 % | Battery Level (SOC) |
| **SOH** | 15 | 2 | 0064 | 100 % | Battery Health (SOH) |
| **Cycle Charge** | 17 | 4 | 00007b55 | 315.73 Ah | Cycle Charge (Remaining Capacity) |
| **Total Charge** | 21 | 4 | 00007c11 | 317.61 Ah | Total Charge (Capacity when fully charged) |
| **Design Capacity** | 25 | 4 | 00007530 | 300.00 Ah | Design Capacity |
| **Cycle Count** | 29 | 2 | 003e | 62 | Cycle Count |
| **Problem Code** | 31 | 2 | ffff | 0 | Problem Code (0 = No Error) |

## Known Unsupported Voltage Protection Settings

The Saihang BMS memory map continues after the supported telemetry block with voltage protection settings. These values are currently documented for future extension, but are not exposed by the driver.

With the current `0x48` request, only the beginning of this settings area may be present. A larger request, such as `0x53`, would be needed to retrieve the complete block.

| Key | Start | Length (bytes) | Divisor |
| --- | --- | --- | --- |
| **pack_ov_alarm** | 125 | 4 | 1000 |
| **pack_ov_protection** | 129 | 4 | 1000 |
| **pack_ov_release** | 133 | 4 | 1000 |
| **pack_ov_delay** | 137 | 2 | 10 |
| **cell_ov_alarm** | 139 | 2 | 1000 |
| **cell_ov_protection** | 141 | 2 | 1000 |
| **cell_ov_release** | 143 | 2 | 1000 |
| **cell_ov_delay** | 145 | 2 | 10 |
| **pack_uv_alarm** | 147 | 4 | 1000 |
| **pack_uv_protection** | 151 | 4 | 1000 |
| **pack_uv_release** | 155 | 4 | 100 |
| **pack_uv_delay** | 159 | 2 | 10 |
| **cell_uv_alarm** | 161 | 2 | 1000 |
| **cell_uv_protection** | 163 | 2 | 1000 |
| **cell_uv_release** | 165 | 2 | 1000 |
| **cell_uv_delay** | 167 | 2 | 10 |