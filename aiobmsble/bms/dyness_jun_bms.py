"""Module to support Dyness Junior BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSInfo, MatcherPattern
from aiobmsble.bms.jbd_bms import BMS as JbdBMS


class BMS(JbdBMS):
    """Dyness Junior BMS implementation."""

    INFO: BMSInfo = {
        "default_manufacturer": "Dyness",
        "default_model": "Junior BMS",
    }
    _INIT_CMD: Final[bytes] = b"\xff\xaa\x55\x00\x00\x77"  # initialization command

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [{"local_name": "R07*", "connectable": True}]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return (normalize_uuid_str("fe00"),)

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "fe02"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        return "fe01"

    async def _init_connection(
        self, char_notify: BleakGATTCharacteristic | int | str | None = None
    ) -> None:
        await self._await_msg(BMS._INIT_CMD, normalize_uuid_str("fed5"), wait_for_notify=False)
        await super()._init_connection(char_notify)
