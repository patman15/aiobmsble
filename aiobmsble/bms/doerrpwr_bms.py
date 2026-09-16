"""Module to support Dörr Power BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from aiobmsble import BMSDp, BMSInfo, MatcherPattern

from .pwrboozt_bms import BMS as PowerBooztBMS


class BMS(PowerBooztBMS):
    """Dörr Power battery implementation."""

    INFO: BMSInfo = {
        "default_manufacturer": "Dörr",
        "default_model": "Power battery",
    }

    _FIELDS: tuple[BMSDp, ...] = (
        BMSDp("battery_level", 69, 1, False),
        BMSDp("battery_charging", 54, 1, False, lambda x: bool(x & 80)),
        # bit 31 (byte 54 bit 7) = charging flag, lower 16 bits = mA magnitude
        BMSDp(
            "current",
            54,
            4,
            False,
            lambda x: (x & 0xFFFF) / 1000 if x & 0x80000000 else -(x & 0xFFFF) / 1000,
        ),
        BMSDp("cycles", 67, 2, False),
        BMSDp("design_capacity", 70, 4, False, lambda x: x // 1000),
        BMSDp("voltage", 62, 2, False, lambda x: x / 1000),
    )

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            {
                "local_name": "BT-Battery*",
                "service_data_uuid": "0000ffe1-0000-1000-8000-00805f9b34fb",
                "connectable": True,
            },
        ]

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "fff6"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        return "fff6"
