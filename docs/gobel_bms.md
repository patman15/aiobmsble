# Gobel Power BLE BMS

## Advertisement
Gobel BMS doesn't advertise service UUID, only reveals it after connection.
Device name format: BMS- followed by 16 characters (may have trailing spaces).

## Data field definitions for READ_CMD_STATUS response

Byte offsets in the response data (after addr+func+len header)
Response format: 01 03 76 [data: 118 bytes] [crc: 2 bytes]

Register map (each register = 2 bytes):
Reg 0  (byte 0-1):   Current /100 A (signed)
Reg 1  (byte 2-3):   Voltage /100 V
Reg 2  (byte 4-5):   SOC %
Reg 3  (byte 6-7):   SOH %
Reg 4  (byte 8-9):   Remaining capacity *10 mAh
Reg 5  (byte 10-11): Full capacity *10 mAh
Reg 6  (byte 12-13): Unknown
Reg 7  (byte 14-15): Cycles
Reg 8-10: Alarm/Protection/Fault
Reg 11 (byte 22-23): Balance status
Reg 14 (byte 28-29): MOS status (bit 14=charge, bit 15=discharge)
Reg 15 (byte 30-31): Cell count
Reg 16+ (byte 32+):  Cell voltages (mV)
Reg 46 (byte 92-93): Temperature sensor count
Reg 47 (byte 94-95): Temperature 1 /10 °C
Reg 57 (byte 114-115): MOSFET temperature /10 °C
