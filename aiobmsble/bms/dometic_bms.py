"""Module to support Dometic BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

import asyncio
from typing import Final, Literal

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSDp, BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS


class BMS(BaseBMS):
    """Dometic BMS implementation."""

    INFO: BMSInfo = {
        "default_manufacturer": "Dometic",
        "default_model": "Büttner BMS",
    }
    _HEAD: Final[bytes] = b"\x23\x85"
    _FRAME_LEN: Final[int] = 8
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("voltage", 4, 2, False, lambda x: x / 100, 0x02),
        BMSDp("current", 6, 2, False, lambda x: (x if x<=32767 else 32767-x) / 100, 0x02),
        BMSDp("design_capacity", 4, 4, False, idx=0x07),
        BMSDp("battery_level", 4, 1, False, idx=0x0B),
        BMSDp("temperature", 4, 2, False, lambda x: (x - 500) / 10, 0x0C),
        BMSDp("cycle_capacity", 4, 2, False, idx=0x36),
        BMSDp("battery_health", 4, 1, False, idx=0x0E),
    )
    _CMDS: Final[set[int]] = {field.idx for field in _FIELDS} | {0x56, 0x57}

    def __init__(self, ble_device: BLEDevice, keep_alive: bool = True) -> None:
        """Initialize BMS."""
        super().__init__(ble_device, keep_alive)
        self._data_final: dict[int, dict[int, bytearray]] = {}

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            {
                "manufacturer_id": 2117,
                "manufacturer_data_start": [0x14, 0x85],
                "connectable": True,
            }
        ]

    @staticmethod
    def uuid_services() -> list[str]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return [normalize_uuid_str("fefb")]

    @staticmethod
    def uuid_rx() -> str:
        """Return UUID of characteristic that provides notification/read property."""
        return "00000002-0000-1000-8000-008025000000"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        raise NotImplementedError

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
            self._log.debug("unkown SOF (%s)", data[:2].hex(" "))
            return

        if len(data) != BMS._FRAME_LEN:
            self._log.debug(
                "incorrect frame length %d != %d", len(data), BMS._FRAME_LEN
            )
            return

        self._data_final.setdefault(data[2], {})[data[3]] = data.copy()
        for device in self._data_final:
            if not BMS._CMDS.issubset(self._data_final[device].keys()):
                break
        else:
            self._data_event.set()

    @staticmethod
    def _cellV(
        data: dict[int, bytearray],
        *,
        cells: int,
    ) -> list[float]:
        """Return cell voltages from status message."""
        voltages: list[float] = []
        for i in range(int(cells // 2)):
            voltages.extend(BMS._cell_voltages(data[0x56 + i], cells=2, start=4))
        return voltages

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""

        await asyncio.wait_for(self._wait_event(), timeout=BMS.TIMEOUT)
        result: BMSSample = self._decode_data(BMS._FIELDS, next(iter(self._data_final.values())))
        result["cell_voltages"] = BMS._cellV(next(iter(self._data_final.values())), cells=4)

        self._data_final.clear()
        return result
