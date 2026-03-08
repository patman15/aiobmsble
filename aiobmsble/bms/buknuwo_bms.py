"""Module to support Buknuwo BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from functools import cache
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSDp, BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS, crc_modbus


class BMS(BaseBMS):
    """Dummy BMS implementation."""

    INFO: BMSInfo = {
        "default_manufacturer": "Buknuwo",
        "default_model": "smart battery",
    }
    _HEAD: Final[bytes] = b"\x01\x03"  # dev, read (0x03)
    _MIN_LEN: Final[int] = 5  # length of frame, including SOF and checksum
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("current", 0, 2, True, lambda x: x / 100),
        BMSDp("voltage", 2, 2, False, lambda x: x / 100),
        BMSDp("battery_level", 4, 2, False),
    )

    def __init__(self, ble_device: BLEDevice, keep_alive: bool = True) -> None:
        """Initialize BMS."""
        super().__init__(ble_device, keep_alive)
        self._exp_len: int = 0
        self._msg: bytes = b""

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [{"local_name": "CDZG*", "connectable": True}]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return (normalize_uuid_str("00002760-08c2-11e1-9073-0e8ac72e1001"),)

    @staticmethod
    def uuid_rx() -> str:
        """Return UUID of characteristic that provides notification/read property."""
        return "00002760-08c2-11e1-9073-0e8ac72e0002"

    @staticmethod
    def uuid_tx() -> str:
        """Return UUID of characteristic that provides write property."""
        return "00002760-08c2-11e1-9073-0e8ac72e0001"

    # @staticmethod
    # def _raw_values() -> frozenset[BMSValue]:
    #     return frozenset({"runtime"})  # never calculate, e.g. runtime

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""

        if (
            len(data) > BMS._MIN_LEN
            and data.startswith(BMS._HEAD)
            and len(self._frame) >= self._exp_len
        ):
            self._exp_len = BMS._MIN_LEN + data[2]
            self._frame = bytearray()

        self._frame += data
        self._log.debug(
            "RX BLE data (%s): %s", "start" if data == self._frame else "cnt.", data
        )

        if len(self._frame) < self._frame[2] + BMS._MIN_LEN:
            return

        if (crc := crc_modbus(self._frame[:-2])) != int.from_bytes(
            self._frame[-2:], byteorder="little"
        ):
            self._log.debug(
                "invalid checksum 0x%X != 0x%X",
                int.from_bytes(self._frame[-2:], "little"),
                crc,
            )
            return

        self._msg = bytes(self._frame)
        self._msg_event.set()

    @staticmethod
    @cache
    def _cmd(addr: int, words: int) -> bytes:
        """Assemble a Buknuwo BMS command."""
        frame: bytearray = (
            bytearray(BMS._HEAD)
            + addr.to_bytes(2, byteorder="big")
            + words.to_bytes(2, byteorder="big")
        )
        frame.extend(crc_modbus(frame).to_bytes(2, "little"))
        return bytes(frame)

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        await self._await_msg(BMS._cmd(0x0, 0x3))

        return BMS._decode_data(BMS._FIELDS, self._msg)
