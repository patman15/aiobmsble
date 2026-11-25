"""Module to support EG4 BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

import logging
from typing import Final, Literal

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSConfig, BMSInfo, BMSSample, PrbType as PT, Severity as SV, TSKind
from aiobmsble.basebms import BaseBMS
from aiobmsble.plugin import BMSDp, BMSPrbDef, BMSValue, MatcherPattern, crc_modbus


class BMS(BaseBMS):
    """EG4 BMS implementation."""

    INFO: BMSInfo = {"manufacturer": "EG4 electronics", "model": "LL"}
    _HEAD: Final[bytes] = b"\x01\x03"  # dev addr, fct code (read)
    _MAX_CELLS: Final[int] = 16
    _MAX_TEMP: Final[int] = 6
    _MIN_LEN: Final[int] = 5
    _FIELDS: Final[tuple[BMSDp[BMSValue], ...]] = (
        BMSDp("voltage", 3, 2, False, lambda x: x / 100),
        BMSDp("current", 5, 2, True, lambda x: x / 10),
        BMSDp("battery_health", 49, 2, False),
        BMSDp("battery_level", 51, 2, False),
        BMSDp("cycle_charge", 45, 2, False, lambda x: x / 10),
        BMSDp("cycles", 61, 4, False),
        BMSDp("cell_count", 75, 2, False),
        BMSDp("design_capacity", 77, 2, False, lambda x: x // 10),
        BMSDp("problem_code", 55, 6, False),
        BMSDp("balancer", 79, 2, False),
    )
    # problem_code contains registers 26 (warning), 27 (protection), and 28 (error code).
    _PROBLEMS: tuple[BMSPrbDef, ...] = (
        BMSPrbDef(1 << 32, PT.PACK_OV, SV.WARN),
        BMSPrbDef(1 << 33, PT.CELL_OV, SV.WARN),
        BMSPrbDef(1 << 34, PT.PACK_UV, SV.WARN),
        BMSPrbDef(1 << 35, PT.CELL_UV, SV.WARN),
        BMSPrbDef(1 << 36, PT.CHARGE_OC, SV.WARN),
        BMSPrbDef(1 << 37, PT.DISCHARGE_OC, SV.WARN),
        BMSPrbDef(1 << 38, PT.SYSTEM_OT, SV.WARN),
        BMSPrbDef(1 << 39, PT.MOSFET_OT, SV.WARN),
        BMSPrbDef(1 << 40, PT.CHARGE_OT, SV.WARN),
        BMSPrbDef(1 << 41, PT.DISCHARGE_OT, SV.WARN),
        BMSPrbDef(1 << 42, PT.CHARGE_UT, SV.WARN),
        BMSPrbDef(1 << 43, PT.DISCHARGE_UT, SV.WARN),
        BMSPrbDef(1 << 44, PT.LOW_SOC, SV.WARN),
        BMSPrbDef(1 << 45, PT.OTHER, SV.WARN, text="Float stopped"),
        BMSPrbDef(1 << 16, PT.PACK_OV),
        BMSPrbDef(1 << 17, PT.CELL_OV),
        BMSPrbDef(1 << 18, PT.PACK_UV),
        BMSPrbDef(1 << 19, PT.CELL_UV),
        BMSPrbDef(1 << 20, PT.CHARGE_OC),
        BMSPrbDef(1 << 21, PT.DISCHARGE_OC),
        BMSPrbDef(1 << 22, PT.SYSTEM_OT),
        BMSPrbDef(1 << 23, PT.MOSFET_OT),
        BMSPrbDef(1 << 24, PT.CHARGE_OT),
        BMSPrbDef(1 << 25, PT.DISCHARGE_OT),
        BMSPrbDef(1 << 26, PT.CHARGE_UT),
        BMSPrbDef(1 << 27, PT.DISCHARGE_UT),
        BMSPrbDef(1 << 28, PT.LOW_SOC, SV.PROTECT),
        BMSPrbDef(1 << 29, PT.SHORT_CIRCUIT),
        BMSPrbDef(1 << 0, PT.OTHER, SV.FAULT, text="Voltage"),
        BMSPrbDef(1 << 1, PT.OTHER, SV.FAULT, text="Temperature"),
        BMSPrbDef(1 << 2, PT.OTHER, SV.FAULT, text="Current flow"),
        BMSPrbDef(1 << 4, PT.CELL_IMBALANCE),
    )
    _OPT_FIELDS: Final[tuple[Literal["cycle_charge", "cycles", "design_capacity"], ...]] = (
        "cycle_charge",
        "cycles",
        "design_capacity",
    )

    def __init__(
        self,
        ble_device: BLEDevice,
        config: BMSConfig | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        """Initialize private BMS members."""
        super().__init__(ble_device, config, logger)
        self._msg: bytes = b""
        self._exp_len: int = 0

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Return the advertisement patterns used to identify the BMS."""
        return [
            {
                "service_uuid": BMS.uuid_services()[0],
                "manufacturer_id": 0x6F80,
                "manufacturer_data_start": [0xB0],
                "connectable": True,
            },
            {
                "manufacturer_id": 0x45CC,
                "manufacturer_data_start": [0xA5],
                "connectable": True,
            },
        ]

    @staticmethod
    def uuid_services() -> tuple[str]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return (normalize_uuid_str("1000"),)

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "1002"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        return "1001"

    def _notification_handler(self, sender: BleakGATTCharacteristic, data: bytearray) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""

        if (
            len(data) > BMS._MIN_LEN
            and data.startswith(BMS._HEAD)
            and (not self._frame or len(self._frame) >= self._exp_len)
        ):
            self._exp_len = BMS._MIN_LEN + data[2]
            self._frame.clear()

        self._frame.extend(data)
        self._log.debug("RX BLE data (%s): %s", "start" if data == self._frame else "cnt.", data)

        # verify that data is long enough
        if len(self._frame) < self._exp_len:
            return

        del self._frame[self._exp_len :]

        if not self._check_integrity(
            self._frame, crc_modbus, slice(None, -2), slice(-2, None), "little"
        ):
            self._frame.clear()
            return

        self._msg = bytes(self._frame)
        self._msg_event.set()

    async def _update(self) -> BMSSample:
        """Update battery status information."""

        await self._await_msg(BMS._cmd_modbus(dev_id=0x1, addr=0x0, count=0x27))

        result: BMSSample = BMS._decode_data(BMS._FIELDS, self._msg)
        for field in BMS._OPT_FIELDS:
            if not result.get(field):
                del result[field]

        result["cell_voltages"] = BMS._decode_cells(
            self._msg, cells=min(result.get("cell_count", 0), BMS._MAX_CELLS), start=7
        )
        result["temperature"] = BMS._decode_temp(
            self._msg, values=1, start=39, types=(TSKind.PCB,)
        ) + BMS._decode_temp(
            self._msg,
            values=BMS._MAX_TEMP,
            start=69,
            size=1,
            types=(TSKind.CELL,) * BMS._MAX_TEMP,
        )
        return result
