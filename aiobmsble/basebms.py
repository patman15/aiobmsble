"""Base class definition for battery management systems (BMS).

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from abc import ABC, abstractmethod
import asyncio
from collections import defaultdict
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterable, MutableMapping
from contextlib import asynccontextmanager, suppress
from functools import lru_cache
import logging
import struct
from types import TracebackType
from typing import Any, Final, Literal, Self, final

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from bleak.exc import BleakCharacteristicNotFoundError, BleakDeviceNotFoundError, BleakError
from bleak_retry_connector import (
    BLEAK_TIMEOUT,
    MAX_CONNECT_ATTEMPTS,
    close_stale_connections,
    establish_connection,
)

from aiobmsble import (
    BMSConfig,
    BMSInfo,
    BMSLimits,
    BMSProblem,
    BMSSample,
    Limit,
    PackSample,
    PrbType,
    Severity,
    TempSensor,
    Threshold,
    __version__,
)
from aiobmsble._boundedbytearr import BoundedByteArray
from aiobmsble._discovery import advertisement_matches
from aiobmsble._sample_calc import derive_missing_fields
from aiobmsble.exceptions import (
    BMSConfigError,
    BMSConnectionError,
    BMSDataError,
    BMSError,
    BMSTimeoutError,
    BMSUnsupportedError,
)
from aiobmsble.plugin import (
    BMSDp,
    BMSPackValue,
    BMSPrbDef,
    BMSValue,
    LimitDp,
    MatcherPattern,
    b2str,
    crc_modbus,
    decode_problems,
)

__all__: list[str] = ["BaseBMS"]

# errors caused by malformed or incomplete BMS data (UnicodeDecodeError is a ValueError)
_PARSE_ERRORS: Final = (BufferError, LookupError, OverflowError, ValueError, struct.error)


class BaseBMS(ABC):
    """Abstract base class for battery management system.

    Every BMS plugin (`aiobmsble.bms.<name>_bms.BMS`) implements this interface. Use
    `aiobmsble.utils.identify()` to find the class for a device, then query it:

    ```python
    async with BMS(ble_device=device) as bms:
        data = await bms.update()
    ```

    Without `async with`, call `update()` directly and `disconnect()` when done.
    The connection is (re-)established automatically by each call.

    Calls to `update()`, `device_info()`, `limits()` and `async with` raise only
    `aiobmsble.exceptions.BMSError` subclasses. Link recovery needs to be handled by
    the caller. `gatt_profile()` returns the GATT services of the connected device
    for diagnostics.
    """

    ACCEPT_SECRET: bool = False  # if True, the BMS accepts a secret for authentication
    INFO: BMSInfo  # static BMS info (available before connect)
    _ALIVE_INTERVAL: float | None = None  # keep-alive period in seconds; None disables
    _BLE_MAX_ATTR_SIZE: Final[int] = 512  # max size of BLE attribute value
    _TIMEOUT: Final[float] = BLEAK_TIMEOUT / 4  # default timeout for BMS operations
    # hard timeout for the whole connection setup (connect + GATT + notify), safety net if BlueZ hangs
    _CONNECT_TIMEOUT: Final[float] = MAX_CONNECT_ATTEMPTS * BLEAK_TIMEOUT + 1
    _HRS_TO_SECS: Final[int] = 60 * 60  # seconds in an hour
    _MAX_CELL_VOLT: Final[float] = 5.906  # max cell potential
    _MAX_MSG_LEN: Final[int] = 0xFF  # maximum allowed frame length
    _MAX_RETRY: Final[int] = 3  # max number of retries for data requests
    _MAX_TIMEOUT_FACTOR: Final[int] = 8  # limit timeout increase to 8x
    _PROBLEMS: tuple[BMSPrbDef, ...] = ()  # decoding of problem_code, empty: not supported
    # calculate time between retries to complete all retries (2 modes) in _TIMEOUT seconds
    _RETRY_TIMEOUT: Final[float] = _TIMEOUT / (2**_MAX_RETRY - 1)
    _SKIP_INFO_CHARS: bool = False  # set True to skip information from _INFO_CHARS for BMSInfo()
    type _InfoCharType = Literal[
        "model", "serial_number", "fw_version", "sw_version", "hw_version", "manufacturer"
    ]
    _INFO_CHARS: Final[tuple[tuple[str, _InfoCharType], ...]] = (
        ("2a24", "model"),
        ("2a25", "serial_number"),
        ("2a26", "fw_version"),
        ("2a27", "hw_version"),
        ("2a28", "sw_version"),
        ("2a29", "manufacturer"),
    )

    class _PrefixAdapter(logging.LoggerAdapter[logging.Logger]):
        """Logging adapter to add instance ID to each log message."""

        def process(
            self, msg: str, kwargs: MutableMapping[str, Any]
        ) -> tuple[str, MutableMapping[str, Any]]:
            """Process the logging message."""
            prefix: Final[str] = str(self.extra.get("prefix") if self.extra else "")
            # prefix must not act as format directive
            return (f"{prefix.replace('%', '%%')} {msg}", kwargs)

    def __init__(
        self,
        ble_device: BLEDevice,
        config: BMSConfig | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        """Initialize the BMS.

        Args:
            ble_device (BLEDevice): the Bleak BLE device to connect to
            config (BMSConfig | None): optional BMS configuration; defaults to `BMSConfig()` if not provided
            logger (logging.Logger | None): logger for this BMS instance; defaults to the module logger

        """
        assert {"manufacturer", "model"}.issubset(self.INFO), "BMS class must define `INFO`"
        self._ble_device: Final[BLEDevice] = ble_device
        self._cfg: Final[BMSConfig] = config or BMSConfig()
        self.name: Final[str] = (self._ble_device.name or "undefined").rstrip()
        """BLE device name of this instance, see `bms_descr()` for manufacturer and model."""
        self._inv_wr_mode: bool | None = None  # invert write mode (WNR <-> W)
        self._log: Final[BaseBMS._PrefixAdapter] = BaseBMS._PrefixAdapter(
            logger or logging.getLogger(self.__class__.__module__),
            {"prefix": f"{self.name}|{self._ble_device.address[-5:].replace(':', '')}:"},
        )

        self._log.debug(
            "%s: initializing %s, BT address: %s",
            __version__,
            self.bms_descr(),
            ble_device.address,
        )
        self._client: BleakClient = BleakClient(
            self._ble_device,
            disconnected_callback=self._on_disconnect,
            services=[*self.uuid_services(), "180a"],
        )
        self._frame: BoundedByteArray = BoundedByteArray(
            max(BaseBMS._MAX_MSG_LEN, BaseBMS._BLE_MAX_ATTR_SIZE) * 2
        )
        self._msg_event: Final[asyncio.Event] = asyncio.Event()
        self._connect_lock: Final[asyncio.Lock] = asyncio.Lock()
        self._op_lock: Final[asyncio.Lock] = asyncio.Lock()
        self._alive_task: asyncio.Task[None] | None = None

    @asynccontextmanager
    async def _translate_errors(self) -> AsyncGenerator[None, None]:
        """Translate BLE and built-in errors to the public aiobmsble exceptions."""
        try:
            yield
        except BMSError as exc:
            exc.bms_type = exc.bms_type or self.bms_type()
            exc.address = exc.address or self._ble_device.address
            raise
        except BleakCharacteristicNotFoundError as exc:
            raise BMSUnsupportedError(
                str(exc), bms_type=self.bms_type(), address=self._ble_device.address
            ) from exc
        except TimeoutError as exc:
            raise BMSTimeoutError(
                str(exc), bms_type=self.bms_type(), address=self._ble_device.address
            ) from exc
        except (BleakError, EOFError, BleakDeviceNotFoundError, ConnectionError) as exc:
            raise BMSConnectionError(
                str(exc), bms_type=self.bms_type(), address=self._ble_device.address
            ) from exc
        except _PARSE_ERRORS as exc:
            # internal parser text (e.g. 'index out of range') is kept in __cause__ only
            raise BMSDataError(bms_type=self.bms_type(), address=self._ble_device.address) from exc
        finally:
            if not self._cfg.keep_alive:
                self._log.debug("forced disconnect after BMS operation")
                await self.disconnect()

    @final
    async def __aenter__(self) -> Self:
        """Asynchronous context manager to implement `async with` functionality."""
        if not self._cfg.keep_alive:
            raise BMSConfigError(
                "usage of context manager requires `BMSConfig(keep_alive=True)`.",
                bms_type=self.bms_type(),
                address=self._ble_device.address,
            )
        async with self._translate_errors():
            await self._connect()
            return self

    @final
    async def __aexit__(
        self,
        typ: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Asynchronous context manager exit functionality."""
        await self.disconnect()

    @final
    @property
    def is_connected(self) -> bool:
        """Return True if BMS is connected."""
        return self._client.is_connected

    @final
    @classmethod
    def module(cls) -> str:
        """Return the plugin module name of the BMS class, e.g. aiobmsble.bms.dummy_bms."""
        return cls.__module__

    @staticmethod
    @abstractmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Return the Bluetooth advertisement patterns used to identify the BMS."""

    @final
    @classmethod
    def matches(cls, adv: AdvertisementData, address: str) -> bool:
        """Return whether this BMS matches BLE advertisement data."""
        return any(
            advertisement_matches(matcher, adv, address) for matcher in cls.matcher_dict_list()
        )

    @final
    @classmethod
    def bms_descr(cls) -> str:
        """Return manufacturer and model of the BMS type."""
        return f"{cls.INFO.get('manufacturer', 'unknown')} {cls.INFO.get('model', 'unknown')}"

    @final
    @classmethod
    def bms_type(cls) -> str:
        """Return the BMS type (plugin module name), e.g. dummy_bms."""
        return cls.module().rpartition(".")[2]

    @staticmethod
    @abstractmethod
    def uuid_services() -> tuple[str, ...]:
        """Return the UUIDs of the services required by the BMS."""

    @staticmethod
    @abstractmethod
    def uuid_rx() -> str:
        """Return the UUID (16/32/128-bit) of the characteristic providing notifications."""

    @staticmethod
    @abstractmethod
    def uuid_tx() -> str:
        """Return the UUID (16/32/128-bit) of the characteristic used to send commands."""

    @final
    async def device_info(self, *, raw: bool = False) -> BMSInfo:
        """Return device information read from the BMS over Bluetooth LE.

        Args:
            raw (bool): If `True`, return the raw values reported by the BMS
                without default information

        Returns:
            Available device information, such as manufacturer, model, model ID,
            name, serial number, and software or hardware version.

        Raises:
            aiobmsble.exceptions.BMSError: if the information cannot be read,
                see `aiobmsble.exceptions` for the subclasses.

        """
        dev_info: BMSInfo = BMSInfo() if raw else self.INFO.copy()
        async with self._op_lock, self._translate_errors():
            await self._connect()
            if not self._SKIP_INFO_CHARS and self._client.services.get_service("180a"):
                for char, key in BaseBMS._INFO_CHARS:
                    with suppress(BleakCharacteristicNotFoundError):
                        if value := bytes(await self._client.read_gatt_char(char)):
                            dev_info[key] = b2str(value)
                            self._log.debug("BT device %s: '%s'", key, dev_info.get(key))
            else:
                self._log.debug(
                    "No BT device information %s.",
                    "queried" if self._SKIP_INFO_CHARS else "available",
                )

            dev_info |= await self._fetch_device_info()
            self._log.debug("BMS info %s", dev_info)
        return dev_info

    async def _fetch_device_info(self) -> BMSInfo:
        """Fetch the device information via BLE."""
        return BMSInfo()

    @final
    async def limits(self) -> BMSLimits:
        """Return protection thresholds configured in the BMS.

        The values are trip/recovery points of the BMS protections, not the
        operating envelope, and must not be used as charger/inverter set points.

        Returns:
            Reported protection thresholds, or an empty mapping if the BMS does
            not provide any. See `BMSLimits`.

        Raises:
            aiobmsble.exceptions.BMSError: if the thresholds cannot be read,
                see `aiobmsble.exceptions` for the subclasses.

        """
        async with (
            self._op_lock,
            self._translate_errors(),
        ):
            await self._connect()
            limits: Final[BMSLimits] = await self._fetch_limits()
            self._log.debug("BMS limits %s", limits)
        return limits

    async def _fetch_limits(self) -> BMSLimits:
        """Fetch the thresholds via BLE (default: none available)."""
        return {}

    @staticmethod
    def _raw_values() -> frozenset[BMSValue]:
        """Return values that shall not be calculated even if the BMS cannot provide them.

        Default is an empty set, i.e. calculate all possible missing values.
        See _add_missing_values() function for the required input to actually do so.

        Returns:
            frozenset[BMSValue]: set of BMS values that shall not be calculated

        """
        return frozenset()

    @final
    @staticmethod
    def _add_missing_values(data: BMSSample, raw_values: frozenset[BMSValue] = frozenset()) -> None:
        """Calculate missing BMS values from existing ones.

        Args:
            data: data dictionary with values received from BMS, updated in place
            raw_values: set of values that shall not be added to the dictionary

        """
        if not data:
            return

        derive_missing_fields(data, raw_values)

        battery_level: Final[float | None] = data.get("battery_level")
        cell_voltages: Final[list[float]] = data.get("cell_voltages", [])
        problems: list[BMSProblem] | None = data.get("problems")

        # sanity checks on values, each failing check is reported as a problem
        checks: Final[list[tuple[bool, BMSProblem]]] = [
            (
                data.get("voltage") is not None and data.get("voltage", 0) <= 0,
                BMSProblem(PrbType.SENSOR_FAILURE, Severity.FAULT, "Overall voltage"),
            ),
            (
                any(v <= 0 or v > BaseBMS._MAX_CELL_VOLT for v in cell_voltages),
                BMSProblem(PrbType.CELL_FAILURE, Severity.FAULT, "Cell voltage"),
            ),
            (
                data.get("delta_cell_voltage", 0) > BaseBMS._MAX_CELL_VOLT,
                BMSProblem(PrbType.CELL_FAILURE, Severity.FAULT, "Cell voltage delta"),
            ),
            (
                data.get("cycle_charge") is not None and data.get("cycle_charge", 0.0) <= 0.0,
                BMSProblem(PrbType.SENSOR_FAILURE, Severity.WARN, "Cycle charge"),
            ),
            (
                battery_level is not None and battery_level <= 0,
                BMSProblem(PrbType.SENSOR_FAILURE, Severity.WARN, "Battery level"),
            ),
            (
                battery_level is not None and battery_level > 100,
                BMSProblem(PrbType.SENSOR_FAILURE, Severity.INFO, "Battery level"),
            ),
        ]
        if failed := [problem for check, problem in checks if check]:
            problems = [*(problems or []), *failed]
            data["problems"] = problems

        # decoded problems: operating state notices (INFO) are not a problem
        data["problem"] = any(
            [
                data.get("problem", False),
                (
                    any(p.level >= Severity.WARN for p in problems)
                    if problems is not None
                    else data.get("problem_code", False)
                ),
            ]
        )

    @final
    def _on_disconnect(self, client: BleakClient) -> None:
        """Disconnect callback function."""

        self._log.debug("disconnected from BMS (id: %#x)", id(client))

    async def _alive(self) -> None:
        """Override to run periodic actions while `_ALIVE_INTERVAL` is set."""
        raise NotImplementedError

    @final
    async def _alive_loop(self, interval: float) -> None:
        """Periodically invoke `_alive()` every `interval` seconds."""
        while True:
            await asyncio.sleep(interval)
            async with self._op_lock:
                await self._alive()

    @final
    def _log_alive_loop_exc(self, task: asyncio.Task[None]) -> None:
        """Log any exception raised by the keep-alive loop."""
        if task.cancelled():
            self._log.debug("task '%s' was cancelled", task.get_name())
            return

        self._log.error(
            "task '%s' terminated unexpectedly",
            task.get_name(),
            exc_info=task.exception(),
        )

    @final
    def _start_alive_task(self) -> None:
        """Start the periodic keep-alive task if enabled and not already running."""
        if self._ALIVE_INTERVAL is None or self._ALIVE_INTERVAL < 0:
            return

        if self._alive_task is None or self._alive_task.done():
            self._alive_task = asyncio.create_task(
                self._alive_loop(self._ALIVE_INTERVAL), name="BMS keep-alive"
            )
            self._alive_task.add_done_callback(self._log_alive_loop_exc)

    async def _init_connection(
        self, char_notify: BleakGATTCharacteristic | int | str | None = None
    ) -> None:
        """Reset stale frame data and start notifications on the RX characteristic.

        Override to add protocol specific setup, e.g. authentication, and call `super()` first.

        Args:
            char_notify: characteristic to subscribe to, defaults to `uuid_rx()`

        """
        # reset any stale data from BMS
        self._frame.clear()
        self._msg_event.clear()

        self._log.debug("start notify on RX characteristic %s", str(char_notify or self.uuid_rx()))
        await self._client.start_notify(char_notify or self.uuid_rx(), self._notification_handler)

    @abstractmethod
    def _notification_handler(
        self, sender: BleakGATTCharacteristic, data: bytearray
    ) -> Awaitable[None] | None:
        """Handle a notification of the RX characteristic (implemented by the plugin).

        Assemble and validate frames in `self._frame`. Then store a complete valid frame
        for `_update()` in `self._msg` and set `self._msg_event`. Do not decode values here.

        Args:
            sender: the characteristic that sent the notification
            data: received fragment, a frame may span several notifications

        """
        raise NotImplementedError

    @final
    async def _connect(self) -> None:
        """Connect to the BMS and setup notification if not connected."""

        async with self._connect_lock:
            if self._client.is_connected:
                self._log.debug("BMS already connected")
                return

            self._log.debug("connecting BMS")

            try:
                async with asyncio.timeout(self._CONNECT_TIMEOUT):
                    try:
                        await self._client.disconnect()  # close existing connection
                    except (BleakError, TimeoutError, EOFError) as exc:
                        self._log.debug(
                            "failed to disconnect stale connection (%s)", type(exc).__name__
                        )

                    self._client = await establish_connection(
                        client_class=BleakClient,
                        device=self._ble_device,
                        name=self._ble_device.address,
                        disconnected_callback=self._on_disconnect,
                        services=[*self.uuid_services(), "180a"],
                    )

                    if self._log.isEnabledFor(logging.DEBUG):
                        gatt: str = await self.gatt_profile()
                        self._log.debug(
                            "GATT profile for request %s:\n %s",
                            self.uuid_services(),
                            gatt,
                        )

                    await self._init_connection()
                    self._start_alive_task()

            except (TimeoutError, BleakError, EOFError, ConnectionError) as exc:
                self._log.info("failed to initialize BMS connection (%s)", type(exc).__name__)
                await self._disconnect_impl()
                raise
            except Exception as exc:
                self._log.info(
                    "unexpected error during BMS connection init (%s)", type(exc).__name__
                )
                # a half-initialized link would be reused as-is by the next call
                await self._disconnect_impl()
                raise

            self._log.debug("BMS connected (id: %#x)", id(self._client))

    def _wr_response(self, char: int | str) -> bool:
        char_tx: Final[BleakGATTCharacteristic | None] = self._client.services.get_characteristic(
            char
        )
        return bool(char_tx and "write" in getattr(char_tx, "properties", []))

    @final
    async def _send_msg(
        self,
        data: bytes,
        max_size: int,
        char: int | str,
        attempt: int,
        inv_wr_mode: bool = False,
    ) -> None:
        """Send message to the bms in chunks if needed."""
        chunk_size: Final[int] = max_size or len(data)

        for i in range(0, len(data), chunk_size):
            chunk: bytes = data[i : i + chunk_size]
            self._log.debug(
                "TX BLE req #%i (%s%s%s): %s",
                attempt + 1,
                "!" if inv_wr_mode else "",
                "W" if self._wr_response(char) else "WNR",
                "." if self._inv_wr_mode is not None else "",
                chunk.hex(" "),
            )
            await self._client.write_gatt_char(
                char,
                chunk,
                response=(self._wr_response(char) != inv_wr_mode),
            )

    async def _await_msg(
        self,
        data: bytes,
        char: int | str | None = None,
        wait_for_notify: bool = True,
        max_size: int = 0,
    ) -> None:
        """Send data to the BMS and wait for valid reply notification."""

        for inv_wr_mode in [False, True] if self._inv_wr_mode is None else [self._inv_wr_mode]:
            try:
                self._msg_event.clear()  # clear event before requesting new data
                for attempt in range(BaseBMS._MAX_RETRY):
                    await self._send_msg(
                        data, max_size, char or self.uuid_tx(), attempt, inv_wr_mode
                    )
                    if not wait_for_notify:
                        return  # write without wait for response selected
                    try:
                        await asyncio.wait_for(
                            self._wait_event(),
                            BaseBMS._RETRY_TIMEOUT * min(2**attempt, BaseBMS._MAX_TIMEOUT_FACTOR),
                        )
                    except TimeoutError:
                        self._log.debug("TX BLE request timed out.")
                        continue  # retry sending data

                    self._inv_wr_mode = inv_wr_mode
                    return  # leave loop if no exception
            except (BleakCharacteristicNotFoundError, BleakDeviceNotFoundError):
                raise  # do not retry on these exceptions
            except BleakError as exc:
                self._log.error("TX BLE request error (%s)", type(exc).__name__)
                # try next write mode, without reconnecting, as recursion might occur
        raise BMSTimeoutError(
            "BMS did not send a valid reply after retries.",
            bms_type=self.bms_type(),
            address=self._ble_device.address,
        )

    async def _disconnect(self, reset: bool) -> None:
        """Override if actions in a subclass are required before connection is closed."""
        return

    @final
    async def _disconnect_impl(self, reset: bool = False) -> None:
        # Tear down the BLE connection (caller must already hold `_connect_lock`).
        assert self._connect_lock.locked(), "caller must hold _connect_lock to disconnect"

        self._log.debug(
            "disconnecting BMS (id: %#x, connected: %s)",
            id(self._client),
            self._client.is_connected,
        )
        self._msg_event.clear()

        task, self._alive_task = self._alive_task, None
        if task and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await task

        try:
            await self._disconnect(reset)
        except (BleakError, TimeoutError, EOFError, ConnectionError) as exc:
            self._log.warning("disconnect hook failed! (%s)", type(exc).__name__)

        try:
            await self._client.disconnect()
        except (BleakError, TimeoutError, EOFError) as exc:
            self._log.warning("disconnect failed! (%s)", type(exc).__name__)
        if reset:
            self._log.debug("closing stale BMS connections and resetting write mode")
            self._inv_wr_mode = None  # reset write mode
            try:  # ensure all connections are closed
                await close_stale_connections(self._ble_device, only_other_adapters=False)
            except (BleakError, TimeoutError, EOFError) as exc:
                self._log.error("failed to close stale BMS connections (%s)", type(exc).__name__)

    @final
    async def disconnect(self, *, reset: bool = False) -> None:
        """Disconnect the BMS, includes stopping notifications.

        Never raises; failures are logged. Safe to call when not connected.

        Args:
            reset (bool): if true, the write mode is reset to default and all connections are
                closed to ensure a clean state for the next connection. This should be used in
                case of stale connections. (Default: False)

        """
        async with self._connect_lock:
            await self._disconnect_impl(reset)

    @final
    async def _wait_event(self) -> None:
        """Wait for data event and clear it."""
        await self._msg_event.wait()
        self._msg_event.clear()

    @abstractmethod
    async def _update(self) -> BMSSample:
        """Return the BMS values as `BMSSample` (implemented by the plugin)."""

    @final
    async def update(self, *, raw: bool = False) -> BMSSample:
        """Fetch the latest battery telemetry from the BMS.

        This calls the protocol-specific implementation in `_update()` and,
        unless `raw` is `True`, fills in any derived or missing values expected by
        the library.

        Args:
            raw (bool): If `True`, return the raw values reported by the BMS
                without adding derived or missing fields.

        Returns:
            BMSSample: The retrieved BMS values.

        Raises:
            aiobmsble.exceptions.BMSError: if no valid data could be retrieved,
                see `aiobmsble.exceptions` for the subclasses.

        """
        async with (
            self._op_lock,
            self._translate_errors(),
        ):
            await self._connect()
            data: BMSSample = await self._update()
            if not raw:
                if self._PROBLEMS and "problem_code" in data:
                    data["problems"] = decode_problems(data["problem_code"], self._PROBLEMS)
                self._add_missing_values(data, self._raw_values())
        return data

    @final
    @staticmethod
    @lru_cache(maxsize=512)
    def _cmd_modbus(dev_id: int = 0, fct: int = 0x3, addr: int = 0, count: int = 1) -> bytes:
        """Assemble a MODBUS command.

        Args:
            dev_id (int): 8-bit slave device id (default: 0x0)
            fct (int): 8-bit function code (default: 0x3, read registers)
            addr (int): 16-bit start address (default: 0x0)
            count (int): 16-bit number of elements (default: 1)

        Returns:
            bytes: assembled MODBUS command bytes

        """
        assert dev_id >= 0x00
        assert fct in (1, 2, 3, 4, 5, 6, 15, 16, 22, 23)
        assert addr >= 0 and count > 0 and addr + count <= 0xFFFF
        frame: bytes = (
            dev_id.to_bytes(1)
            + fct.to_bytes(1)
            + addr.to_bytes(2, byteorder="big")
            + count.to_bytes(2, byteorder="big")
        )
        return frame + crc_modbus(frame).to_bytes(2, "little")

    @staticmethod
    def _decode_data(
        fields: tuple[BMSDp[BMSValue], ...],
        data: bytes | dict[int, bytes],
        *,
        byteorder: Literal["little", "big"] = "big",
        start: int = 0,
    ) -> BMSSample:
        """Decode scalar values from a raw frame using a `BMSDp` field table.

        Fields outside of the frame, or whose message index is missing in `data`, are skipped.

        Args:
            fields: data point definitions (position, size, signedness, conversion)
            data: raw frame, or frames keyed by the message index of the data points
            byteorder: byte order of the values ("big"/"little" endian)
            start: offset added to the position of each data point

        Returns:
            BMSSample: the decoded values by data point key

        """
        result: BMSSample = {}
        for field in fields:
            if isinstance(data, dict) and field.idx not in data:
                continue
            msg: bytes = data[field.idx] if isinstance(data, dict) else data

            pos: int = start + field.pos
            end: int = pos + field.size
            if pos < 0 or end > len(msg):
                continue  # slice out of range, skip this field

            result[field.key] = field.fct(
                int.from_bytes(msg[pos:end], byteorder=byteorder, signed=field.signed)
            )
        return result

    @staticmethod
    def _decode_limits(
        fields: Iterable[LimitDp],
        data: bytes,
        *,
        byteorder: Literal["little", "big"] = "big",
    ) -> BMSLimits:
        """Decode thresholds from a raw frame using a field table."""
        values: defaultdict[Limit, dict[str, float]] = defaultdict(dict)

        for field in fields:
            if field.pos < 0 or field.pos + field.size > len(data):
                continue  # field not present in this (shorter) frame
            raw: int = int.from_bytes(
                data[field.pos : field.pos + field.size],
                byteorder=byteorder,
                signed=field.signed,
            )
            if raw == field.invalid:
                continue
            # rounding removes binary float artifacts, e.g. 2800 * 0.001
            values[field.prot][field.attr] = round(raw * field.scale - field.offset, 6)

        # a threshold without a trip point is meaningless -> drop it
        return {prot: Threshold(**attrs) for prot, attrs in values.items() if "trip" in attrs}

    @staticmethod
    def _decode_pack(
        fields: tuple[BMSDp[BMSPackValue], ...],
        data: bytes,
        *,
        byteorder: Literal["little", "big"] = "big",
        start: int = 0,
    ) -> PackSample:
        """Decode scalar values of a battery pack from a raw frame using a `BMSDp` field table.

        Args:
            fields: data point definitions (position, size, signedness, conversion)
            data: raw frame of the pack
            byteorder: byte order of the values ("big"/"little" endian)
            start: offset added to the position of each data point

        Returns:
            PackSample: the decoded values by data point key

        """
        result: PackSample = {}
        for field in fields:
            pos: int = start + field.pos
            end: int = pos + field.size
            if pos < 0 or end > len(data):
                continue  # slice out of range, skip this field
            result[field.key] = field.fct(
                int.from_bytes(data[pos:end], byteorder=byteorder, signed=field.signed)
            )
        return result

    @staticmethod
    def _decode_cells(
        data: bytes,
        *,
        cells: int,
        start: int,
        size: int = 2,
        gap: int = 0,
        byteorder: Literal["little", "big"] = "big",
        divider: int = 1000,
    ) -> list[float]:
        """Return cell voltages from BMS message.

        Args:
            data: Raw data from BMS
            cells: Number of cells to read
            start: Start position in data array
            size: Number of bytes per cell value (default: 2)
            gap: Number of bytes to skip after each cell value (default: 0)
            byteorder: Byte order ("big"/"little" endian)
            divider: Value to divide raw value by, defaults to 1000 (mv to V)

        Returns:
            list[float]: List of cell voltages in volts

        """
        return [
            value / divider
            for idx in range(cells)
            if (len(data) >= start + idx * (size + gap) + size)
            and (
                value := int.from_bytes(
                    data[start + idx * (size + gap) : start + idx * (size + gap) + size],
                    byteorder=byteorder,
                    signed=False,
                )
            )
        ]

    @staticmethod
    def _decode_temp(
        data: bytes,
        *,
        start: int,
        values: int = 1,
        size: int = 2,
        gap: int = 0,
        byteorder: Literal["little", "big"] = "big",
        signed: bool = True,
        offset: float = 0,
        divider: int = 1,
        types: tuple[TempSensor.T, ...] = (),
    ) -> list[TempSensor]:
        """Return temperature values from BMS message.

        Args:
            data: Raw data from BMS
            start: Start position in data array
            values: Number of values to read (default: 1)
            size: Number of bytes per temperature value (default: 2)
            gap: Number of bytes to skip after each temperature value (default: 0)
            byteorder: Byte order ("big"/"little" endian, default: "big")
            signed: Indicates whether two's complement is used to represent the integer.
            offset: The offset read values are shifted by (for Kelvin use 273.15)
            divider: Value to divide raw value by, defaults to 1
            types: Tuple of sensor types in parsing sequence, defaults to "GENERIC"

        Returns:
            list[TempSensor]: List of temperature values

        """
        return [
            TempSensor(
                (value - offset) / divider,
                types[idx] if idx < len(types) else TempSensor.T.GENERIC,
            )
            for idx in range(values)
            if (len(data) >= start + idx * (size + gap) + size)
            and (
                (
                    value := int.from_bytes(
                        data[start + idx * (size + gap) : start + idx * (size + gap) + size],
                        byteorder=byteorder,
                        signed=signed,
                    )
                )
                or (offset == 0)
            )
        ]

    @final
    def _check_integrity(
        self,
        data: bytes | bytearray | BoundedByteArray,
        integrity_func: Callable[[bytes | bytearray], int],
        dic_data_slice: slice,
        dic_expected: slice | int,
        byteorder: Literal["little", "big"] = "big",
    ) -> bool:
        """Check data integrity of frame data.

        Args:
            data: The frame data to check
            integrity_func: Function to calculate data integrity code (DIC, e.g. CRC/checksum)
            dic_data_slice: Slice of data to calculate DIC on
            dic_expected: Slice where expected DIC is stored or expected DIC as int
            byteorder: Byte order for reading expected DIC

        Returns:
            bool: True if data integrity code (DIC) is valid, False otherwise
        """
        calc_dic: Final[int] = integrity_func(data[dic_data_slice])
        exp_dic: Final[int] = (
            int.from_bytes(data[dic_expected], byteorder)
            if isinstance(dic_expected, slice)
            else dic_expected
        )
        if calc_dic != exp_dic:
            self._log.debug("invalid checksum 0x%X != 0x%X", exp_dic, calc_dic)
            return False
        return True

    @final
    async def gatt_profile(self) -> str:
        """Return a string containing all services, characteristics and descriptors of the connected device."""
        # Do not query values from device to avoid all kinds of exceptions that would need to be handled/ignored.
        if not self.is_connected:
            return "device not connected"

        lines: list[str] = []
        try:
            for service in self._client.services:
                lines.append(f"SRV {service}")
                for char in service.characteristics:
                    lines.append(f"  CHR {char} ({','.join(char.properties)})")
                    lines.extend(f"    DCR {desc}" for desc in char.descriptors)
        except BleakError as exc:
            return str(exc)

        if not lines:
            return "no services found"

        return "\n".join(lines)
