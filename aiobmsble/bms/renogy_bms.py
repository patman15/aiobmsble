"""Module to support Renogy BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

import logging
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSConfig, BMSInfo, BMSSample, PrbType as PT, Severity as SV
from aiobmsble.basebms import BaseBMS
from aiobmsble.exceptions import BMSDataError
from aiobmsble.plugin import BMSDp, BMSPrbDef, BMSValue, MatcherPattern, b2str, crc_modbus


class BMS(BaseBMS):
    """Renogy battery class implementation."""

    INFO: BMSInfo = {"manufacturer": "Renogy", "model": "Bluetooth battery"}
    _HEAD: bytes = b"\x30\x03"  # SOP, read fct (x03)
    _CRC_POS: Final[int] = -2
    _TEMP_POS: Final[int] = 37
    _CELL_POS: Final[int] = 3
    _MIN_LEN: Final[int] = 5
    _PRB_MASK: Final[int] = ~((0xE << 16) | (0xFF << 8))
    FIELDS: tuple[BMSDp[BMSValue], ...] = (
        BMSDp("voltage", 5, 2, False, lambda x: x / 10),
        BMSDp("current", 3, 2, True, lambda x: x / 100),
        BMSDp("design_capacity", 11, 4, False, lambda x: x // 1000),
        BMSDp("cycle_charge", 7, 4, False, lambda x: x / 1000),
        BMSDp("cycles", 15, 2, False),
    )
    _PROBLEMS: tuple[BMSPrbDef, ...] = (
        BMSPrbDef(1 << 16, PT.SHORT_CIRCUIT),
        BMSPrbDef(1 << 20, PT.CHARGE_OVERCURRENT, text="Charge overcurrent 2"),
        BMSPrbDef(1 << 21, PT.DISCHARGE_OVERCURRENT, text="Discharge overcurrent 2"),
        BMSPrbDef(1 << 22, PT.PACK_OVERVOLTAGE),
        BMSPrbDef(1 << 23, PT.CELL_UNDERVOLTAGE),
        BMSPrbDef(1 << 24, PT.CELL_OVERVOLTAGE),
        BMSPrbDef(1 << 25, PT.CHARGE_OVERCURRENT, text="Charge overcurrent 1"),
        BMSPrbDef(1 << 26, PT.DISCHARGE_OVERCURRENT, text="Discharge overcurrent 1"),
        BMSPrbDef(1 << 27, PT.DISCHARGE_UNDERTEMP),
        BMSPrbDef(1 << 28, PT.DISCHARGE_OVERTEMP),
        BMSPrbDef(1 << 29, PT.CHARGE_UNDERTEMP),
        BMSPrbDef(1 << 30, PT.CHARGE_OVERTEMP),
        BMSPrbDef(1 << 31, PT.PACK_UNDERVOLTAGE),
        BMSPrbDef(1 << 0, PT.CELL_UNDERVOLTAGE, SV.WARN),
        BMSPrbDef(1 << 1, PT.CELL_OVERVOLTAGE, SV.WARN),
        BMSPrbDef(1 << 2, PT.PACK_UNDERVOLTAGE, SV.WARN),
        BMSPrbDef(1 << 3, PT.PACK_OVERVOLTAGE, SV.WARN),
        BMSPrbDef(1 << 4, PT.CHARGE_UNDERTEMP, SV.WARN),
        BMSPrbDef(1 << 5, PT.CHARGE_OVERTEMP, SV.WARN),
        BMSPrbDef(1 << 6, PT.DISCHARGE_UNDERTEMP, SV.WARN),
        BMSPrbDef(1 << 7, PT.DISCHARGE_OVERTEMP, SV.WARN),
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

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            {
                "local_name": "BT-TH-*",
                "service_uuid": BMS.uuid_services()[0],
                "connectable": True,
            },
        ]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return (normalize_uuid_str("ffd0"), normalize_uuid_str("fff0"))

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "fff1"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        return "ffd1"

    async def _fetch_device_info(self) -> BMSInfo:
        """Fetch the device information via BLE."""
        await self._await_msg(self._cmd_modbus(dev_id=0x30, addr=0x13F0, count=0x1C))
        return {
            "serial_number": b2str(self._msg[15:31]),
            "name": b2str(self._msg[39:55]),
            "sw_version": b2str(self._msg[55:59]),
        }

    def _notification_handler(self, sender: BleakGATTCharacteristic, data: bytearray) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        self._log.debug("RX BLE data: %s", data)

        if not data.startswith(BMS._HEAD) or len(data) < 3:
            self._log.debug("incorrect SOF")
            return

        if data[2] + BMS._MIN_LEN != len(data):
            self._log.debug("incorrect frame length: %i != %i", len(data), data[2] + BMS._MIN_LEN)
            return

        if not self._check_integrity(
            data,
            crc_modbus,
            slice(None, BMS._CRC_POS),
            slice(BMS._CRC_POS, None),
            "little",
        ):
            return

        self._msg = bytes(data)
        self._msg_event.set()

    @staticmethod
    def _read_int16(data: bytes, pos: int, signed: bool = False) -> int:
        return int.from_bytes(data[pos : pos + 2], byteorder="big", signed=signed)

    async def _update(self) -> BMSSample:
        """Update battery status information."""

        await self._await_msg(self._cmd_modbus(dev_id=0x30, addr=0x13B2, count=0x7))
        result: BMSSample = BMS._decode_data(type(self).FIELDS, self._msg)

        await self._await_msg(self._cmd_modbus(dev_id=0x30, addr=0x1388, count=0x22))
        result["cell_count"] = BMS._read_int16(self._msg, BMS._CELL_POS)
        result["cell_voltages"] = BMS._cell_voltages(
            self._msg,
            cells=min(16, result.get("cell_count", 0)),
            start=BMS._CELL_POS + 2,
            byteorder="big",
            divider=10,
        )

        result["temp_count"] = BMS._read_int16(self._msg, BMS._TEMP_POS)
        result["temperature"] = BMS._temperature(
            self._msg,
            values=min(16, result.get("temp_count", 0)),
            start=BMS._TEMP_POS + 2,
            divider=10,
        )  # TODO: add other sensors, but all are 0 in test.

        await self._await_msg(self._cmd_modbus(dev_id=0x30, addr=0x13EC, count=0x8))
        if len(self._msg) < BMS._MIN_LEN + 0x8 * 2:
            raise BMSDataError("BMS data incomplete.")
        result["problem_code"] = (
            int.from_bytes(self._msg[3:19], byteorder="big") & BMS._PRB_MASK
        )
        result["chrg_mosfet"] = bool(self._msg[16] & 0x2)
        result["dischrg_mosfet"] = bool(self._msg[16] & 0x4)
        result["heater"] = bool(self._msg[17] & 0x20)

        return result
