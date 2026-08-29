"""Module to support PACEEX BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from enum import Enum
from functools import lru_cache
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSConfig, BMSDp, BMSInfo, BMSSample, MatcherPattern, TempSensor
from aiobmsble.basebms import BaseBMS, b2str, crc_modbus


class BMS(BaseBMS):
    """PACEEX BMS implementation."""

    INFO: BMSInfo = {
        "default_manufacturer": "PeiCheng Technology",
        "default_model": "PACEEX Smart BMS",
    }

    class _Cmd(bytes, Enum):
        SERIAL = b"\x00\x00\x00\x02\x00\x00"
        VERSIONS = b"\x00\x00\x00\x01\x00\x00"
        SYS_INFO = b"\x00\x00\x0a\x00\x00\x00"
        PACK_INFO = b"\x00\x00\x0a\x01\x00\x00"
        CELL_INFO = b"\x00\x00\x0a\x02\x00\x00"

    _HEAD: Final[bytes] = b"\x9a"
    _TAIL: Final[bytes] = b"\x9d"
    _FRM_TYPE: Final[slice] = slice(1, 7)
    _MIN_LEN: Final[int] = 11  # minimal frame length
    _CELL_POS: Final[int] = 12  # position of first cell voltage
    _FIELDS: Final[tuple[BMSDp, ...]] = (  # pack values, 0x0a01 reply
        BMSDp("current", 1, 2, True, lambda x: x / 100),
        BMSDp("voltage", 3, 2, False, lambda x: x / 100),
        BMSDp("cycle_charge", 5, 2, False, lambda x: x / 100),
        BMSDp("design_capacity", 9, 2, False, lambda x: x // 100),
        BMSDp("battery_level", 11, 1, False),
        BMSDp("battery_health", 12, 1, False),
        BMSDp("cycles", 13, 2, False),
    )

    def __init__(
        self,
        ble_device: BLEDevice,
        config: BMSConfig | None = None,
        logger_name: str = "",
    ) -> None:
        """Initialize private BMS members."""
        super().__init__(ble_device, config, logger_name)
        self._valid_reply: bytes = b""  # expected reply type
        self._msg: bytes = b""

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [{"local_name": "PC-????", "connectable": True}]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return (normalize_uuid_str("fff0"),)

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "fff1"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        return "fff2"

    async def _fetch_device_info(self) -> BMSInfo:
        """Fetch the device information via BLE."""
        _SW_VER_POS: Final[int] = 10
        _HW_VER_POS: Final[int] = 65

        result: BMSInfo = BMSInfo()
        await self._await_msg(self._cmd(BMS._Cmd.SERIAL))
        length: int = self._msg[8]
        result["serial_number"] = b2str(self._msg[9 : 9 + length])
        await self._await_msg(self._cmd(BMS._Cmd.VERSIONS))
        if len(self._msg) < _HW_VER_POS:
            raise ValueError("BMS data incomplete.")
        result["sw_version"] = b2str(
            self._msg[_SW_VER_POS : _SW_VER_POS + self._msg[_SW_VER_POS - 1]]
        )
        result["hw_version"] = b2str(
            self._msg[_HW_VER_POS : _HW_VER_POS + self._msg[_HW_VER_POS - 1]]
        )
        return result

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        self._log.debug("RX BLE data: %s", data)

        if not data.startswith(BMS._HEAD):
            self._log.debug("incorrect SOF")
            return

        if len(data) < BMS._MIN_LEN or len(data) != BMS._MIN_LEN + data[7]:
            self._log.debug("incorrect frame length")
            return

        if not self._check_integrity(data, crc_modbus, slice(None, -3), slice(-3, -1)):
            return

        if data[BMS._FRM_TYPE] != self._valid_reply:
            self._log.debug("unexpected response")
            return

        self._msg = bytes(data)
        self._msg_event.set()

    @staticmethod
    @lru_cache(maxsize=32)
    def _cmd(cmd: bytes, data: bytes = b"") -> bytes:
        """Assemble a Pace BMS command."""
        frame: bytearray = bytearray(BMS._HEAD) + cmd + len(data).to_bytes(1) + data
        frame.extend(int.to_bytes(crc_modbus(frame), 2, byteorder="big") + BMS._TAIL)
        return bytes(frame)

    async def _await_msg(
        self,
        data: bytes,
        char: int | str | None = None,
        wait_for_notify: bool = True,
        max_size: int = 0,
    ) -> None:
        """Send data to the BMS and wait for valid reply notification."""

        self._valid_reply = data[BMS._FRM_TYPE]  # expected reply type
        await super()._await_msg(data, char, wait_for_notify, max_size)

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        await self._await_msg(BMS._cmd(BMS._Cmd.PACK_INFO, b"\x01\x01"))
        result: BMSSample = BMS._decode_data(
            BMS._FIELDS, self._msg, byteorder="big", start=8
        )
        await self._await_msg(BMS._cmd(BMS._Cmd.CELL_INFO, b"\x01\x01"))
        if len(self._msg) < BMS._CELL_POS:
            raise ValueError("BMS data incomplete.")
        result["cell_count"] = self._msg[BMS._CELL_POS - 1]
        result["cell_voltages"] = BMS._cell_voltages(
            self._msg, cells=result["cell_count"], start=BMS._CELL_POS, gap=2
        )
        result["temp_values"] = BMS._temp_values(
            self._msg,
            values=6,
            start=14,
            gap=2,
            signed=False,
            offset=2731,
            divider=10,
            types=(TempSensor.T.CELL,) * 4
            + (TempSensor.T.MOSFET, TempSensor.T.AMBIENT),
        )
        await self._await_msg(BMS._cmd(BMS._Cmd.SYS_INFO))
        if pack_count := self._msg[8]:  # zero on all packs except the master
            result["pack_count"] = pack_count
        return result
