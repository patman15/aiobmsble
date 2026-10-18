# Volta Power System My Volta Bluetooth hardware kit

[Specification sheet](https://voltagenpower.com/wp-content/uploads/2022/12/VPS-Bluetooth-Hardware-Kit-Spec-Sheet-2021.12.30.pdf)


## Frame format

| Header| BLE command | CAN message type | pack ID | arbitration ID bits | extended ID | DLC | Payload | Checksum | Tail
|---|---|---|---|---|---|---|---|---|---|
55 55 | 01 | 00 | 02 | 00 00 | 00 | 08 | 01e0 c8ff 14e0 ae03 | a8 | 04 | 04

### CAN message types
    METRICS = 0x0
    INFO = 0x1
    CELL_VOLTAGES1 = 0x11
    CELL_VOLTAGES2 = 0x12
    CELL_VOLTAGES3 = 0x13
    CELL_VOLTAGES4 = 0x14
    CELL_TEMPS1 = 0x21
    CELL_TEMPS2 = 0x22
    ADD_INFO = 0x23 (not used)
    TEMPS3 = 0x24
    TEMPS4 = 0x25
    TEMPS5 = 0x26
    TEMPS6 = 0x27
    TEMPS7 = 0x28
    TEMPS8 = 0x29

## Problem Codes

Fault Name|Flag Value (Hex)|Bit Position|Byte Index|Description
|---|---|---|---|---|
PackTempLow|0x8000|15|1|Low pack temperature fault.
PackTempHigh|0x4000|14|1|High pack temperature fault.
ChargeOvercurrent|0x2000|13|1|Charge overcurrent fault.
DischargeOvercurrent|0x1000|12|1|Discharge overcurrent fault.
VCellLow|0x800|11|1|Low cell voltage fault.
VCellHigh|0x400|10|1|High cell voltage fault.
VPackLow|0x200|9|1|Low pack voltage fault.
VPackHigh|0x100|8|1|High pack voltage fault.
Precharge|0x10000|16|2|Precharge fault.
OpenCellWire|0x20000|17|2|Open cell wire fault.
ACDetect|0x40000|18|2|AC detect fault.
Thermistor|0x80000|19|2|Thermistor fault.
VPackCalibration|0x100000|20|2|Pack voltage calibration fault.
AFECommLoss|0x200000|21|2|Analogue front-end communication loss fault.
InvalidParameter|0x400000|22|2|Invalid parameter fault.
FlashChecksum|0x800000|23|2|Flash checksum fault.
RAMMemory|0x100000000|32|4|RAM memory fault.
EepromCRC|0x200000000|33|4|EEPROM CRC fault.
AFEInitFailure|0x400000000|34|4|Analogue front-end initialization failure fault.