"""Module to support TianPwr BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import (
    BMSConfig,
    BMSDp,
    BMSInfo,
    BMSPrbDef,
    BMSSample,
    MatcherPattern,
    PrbType as PT,
    Severity as SV,
    TempSensor,
)
from aiobmsble.basebms import BaseBMS, b2str


class BMS(BaseBMS):
    """TianPwr BMS implementation."""

    INFO: BMSInfo = {"manufacturer": "TianPwr", "model": "smart BMS"}
    _HEAD: Final[bytes] = b"\x55"
    _TAIL: Final[bytes] = b"\xaa"
    _RDCMD: Final[bytes] = b"\x04"
    _MAX_CELLS: Final[int] = 16
    _MAX_TEMP: Final[int] = 6
    _MIN_LEN: Final[int] = 4
    _DEF_LEN: Final[int] = 20
    _PRB_MASK: Final[int] = 0x7FFFFFFCFFFFFFFF
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("battery_level", 3, 2, False, idx=0x83),
        BMSDp("voltage", 5, 2, False, lambda x: x / 100, 0x83),
        BMSDp("current", 13, 2, True, lambda x: x / 100, 0x83),
        BMSDp("battery_health", 17, 2, False, idx=0x83),
        BMSDp("problem_code", 11, 8, False, lambda x: x & BMS._PRB_MASK, 0x84),
        BMSDp("cell_count", 3, 1, False, idx=0x84),
        BMSDp("temp_count", 4, 1, False, idx=0x84),
        BMSDp("design_capacity", 5, 2, False, lambda x: x // 100, 0x84),
        BMSDp("cycle_charge", 7, 2, False, lambda x: x / 100, 0x84),
        BMSDp("cycles", 9, 2, False, idx=0x84),
        BMSDp("balancer", 13, 2, False, idx=0x85),
        BMSDp("chrg_mosfet", 4, 1, False, lambda x: bool(x & 0x2), 0x85),
        BMSDp("dischrg_mosfet", 4, 1, False, lambda x: bool(x & 0x1), 0x85),
    )
    # problem_code bit layout (64 bit, MSB first): voltage status 63-48, current status 47-32,
    # temperature status 31-16 (warnings 31-24, protections 23-16), alarms 15-0
    _PROBLEMS: tuple[BMSPrbDef, ...] = (
        # alarms (bits 0-15)
        BMSPrbDef(1 << 0, PT.CELL_IMBALANCE, SV.WARN),
        BMSPrbDef(1 << 1, PT.FET_FAILURE, text="Charge MOSFET damaged"),
        BMSPrbDef(1 << 2, PT.OTHER, SV.FAULT, text="SD card failure"),
        BMSPrbDef(1 << 3, PT.OTHER, SV.FAULT, text="SPI failure"),
        BMSPrbDef(1 << 4, PT.OTHER, SV.FAULT, text="EEPROM failure"),
        BMSPrbDef(1 << 5, PT.OTHER, SV.FAULT, text="LED failure"),
        BMSPrbDef(1 << 6, PT.OTHER, SV.FAULT, text="Buzzer failure"),
        BMSPrbDef(1 << 7, PT.LOW_SOC),
        BMSPrbDef(1 << 8, PT.MOSFET_OVERTEMP, SV.PROTECT),
        BMSPrbDef(1 << 9, PT.MOSFET_OVERTEMP, SV.WARN),
        BMSPrbDef(1 << 10, PT.OTHER, SV.FAULT, text="Current limiter board failure"),
        BMSPrbDef(1 << 11, PT.SENSOR_FAILURE, text="Sampling failure"),
        BMSPrbDef(1 << 12, PT.CELL_FAILURE),
        BMSPrbDef(1 << 13, PT.SENSOR_FAILURE, text="NTC fault"),
        BMSPrbDef(1 << 14, PT.FET_FAILURE, text="Charge MOSFET fault"),
        BMSPrbDef(1 << 15, PT.FET_FAILURE, text="Discharge MOSFET fault"),
        # temperature protections (bits 16-23) and warnings (bits 24-31), same order
        BMSPrbDef(1 << 16, PT.CHARGE_OVERTEMP, SV.PROTECT),
        BMSPrbDef(1 << 17, PT.CHARGE_UNDERTEMP, SV.PROTECT),
        BMSPrbDef(1 << 18, PT.DISCHARGE_OVERTEMP, SV.PROTECT),
        BMSPrbDef(1 << 19, PT.DISCHARGE_UNDERTEMP, SV.PROTECT),
        BMSPrbDef(1 << 20, PT.AMBIENT_OVERTEMP, SV.PROTECT),
        BMSPrbDef(1 << 21, PT.AMBIENT_UNDERTEMP, SV.PROTECT),
        BMSPrbDef(1 << 22, PT.MOSFET_OVERTEMP, SV.PROTECT),
        BMSPrbDef(1 << 23, PT.OTHER, SV.PROTECT, text="MOSFET under-temperature"),
        BMSPrbDef(1 << 24, PT.CHARGE_OVERTEMP, SV.WARN),
        BMSPrbDef(1 << 25, PT.CHARGE_UNDERTEMP, SV.WARN),
        BMSPrbDef(1 << 26, PT.DISCHARGE_OVERTEMP, SV.WARN),
        BMSPrbDef(1 << 27, PT.DISCHARGE_UNDERTEMP, SV.WARN),
        BMSPrbDef(1 << 28, PT.AMBIENT_OVERTEMP, SV.WARN),
        BMSPrbDef(1 << 29, PT.AMBIENT_UNDERTEMP, SV.WARN),
        BMSPrbDef(1 << 30, PT.MOSFET_OVERTEMP, SV.WARN),
        BMSPrbDef(1 << 31, PT.OTHER, SV.WARN, text="MOSFET under-temperature warning"),
        # current status (bits 32-47), bits 32 and 33 are FET state (not a problem)
        BMSPrbDef(1 << 34, PT.CHARGE_OVERCURRENT, SV.PROTECT),
        BMSPrbDef(1 << 35, PT.SHORT_CIRCUIT),
        BMSPrbDef(1 << 36, PT.DISCHARGE_OVERCURRENT, SV.PROTECT, text="Discharge overcurrent 1"),
        BMSPrbDef(1 << 37, PT.DISCHARGE_OVERCURRENT, SV.PROTECT, text="Discharge overcurrent 2"),
        BMSPrbDef(1 << 38, PT.CHARGE_OVERCURRENT, SV.WARN, text="Charge current warning"),
        BMSPrbDef(1 << 39, PT.DISCHARGE_OVERCURRENT, SV.WARN, text="Discharge current warning"),
        BMSPrbDef(1 << 46, PT.FET_LOCKED, SV.PROTECT, text="Anti-theft lock"),
        # voltage status (bits 48-63), bit 63 is sleep (not a problem)
        BMSPrbDef(1 << 48, PT.CELL_OVERVOLTAGE),
        BMSPrbDef(1 << 49, PT.CELL_UNDERVOLTAGE),
        BMSPrbDef(1 << 50, PT.PACK_OVERVOLTAGE),
        BMSPrbDef(1 << 51, PT.PACK_UNDERVOLTAGE),
        BMSPrbDef(1 << 52, PT.CELL_OVERVOLTAGE, SV.WARN),
        BMSPrbDef(1 << 53, PT.CELL_UNDERVOLTAGE, SV.WARN),
        BMSPrbDef(1 << 54, PT.PACK_OVERVOLTAGE, SV.WARN),
        BMSPrbDef(1 << 55, PT.PACK_UNDERVOLTAGE, SV.WARN),
        BMSPrbDef(1 << 56, PT.CELL_IMBALANCE, SV.WARN),
    )
    _CMDS: Final = frozenset(field.idx for field in _FIELDS) | set({0x87})

    def __init__(
        self,
        ble_device: BLEDevice,
        config: BMSConfig | None = None,
        logger_name: str = "",
    ) -> None:
        """Initialize private BMS members."""
        super().__init__(ble_device, config, logger_name)
        self._msg: dict[int, bytes] = {}

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [{"local_name": "TP_*", "connectable": True}]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return (normalize_uuid_str("ff00"),)

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "ff01"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        return "ff02"

    async def _fetch_device_info(self) -> BMSInfo:
        """Fetch the device information via BLE."""
        for cmd in (0x81, 0x82):
            await self._await_msg(BMS._cmd(cmd))
        return {
            "sw_version": b2str(self._msg[0x81][3:-1]),
            "hw_version": b2str(self._msg[0x82][3:-1]),
        }

    def _notification_handler(self, _sender: BleakGATTCharacteristic, data: bytearray) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        self._log.debug("RX BLE data: %s", data)

        # verify that data is long enough
        if len(data) != BMS._DEF_LEN:
            self._log.debug("incorrect frame length")
            return

        if not data.startswith(BMS._HEAD):
            self._log.debug("incorrect SOF")
            return

        if not data.endswith(BMS._TAIL):
            self._log.debug("incorrect EOF")
            return

        self._msg[data[2]] = bytes(data)
        self._msg_event.set()

    @staticmethod
    def _cmd(addr: int) -> bytes:
        """Assemble a TianPwr BMS command."""
        return BMS._HEAD + BMS._RDCMD + addr.to_bytes(1) + BMS._TAIL

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""

        self._msg.clear()
        for cmd in BMS._CMDS:
            await self._await_msg(BMS._cmd(cmd))

        if not BMS._CMDS.issubset(self._msg):
            self._log.debug("incomplete data set %s", self._msg.keys())
            raise ValueError("BMS data incomplete.")

        result: BMSSample = BMS._decode_data(BMS._FIELDS, self._msg)

        for cmd in range(0x88, 0x89 + min(result.get("cell_count", 0), BMS._MAX_CELLS) // 8):
            await self._await_msg(BMS._cmd(cmd))
            result["cell_voltages"] = result.setdefault("cell_voltages", []) + BMS._cell_voltages(
                self._msg.get(cmd, b""), cells=8, start=3
            )

        result["temperature"] = BMS._temperature(
            self._msg[0x87],
            values=min(BMS._MAX_TEMP, result.get("temp_count", 0)),
            start=3,
            divider=10,
        )

        for idx, sensor_t in ((9, TempSensor.T.AMBIENT), (11, TempSensor.T.MOSFET)):
            result["temperature"] += BMS._temperature(
                self._msg[0x83], start=idx, divider=10, types=(sensor_t,)
            )

        return result
