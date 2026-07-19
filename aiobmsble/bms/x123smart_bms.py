r"""Module to support 123\\SmartBMS (123electric) generation 3.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/

Implemented for interoperability. The data semantics (value scaling, cell/pack
fields) are documented by 123electric's own open-source, MIT-licensed projects
`123electric/123SmartBMS-Venus` and `123electric/smartbms-thingspeak`; the BLE
ASCII transport is additionally covered by the pre-existing public
implementation `dudeofea/123SmartBMS_Python_Client` (2021). This module is an
independent, clean-room implementation and contains no third-party code.

Protocol notes:

* gen3 hardware uses a Raytac/Nordic module exposing the Nordic UART Service
  (6e400001) with RX=6e400002 (write), TX=6e400003 (notify).
* All commands are ASCII, terminated with a carriage return ('\\r'); replies are
  '\\r'-terminated as well. Success = "OK", failure/not-authorized = "NA"/"WRONG".
* The module only clocks out its serial buffer while it is polled: a single-byte
  ping "$" has to be sent continuously (~330 ms) or no data is returned at all.
* A 4-digit PIN is mandatory before any command is accepted:
      PW<pin>!         -> "OK"
* Streaming of live values is enabled with:
      E!               -> "OK", afterwards the device pushes data frames
* Data frames (underscore separated, hex fields):
      U_<packV>_<inA>_<packA>_<outA>       pack voltage (*0.005 V), currents (*0.05 A)
      C_<idx>_<n>_<cellV>_<cellT>_<..>_<>  per-cell voltage (*0.005 V), temp (raw)
      E_<inWh>_<packWh>_<outWh>_<soc>      state of charge (hex %)
      T / V / M / B / H                    min/max temp, min/max volt, power, capacity, history
  Cell/pack temperature raw value converts as: degC = raw * 0.857 - 232.1
"""

import asyncio
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSConfig, BMSInfo, BMSSample, MatcherPattern, TempSensor
from aiobmsble.basebms import BaseBMS


