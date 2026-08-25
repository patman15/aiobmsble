"""Module to support "C4S100"-family generic Modbus-over-BLE Smart BMS.

Reverse-engineered from a 4S/100A LiFePO4 BMS sold under the local BLE name
"C4S100IEnnnnn" (app: "E-BMS"), HW module RC6621A (Onmicro HS6621CM,
transparent BLE-UART bridge). Shares the exact same transport layer and
Modbus register map as VatrerBMS (slave id 0x02, function 0x03, Read
Holding Registers over the Nordic UART Service) -- both are built around
the same RC6621A-style bridge module -- so this implementation derives
from VatrerBMS to reuse its transport-layer code as-is.

The register *query pattern* differs, though: VatrerBMS reads the table in
three separate partial requests ((0x0,0x14), (0x34,0x12), (0x15,0x1F)),
while this device only responds to a single combined read of all 70
holding registers (0x0, 0x46) -- verified against real hardware: sending
VatrerBMS's three partial-range requests to this device produced no
response at all for any of them, only the combined read works.

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
    __init__ are all identical between the two devices.
    """

    INFO: BMSInfo = {
        "default_manufacturer": "Generic",
        "default_model": "C4S100 Smart BMS (RC6621A)",
    }
    _CELLS: Final[int] = 4  # fixed 4S pack
    _TEMPS: Final[int] = 2  # 2 physical temp sensors (MOS_T, ENV_T); app mirrors
    #  them a second time as TCell1/TCell2 with identical values, not reported here
    _REG_COUNT: Final[int] = 0x46  # 70 holding registers polled in one request
    _RESP_LEN: Final[int] = _REG_COUNT * 2  # expected byte-count field (0x8C)

    # BMSDp(key, pos, size, signed, fct, idx)
    # pos = byte offset within the full received frame (0=addr,1=func,2=byte-count,
    # 3.. = register data, big-endian, 2 bytes/register)
    _FIELDS: tuple[BMSDp, ...] = (
        BMSDp("voltage", 3, 2, False, lambda x: x / 100, _RESP_LEN),  # reg0
        # reg1 (hi word) + reg2 (lo word): signed 32-bit current, 0.01A,
        # positive = charging, negative = discharging
        BMSDp("current", 5, 4, True, lambda x: x / 100, _RESP_LEN),  # reg1+reg2
        BMSDp("battery_level", 9, 2, False, idx=_RESP_LEN),  # reg3, SOC %
        BMSDp("cycle_charge", 11, 2, False, lambda x: x / 100, _RESP_LEN),  # reg4, Ah
        BMSDp(
            "design_capacity", 13, 2, False, lambda x: round(x / 100), _RESP_LEN
        ),  # reg5, Ah
        BMSDp("cycles", 15, 2, False, idx=_RESP_LEN),  # reg6
        BMSDp("battery_health", 17, 2, False, idx=_RESP_LEN),  # reg7, SOH %
        BMSDp("delta_voltage", 29, 2, False, lambda x: x / 1000, _RESP_LEN),  # reg13
        BMSDp("cell_count", 45, 2, False, idx=_RESP_LEN),  # reg21
    )
    _RESPS = frozenset(field.idx for field in _FIELDS)
    _CMDS: frozenset[tuple[int, int]] = frozenset({(0x0, _REG_COUNT)})

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
        for addr, length in BMS._CMDS:
            await self._await_msg(BMS._cmd_modbus(dev_id=0x2, addr=addr, count=length))
        if not BMS._RESPS.issubset(set(self._msg.keys())):
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
