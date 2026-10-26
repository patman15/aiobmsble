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
    BMSPDp,
    BMSSample,
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
    _FRAME_COMMAND_POS: Final[int] = 2
    _FRAME_ADDRESS_POS: Final[int] = 1
    _FRAME_TAG: Final[slice] = slice(22, 24)
    _PACK_COUNT_POS: Final[int] = 26
    _SYSTEM_ADDRESS: Final[int] = 0x01
    _FRAME_LENGTHS: Final[dict[int, int]] = {
        _Cmd.SUMMARY: 112,
        _Cmd.DETAIL: 124,
        _Cmd.CONFIG: 72,
        _Cmd.INFO: 163,
    }
    _FRAME_TAGS: Final[dict[int, bytes]] = {
        _Cmd.SUMMARY: b"\x00\x55",
        _Cmd.DETAIL: b"\x00\x61",
        _Cmd.CONFIG: b"\x00\x2d",
        _Cmd.INFO: b"\x00\x88",
    }
    _CELLS: Final[int] = 16
    _CELL_START: Final[int] = 34
    _CELL_TEMPERATURE_START: Final[int] = 68
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("pack_count", 26, 1, False),
        BMSDp("voltage", 28, 2, False, lambda x: x / 100),
        BMSDp("current", 30, 2, True, lambda x: x / 10),
        BMSDp("design_capacity", 32, 2, False),
        BMSDp("battery_level", 38, 2, False, lambda x: x / 100),
        BMSDp("battery_health", 40, 2, False, lambda x: x / 100),
        BMSDp("cycles", 82, 2, False),
        BMSDp("cycle_charge", 101, 4, False),
        BMSDp("total_charge", 105, 4, False),
    )
    _PFIELDS: Final[tuple[BMSPDp, ...]] = (
        BMSPDp("voltage", 25, 2, False, lambda x: x / 100),
        BMSPDp("current", 27, 2, True, lambda x: x / 100),
        BMSPDp("battery_level", 29, 2, False, lambda x: x / 10),
        BMSPDp("cycles", 79, 2, False),
        BMSPDp("cycle_charge", 83, 2, False),
        BMSPDp("battery_health", 91, 2, False, lambda x: x / 10),
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
        self._msg_event.clear()
        await super()._init_connection(char_notify)

    def _notification_handler(self, _sender: BleakGATTCharacteristic, data: bytearray) -> None:
        """Assemble complete frames from the continuous RX stream."""
        self._log.debug("RX BLE data: %s", data)

        for byte in data:
            self._frame.append(byte)

            if len(self._frame) < 3:
                continue

            command: int = self._frame[BMS._FRAME_COMMAND_POS]
            if command not in BMS._FRAME_LENGTHS:
                self._log.debug("unknown frame command 0x%02X", command)
                self._frame.clear()
                return

            if len(self._frame) < BMS._FRAME_LENGTHS[command]:
                continue

            frame: bytes = bytes(self._frame)
            self._frame.clear()
            self._process_frame(frame)

    def _process_frame(self, frame: bytes) -> None:
        """Validate a complete frame and retain the system status or pack data."""
        command: int = (
            frame[BMS._FRAME_COMMAND_POS]
            if len(frame) > BMS._FRAME_COMMAND_POS
            else -1
        )
        expected_length: int | None = BMS._FRAME_LENGTHS.get(command)
        if expected_length is None or len(frame) != expected_length:
            self._log.debug("incorrect frame length: %s", len(frame))
            return

        if (
            frame[0] != BMS._FRAME_START
            or frame[-1] != BMS._FRAME_END
            or frame[BMS._FRAME_TAG] != BMS._FRAME_TAGS[command]
        ):
            self._log.debug("incorrect frame markers or tag for command 0x%02X", command)
            return

        if command == BMS._Cmd.SUMMARY:
            if frame[BMS._FRAME_ADDRESS_POS] != BMS._SYSTEM_ADDRESS:
                self._log.debug(
                    "unexpected system status address 0x%02X", frame[BMS._FRAME_ADDRESS_POS]
                )
                return
            self._process_summary(frame)
        elif command == BMS._Cmd.DETAIL:
            self._process_detail(frame)

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
        self._pack_count = pack_count
        self._pending_packs.clear()

    def _process_detail(self, frame: bytes) -> None:
        """Retain each detail frame and queue a sample when all packs arrive."""
        if self._summary is None:
            self._log.debug("ignoring pack details before system status")
            return
        if not 1 <= frame[1] <= self._pack_count:
            self._log.debug("unexpected pack address 0x%02X", frame[1])
            return
        self._pending_packs[frame[1]] = frame
        if len(self._pending_packs) == self._pack_count:
            self._ready_samples.append((self._summary, self._pending_packs.copy()))
            self._summary = None
            self._pack_count = 0
            self._pending_packs.clear()
            self._msg_event.set()

    async def _async_update(self) -> BMSSample:
        """Return system status and pack data after all reported packs respond."""
        while not self._ready_samples:
            await asyncio.wait_for(self._wait_event(), timeout=BMS.TIMEOUT)

        summary, frames = self._ready_samples.popleft()
        if not self._ready_samples:
            self._msg_event.clear()

        packs: list[PackSample] = []
        for pack_id in sorted(frames):
            frame: bytes = frames[pack_id]
            pack: PackSample = BMS._decode_pack(BMS._PFIELDS, frame)
            pack["cell_voltages"] = BMS._cell_voltages(
                frame,
                cells=BMS._CELLS,
                start=BMS._CELL_START,
            )
            pack["temp_values"] = BMS._temp_values(
                frame,
                start=BMS._CELL_TEMPERATURE_START,
                values=6,
                size=1,
                gap=1,
                signed=False,
                divider=10,
                types=(TempSensor.T.CELL,) * 4 + (TempSensor.T.MOSFET, TempSensor.T.AMBIENT),
            )
            packs.append(pack)

        data: BMSSample = BMS._decode_data(BMS._FIELDS, summary)
        data["packs"] = packs
        return data
