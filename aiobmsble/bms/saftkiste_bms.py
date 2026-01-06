"""Module to support Saftkiste BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from functools import cache
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSDp, BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS


class BMS(BaseBMS):
    """Dummy BMS implementation."""

    INFO: BMSInfo = {
        "default_manufacturer": "Batterieschmiede",
        "default_model": "Saftkiste BMS",
    }
    _HEAD: Final[bytes] = b"\xf0\xff"  # beginning of frame
    _MAX_CELLS: Final[int] = 4
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("current", 15, 2, True, lambda x: x / 100, 0x2),
        BMSDp("cycles", 25, 2, False, idx=0x2),  # after cell voltages(!)
        BMSDp("design_capacity", 11, 2, False, idx=0x2),
        BMSDp("voltage", 13, 2, False, lambda x: x / 1000, 0x2),
    )

    def __init__(self, ble_device: BLEDevice, keep_alive: bool = True) -> None:
        """Initialize BMS."""
        super().__init__(ble_device, keep_alive)
        self._data_final: dict[int, bytearray] = {}

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            {
                "manufacturer_id": 4660,
                "manufacturer_data_start": list(range(1, 8)),
                "connectable": True,
            }
        ]

    @staticmethod
    def uuid_services() -> list[str]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return [normalize_uuid_str("6e400001-b5a3-f393-e0a9-e50e24dcca9e")]

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        return "6e400002-b5a3-f393-e0a9-e50e24dcca9e"

    # async def _fetch_device_info(self) -> BMSInfo:
    #     """Fetch the device information via BLE."""
    #     return BMSInfo(
    #         default_manufacturer="Dummy manufacturer", default_model="Dummy BMS"
    #     )  # TODO: implement query code or remove function to query service 0x180A

    # @staticmethod
    # def _raw_values() -> frozenset[BMSValue]:
    #     return frozenset({"runtime"})  # never calculate, e.g. runtime

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        self._log.debug("RX BLE data: %s", data)

        if not data.startswith(BMS._HEAD):
            self._log.debug("incorrect SOF")
            return

        # if (crc := crc_sum(self._data[:-1])) != self._data[-1]:
        #     self._log.debug("invalid checksum 0x%X != 0x%X", self._data[-1], crc)
        #     return

        self._data_final[data[2]] = data.copy()
        self._data_event.set()

    @staticmethod
    @cache
    def _cmd(cmd: int) -> bytes:
        """Assemble a Seplos BMS command."""
        assert cmd in range(6)
        return BMS._HEAD + cmd.to_bytes(1)

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        self._log.debug("replace with command to UUID %s", BMS.uuid_tx())
        await self._await_reply(BMS._cmd(0x02))

        result: BMSSample = self._decode_data(
            BMS._FIELDS, self._data_final, byteorder="little"
        )
        result["cell_voltages"] = BMS._cell_voltages(
            self._data_final[0x2], cells=BMS._MAX_CELLS, start=17, byteorder="little"
        )

        return result
