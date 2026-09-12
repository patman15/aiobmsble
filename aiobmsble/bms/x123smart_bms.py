r"""Module to support 123\\SmartBMS (123electric) generation 3.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

import asyncio
from string import ascii_uppercase, digits
from typing import Final, Literal

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSConfig, BMSDp, BMSInfo, BMSSample, MatcherPattern, TempSensor
from aiobmsble.basebms import BaseBMS


class BMS(BaseBMS):
    r"""123\\SmartBMS gen3 implementation."""

    INFO: BMSInfo = {
        "default_manufacturer": "123electric",
        "default_model": "123\\SmartBMS",
    }

    accept_secret: bool = True  # requires a 4-digit PIN for authentication

    ALIVE_INTERVAL = 1.0  # s, keep-alive poll rate (app uses 330 ms)
    _CR: Final[bytes] = b"\r"
    _FIELDS: tuple[BMSDp, ...] = (
        BMSDp("voltage", 1, 1, False, lambda x: x * BMS._V_SCALE, ord("U") << 8),
        BMSDp("current", 3, 1, False, lambda x: x * 0.05, ord("U") << 8),
        BMSDp("battery_level", 4, 1, False, idx=ord("E") << 8),
        BMSDp("battery_health", 1, 1, False, idx=ord("H") << 8),
    )
    HEX_UPPER: Final[str] = digits + ascii_uppercase[:6]  # hex characters in upper case
    _LMSG: Final[int] = -1  # last message index
    _MSG_FMT: Final[dict[str, int]] = {
        "U": 5,
        "T": 5,
        "M": 4,
        "V": 6,
        "C": 6,
        "E": 5,
        "H": 7,
        "B": 5,
    }
    _PING: Final[bytes] = b"$"
    _REPLIES: Final[frozenset[bytes]] = frozenset({b"OK", b"NA", b"WRONG", b"KO"})
    _RESPS: frozenset[int] = frozenset(field.idx for field in _FIELDS)
    _T_OFFS: Final[int] = 0x114  # temperature offset
    _TAGS: set[str] = set(_MSG_FMT.keys())
    _V_SCALE: Final[float] = 0.005  # voltage scale factor

    def __init__(
        self,
        ble_device: BLEDevice,
        config: BMSConfig | None = None,
        logger_name: str = "",
    ) -> None:
        """Initialize private BMS members."""
        super().__init__(ble_device, config, logger_name)
        self._msg: dict[int, bytes] = {}
        self._cell_count: int = 0

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            MatcherPattern(
                local_name="123\\SmartBMS",
                service_uuid=BMS.uuid_services()[0],
                connectable=True,
            )
        ]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return (normalize_uuid_str("6e400001-b5a3-f393-e0a9-e50e24dcca9e"),)

    @staticmethod
    def uuid_rx() -> str:
        """Return UUID of characteristic that provides notifications (TX of the module)."""
        return "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

    @staticmethod
    def uuid_tx() -> str:
        """Return UUID of characteristic that accepts writes (RX of the module)."""
        return "6e400002-b5a3-f393-e0a9-e50e24dcca9e"

    async def _fetch_device_info(self) -> BMSInfo:
        """Fetch the device information via BLE."""
        await self._cmd_expect_ok(b"D!")
        await self._await_msg(b"V@" + BMS._CR)
        ver: Final[str] = self._msg[BMS._LMSG].decode("ascii").split("_", 1)[0]
        build: Final[str] = ver[2:]
        await self._cmd_expect_ok(b"E!")
        return {"fw_version": f"{int(ver[0],16)}.{int(ver[1],16)}.{int(build,16)}"}

    @staticmethod
    def _parse_int(hex_str: str) -> int:
        num: Literal[-1, 1] = 1
        if hex_str[0] == "+" or hex_str[0] == "-":
            num = -1 if hex_str[0] == "-" else 1
            hex_str = hex_str[1:]

        try:
            result = int(hex_str, 16)
            return result * num
        except ValueError:
            return 0

    async def _alive(self) -> None:
        """Send the keep-alive ping while connected."""
        await self._await_msg(BMS._PING, wait_for_notify=False)

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle notifications: split CR-terminated ASCII lines."""
        self._log.debug("RX BLE data: %s", data)
        self._frame.extend(data)
        while (pos := self._frame.find(BMS._CR)) != -1:
            line = bytes(self._frame[:pos])
            del self._frame[: pos + 1]

            msg_t: str = chr(line[0])
            if (line in BMS._REPLIES) or (
                line[1] != ord("_")
                and (msg_t in BMS.HEX_UPPER)
                and self._crc_sum(line[:-2]) == int(line[-2:], 16)
            ):
                self._msg[BMS._LMSG] = line
                self._msg_event.set()
                return

            if msg_t not in self._TAGS or line[1:2] != b"_":
                self._log.debug("invalid message type '%s'", msg_t)
                continue
            if line.count(b"_") + 1 < BMS._MSG_FMT.get(msg_t, 0xFF):
                self._log.debug("invalid message format: %s", line)
                continue
            if msg_t == "C":
                self._msg[line[0] << 8 + int(line[2:4])] = bytes(line)
                self._cell_count = int(line[5:7])
            else:
                self._msg[line[0] << 8] = bytes(line)
        if BMS._RESPS.issubset(self._msg.keys()):
            self._msg_event.set()

    async def _cmd_expect_ok(self, cmd: bytes) -> None:
        """Send a command and wait for an 'OK' reply, raise otherwise."""
        await self._await_msg(cmd + BMS._CR)
        if self._msg[BMS._LMSG] != b"OK":
            raise ConnectionRefusedError(
                f"command rejected ({self._msg[BMS._LMSG].decode('ascii')})"
            )
        self._msg.clear()
        self._msg_event.clear()

    async def _init_connection(
        self, char_notify: BleakGATTCharacteristic | int | str | None = None
    ) -> None:
        """Set up notifications, keep-alive ping, PIN auth and data streaming."""
        await super()._init_connection(char_notify)

        if self._cfg.secret:
            # authenticate (4-digit PIN)
            await self._cmd_expect_ok(f"PW{self._cfg.secret}!".encode("ascii"))

        # enable live data streaming (fails if not authorized) and ping once
        await self._cmd_expect_ok(b"E!")
        await self._await_msg(BMS._PING, wait_for_notify=False)

    @staticmethod
    def _crc_sum(data: bytes | bytearray) -> int:
        return (sum(data) - data.count(0x5F) * 0x5F) & 0xFF

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""

        try:
            await asyncio.wait_for(self._msg_event.wait(), timeout=BMS.TIMEOUT)
        except TimeoutError as exc:
            if len(self._msg):
                raise ValueError("BMS data incomplete.") from exc
            raise
        self._msg_event.clear()

        result: BMSSample = (
            BMS._decode_data(BMS._FIELDS, self._msg)
            | BMS._parse_cells(self._msg, cells=self._cell_count)
            | {"cell_count": self._cell_count}
        )
        self._msg.clear()

        return result

    @staticmethod
    def _decode_data(
        fields: tuple[BMSDp, ...],
        data: bytes | dict[int, bytes],
        *,
        byteorder: Literal["little", "big"] = "big",
        start: int = 0,
    ) -> BMSSample:
        result: BMSSample = {}
        for field in fields:
            assert isinstance(data, dict) and field.idx in data, "Invalid field index."

            elements: list[bytes] = data[field.idx].split(b"_")
            pos: int = start + field.pos
            if pos < 0 or pos >= len(elements):
                continue  # slice out of range, skip this field

            result[field.key] = field.fct(
                BMS._parse_int(elements[pos].decode("ascii", errors="ignore"))
            )
        return result

    @staticmethod
    def _parse_cells(
        data: dict[int, bytes],
        cells: int,
    ) -> BMSSample:
        """Parse cell voltages from message."""
        cell_v: list[float] = []
        cell_t: list[TempSensor] = []
        cell_s: int = 0

        for cell in range(cells):
            elements: list[str] = (
                data[ord("C") << 8 + cell + 1]
                .decode("ascii", errors="ignore")
                .split("_")
            )
            cell_v.append(BMS._parse_int(elements[3]) * BMS._V_SCALE)
            cell_t.append(
                TempSensor(BMS._parse_int(elements[4]) - BMS._T_OFFS, TempSensor.T.CELL)
            )
            cell_s |= BMS._parse_int(elements[5])
            if len(elements) >= 7:
                cell_s |= BMS._parse_int(elements[6]) << 8

        return {
            "cell_voltages": cell_v,
            "temp_values": cell_t,
            "chrg_mosfet": bool(cell_s & 0x1),
            "dischrg_mosfet": bool(cell_s & 0x1),
            "problem_code": cell_s & 0x0EFC,
        }
