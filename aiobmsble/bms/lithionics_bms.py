"""Module to support Lithionics BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from aiobmsble import BMSInfo, MatcherPattern
from aiobmsble.bms.roypow_bms import BMS as RoyPowBMS


class BMS(RoyPowBMS):
    """Lithionics BMS implementation.

    Lithionics batteries use the same BLE protocol as RoyPow-based systems, so this
    class specializes identification while reusing the proven protocol implementation.
    """

    INFO: BMSInfo = {
        "default_manufacturer": "Lithionics",
        "default_model": "NeverDie smart BMS",
    }

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            {
                "local_name": pattern,
                "service_uuid": BMS.uuid_services()[0],
                "connectable": True,
            }
            for pattern in (
                "Lithionics*",
                "LITHIONICS*",
                "NeverDie*",
                "NEVERDIE*",
            )
        ]
