"""Module to support Dummy BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice

from aiobmsble import BMSDp, BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS


class BMS(BaseBMS):
    """Dummy BMS implementation."""

    INFO: BMSInfo = {
        "default_manufacturer": "Dummy Manufacturer",
        "default_model": "dummy model",
    }  # TODO: fill correct manufacturer/model
    # _HEAD: Final[bytes] = b"\x00"  # beginning of frame
    # _TAIL: Final[bytes] = b"\xAA"  # end of frame
    # _FRAME_LEN: Final[int] = 10  # length of frame, including SOF and checksum
    # 00 23 04 13 00 00 f6 81 00 00 00 00 00 00 00 00 00 00 12 64 00 01 b1 d7
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("current", 6, 4, True, lambda x: x/1000, 0x2),
        BMSDp("voltage", 10, 2, False, lambda x: x/1000, 0x2),
        BMSDp("battery_level", 1, 1, False, idx= 0x0),
        BMSDp("battery_health", 19, 1, False, idx=0x0),
        BMSDp("cycles", 18, 1, False, idx=0x0),

        #BMSDp("runtime", 4, 4, False, float),
        #BMSDp("problem_code", 1, 1, False, lambda x: (x & 0x1) ^ 0x1),
        #BMSDp("balancer", 1, 1, False, lambda x: bool(x & 0x80)),
    )



    def __init__(self, ble_device: BLEDevice, keep_alive: bool = True) -> None:
        """Initialize BMS."""
        super().__init__(ble_device, keep_alive)
        self._data_final: dict[int, bytearray] = {}

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            MatcherPattern(
                local_name="Epsilon *",
                manufacturer_id=0x50BE,
                manufacturer_data_start=list(b"Epsilon V2"),
                connectable=True,
            )
        ]

    @staticmethod
    def uuid_services() -> list[str]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return ["e0fef452-9d2b-4005-a1e3-69fe1102b436"]

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "e0fef453-9d2b-4005-a1e3-69fe1102b436"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        raise NotImplementedError

    # @staticmethod
    # def _raw_values() -> frozenset[BMSValue]:
    #     return frozenset({"runtime"})  # never calculate, e.g. runtime

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        self._log.debug("RX BLE data: %s", data)

        if len(data) != 24:
            self._log.debug("incorrect frame length")
            return

        self._data_final[data[0]] = data.copy()
        self._data_event.set()

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""

        result: BMSSample = self._decode_data(BMS._FIELDS, self._data_final)

        # remove runtime if not discharging
        # if result.get("current", 0) >= 0:
        #     result.pop("runtime", None)

        return result
