"""Module to support JBD smart BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSInfo, MatcherPattern
from aiobmsble.bms.jbd_bms import BMS as JbdBMS


class BMS(JbdBMS):
    """Eleksol battery BMS class implementation."""

    INFO: BMSInfo = {"default_manufacturer": "Jiabaida", "default_model": "Eleksol BMS"}

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            MatcherPattern(
                oui=oui, service_uuid=BMS.uuid_services()[0], connectable=True
            )
            for oui in (
                "A4:C1:37",
                "A4:C1:38",
                "A5:C2:37",
                "A5:C2:39",
                "AA:C2:37",
            )
        ]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return (normalize_uuid_str("ff06"),)

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "ff07"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        return "ff08"
