"""Module to support PowerXtreme BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

import asyncio

from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSInfo, BMSSample, MatcherPattern
from aiobmsble.bms.topband_bms import BMS as TopbandBMS


class BMS(TopbandBMS):
    """PowerXtreme BMS implementation."""

    INFO: BMSInfo = {
        "default_manufacturer": "PowerXtreme",
        "default_model": "smart BMS",
    }

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            {
                "service_uuid": BMS.uuid_services()[0],
                "connectable": True,
                "manufacturer_id": 76,
            }
        ]

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

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""

        for cmd in (b"<B:AN>", b"<I:EM>", b"<I:WA>", b"<N:NA>"):
            try:
                await self._await_msg(cmd)
            except TimeoutError:
                continue
            await asyncio.sleep(0.5)
        return self._decode_data(BMS._FIELDS, self._msg, byteorder="little") | {
            "cell_voltages": BMS._cell_voltages(
                self._msg, cells=BMS._MAX_CELLS, start=22, byteorder="little"
            )
        }
