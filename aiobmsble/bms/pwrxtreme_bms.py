"""Module to support PowerXtreme BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSInfo, MatcherPattern
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
