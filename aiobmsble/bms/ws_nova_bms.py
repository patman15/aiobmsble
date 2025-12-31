"""Module to support Wattstunde Nova BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from functools import cache
from string import hexdigits
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSDp, BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS, barr2str, crc_sum


class BMS(BaseBMS):
    """Wattstunde Nova Core BMS implementation."""

    INFO: BMSInfo = {
        "default_manufacturer": "Wattstunde",
        "default_model": "Nova Core",
    }
    _HEAD: Final[bytes] = b"\x3a"  # beginning of frame
    _TAIL: Final[bytes] = b"\x7e"  # end of frame
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp(
            "current",
            2,
            4,
            False,
            lambda x: (x & 0x7FFF) / 1000 * (-1 if x >> 15 else 1),
        ),
        BMSDp("voltage", 10, 2, False, lambda x: x / 1000),
        BMSDp("cycles", 15, 2, False),
        BMSDp("battery_level", 17, 1, False),
        BMSDp("design_capacity", 18, 4, False, lambda x: x // 1000),
        BMSDp("cycle_charge", 22, 4, False, lambda x: x / 1000),
        BMSDp("heater", 107, 4, False, lambda x: bool(x)),
    )

    def __init__(self, ble_device: BLEDevice, keep_alive: bool = True) -> None:
        """Initialize BMS."""
        super().__init__(ble_device, keep_alive)
        self._data_final: bytearray = bytearray()

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            {
                "manufacturer_id": 28256,
                "manufacturer_data_start": [0x41],
                "connectable": True,
            }
        ]

    @staticmethod
    def uuid_services() -> list[str]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return [normalize_uuid_str("FFF0")]

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "FFF1"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        return "FFF1"

    async def _fetch_device_info(self) -> BMSInfo:
        """Fetch the device information via BLE."""
        await self._await_reply(
            self._cmd(b"\x30\x31\x35\x31\x35\x30\x30\x30\x30\x45\x46\x45")
        )
        self._data_event.clear()
        return BMSInfo(serial_number=barr2str(self._data_final[91:107]))

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""

        if data.startswith(BMS._HEAD):
            self._data.clear()

        self._data += data

        self._log.debug(
            "RX BLE data (%s): %s", "start" if data == self._data else "cnt.", data
        )

        if not (self._data.startswith(BMS._HEAD) and self._data.endswith(BMS._TAIL)):
            return

        if len(self._data) % 2:
            self._log.debug("incorrect frame length (%i)", len(self._data))
            return

        if not all(chr(c) in hexdigits for c in self._data[1:-1]):
            self._log.debug("incorrect frame encoding.")
            self._data.clear()
            return

        decoded = bytearray(
            b ^ int(self._data[7:9], 16)
            for b in bytes.fromhex(self._data[1:-3].decode("ascii"))
        )
        # incoming frames seem to have invalid checksum, thus not checked here

        if not decoded.startswith(b"\x01\x54"):
            self._log.debug("incorrect frame type.")
            self._data.clear()
            return

        self._data_final = decoded.copy()
        self._data_event.set()

    @staticmethod
    @cache
    def _cmd(cmd: bytes) -> bytes:
        """Assemble a Wattstunde Nova BMS command frame."""
        return BMS._HEAD + cmd + BMS._TAIL

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        if not self._data_event.is_set():
            self._log.debug("requesting BMS data")
            await self._await_reply(
                self._cmd(b"\x30\x31\x35\x31\x35\x30\x30\x30\x30\x45\x46\x45")
            )

        result: BMSSample = BMS._decode_data(BMS._FIELDS, self._data_final, offset=52)
        result["cell_voltages"] = BMS._cell_voltages(
            self._data_final, cells=16, start=12
        )
        result["temp_values"] = BMS._temp_values(
            self._data_final, values=4, start=48, size=1, signed=False, offset=40
        )
        self._data_event.clear()
        return result
