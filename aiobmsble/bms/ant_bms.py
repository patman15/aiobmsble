"""Module to support ANT BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from functools import lru_cache
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
from aiobmsble.basebms import BaseBMS, b2str, crc_modbus


class BMS(BaseBMS):
    """ANT BMS implementation."""

    INFO: BMSInfo = {"manufacturer": "ANT", "model": "smart BMS"}
    _HEAD: Final[bytes] = b"\x7e\xa1"
    _TAIL: Final[bytes] = b"\xaa\x55"
    _MIN_LEN: Final[int] = 10  # frame length without data
    _CMD_STAT: Final[int] = 0x01
    _CMD_DEV: Final[int] = 0x02
    _CMD_AUTH: Final[int] = 0x23
    _TEMP_POS: Final[int] = 8
    _MAX_TEMPS: Final[int] = 6
    _CELL_COUNT: Final[int] = 9
    _CELL_POS: Final[int] = 34
    _MAX_CELLS: Final[int] = 32
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("voltage", 38, 2, False, lambda x: x / 100),
        BMSDp("current", 40, 2, True, lambda x: x / 10),
        BMSDp("design_capacity", 50, 4, False, lambda x: x // 10**6),
        BMSDp("battery_level", 42, 2, False),
        BMSDp("battery_health", 44, 2, False),
        BMSDp(
            "problem_code",
            46,
            2,
            False,
            lambda x: (
                (x & 0xFF00 if (x >> 8) not in (0x1, 0x4) else 0)
                | (x & 0xFF if (x & 0xFF) > 0x1 else 0)
            ),
        ),
        BMSDp("cycle_charge", 54, 4, False, lambda x: x / 1e6),
        BMSDp("total_charge", 58, 4, False, lambda x: x // 1000),
        BMSDp("delta_cell_voltage", 82, 2, False, lambda x: x / 1000),
        BMSDp("power", 62, 4, True, float),
        BMSDp("chrg_mosfet", 47, 1, False, lambda x: x == 0x1),
        BMSDp("dischrg_mosfet", 46, 1, False, lambda x: x == 0x1),
        BMSDp("balancer", 48, 1, False, lambda x: bool(x & 0x4)),
    )
    # problem_code: chMosState (bits 8-15) | disMosState (bits 0-7), states 0/1 are no problem,
    # charge MOS state 0x04 (battery full) is not a problem
    _PROBLEMS: tuple[BMSPrbDef, ...] = (
        BMSPrbDef(0xFF, PT.CELL_UNDERVOLTAGE, value=0x02),
        BMSPrbDef(0xFF, PT.DISCHARGE_OVERCURRENT, value=0x03),
        BMSPrbDef(0xFF, PT.DISCHARGE_OVERCURRENT, value=0x04, text="Discharge overcurrent (2)"),
        BMSPrbDef(0xFF, PT.PACK_UNDERVOLTAGE, value=0x05),
        BMSPrbDef(0xFF, PT.DISCHARGE_OVERTEMP, value=0x06),
        BMSPrbDef(0xFF, PT.MOSFET_OVERTEMP, value=0x07),
        BMSPrbDef(0xFF, PT.OTHER, SV.PROTECT, value=0x08, text="Abnormal discharge current"),
        BMSPrbDef(0xFF, PT.OTHER, SV.FAULT, value=0x09, text="Balancing wire loose"),
        BMSPrbDef(0xFF, PT.AMBIENT_OVERTEMP, value=0x0A, text="Board overheated"),
        BMSPrbDef(0xFF, PT.OTHER, SV.INFO, value=0x0B, text="Charger connected"),
        BMSPrbDef(0xFF, PT.SHORT_CIRCUIT, value=0x0C),
        BMSPrbDef(0xFF, PT.FET_FAILURE, value=0x0D, text="Abnormal discharge MOSFET"),
        BMSPrbDef(0xFF, PT.FET_FAILURE, value=0x0E, text="Discharge MOSFET failed to open"),
        BMSPrbDef(0xFF, PT.FET_LOCKED, value=0x0F, text="Discharge MOSFET manually closed"),
        BMSPrbDef(0xFF, PT.PACK_UNDERVOLTAGE, value=0x10, text="Undervoltage (2)"),
        BMSPrbDef(0xFF, PT.DISCHARGE_UNDERTEMP, value=0x11),
        BMSPrbDef(0xFF, PT.CELL_IMBALANCE, SV.PROTECT, value=0x12),
        BMSPrbDef(0xFF, PT.OTHER, SV.FAULT, value=0x13, text="Discharge self-test error"),
        BMSPrbDef(0xFF00, PT.CELL_OVERVOLTAGE, value=0x0200),
        BMSPrbDef(0xFF00, PT.CHARGE_OVERCURRENT, value=0x0300),
        BMSPrbDef(0xFF00, PT.PACK_OVERVOLTAGE, value=0x0500),
        BMSPrbDef(0xFF00, PT.CHARGE_OVERTEMP, value=0x0600),
        BMSPrbDef(0xFF00, PT.MOSFET_OVERTEMP, value=0x0700),
        BMSPrbDef(0xFF00, PT.OTHER, SV.PROTECT, value=0x0800, text="Abnormal charge current"),
        BMSPrbDef(0xFF00, PT.OTHER, SV.FAULT, value=0x0900, text="Balancing wire loose"),
        BMSPrbDef(0xFF00, PT.AMBIENT_OVERTEMP, value=0x0A00, text="Board overheated"),
        BMSPrbDef(0xFF00, PT.FET_FAILURE, value=0x0B00, text="Charge MOSFET failed to open"),
        BMSPrbDef(0xFF00, PT.FET_FAILURE, value=0x0C00, text="Abnormal discharge MOSFET"),
        BMSPrbDef(0xFF00, PT.OTHER, SV.INFO, value=0x0D00, text="Waiting"),
        BMSPrbDef(0xFF00, PT.FET_LOCKED, value=0x0E00, text="Charge MOSFET manually closed"),
        BMSPrbDef(0xFF00, PT.CELL_OVERVOLTAGE, value=0x0F00, text="Level-2 overvoltage"),
        BMSPrbDef(0xFF00, PT.CHARGE_UNDERTEMP, value=0x1000),
        BMSPrbDef(0xFF00, PT.CELL_IMBALANCE, SV.PROTECT, value=0x1100),
        BMSPrbDef(0xFF00, PT.OTHER, SV.FAULT, value=0x1200, text="Charge self-test error"),
    )
    accept_secret: bool = True

    def __init__(
        self,
        ble_device: BLEDevice,
        config: BMSConfig | None = None,
        logger_name: str = "",
    ) -> None:
        """Initialize private BMS members."""
        super().__init__(ble_device, config, logger_name)
        self._msg: bytes = b""
        self._valid_reply: int = BMS._CMD_STAT | 0x10  # valid reply mask
        self._exp_len: int = 0

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            {
                "local_name": pattern,
                "service_uuid": BMS.uuid_services()[0],
                "connectable": True,
            }
            for pattern in ("ANT?BLE24*", "ANT?BLE3*")
        ]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return (normalize_uuid_str("ffe0"),)

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "ffe1"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        return "ffe1"

    async def _fetch_device_info(self) -> BMSInfo:
        """Fetch the device information via BLE."""

        await self._await_msg(BMS._cmd(BMS._CMD_DEV, 0x026C, 0x20))
        return BMSInfo(
            hw_version=b2str(self._msg[6:22]),
            sw_version=b2str(self._msg[22:38]),
        )

    async def _init_connection(
        self, char_notify: BleakGATTCharacteristic | int | str | None = None
    ) -> None:
        """Initialize RX/TX characteristics and protocol state."""
        await super()._init_connection(char_notify)
        self._exp_len = 0
        if self._cfg.secret:
            await self._await_msg(
                self._cmd(
                    BMS._CMD_AUTH,
                    0x6A01,
                    len(self._cfg.secret),
                    self._cfg.secret.encode("ASCII"),
                ),
                wait_for_notify=False,
            )

    def _notification_handler(self, _sender: BleakGATTCharacteristic, data: bytearray) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""

        if (
            data.startswith(BMS._HEAD)
            and (not self._frame or len(self._frame) >= self._exp_len)
            and len(data) >= BMS._MIN_LEN
        ):
            self._frame.clear()
            self._exp_len = data[5] + BMS._MIN_LEN

        self._frame.extend(data)
        self._log.debug("RX BLE data (%s): %s", "start" if data == self._frame else "cnt.", data)

        if len(self._frame) < self._exp_len or len(self._frame) < BMS._MIN_LEN:
            return

        if self._frame[2] != self._valid_reply:
            self._log.debug("unexpected response (type 0x%X)", self._frame[2])
            self._frame.clear()
            return

        if len(self._frame) != self._exp_len and self._frame[2] != BMS._CMD_DEV | 0x10:
            # length of CMD_DEV is incorrect, so we ignore the length check here
            self._log.debug("invalid frame length %d != %d", len(self._frame), self._exp_len)
            self._frame.clear()
            return

        if not self._frame.endswith(BMS._TAIL):
            self._log.debug("invalid EOF")
            self._frame.clear()
            return

        if not self._check_integrity(
            self._frame,
            crc_modbus,
            slice(1, self._exp_len - 4),
            slice(self._exp_len - 4, self._exp_len - 2),
            "little",
        ):
            self._frame.clear()
            return

        self._msg = bytes(self._frame)
        self._frame.clear()
        self._msg_event.set()

    @staticmethod
    @lru_cache(maxsize=32)
    def _cmd(cmd: int, adr: int, length: int, data: bytes = b"") -> bytes:
        """Assemble an ANT BMS command."""
        assert 0 <= cmd <= 0xFF
        assert 0 <= adr <= 0xFFFF
        assert 0 <= length <= 0xFF

        frame: bytearray = (
            bytearray([*BMS._HEAD, cmd & 0xFF])
            + adr.to_bytes(2, "little")
            + int.to_bytes(length & 0xFF, 1)
            + data
        )
        frame.extend(int.to_bytes(crc_modbus(frame[1:]), 2, "little"))
        return bytes(frame) + BMS._TAIL

    async def _await_msg(
        self,
        data: bytes,
        char: int | str | None = None,
        wait_for_notify: bool = True,
        max_size: int = 0,
    ) -> None:
        """Send data to the BMS and wait for valid reply notification."""

        self._valid_reply = data[2] | 0x10  # expected reply type
        await super()._await_msg(data, char, wait_for_notify, max_size)

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        await self._await_msg(BMS._cmd(BMS._CMD_STAT, 0, 0xBE))

        result: BMSSample = {}
        result["battery_charging"] = self._msg[7] == 0x2
        result["cell_count"] = min(self._msg[BMS._CELL_COUNT], BMS._MAX_CELLS)
        result["cell_voltages"] = BMS._cell_voltages(
            self._msg,
            cells=result["cell_count"],
            start=BMS._CELL_POS,
            byteorder="little",
        )
        result["temp_count"] = min(self._msg[BMS._TEMP_POS], BMS._MAX_TEMPS)
        result["temperature"] = BMS._temperature(
            self._msg,
            values=result["temp_count"] + 2,  # + MOSFET, balancer temperature
            start=BMS._CELL_POS + result["cell_count"] * 2,
            byteorder="little",
            types=(TempSensor.T.GENERIC,) * result["temp_count"]
            + (TempSensor.T.MOSFET, TempSensor.T.BALANCER),
        )
        result.update(
            BMS._decode_data(
                BMS._FIELDS,
                self._msg,
                byteorder="little",
                start=(result["temp_count"] + result["cell_count"]) * 2,
            )
        )

        return result
