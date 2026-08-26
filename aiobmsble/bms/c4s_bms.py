"""Module to support "C4S100"-family generic Modbus-over-BLE Smart BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from typing import Final

from aiobmsble import BMSDp, BMSInfo, BMSSample, MatcherPattern, TempSensor
from aiobmsble.bms.vatrer_bms import BMS as VatrerBMS


class BMS(VatrerBMS):
    """C4S100-family generic Modbus-over-BLE Smart BMS (derived from VatrerBMS).

    Inherits the transport layer unchanged from VatrerBMS: uuid_services(),
    uuid_rx(), uuid_tx(), _notification_handler(), _HEAD, _FRAME_LEN, and
    __init__ are all identical between the two devices. See
    docs/c4s_bms.md for the full protocol writeup.
    """

    INFO: BMSInfo = {
        "default_manufacturer": "Generic",
        "default_model": "C4S100 Smart BMS (RC6621A)",
    }
    _CELLS: Final[int] = 4  # fixed 4S pack
    _TEMPS: Final[int] = 2  # 2 physical temp sensors (MOS_T, ENV_T), see docs
    _REG_COUNT: Final[int] = 0x46  # 70 holding registers polled in one request
    _RESP_LEN: Final[int] = _REG_COUNT * 2  # expected byte-count field (0x8C)

    # BMSDp(key, pos, size, signed, fct, idx); pos/idx documented in docs/c4s_bms.md
    _FIELDS: tuple[BMSDp, ...] = (
        BMSDp("voltage", 3, 2, False, lambda x: x / 100, _RESP_LEN),
        BMSDp("current", 5, 4, True, lambda x: x / 100, _RESP_LEN),
        BMSDp("battery_level", 9, 2, False, idx=_RESP_LEN),
        BMSDp("cycle_charge", 11, 2, False, lambda x: x / 100, _RESP_LEN),
        BMSDp(
            "design_capacity", 13, 2, False, lambda x: round(x / 100), _RESP_LEN
        ),
        BMSDp("cycles", 15, 2, False, idx=_RESP_LEN),
        BMSDp("battery_health", 17, 2, False, idx=_RESP_LEN),
        BMSDp("delta_voltage", 29, 2, False, lambda x: x / 1000, _RESP_LEN),
        BMSDp("cell_count", 45, 2, False, idx=_RESP_LEN),
    )

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            {  # observed name: "C4S100IE06007" (model prefix + serial, Unix glob)
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
        if BMS._RESP_LEN not in self._msg:
            self._log.debug("incomplete data set %s", self._msg.keys())
            raise TimeoutError("BMS data incomplete.")

        result: BMSSample = BMS._decode_data(BMS._FIELDS, self._msg)
        result["cell_voltages"] = BMS._cell_voltages(
            self._msg[BMS._RESP_LEN],
            cells=result.get("cell_count", BMS._CELLS),
            start=47,  # reg22
        )
        result["temp_sensors"] = BMS._TEMPS
        result["temp_values"] = BMS._temp_values(
            self._msg[BMS._RESP_LEN],
            start=35,  # reg16 (MOS_T), reg17 (ENV_T)
            values=BMS._TEMPS,
            types=(TempSensor.T.MOSFET, TempSensor.T.AMBIENT),
        )

        return result
