"""Module to support E&J EJ PRO BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from aiobmsble import MatcherPattern
from aiobmsble.bms.ej_bms import BMS as EJBMS


class BMS(EJBMS):
    """E&J EJ PRO BMS implementation."""

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        # manufacturer_data_start=[0x11, 0x12, 0x13, 0x14, 0x15, 0x16],
        return [MatcherPattern(local_name="EJ*", manufacturer_id=21320, connectable=True)]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return ("00008000-0000-1000-8000-57616c6b697a",)

    @staticmethod
    def uuid_rx() -> str:
        """Return 128-bit UUID of characteristic that provides notifications."""
        return "00008002-0000-1000-8000-57616c6b697a"

    @staticmethod
    def uuid_tx() -> str:
        """Return 128-bit UUID of characteristic used to send commands."""
        return "00008001-0000-1000-8000-57616c6b697a"
