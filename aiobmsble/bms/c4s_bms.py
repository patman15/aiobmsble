"""Module to support "C4S100"-family generic Modbus-over-BLE Smart BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from typing import Final

from aiobmsble import BMSDp, BMSInfo, BMSSample, MatcherPattern, TempSensor
from aiobmsble.bms.vatrer_bms import BMS as VatrerBMS


class BMS(VatrerBMS):
    """C4S100-family generic Modbus-over-BLE Smart BMS (derived from VatrerBMS)."""

    INFO: BMSInfo = {
        "default_manufacturer": "Generic",
        "default_model": "C4S100 Smart BMS (RC6621A)",
    }
    _TEMPS: Final[int] = 2  # 2 physical temp sensors (MOS_T, ENV_T), see docs
    _REG_COUNT: Final[int] = 0x46  # 70 holding registers polled in one request

    # BMSDp(key, pos, size, signed, fct, idx); pos/idx documented in docs/c4s_bms.md
    _FIELDS: tuple[BMSDp, ...] = (
        BMSDp("voltage", 3, 2, False, lambda x: x / 100),
        BMSDp("current", 5, 4, True, lambda x: x / 100),
        BMSDp("battery_level", 9, 2, False),
        BMSDp("cycle_charge", 11, 2, False, lambda x: x / 100),
        BMSDp("design_capacity", 13, 2, False, lambda x: round(x / 100)),
        BMSDp("cycles", 15, 2, False),
        BMSDp("battery_health", 17, 2, False),
        BMSDp("delta_voltage", 29, 2, False, lambda x: x / 1000),
        BMSDp("cell_count", 45, 2, False),
    )

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            {
                "local_name": "C4S100IE?????",
                "service_uuid": BMS.uuid_services()[0],
                "connectable": True,
            }
        ]

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        self._msg.clear()
        await self._await_msg(
            BMS._cmd_modbus(dev_id=0x2, addr=0x0, count=BMS._REG_COUNT)
        )
        if BMS._REG_COUNT * 2 not in self._msg:
            self._log.debug("incomplete data set %s", self._msg.keys())
            raise ValueError("BMS data incomplete.")

        result: BMSSample = BMS._decode_data(BMS._FIELDS, self._msg[BMS._REG_COUNT * 2])
        result["cell_voltages"] = BMS._cell_voltages(
            self._msg[BMS._REG_COUNT * 2], cells=result.get("cell_count", 0), start=47
        )
        result["temp_values"] = BMS._temp_values(
            self._msg[BMS._REG_COUNT * 2],
            start=35,
            values=BMS._TEMPS,
            types=(TempSensor.T.MOSFET, TempSensor.T.AMBIENT),
        )

        return result
