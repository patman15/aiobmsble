"""Module to support ANT BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

import contextlib
from enum import IntEnum
from functools import lru_cache
import logging
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSConfig, BMSInfo, BMSSample, PrbType as PT, Severity as SV
from aiobmsble.basebms import BaseBMS
from aiobmsble.plugin import BMSDp, BMSPrbDef, BMSValue, MatcherPattern, crc_sum


class BMS(BaseBMS):
    """ANT BMS (legacy) implementation."""

    class CMD(IntEnum):
        """Command codes for ANT BMS."""

        GET = 0xDB
        SET = 0xA5

    class ADR(IntEnum):
        """Address codes for ANT BMS."""

        STATUS = 0x00

    INFO: BMSInfo = {"manufacturer": "ANT", "model": "legacy smart BMS"}
    _RX_HEADER: Final[bytes] = b"\xaa\x55\xaa"
    _RX_HEADER_RSP_STAT: Final[bytes] = b"\xaa\x55\xaa\xff"

    _RSP_STAT: Final[int] = 0xFF
    _RSP_STAT_LEN: Final[int] = 140

    _FIELDS: Final[tuple[BMSDp[BMSValue], ...]] = (
        BMSDp("voltage", 4, 2, False, lambda x: x / 10),
        BMSDp("current", 70, 4, True, lambda x: x / -10),
        BMSDp("battery_level", 74, 1, False),
        BMSDp("design_capacity", 75, 4, False, lambda x: x // 10**6),
        BMSDp("cycle_charge", 79, 4, False, lambda x: x / 1e6),
        BMSDp("total_charge", 83, 4, False, lambda x: x // 1000),
        BMSDp("runtime", 87, 4, False),
        BMSDp("cell_count", 123, 1, False),
        BMSDp(
            "problem_code",
            103,
            2,
            False,
            lambda x: ((x & 0xF00) if (x >> 8) not in (0x1, 0x4) else 0)
            | ((x & 0xF) if (x & 0xF) not in (0x1, 0x4, 0xB) else 0),
        ),
        BMSDp("chrg_mosfet", 103, 1, False, lambda x: x == 0x1),
        BMSDp("dischrg_mosfet", 104, 1, False, lambda x: x == 0x1),
        BMSDp("balancer", 105, 1, False, lambda x: bool(x & 0x4)),
    )
    # problem_code: charge MOSFET status (bits 8-15) | discharge MOSFET status.
    _PROBLEMS: tuple[BMSPrbDef, ...] = (
        BMSPrbDef(0xFF, PT.CELL_UNDERVOLTAGE, value=0x02),
        BMSPrbDef(0xFF, PT.DISCHARGE_OVERCURRENT, value=0x03),
        BMSPrbDef(0xFF, PT.PACK_UNDERVOLTAGE, value=0x05),
        BMSPrbDef(0xFF, PT.DISCHARGE_OVERTEMP, value=0x06),
        BMSPrbDef(0xFF, PT.MOSFET_OVERTEMP, value=0x07),
        BMSPrbDef(0xFF, PT.OTHER, SV.PROTECT, value=0x08, text="Discharge current"),
        BMSPrbDef(0xFF, PT.OTHER, SV.FAULT, value=0x09, text="Balancing wire loose"),
        BMSPrbDef(0xFF, PT.SYSTEM_OVERTEMP, value=0x0A, text="Board overheated"),
        BMSPrbDef(0xFF, PT.SHORT_CIRCUIT, value=0x0C),
        BMSPrbDef(0xFF, PT.FET_FAILURE, value=0x0D, text="Discharge MOSFET"),
        BMSPrbDef(0xFF, PT.OTHER, SV.FAULT, value=0x0E, text="Start exception"),
        BMSPrbDef(0xFF, PT.FET_LOCKED, value=0x0F, text="Discharge MOSFET manually closed"),
        BMSPrbDef(0xFF00, PT.CELL_OVERVOLTAGE, value=0x0200),
        BMSPrbDef(0xFF00, PT.CHARGE_OVERCURRENT, value=0x0300),
        BMSPrbDef(0xFF00, PT.PACK_OVERVOLTAGE, value=0x0500),
        BMSPrbDef(0xFF00, PT.CHARGE_OVERTEMP, value=0x0600),
        BMSPrbDef(0xFF00, PT.MOSFET_OVERTEMP, value=0x0700),
        BMSPrbDef(0xFF00, PT.OTHER, SV.PROTECT, value=0x0800, text="Charge current"),
        BMSPrbDef(0xFF00, PT.OTHER, SV.FAULT, value=0x0900, text="Balancing wire loose"),
        BMSPrbDef(0xFF00, PT.SYSTEM_OVERTEMP, value=0x0A00, text="Board overheated"),
        BMSPrbDef(0xFF00, PT.FET_FAILURE, value=0x0D00, text="Discharge MOSFET"),
        BMSPrbDef(0xFF00, PT.FET_LOCKED, value=0x0F00, text="Charge MOSFET manually closed"),
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
                "local_name": pattern,
                "service_uuid": BMS.uuid_services()[0],
                "connectable": True,
            } for pattern in ("ANT-BLE[01]*", "ANT-BLE22*")
        ]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return (normalize_uuid_str("ffe0"),)  # change service UUID here!

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "ffe1"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        return "ffe1"

    def _notification_handler(
        self, sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""

        self._log.debug("RX BLE data: %s", data)

        if data.startswith(BMS._RX_HEADER_RSP_STAT):
            self._frame.clear()
        elif not self._frame:
            self._log.debug("invalid SOF")
            return

        self._frame.extend(data)

        _data_len: Final[int] = len(self._frame)
        if _data_len < BMS._RSP_STAT_LEN:
            return

        if _data_len > BMS._RSP_STAT_LEN:
            self._log.debug("invalid length %d > %d", _data_len, BMS._RSP_STAT_LEN)
            self._frame.clear()
            return

        if not self._check_integrity(
            self._frame,
            lambda x: crc_sum(x[4:-2], 2),
            slice(None, None),
            slice(-2, None),
            "big",
        ):
            self._frame.clear()
            return

        self._msg = bytes(self._frame)
        self._frame.clear()
        self._msg_event.set()

    @staticmethod
    @lru_cache(maxsize=32)
    def _cmd(cmd: CMD, adr: ADR, value: int = 0x0000) -> bytes:
        """Assemble a ANT BMS command."""
        assert cmd in BMS.CMD
        assert adr in BMS.ADR
        assert 0 <= value <= 0xFFFF
        _frame: bytes = bytes((cmd, cmd, adr)) + value.to_bytes(2, "big")
        return bytes(_frame) + crc_sum(_frame[2:]).to_bytes(1, "big")

    async def _update(self) -> BMSSample:
        """Update battery status information."""
        await self._await_msg(BMS._cmd(BMS.CMD.GET, BMS.ADR.STATUS))

        result: BMSSample = BMS._decode_data(BMS._FIELDS, self._msg, byteorder="big")

        result["cell_voltages"] = BMS._cell_voltages(
            self._msg,
            cells=result.get("cell_count", 0),
            start=6,
            size=2,
            byteorder="big",
            divider=1000,
        )

        if not result.get("design_capacity", 1):
            # Workaround for some BMS always reporting 0 for design_capacity
            result.pop("design_capacity")
            with contextlib.suppress(ZeroDivisionError):
                result["design_capacity"] = int(
                    round(
                        result.get("cycle_charge", 0)
                        / result.get("battery_level", 0)
                        * 100,
                        -1,
                    )
                )  # leads to `cycles` not available when level == 0

        # ANT-BMS carries 6 slots for temp sensors but only 4 looks like being connected by default
        result["temperature"] = BMS._temperature(
            self._msg, values=4, start=91, size=2, byteorder="big", signed=True
        )

        return result
