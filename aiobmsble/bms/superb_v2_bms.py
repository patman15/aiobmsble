"""Module to support Super-B v2 BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice

from aiobmsble import BMSDp, BMSInfo, BMSSample, BMSValue, MatcherPattern
from aiobmsble.basebms import BaseBMS


class BMS(BaseBMS):
    """Super-B v2 BMS implementation."""

    INFO: BMSInfo = {"default_manufacturer": "Super-B", "default_model": "Epsilon v2"}
    _NOTIFY_CHAR: Final[str] = "e0fef452-9d2b-4005-a1e3-69fe1102b436"
    _FRAME_LEN: Final[int] = 24
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("current", 6, 4, True, lambda x: x / 1000, 0x2),
        BMSDp("voltage", 10, 2, False, lambda x: x / 1000, 0x2),
        BMSDp("battery_level", 1, 1, False, idx=0x0),
        BMSDp("battery_health", 19, 1, False, idx=0x0),
        BMSDp("runtime", 20, 4, False, idx=0x0),
        BMSDp("cycles", 18, 1, False, idx=0x0),
        # BMSDp("problem_code", 1, 1, False, lambda x: (x & 0x1) ^ 0x1),
        # BMSDp("balancer", 1, 1, False, lambda x: bool(x & 0x80)),
    )
    _CMDS: Final[set[int]] = {field.idx for field in _FIELDS}

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
        return ["cf9ccdf7-eee9-43ce-87a5-82b54af5324e"]

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "cf9ccdfa-eee9-43ce-87a5-82b54af5324e"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        return "cf9ccdfa-eee9-43ce-87a5-82b54af5324e"

    @staticmethod
    def _raw_values() -> frozenset[BMSValue]:
        return frozenset({"runtime"})  # never calculate runtime

    async def _init_connection(
        self, char_notify: BleakGATTCharacteristic | int | str | None = None
    ) -> None:
        await super()._init_connection(char_notify)
        # subscribe to second notify characteristic
        await self._client.start_notify(
            BMS._NOTIFY_CHAR, getattr(self, "_notification_handler")
        )

    def _notification_handler(
        self, sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        self._log.debug("RX BLE data from %s: %s", str(sender)[:8], data)

        if len(data) != BMS._FRAME_LEN:
            self._log.debug("incorrect frame length")
            return

        self._data_final[data[0]] = data.copy()
        if BMS._CMDS.issubset(self._data_final.keys()):
            self._data_event.set()

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        await self._await_reply(b"\x21\x54\x00")
        result: BMSSample = self._decode_data(BMS._FIELDS, self._data_final)

        # remove runtime if not discharging
        if result.get("runtime", 0) == 0xFFFFFFFF:
            result.pop("runtime", None)
        self._data_final.clear()
        return result
