"""Module to support V-TAC TBESS batteries using the 6233bc BMS protocol.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

import asyncio
from collections import deque
from enum import IntEnum
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import (
    BMSConfig,
    BMSDp,
    BMSInfo,
    BMSLimits,
    BMSPDp,
    BMSSample,
    Limit,
    LimitDp,
    MatcherPattern,
    PackSample,
    TempSensor,
)
from aiobmsble.basebms import BaseBMS


class BMS(BaseBMS):
    """V-TAC TBESS BMS implementation."""

    class _Cmd(IntEnum):
        """TBESS protocol frame command codes."""

        SUMMARY = 0x73
        DETAIL = 0xDB
        CONFIG = 0xDC
        INFO = 0xD0

    INFO: BMSInfo = {"manufacturer": "V-TAC", "model": "TBESS"}
    _FRAME_START: Final[int] = 0xEF
    _FRAME_END: Final[int] = 0x16
    _FRAME_CMD_POS: Final[int] = 2
    _FRAME_ADDR_POS: Final[int] = 1
    _LEN_POS: Final[int] = 22
    _PACK_COUNT_POS: Final[int] = 26
    _SYSTEM_ADDR: Final[int] = 0x01
    _FRAME_LEN: Final[dict[int, int]] = {
        _Cmd.SUMMARY: 112,
        _Cmd.DETAIL: 124,
        _Cmd.CONFIG: 72,
        _Cmd.INFO: 163,
    }
    _CELLS: Final[int] = 16
    _CELL_START: Final[int] = 34
    _CELL_TEMP_START: Final[int] = 68
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("pack_count", 26, 1, False),
        BMSDp("voltage", 28, 2, False, lambda x: x / 100),
        BMSDp("current", 30, 2, True, lambda x: x / 10),
        BMSDp("design_capacity", 32, 2, False, lambda x: x // 10),
        BMSDp("cycle_charge", 36, 2, False, lambda x: x / 10),
        BMSDp("battery_level", 38, 2, False, lambda x: x / 100),
        BMSDp("battery_health", 40, 2, False, lambda x: x / 100),
        BMSDp("cycles", 82, 2, False),
        BMSDp("total_charge", 105, 4, False),
    )
    _LIMIT_FIELDS: Final[tuple[LimitDp, ...]] = (
        LimitDp(Limit.PACK_OVP, "trip", 25 + 19, scale=0.01),  # payload 19: charge voltage
        LimitDp(Limit.PACK_UVP, "trip", 25 + 23, scale=0.01),  # payload 23: discharge cutoff
        LimitDp(Limit.CHARGE_OCP, "trip", 25 + 17, scale=0.1),  # payload 17: charge current
        LimitDp(Limit.DISCHARGE_OCP, "trip", 25 + 21, scale=0.1),  # payload 21: discharge current
    )
    _PFIELDS: Final[tuple[BMSPDp, ...]] = (
        BMSPDp("voltage", 25, 2, False, lambda x: x / 100),
        BMSPDp("current", 27, 2, True, lambda x: x / 100),
        BMSPDp("battery_level", 29, 2, False, lambda x: x / 10),
        BMSPDp("cycle_charge", 31, 2, False, lambda x: x / 10),
        BMSPDp("cell_count", 33, 1, False),
    )
    _PDFIELDS: Final[tuple[BMSPDp, ...]] = (
        BMSPDp("cycles", 0, 2, False),
        BMSPDp("battery_health", 12, 2, False, lambda x: x / 10),
        BMSPDp("design_capacity", 16, 2, False, lambda x: x // 10),
    )

    def __init__(
        self,
        ble_device: BLEDevice,
        config: BMSConfig | None = None,
        logger_name: str = "",
    ) -> None:
        """Initialize private BMS members."""
        super().__init__(ble_device, config, logger_name)
        self._summary: bytes | None = None
        self._pack_count: int = 0
        self._pending_packs: dict[int, bytes] = {}
        self._ready_samples: deque[tuple[bytes, dict[int, bytes]]] = deque()
        self._exp_len: int = 0
        self._limits_src: bytes | None = None
        self._limits_event: asyncio.Event = asyncio.Event()

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            {
                "service_uuid": normalize_uuid_str("e0ff"),
                "connectable": True,
            }
        ]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return (normalize_uuid_str("fff0"),)

    @staticmethod
    def uuid_rx() -> str:
        """Return UUID of the characteristic that provides notifications."""
        return "fff1"

    @staticmethod
    def uuid_tx() -> str:
        """Return the characteristic used by this notification-only protocol."""
        return "fff1"

    async def _init_connection(
        self, char_notify: BleakGATTCharacteristic | int | str | None = None
    ) -> None:
        """Reset stream state before starting notifications."""
        self._frame.clear()
        self._summary = None
        self._pack_count = 0
        self._pending_packs.clear()
        self._ready_samples.clear()
        self._limits_src = None
        self._limits_event.clear()
        self._msg_event.clear()
        await super()._init_connection(char_notify)

    def _notification_handler(self, _sender: BleakGATTCharacteristic, data: bytearray) -> None:
        """Assemble complete frames from the continuous RX stream."""
        if (
            len(data) > BMS._LEN_POS + 2
            and data[0] == BMS._FRAME_START
            and (not self._frame or len(self._frame) >= self._exp_len)
        ):
            self._exp_len = int.from_bytes(data[BMS._LEN_POS : BMS._LEN_POS + 2]) + 27
            self._frame.clear()

        self._frame.extend(data)

        self._log.debug("RX BLE data (%s): %s", "start" if data == self._frame else "cnt.", data)

        if len(self._frame) < self._exp_len:
            return

        if (cmd := self._frame[BMS._FRAME_CMD_POS]) not in BMS._FRAME_LEN:
            self._log.debug("unknown frame type 0x%02X", cmd)
            self._frame.clear()
            return

        del self._frame[self._exp_len :]

        if BMS._FRAME_LEN[cmd] != len(self._frame):
            self._log.debug("incorrect frame length")
            self._frame.clear()
            return

        if self._frame[0] != BMS._FRAME_START or self._frame[-1] != BMS._FRAME_END:
            self._log.debug("incorrect frame format")
            self._frame.clear()
            return

        if cmd == BMS._Cmd.SUMMARY:
            if self._frame[BMS._FRAME_ADDR_POS] != BMS._SYSTEM_ADDR:
                self._log.debug(
                    "unexpected system status address 0x%02X", self._frame[BMS._FRAME_ADDR_POS]
                )
                return
            self._process_summary(bytes(self._frame))
        elif cmd == BMS._Cmd.DETAIL:
            self._process_detail(bytes(self._frame))

    def _process_summary(self, frame: bytes) -> None:
        """Retain system status and use its pack count for the following details."""
        pack_count: int = frame[BMS._PACK_COUNT_POS]
        if pack_count < 1:
            self._log.debug("system status reports no packs")
            self._summary = None
            self._pack_count = 0
            self._pending_packs.clear()
            return
        self._summary = frame
        self._limits_src = frame
        self._limits_event.set()
        self._pack_count = pack_count
        self._pending_packs.clear()

    def _process_detail(self, frame: bytes) -> None:
        """Retain each detail frame and queue a sample when all packs arrive."""
        if self._summary is None:
            self._log.debug("ignoring pack details before system status")
            return
        pack_address: int = frame[BMS._FRAME_ADDR_POS]
        if not 1 <= pack_address <= self._pack_count:
            self._log.debug("unexpected pack address 0x%02X", pack_address)
            return
        self._pending_packs[pack_address] = frame
        if len(self._pending_packs) == self._pack_count:
            self._ready_samples.append((self._summary, self._pending_packs.copy()))
            self._summary = None
            self._pack_count = 0
            self._pending_packs.clear()
            self._msg_event.set()

    async def _fetch_limits(self) -> BMSLimits:
        """Return the protection thresholds from the next system status frame."""
        if self._limits_src is None:
            self._limits_event.clear()
            await asyncio.wait_for(self._limits_event.wait(), timeout=BMS.TIMEOUT)
        assert self._limits_src is not None
        return BMS._decode_limits(self._limits_src, BMS._LIMIT_FIELDS)

    async def _async_update(self) -> BMSSample:
        """Return system status and pack data after all reported packs respond."""
        await asyncio.wait_for(self._wait_event(), timeout=BMS.TIMEOUT)

        summary, frames = self._ready_samples.popleft()
        if not self._ready_samples:
            self._msg_event.clear()

        result: BMSSample = BMS._decode_data(BMS._FIELDS, summary)

        packs: list[PackSample] = []
        for pack_id in sorted(frames):
            frame: bytes = frames[pack_id]
            pack: PackSample = BMS._decode_pack(BMS._PFIELDS, frame)
            cells: int = pack.get("cell_count", 0)
            pack["cell_voltages"] = BMS._cell_voltages(frame, cells=cells, start=BMS._CELL_START)
            temp_sensors: int = frame[BMS._CELL_START + 2 * cells]
            pack["temp_sensors"] = temp_sensors
            pack["temp_values"] = BMS._temp_values(
                frame,
                start=BMS._CELL_START + 2 * cells + 1,
                values=temp_sensors + 2,
                size=2,
                signed=False,
                divider=10,
                types=(TempSensor.T.CELL,) * temp_sensors
                + (TempSensor.T.MOSFET, TempSensor.T.AMBIENT),
            )
            pack |= BMS._decode_pack(
                BMS._PDFIELDS, frame, start=BMS._CELL_START + 2 * (cells + temp_sensors) + 5
            )
            packs.append(pack)

        result["packs"] = packs
        return result
