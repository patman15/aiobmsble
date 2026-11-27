"""Module to support LULIS BMS (LK86xx Telink BLE module).

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from functools import lru_cache
import logging
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice

from aiobmsble import BMSConfig, BMSInfo, BMSSample, PrbType as PT, Severity
from aiobmsble.basebms import BaseBMS
from aiobmsble.plugin import BMSDp, BMSPrbDef, BMSValue, MatcherPattern, b2str, crc_sum

# problem code: alarm (4 bytes), protection (4 bytes) and fault (2 bytes) words, little endian
_PRB_SHIFT_PROTECT: Final[int] = 32
_PRB_SHIFT_FAULT: Final[int] = 64


class BMS(BaseBMS):
    """LULIS BMS implementation."""

    INFO: BMSInfo = {"manufacturer": "LULIS", "model": "LK86xx"}
    _HEAD: Final[bytes] = b"\x3b\x7e"  # start of response
    _REQ_HEAD: Final[bytes] = b"\x3a\x7e\x01\x01"  # start of read request
    _MIN_LEN: Final[int] = 7  # head (3), flag, cmd, length, checksum
    _CMD_MODEL: Final[int] = 0x02
    _CMD_SERIAL: Final[int] = 0x05
    _CMD_CYCLES: Final[int] = 0x09
    _CMD_PACK: Final[int] = 0x1E
    _CMD_TEMPS: Final[int] = 0x1F
    _CMD_CELLS: Final[int] = 0x20
    _TEMP_OFFSET: Final[int] = 2731  # temperatures in 0.1 K
    _PRB_MASK: Final[int] = 0x3FFFF | (0x3FFFF << _PRB_SHIFT_PROTECT) | (0x1F << _PRB_SHIFT_FAULT)
    _FIELDS: tuple[BMSDp[BMSValue], ...] = (
        BMSDp("voltage", 0, 2, True, lambda x: x / 100, _CMD_PACK),
        BMSDp("current", 2, 2, True, lambda x: x / 100, _CMD_PACK),
        BMSDp("battery_level", 4, 2, True, lambda x: x / 50, _CMD_PACK),
        BMSDp("battery_health", 6, 2, True, idx=_CMD_PACK),
        BMSDp("problem_code", 26, 10, False, lambda x: x & BMS._PRB_MASK, _CMD_PACK),
        BMSDp("chrg_mosfet", 36, 1, False, lambda x: bool(x & 0x40), _CMD_PACK),
        BMSDp("dischrg_mosfet", 36, 1, False, lambda x: bool(x & 0x80), _CMD_PACK),
        BMSDp("cycles", 2, 2, True, idx=_CMD_CYCLES),
        BMSDp("design_capacity", 6, 2, True, lambda x: x // 100, _CMD_CYCLES),
    )
    # bits 0-15 of the alarm/protection words and bits 16, 17 of their second word
    _STATUS_PROBLEMS: Final[tuple[tuple[PT, str], ...]] = (
        (PT.CELL_OV, ""),
        (PT.CELL_UV, ""),
        (PT.PACK_OV, ""),
        (PT.PACK_UV, ""),
        (PT.DISCHARGE_OC, ""),
        (PT.CHARGE_OC, ""),
        (PT.DISCHARGE_OT, ""),
        (PT.CHARGE_OT, ""),
        (PT.DISCHARGE_UT, ""),
        (PT.CHARGE_UT, ""),
        (PT.OTHER, "SOC high"),
        (PT.LOW_SOC, ""),
        (PT.CELL_IMBALANCE, ""),
        (PT.OTHER, "Temperature imbalance"),
        (PT.FET_OT, ""),
        (PT.SYSTEM_OT, ""),
        (PT.SYSTEM_UT, ""),
        (PT.DISCHARGE_OC, "Discharge overcurrent (instant)"),
    )
    _PROBLEMS: tuple[BMSPrbDef, ...] = (
        *(
            BMSPrbDef(1 << bit, kind, Severity.WARN, text=text)
            for bit, (kind, text) in enumerate(_STATUS_PROBLEMS)
        ),
        *(
            BMSPrbDef(1 << (_PRB_SHIFT_PROTECT + bit), kind, Severity.PROTECT, text=text)
            for bit, (kind, text) in enumerate(_STATUS_PROBLEMS)
        ),
        BMSPrbDef(1 << _PRB_SHIFT_FAULT, PT.FET_FAILURE, text="Discharge MOSFET"),
        BMSPrbDef(1 << (_PRB_SHIFT_FAULT + 1), PT.FET_FAILURE, text="Charge MOSFET"),
        BMSPrbDef(1 << (_PRB_SHIFT_FAULT + 2), PT.OTHER, Severity.FAULT, text="EEPROM"),
        BMSPrbDef(1 << (_PRB_SHIFT_FAULT + 3), PT.FET_LOCKED, text="Low voltage charge lock"),
        BMSPrbDef(1 << (_PRB_SHIFT_FAULT + 4), PT.SHORT_CIRCUIT),
    )

    def __init__(
        self,
        ble_device: BLEDevice,
        config: BMSConfig | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        """Initialize private BMS members."""
        super().__init__(ble_device, config, logger)
        self._msg: dict[int, bytes] = {}
        self._exp_cmd: int = -1

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Return the advertisement patterns used to identify the BMS."""
        return [{"local_name": "LK86??-??????", "connectable": True}]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return ("00010203-0405-0607-0809-0a0b0c0dffe0",)

    @staticmethod
    def uuid_rx() -> str:
        """Return 128-bit UUID of characteristic that provides notification/read property."""
        return "00010203-0405-0607-0809-0a0b0c0dffe1"

    @staticmethod
    def uuid_tx() -> str:
        """Return 128-bit UUID of characteristic that provides write property."""
        return "00010203-0405-0607-0809-0a0b0c0dffe2"

    @staticmethod
    @lru_cache(maxsize=8)
    def _cmd(cmd: int) -> bytes:
        """Return the read request frame for the given command."""
        assert 0 <= cmd <= 0xFF
        frame: Final[bytes] = BMS._REQ_HEAD + cmd.to_bytes(1) + b"\x00"
        return frame + crc_sum(frame).to_bytes(1)

    async def _fetch_device_info(self) -> BMSInfo:
        """Fetch the device information via BLE."""
        return BMSInfo(
            model=b2str(await self._request(BMS._CMD_MODEL)),
            serial_number=b2str(await self._request(BMS._CMD_SERIAL)),
        )

    def _notification_handler(self, sender: BleakGATTCharacteristic, data: bytearray) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        self._log.debug("RX BLE data: %s", data)
        self._frame.extend(data)

        while (start := self._frame.find(BMS._HEAD)) >= 0:
            del self._frame[:start]
            if len(self._frame) < BMS._MIN_LEN:
                return
            length = BMS._MIN_LEN + self._frame[5]
            if len(self._frame) < length:
                return

            frame = bytes(self._frame[:length])
            del self._frame[:length]

            if not self._check_integrity(frame, crc_sum, slice(None, -1), frame[-1]):
                continue

            self._msg[frame[4]] = frame[6:-1]
            if frame[4] == self._exp_cmd:
                self._msg_event.set()

        self._frame.clear()  # no start of frame, discard garbage

    async def _request(self, cmd: int) -> bytes:
        """Request a command and return its reply payload."""
        self._msg.pop(cmd, None)
        self._exp_cmd = cmd
        await self._await_msg(BMS._cmd(cmd))
        return self._msg[cmd]

    async def _update(self) -> BMSSample:
        """Update battery status information."""
        for cmd in (BMS._CMD_PACK, BMS._CMD_TEMPS, BMS._CMD_CELLS, BMS._CMD_CYCLES):
            await self._request(cmd)

        result: BMSSample = self._decode_data(BMS._FIELDS, self._msg, byteorder="little")

        temps: Final[bytes] = self._msg[BMS._CMD_TEMPS]
        cells: Final[bytes] = self._msg[BMS._CMD_CELLS]
        cell_cnt: Final[int] = int.from_bytes(cells[:2], "little")
        result["temperature"] = BMS._decode_temp(
            temps,
            start=2,
            values=int.from_bytes(temps[:2], "little"),
            byteorder="little",
            offset=BMS._TEMP_OFFSET,
            divider=10,
        )
        result["cell_voltages"] = BMS._decode_cells(
            cells, cells=cell_cnt, start=2 + (cell_cnt + 7) // 8, byteorder="little"
        )
        return result
