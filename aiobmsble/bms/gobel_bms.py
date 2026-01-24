"""Module to support Gobel Power BLE BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/

This module implements support for Gobel Power BMS devices that use Modbus RTU
protocol over Bluetooth Low Energy.
"""

from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice

from aiobmsble import BMSDp, BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS, crc_modbus


class BMS(BaseBMS):
    """Gobel Power BLE BMS class implementation using Modbus RTU over BLE."""

    INFO: BMSInfo = {"default_manufacturer": "Gobel Power", "default_model": "BLE BMS"}

    # Modbus constants
    SLAVE_ADDR: Final[int] = 0x01
    FUNC_READ: Final[int] = 0x03
    FUNC_WRITE: Final[int] = 0x10

    # Frame constants
    HEAD_RSP: Final[bytes] = bytes([SLAVE_ADDR, FUNC_READ])
    MIN_FRAME_LEN: Final[int] = 5  # addr + func + len + 2*crc minimum
    MAX_CELLS: Final[int] = 32
    MAX_TEMP: Final[int] = 8

    # Register read commands (from Android app analysis)
    # Each command: (start_address, register_count)
    READ_CMD_1: Final[tuple[int, int]] = (0x0000, 0x003B)  # 59 registers - basic data
    READ_CMD_2: Final[tuple[int, int]] = (0x0053, 0x0037)  # 55 registers - thresholds
    READ_CMD_3: Final[tuple[int, int]] = (0x00AA, 0x0023)  # 35 registers - device info

    # Data field definitions for READ_CMD_1 response
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

    # Standard fields decoded via _decode_data (framework-compliant field names only)
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp(
            "current", 0, 2, True, lambda x: x / 100
        ),  # Reg 0: Current /100 A (signed)
        BMSDp("voltage", 2, 2, False, lambda x: x / 100),  # Reg 1: Pack voltage /100 V
        BMSDp("battery_level", 4, 2, False),  # Reg 2: SOC %
        BMSDp("battery_health", 6, 2, False),  # Reg 3: SOH %
        BMSDp("cycles", 14, 2, False),  # Reg 7: Cycle count
        BMSDp("cell_count", 30, 2, False, lambda x: x & 0xFF),  # Reg 15: Cell count
        BMSDp("temp_sensors", 92, 2, False, lambda x: x & 0xFF),  # Reg 46: Count
    )

    # Byte offsets for fields parsed manually (not using _decode_data)
    OFF_REMAIN_CAP: Final[int] = 8  # Reg 4: Remaining capacity *10 mAh
    OFF_FULL_CAP: Final[int] = 10  # Reg 5: Full capacity *10 mAh
    OFF_ALARM: Final[int] = 16  # Reg 8: Alarm status
    OFF_PROTECTION: Final[int] = 18  # Reg 9: Protection status
    OFF_FAULT: Final[int] = 20  # Reg 10: Fault status
    OFF_MOS_STATUS: Final[int] = 28  # Reg 14: MOS status

    # Cell voltages start at byte 32 (register 16)
    CELL_VOLT_START: Final[int] = 32
    # Temperature values start at byte 94 (register 47)
    TEMP_START: Final[int] = 94
    # MOSFET temperature at byte 114 (register 57)
    TEMP_MOS_OFFSET: Final[int] = 114

    def __init__(self, ble_device: BLEDevice, keep_alive: bool = True) -> None:
        """Initialize private BMS members."""
        super().__init__(ble_device, keep_alive)
        self._expected_len: int = 0

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            MatcherPattern(
                local_name="BMS-*",
                service_uuid=BMS.uuid_services()[0],
                connectable=True,
            )
        ]

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
    def _build_read_cmd(start_addr: int, num_regs: int) -> bytes:
        """Build Modbus read holding registers command with CRC.

        Args:
            start_addr: Starting register address
            num_regs: Number of registers to read

        Returns:
            Complete Modbus command with CRC

        """
        cmd = bytearray(
            [
                BMS.SLAVE_ADDR,
                BMS.FUNC_READ,
                (start_addr >> 8) & 0xFF,
                start_addr & 0xFF,
                (num_regs >> 8) & 0xFF,
                num_regs & 0xFF,
            ]
        )
        crc = crc_modbus(cmd)
        cmd.extend([crc & 0xFF, (crc >> 8) & 0xFF])  # CRC low byte first
        return bytes(cmd)

    @staticmethod
    def _parse_mos_status(value: int) -> tuple[bool, bool]:
        """Parse MOS status register.

        Args:
            value: Raw MOS status register value

        Returns:
            Tuple of (charge_mos_on, discharge_mos_on)

        """
        # Based on observed data: 0xC000 means both MOSFETs ON
        # Bit 14 = charge, bit 15 = discharge
        return bool(value & 0x4000), bool(value & 0x8000)

    @staticmethod
    def _convert_signed_temp(value: int) -> float:
        """Convert temperature register value to Celsius.

        Uses 16-bit signed value with /10 scale.

        Args:
            value: Raw 16-bit register value

        Returns:
            Temperature in Celsius

        """
        if value >= 0x8000:  # Negative (bit 15 set)
            value = -((value ^ 0xFFFF) + 1)
        return value / 10.0

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        self._log.debug(
            "RX BLE data (%s): %s",
            "start" if not self._data else "cnt.",
            data.hex(" "),
        )

        # Start of a new frame - check for valid Modbus response header
        if len(data) >= 2 and data[0] == BMS.SLAVE_ADDR:
            # Check if it's a valid read response or error response
            if data[1] == BMS.FUNC_READ or data[1] == (BMS.FUNC_READ | 0x80):
                # Start new frame (clear any old data)
                self._data = bytearray(data)
            else:
                self._log.debug("unexpected function code: 0x%02X", data[1])
                return
        elif self._data:
            # Continuation of existing frame
            self._data.extend(data)
        else:
            self._log.debug("unexpected data, ignoring: %s", data.hex(" "))
            return

        # Check if we have enough data for minimum frame
        if len(self._data) < BMS.MIN_FRAME_LEN:
            return

        # Check for error response
        if self._data[1] == (BMS.FUNC_READ | 0x80):
            self._log.warning("Modbus error response: 0x%02X", self._data[2])
            self._data.clear()
            return

        # Get expected frame length from byte count field
        byte_count = self._data[2]
        expected_len = 3 + byte_count + 2  # header(3) + data + crc(2)

        if len(self._data) < expected_len:
            self._log.debug(
                "waiting for more data: %d/%d bytes", len(self._data), expected_len
            )
            return

        # Truncate if we received extra data
        frame = self._data[:expected_len]

        # Verify CRC
        payload = frame[:-2]
        received_crc = int.from_bytes(frame[-2:], byteorder="little")
        calculated_crc = crc_modbus(payload)

        if received_crc != calculated_crc:
            self._log.debug(
                "invalid CRC: 0x%04X != 0x%04X", received_crc, calculated_crc
            )
            self._data.clear()
            return

        self._log.debug("valid frame received: %d bytes", len(frame))
        self._data = frame
        self._data_event.set()

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        result: BMSSample = {}

        # Read basic data (command 1: 59 registers from 0x0000)
        cmd = self._build_read_cmd(*BMS.READ_CMD_1)
        await self._await_reply(cmd)

        # Parse response (skip 3-byte header: addr, func, byte_count)
        data = self._data[3:-2]  # Exclude header and CRC

        expected_bytes = BMS.READ_CMD_1[1] * 2  # registers * 2 bytes each
        if len(data) < expected_bytes:
            self._log.warning(
                "response too short: %d bytes, expected %d",
                len(data),
                expected_bytes,
            )
            return {}

        # Decode standard fields (framework-compliant names)
        result = BMS._decode_data(BMS._FIELDS, data, byteorder="big", start=0)

        # Parse MOS status manually (bits 14, 15 for charge/discharge)
        mos_status = int.from_bytes(
            data[BMS.OFF_MOS_STATUS : BMS.OFF_MOS_STATUS + 2], "big"
        )
        charge_mos, discharge_mos = self._parse_mos_status(mos_status)
        result["chrg_mosfet"] = charge_mos
        result["dischrg_mosfet"] = discharge_mos

        # Parse capacity values manually (stored as *10 mAh, convert to Ah)
        remain_cap = int.from_bytes(
            data[BMS.OFF_REMAIN_CAP : BMS.OFF_REMAIN_CAP + 2], "big"
        )
        full_cap = int.from_bytes(data[BMS.OFF_FULL_CAP : BMS.OFF_FULL_CAP + 2], "big")
        if remain_cap > 0:
            result["cycle_charge"] = (
                remain_cap / 100.0
            )  # Convert to Ah (*10 mAh / 1000)
        if full_cap > 0:
            result["design_capacity"] = full_cap // 100  # Convert to Ah (int)

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

        # Parse temperature values
        temp_count = result.get("temp_sensors", 0)
        temps: list[float] = []

        # Read temperature sensors (starting at byte 94)
        for i in range(min(temp_count, BMS.MAX_TEMP)):
            temp_offset = BMS.TEMP_START + (i * 2)
            if temp_offset + 2 <= len(data):  # pragma: no branch
                temp_raw = int.from_bytes(data[temp_offset : temp_offset + 2], "big")
                temps.append(self._convert_signed_temp(temp_raw))

        # Also read MOSFET temperature (at byte 114) if available
        if len(data) >= BMS.TEMP_MOS_OFFSET + 2:  # pragma: no branch
            mos_temp_raw = int.from_bytes(
                data[BMS.TEMP_MOS_OFFSET : BMS.TEMP_MOS_OFFSET + 2], "big"
            )
            if mos_temp_raw not in {0xFFFF, 0}:  # Valid temperature
                temps.append(self._convert_signed_temp(mos_temp_raw))

        if temps:
            result["temp_values"] = temps

        # Calculate delta voltage if we have cell voltages
        if "cell_voltages" in result and len(result["cell_voltages"]) > 1:
            cell_volts = result["cell_voltages"]
            result["delta_voltage"] = round(max(cell_volts) - min(cell_volts), 4)

        return result

    async def _fetch_device_info(self) -> BMSInfo:
        """Fetch device info from BMS via Modbus (READ_CMD_3)."""
        # First get standard BLE device info (may contain generic values)
        info: BMSInfo = await super()._fetch_device_info()

        try:
            # Read device info registers via Modbus
            cmd = self._build_read_cmd(*BMS.READ_CMD_3)
            await self._await_reply(cmd)

            # Parse response
            data = self._data[3:-2]  # Skip header and CRC

            self._log.debug("device info raw (%d bytes): %s", len(data), data.hex(" "))

            if len(data) >= 60:
                # BMS Version: bytes 0-17 (null-terminated string)
                # Example: "P4S200A-40569-1.02"
                version_bytes = data[0:18].rstrip(b"\x00")
                if version_bytes:
                    info["sw_version"] = version_bytes.decode(
                        "ascii", errors="ignore"
                    ).strip()

                # BMS Serial Number: bytes 20-39 (with trailing spaces)
                # Example: "4056911A1100032P    "
                sn_bytes = data[20:40].rstrip(b"\x00").rstrip(b" ")
                if sn_bytes:
                    info["serial_number"] = sn_bytes.decode(
                        "ascii", errors="ignore"
                    ).strip()

                # Pack Serial Number: bytes 40-60 (stored in model_id field)
                # Example: "GP-LA12-31420250618"
                pack_sn_bytes = data[40:60].rstrip(b"\x00")
                if pack_sn_bytes:
                    info["model_id"] = pack_sn_bytes.decode(
                        "ascii", errors="ignore"
                    ).strip()

        except Exception as exc:  # noqa: BLE001
            self._log.debug("failed to read device info via Modbus: %s", exc)

        return info
