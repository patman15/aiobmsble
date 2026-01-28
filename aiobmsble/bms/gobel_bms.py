"""Module to support Gobel Power BLE BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/

This module implements support for Gobel Power BMS devices that use Modbus RTU
protocol over Bluetooth Low Energy.
"""

from functools import cache
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice

from aiobmsble import BMSDp, BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS, b2str, crc_modbus


class BMS(BaseBMS):
    """Gobel Power BLE BMS class implementation using Modbus RTU over BLE."""

    INFO: BMSInfo = {"default_manufacturer": "Gobel Power", "default_model": "BLE BMS"}

    # Modbus constants
    SLAVE_ADDR: Final[int] = 0x01
    FUNC_READ: Final[int] = 0x03

    # Frame constants
    MIN_FRAME_LEN: Final[int] = 5  # addr + func + len + 2*crc minimum
    MAX_CELLS: Final[int] = 32
    MAX_TEMP: Final[int] = 8

    # Register read commands (from Android app analysis)
    # Each command: (slave_addr, func_code, start_address, register_count)
    READ_CMD_STATUS: Final[tuple[int, int, int, int]] = (
        SLAVE_ADDR,
        FUNC_READ,
        0x0000,
        0x003B,
    )  # 59 registers
    READ_CMD_DEVICE_INFO: Final[tuple[int, int, int, int]] = (
        SLAVE_ADDR,
        FUNC_READ,
        0x00AA,
        0x0023,
    )  # 35 registers

    # Data field definitions for READ_CMD_STATUS response
    # Byte offsets in the response data (after addr+func+len header)
    # Response format: 01 03 76 [data: 118 bytes] [crc: 2 bytes]
    #
    # Register map (each register = 2 bytes):
    # Reg 0  (byte 0-1):   Current /100 A (signed)
    # Reg 1  (byte 2-3):   Voltage /100 V
    # Reg 2  (byte 4-5):   SOC %
    # Reg 3  (byte 6-7):   SOH %
    # Reg 4  (byte 8-9):   Remaining capacity *10 mAh
    # Reg 5  (byte 10-11): Full capacity *10 mAh
    # Reg 6  (byte 12-13): Unknown
    # Reg 7  (byte 14-15): Cycles
    # Reg 8-10: Alarm/Protection/Fault
    # Reg 11 (byte 22-23): Balance status
    # Reg 14 (byte 28-29): MOS status (bit 14=charge, bit 15=discharge)
    # Reg 15 (byte 30-31): Cell count
    # Reg 16+ (byte 32+):  Cell voltages (mV)
    # Reg 46 (byte 92-93): Temperature sensor count
    # Reg 47 (byte 94-95): Temperature 1 /10 °C
    # Reg 57 (byte 114-115): MOSFET temperature /10 °C

    # Standard fields decoded via _decode_data
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp(
            "current", 0, 2, True, lambda x: x / 100
        ),  # Reg 0: Current /100 A (signed)
        BMSDp("voltage", 2, 2, False, lambda x: x / 100),  # Reg 1: Pack voltage /100 V
        BMSDp("battery_level", 4, 2, False),  # Reg 2: SOC %
        BMSDp("battery_health", 6, 2, False),  # Reg 3: SOH %
        BMSDp("cycle_charge", 8, 2, False, lambda x: x / 100),  # Reg 4: Capacity Ah
        BMSDp("design_capacity", 10, 2, False, lambda x: x // 100),  # Reg 5: Full cap Ah
        BMSDp("cycles", 14, 2, False),  # Reg 7: Cycle count
        BMSDp("problem_code", 16, 6, False),  # Reg 8-10, Alarm, Protection, Fault
        BMSDp("chrg_mosfet", 28, 2, False, lambda x: bool(x & 0x4000)),  # Reg 14 bit 14
        BMSDp("dischrg_mosfet", 28, 2, False, lambda x: bool(x & 0x8000)),  # Reg 14 bit 15
        BMSDp("cell_count", 30, 2, False, lambda x: x & 0xFF),  # Reg 15: Cell count
        BMSDp("temp_sensors", 92, 2, False, lambda x: x & 0xFF),  # Reg 46: Count
    )

    # Cell voltages start at byte 35 (register 16 + 3-byte header)
    CELL_VOLT_START: Final[int] = 35
    # Temperature values start at byte 97 (register 47 + 3-byte header)
    TEMP_START: Final[int] = 97
    # MOSFET temperature at byte 117 (register 57 + 3-byte header)
    TEMP_MOS_OFFSET: Final[int] = 117

    def __init__(self, ble_device: BLEDevice, keep_alive: bool = True) -> None:
        """Initialize private BMS members."""
        super().__init__(ble_device, keep_alive)
        self._msg: bytes = b""

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition.

        Note: Gobel BMS doesn't advertise service UUID, only reveals it after connection.
        Device name format: BMS- followed by 16 characters (may have trailing spaces).
        """
        return [MatcherPattern(local_name="BMS-????????????????*", connectable=True)]

    @staticmethod
    def uuid_services() -> list[str]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        # Custom BLE service used by Gobel Power BMS devices
        return ["00002760-08c2-11e1-9073-0e8ac72e1001"]

    @staticmethod
    def uuid_rx() -> str:
        """Return UUID of characteristic that provides notification/read property."""
        return "00002760-08c2-11e1-9073-0e8ac72e0002"

    @staticmethod
    def uuid_tx() -> str:
        """Return UUID of characteristic that provides write property."""
        return "00002760-08c2-11e1-9073-0e8ac72e0001"

    @staticmethod
    @cache
    def _cmd(addr: int, func: int, start: int, regs: int) -> bytes:
        """Build Modbus read command with CRC (cached)."""
        cmd = (
            addr.to_bytes(1, "big")
            + func.to_bytes(1, "big")
            + start.to_bytes(2, "big")
            + regs.to_bytes(2, "big")
        )
        return cmd + crc_modbus(cmd).to_bytes(2, "little")

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        self._log.debug(
            "RX BLE data (%s): %s",
            "start" if not self._frame else "cnt.",
            data.hex(" "),
        )

        # Start of a new frame - check for valid Modbus response header
        if len(data) >= 2 and data[0] == BMS.SLAVE_ADDR:
            # Check if it's a valid read response or error response
            if data[1] == BMS.FUNC_READ or data[1] == (BMS.FUNC_READ | 0x80):
                # Start new frame (clear any old data)
                self._frame = bytearray(data)
            else:
                self._log.debug("unexpected function code: 0x%02X", data[1])
                return
        elif self._frame:
            # Continuation of existing frame
            self._frame.extend(data)
        else:
            self._log.debug("unexpected data, ignoring: %s", data.hex(" "))
            return

        # Check if we have enough data for minimum frame
        if len(self._frame) < BMS.MIN_FRAME_LEN:
            return

        # Check for error response
        if self._frame[1] == (BMS.FUNC_READ | 0x80):
            self._log.warning("Modbus error response: 0x%02X", self._frame[2])
            self._frame.clear()
            return

        # Get expected frame length from byte count field
        expected_len = BMS.MIN_FRAME_LEN + self._frame[2]

        if len(self._frame) < expected_len:
            return

        # Truncate if we received extra data
        frame = self._frame[:expected_len]

        # Verify CRC
        payload = frame[:-2]
        received_crc = int.from_bytes(frame[-2:], byteorder="little")
        calculated_crc = crc_modbus(payload)

        if received_crc != calculated_crc:
            self._log.debug(
                "invalid CRC: 0x%04X != 0x%04X", received_crc, calculated_crc
            )
            self._frame.clear()
            return

        self._log.debug("valid frame received: %d bytes", len(frame))
        self._msg = bytes(frame)
        self._msg_event.set()

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        await self._await_msg(BMS._cmd(*BMS.READ_CMD_STATUS))

        data = self._msg[:-2]  # Exclude CRC
        if data[2] != BMS.READ_CMD_STATUS[3] * 2:
            self._log.debug(
                "incorrect response: %d bytes, expected %d",
                data[2],
                BMS.READ_CMD_STATUS[3] * 2,
            )
            return {}

        result = BMS._decode_data(BMS._FIELDS, data, byteorder="big", start=3)

        result["cell_voltages"] = BMS._cell_voltages(
            data,
            cells=min(result.get("cell_count", 0), BMS.MAX_CELLS),
            start=BMS.CELL_VOLT_START,
            byteorder="big",
        )

        result["temp_values"] = BMS._temp_values(
            data,
            values=min(result.get("temp_sensors", 0), BMS.MAX_TEMP),
            start=BMS.TEMP_START,
            byteorder="big",
            signed=True,
            divider=10,
        )

        # Append MOSFET temperature if valid (0xFFFF indicates no sensor)
        mos_temp_raw = int.from_bytes(
            data[BMS.TEMP_MOS_OFFSET : BMS.TEMP_MOS_OFFSET + 2], "big"
        )
        if mos_temp_raw != 0xFFFF:
            result["temp_values"].extend(
                BMS._temp_values(
                    data,
                    values=1,
                    start=BMS.TEMP_MOS_OFFSET,
                    byteorder="big",
                    signed=True,
                    divider=10,
                )
            )

        return result

    async def _fetch_device_info(self) -> BMSInfo:
        """Fetch device info from BMS via Modbus."""
        # First get standard BLE device info (may contain generic values)
        info: BMSInfo = await super()._fetch_device_info()

        # Read device info registers via Modbus
        try:
            await self._await_msg(BMS._cmd(*BMS.READ_CMD_DEVICE_INFO))
        except TimeoutError:
            return info

        if len(self._msg) >= 65:
            info.update({
                "sw_version": b2str(self._msg[3:21]),
                "serial_number": b2str(self._msg[23:43]),
                "model_id": b2str(self._msg[43:63]),
            })

        return info