class BMS(BaseBMS):
    r"""123\\SmartBMS gen3 implementation."""

    INFO: BMSInfo = {
        "default_manufacturer": "123electric",
        "default_model": "123\\SmartBMS",
    }

    accept_secret: bool = True  # requires a 4-digit PIN for authentication

    _PING: Final[bytes] = b"$"
    _PING_INTERVAL: float = 0.33  # s, keep-alive poll rate (app uses 330 ms)
    _WARMUP: float = 1.5  # s, poll warm-up before the first command
    _CMD_TIMEOUT: float = 4.0  # s, wait for OK/NA reply
    _CYCLE_TIMEOUT: float = 15.0  # s, wait for a full data cycle

    def __init__(
        self,
        ble_device: BLEDevice,
        config: BMSConfig | None = None,
        logger_name: str = "",
    ) -> None:
        """Initialize private BMS members."""
        super().__init__(ble_device, config, logger_name)
        self._buffer: bytearray = bytearray()
        self._last_reply: str = ""  # last "OK"/"NA"/"WRONG" style reply
        self._reply_event: Final[asyncio.Event] = asyncio.Event()
        self._wr_lock: Final[asyncio.Lock] = asyncio.Lock()
        self._ping_task: asyncio.Task | None = None
        self._cells: dict[int, tuple[float, float]] = {}  # idx -> (volt, temp)
        self._cell_total: int = 0
        self._values: BMSSample = {}

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        # advertised name is literally "123\SmartBMS"; '?' matches the backslash
        return [{"local_name": "123?SmartBMS", "connectable": True}]

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

    @staticmethod
    def _to_int(field: str) -> int:
        """Parse a hex field; 'X...' (unavailable) yields 0."""
        return 0 if not field or field[0] in "Xx" else int(field, 16)

    @staticmethod
    def _to_sint(field: str) -> int:
        """Parse a signed hex field (leading + or -)."""
        sign: int = -1 if field[:1] == "-" else 1
        return sign * BMS._to_int(field.lstrip("+-"))

    @staticmethod
    def _to_temp(field: str) -> float:
        """Convert a raw temperature field to degrees Celsius."""
        return round(BMS._to_int(field) * 0.857 - 232.1, 1)

    async def _ping_loop(self) -> None:
        """Continuously poll the module so it keeps streaming."""
        try:
            while True:
                async with self._wr_lock:
                    await self._client.write_gatt_char(
                        self.uuid_tx(), BMS._PING, response=False
                    )
                await asyncio.sleep(BMS._PING_INTERVAL)
        except asyncio.CancelledError:
            return
        except Exception as exc:  # noqa: BLE001 - keep-alive must not crash the loop
            self._log.debug("ping loop stopped (%s)", type(exc).__name__)

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        r"""Handle notifications: split '\\r'-terminated ASCII lines."""
        self._buffer += data
        while b"\r" in self._buffer:
            raw, _, self._buffer = self._buffer.partition(b"\r")
            line: str = raw.decode("ascii", "ignore").strip()
            if line:
                self._process_line(line)

    def _process_line(self, line: str) -> None:
        """Parse a single protocol line into internal state."""
        self._log.debug("RX %s", line)
        if line in ("OK", "NA", "WRONG", "KO"):
            self._last_reply = line
            self._reply_event.set()
            return

        parts: list[str] = line.split("_")
        tag: str = parts[0]
        try:
            if tag == "U" and len(parts) >= 5:
                self._values["voltage"] = round(BMS._to_int(parts[1]) * 0.005, 3)
                self._values["current"] = round(BMS._to_sint(parts[3]) * 0.05, 2)
            elif tag == "E" and len(parts) >= 5:
                self._values["battery_level"] = BMS._to_int(parts[4])
            elif tag == "C" and len(parts) >= 5:
                idx: int = BMS._to_int(parts[1])
                self._cell_total = BMS._to_int(parts[2])
                if 1 <= idx <= max(self._cell_total, idx):
                    self._cells[idx] = (
                        round(BMS._to_int(parts[3]) * 0.005, 3),
                        BMS._to_temp(parts[4]),
                    )
        except (ValueError, IndexError):
            self._log.debug("could not parse line: %s", line)

    async def _write_cmd(self, command: str) -> None:
        r"""Send an ASCII command terminated by '\\r'."""
        async with self._wr_lock:
            await self._client.write_gatt_char(
                self.uuid_tx(), (command + "\r").encode("ascii"), response=True
            )

    async def _cmd_expect_ok(self, command: str) -> None:
        """Send a command and wait for an 'OK' reply, raise otherwise."""
        self._last_reply = ""
        self._reply_event.clear()
        await self._write_cmd(command)
        try:
            await asyncio.wait_for(self._reply_event.wait(), BMS._CMD_TIMEOUT)
        except TimeoutError as exc:
            raise TimeoutError(f"no reply to '{command}'") from exc
        if self._last_reply != "OK":
            raise ConnectionError(f"'{command}' rejected ({self._last_reply})")

    async def _init_connection(
        self, char_notify: BleakGATTCharacteristic | int | str | None = None
    ) -> None:
        """Set up notifications, keep-alive ping, PIN auth and data streaming."""
        self._buffer.clear()
        self._cells.clear()
        self._values = {}
        await super()._init_connection(char_notify)

        # start keep-alive polling first; the module only replies while polled
        if self._ping_task is None or self._ping_task.done():
            self._ping_task = asyncio.create_task(self._ping_loop())
        await asyncio.sleep(BMS._WARMUP)  # let a few polls warm up before first command

        if self._cfg.secret:
            await self._cmd_expect_ok(
                f"PW{self._cfg.secret}!"
            )  # authenticate (4-digit PIN)
        await self._cmd_expect_ok(
            "E!"
        )  # enable live data streaming (fails if not authorized)

    async def disconnect(self, reset: bool = False) -> None:
        """Stop the keep-alive ping task, then disconnect."""
        if self._ping_task is not None:
            self._ping_task.cancel()
            self._ping_task = None
        await super().disconnect(reset)

    async def _async_update(self) -> BMSSample:
        """Return the latest known values.

        Cell data trickles in over several poll cycles on a congested BLE
        adapter, so values are accumulated (not cleared each update): once a
        full set has been seen, every update returns fresh values immediately.
        """

        async def _complete() -> None:
            while not (
                "battery_level" in self._values
                and self._cell_total
                and len(self._cells) >= self._cell_total
            ):
                await asyncio.sleep(0.1)

        try:
            await asyncio.wait_for(_complete(), BMS._CYCLE_TIMEOUT)
        except TimeoutError:
            self._log.warning(
                "incomplete cycle after %.0fs: %i/%i cells, soc=%s, keys=%s, ping_alive=%s",
                BMS._CYCLE_TIMEOUT,
                len(self._cells),
                self._cell_total,
                "battery_level" in self._values,
                sorted(self._values),
                self._ping_task is not None and not self._ping_task.done(),
            )

        sample: BMSSample = dict(self._values)
        if self._cells:
            ordered: list[tuple[float, float]] = [
                self._cells[i] for i in sorted(self._cells)
            ]
            sample["cell_voltages"] = [v for v, _ in ordered]
            sample["temp_values"] = [
                TempSensor(t, TempSensor.T.CELL) for _, t in ordered
            ]
            sample["cell_count"] = len(ordered)
        return sample
