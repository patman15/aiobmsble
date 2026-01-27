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
        BMSDp("chrg_mosfet", 28, 2, False, lambda x: bool(x & 0x4000)),  # Reg 14 bit 14
        BMSDp("dischrg_mosfet", 28, 2, False, lambda x: bool(x & 0x8000)),  # Reg 14 bit 15
        BMSDp("cell_count", 30, 2, False, lambda x: x & 0xFF),  # Reg 15: Cell count
        BMSDp("temp_sensors", 92, 2, False, lambda x: x & 0xFF),  # Reg 46: Count
    )

    # Byte offsets for fields parsed manually (includes 3-byte Modbus header)
    OFF_ALARM: Final[int] = 19  # Reg 8: Alarm status
    OFF_PROTECTION: Final[int] = 21  # Reg 9: Protection status
    OFF_FAULT: Final[int] = 23  # Reg 10: Fault status

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
        byte_count = self._frame[2]
        expected_len = 3 + byte_count + 2  # header(3) + data + crc(2)

        if len(self._frame) < expected_len:
            self._log.debug(
                "waiting for more data: %d/%d bytes", len(self._frame), expected_len
            )
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
        result: BMSSample = {}

        # Read basic battery status data
        cmd = BMS._cmd(*BMS.READ_CMD_STATUS)
        await self._await_msg(cmd)

        data = self._msg[:-2]  # Exclude CRC
        expected_bytes = BMS.READ_CMD_STATUS[3] * 2 + 3  # header + registers * 2 bytes
        if len(data) < expected_bytes:
            self._log.warning(
                "response too short: %d bytes, expected %d",
                len(data),
                expected_bytes,
            )
            return {}

        # Decode standard fields using start parameter for header offset
        result = BMS._decode_data(BMS._FIELDS, data, byteorder="big", start=3)

        # Parse alarm/protection/fault status manually
        alarm = int.from_bytes(data[BMS.OFF_ALARM : BMS.OFF_ALARM + 2], "big")
        protection = int.from_bytes(
            data[BMS.OFF_PROTECTION : BMS.OFF_PROTECTION + 2], "big"
        )
        fault = int.from_bytes(data[BMS.OFF_FAULT : BMS.OFF_FAULT + 2], "big")

        # Combine into problem code if any are non-zero
        if alarm or protection or fault:
            result["problem_code"] = (alarm << 16) | (protection << 8) | fault

        # Get cell voltages (starting at byte 32, each cell is 2 bytes in mV)
        cell_count = min(result.get("cell_count", 0), BMS.MAX_CELLS)
        if cell_count > 0:
            result["cell_voltages"] = BMS._cell_voltages(
                data,
                cells=cell_count,
                start=BMS.CELL_VOLT_START,
                byteorder="big",
                divider=1000,  # mV to V
            )

        # Parse temperature values using _temp_values helper
        temp_count = min(result.get("temp_sensors", 0), BMS.MAX_TEMP)
        temps: list[float] = BMS._temp_values(
            data,
            values=temp_count,
            start=BMS.TEMP_START,
            byteorder="big",
            signed=True,
            divider=10,
        )

        # Also read MOSFET temperature (at byte 114) if valid
        # 0xFFFF and 0 are invalid markers
        if len(data) >= BMS.TEMP_MOS_OFFSET + 2:  # pragma: no branch
            mos_temp_raw = int.from_bytes(
                data[BMS.TEMP_MOS_OFFSET : BMS.TEMP_MOS_OFFSET + 2], "big"
            )
            if mos_temp_raw not in {0xFFFF, 0}:
                temps.extend(
                    BMS._temp_values(
                        data,
                        values=1,
                        start=BMS.TEMP_MOS_OFFSET,
                        byteorder="big",
                        signed=True,
                        divider=10,
                    )
                )

        if temps:
            result["temp_values"] = temps

        return result

    async def _fetch_device_info(self) -> BMSInfo:
        """Fetch device info from BMS via Modbus."""
        # First get standard BLE device info (may contain generic values)
        info: BMSInfo = await super()._fetch_device_info()

        try:
            # Read device info registers via Modbus
            cmd = BMS._cmd(*BMS.READ_CMD_DEVICE_INFO)
            await self._await_msg(cmd)

            # Parse response
            data = self._msg[3:-2]  # Skip header and CRC

            self._log.debug("device info raw (%d bytes): %s", len(data), data.hex(" "))

            if len(data) >= 60:
                # BMS Version: bytes 0-17 (null-terminated string)
                # Example: "P4S200A-40569-1.02"
                if sw_ver := b2str(data[0:18]):
                    info["sw_version"] = sw_ver

                # BMS Serial Number: bytes 20-39 (with trailing spaces)
                # Example: "4056911A1100032P    "
                if serial := b2str(data[20:40]):
                    info["serial_number"] = serial

                # Pack Serial Number: bytes 40-60 (stored in model_id field)
                # Example: "GP-LA12-31420250618"
                if model_id := b2str(data[40:60]):
                    info["model_id"] = model_id

        except Exception as exc:  # noqa: BLE001
            self._log.debug("failed to read device info via Modbus: %s", exc)

        return info
