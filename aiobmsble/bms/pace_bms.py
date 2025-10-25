"""Module to support Dummy BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from functools import cache
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSDp, BMSInfo, BMSSample, BMSValue, MatcherPattern
from aiobmsble.basebms import BaseBMS, barr2str, crc_modbus


class BMS(BaseBMS):
    """Dummy BMS implementation."""

    INFO: BMSInfo = {
        "default_manufacturer": "PeiCheng Technology",
        "default_model": "PACEEX Smart BMS",
    }  # TODO: fill correct manufacturer/model
    _HEAD: Final[bytes] = b"\x9a"  # beginning of frame
    _TAIL: Final[bytes] = b"\x9d"  # end of frame
    _MIN_LEN: Final[int] = 11  # minimal frame length
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("current", 1, 4, True, lambda x: x / 100),
        BMSDp("voltage", 5, 4, False, lambda x: x / 100),
        BMSDp("cycle_charge", 9, 4, False, lambda x: x / 100),
        BMSDp("design_capacity", 13, 4, False, lambda x: x // 100),
        BMSDp("battery_level", 21, 1, False, lambda x: x),
        # BMSDp("battery_health", 22, 1, False, lambda x: x),
        BMSDp("pack_count", 0, 1, False, lambda x: x),
        BMSDp("cycles", 23, 4, False, lambda x: x),
        # BMSDp("problem_code", 1, 9, False, lambda x: x & 0xFFFF00FF00FF0000FF, EIC_LEN),
    )

    def __init__(self, ble_device: BLEDevice, keep_alive: bool = True) -> None:
        """Initialize BMS."""
        super().__init__(ble_device, keep_alive)

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [{"local_name": "dummy", "connectable": True}]  # TODO: define matcher

    @staticmethod
    def uuid_services() -> list[str]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return [normalize_uuid_str("fff0")]

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
        result: BMSInfo = BMSInfo()
        await self._await_reply(self._cmd(b"\x00\x00\x00\x02\x00\x00"))
        length: int = self._data[8]
        result["serial_number"] = barr2str(self._data[9 : 9 + length])
        await self._await_reply(self._cmd(b"\x00\x00\x00\x01\x00\x00"))
        result["sw_version"] = barr2str(self._data[10:10+self._data[9]])
        result["hw_version"] = barr2str(self._data[65:65+self._data[64]])
        return result

    @staticmethod
    def _calc_values() -> frozenset[BMSValue]:
        return frozenset(
            {"power", "battery_charging"}
        )  # calculate further values from BMS provided set ones

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

        if (crc := crc_modbus(data[:-3])) != int.from_bytes(
            data[-3:-1], byteorder="big"
        ):
            self._log.debug(
                "invalid checksum 0x%X != 0x%X",
                int.from_bytes(data[-3:-1], byteorder="big"),
                crc,
            )
            return

        self._data = data.copy()
        self._data_event.set()

    @staticmethod
    @cache
    def _cmd(cmd: bytes, data: bytes = b"") -> bytes:
        """Assemble a Pace BMS command."""
        # assert device >= 0x00 and (device <= 0x10 or device in (0xC0, 0xE0))
        # assert cmd in (0x01, 0x04)  # allow only read commands
        # assert start >= 0 and count > 0 and start + count <= 0xFFFF
        frame: bytearray = bytearray(BMS._HEAD) + cmd + len(data).to_bytes(1) + data
        # frame += int.to_bytes(start, 2, byteorder="big")
        # frame += int.to_bytes(count * (0x10 if cmd == 0x1 else 0x1), 2, byteorder="big")
        frame += int.to_bytes(crc_modbus(frame), 2, byteorder="big") + BMS._TAIL
        return bytes(frame)

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        await self._await_reply(BMS._cmd(b"\x00\x00\x0a\x00\x00\x00"))

        return BMS._decode_data(BMS._FIELDS, self._data, byteorder="big", offset=8)
