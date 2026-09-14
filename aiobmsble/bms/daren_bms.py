"""Module to support Daren smart BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from typing import Final

from aiobmsble import BMSDp, BMSInfo, MatcherPattern, TempSensor as TS
from aiobmsble.basebms import b2str, swap32
from aiobmsble.bms.jbd_bms import BMS as JBDBMS


class BMS(JBDBMS):
    """Daren smart BMS class implementation."""

    INFO: BMSInfo = {"default_manufacturer": "Daren", "default_model": "smart BMS"}
    _VALID_CMD: frozenset[int] = frozenset({0x03, 0x04, 0x05, 0x08, 0xFF})
    _MAX_TEMP_COUNT: Final[int] = 4
    _TEMP_TYPES: tuple[TS.T, ...] = (TS.T.CELL,) * 4 + (TS.T.MOSFET, TS.T.AMBIENT)
    _FIELDS: tuple[BMSDp, ...] = (
        BMSDp("voltage", 4, 2, False, lambda x: x / 100),
        BMSDp("current", 6, 2, True, lambda x: x / 100),
        BMSDp("cycle_charge", 8, 2, False, lambda x: x / 100),
        BMSDp("design_capacity", 10, 2, False, lambda x: x // 100),
        BMSDp("cycles", 12, 2, False),
        BMSDp("balancer", 16, 4, False, swap32),
        BMSDp("problem_code", 20, 2, False),
        BMSDp("battery_level", 23, 1, False),
        BMSDp("chrg_mosfet", 24, 1, False, lambda x: bool(x & 0x1)),
        BMSDp("dischrg_mosfet", 24, 1, False, lambda x: bool(x & 0x2)),
        BMSDp("cell_count", 25, 1, False, lambda x: min(x, BMS._MAX_CELL_COUNT)),
        BMSDp("temp_sensors", 26, 1, False, lambda x: min(x, BMS._MAX_TEMP_COUNT) + 2),
        # extended frame fields, overwrite previous fields
        BMSDp("battery_health", 39, 1, False),
        BMSDp("cycle_charge", 43, 2, False, lambda x: x / 10),
        BMSDp("design_capacity", 45, 2, False, lambda x: x / 10),
        BMSDp("current", 49, 2, True, lambda x: x / 10),
    )

    accept_secret: bool = False

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            MatcherPattern(
                local_name=pattern,
                service_uuid=BMS.uuid_services()[0],
                connectable=True,
            )
            for pattern in ("DWF*",)  # Daren BMS, Docan battery
        ]

    async def _fetch_device_info(self) -> BMSInfo:
        """Fetch the device information via BLE."""
        await self._await_cmd_resp(0x08)
        result: BMSInfo = {
            "fw_version": b2str(self._msg[177:197]),
            "hw_version": b2str(self._msg[117:127]),
            "sw_version": b2str(self._msg[127:157]),
            "model": b2str(self._msg[64:94]),
        }
        return result
