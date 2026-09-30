# Protocol (R1500 V2.0, big-endian multi-byte values)

## BLE Characteristics
Service UUID `fff0`
Notify UUID `fff1`
Write UUID `fff2`

## Frame Format
Status notification (length > 14 bytes, prefix 0xA5):
  Byte  0: 0xA5  (SOF)
  Byte  1: 0x65
  Byte  2: 0xB1
  Bytes 3-6: unknown
  Byte  7: flags
            bit0 = DC on
            bit1 = AC on
            bit2 = AC frequency (0 = 50 Hz, 1 = 60 Hz)
            bit4 = Torch/light on
            AC output ↔ charge MOSFET, DC output ↔ discharge MOSFET
  Byte  8: battery level [%]
  Bytes 9-10: input power [W] (big-endian)
  Bytes 11-12: output power [W] (big-endian)
  Bytes 13-14: minutes remaining (big-endian); 0xFFFF = charging/idle

Settings notification (length ~10 bytes, prefix 0xA5 0x65 0xB1 0x00 0x01 0x06 0x03):
  Byte  7: X = (work_mode_bits | eco_flag)
            bits 1-2: work mode (0x00=Mute, 0x02=Standard, 0x04=Fast)
            bit  0:   eco mode enabled
  Byte  8: Y = eco shutdown timer in hours (1/2/4/6)

The Allpowers PPS pushes status frames autonomously once a BLE
connection with notifications enabled is established.  We simply
wait for the next inbound notification without sending a TX command.