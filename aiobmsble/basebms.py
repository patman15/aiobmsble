"""Base class defintion for battery management systems (BMS)."""

from abc import ABC, abstractmethod
import asyncio
from collections.abc import Callable
import logging
from statistics import fmean
from typing import Any, Final

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import establish_connection

from aiobmsble import AdvertisementPattern, BMSsample, BMSvalue

KEY_CELL_VOLTAGE: Final[str] = "cell#"  # [V]


class BaseBMS(ABC):
    """Abstract base class for battery management system."""

    TIMEOUT = 5.0
    _MAX_CELL_VOLT: Final[float] = 5.906  # max cell potential
    _HRS_TO_SECS: Final[int] = 60 * 60  # seconds in an hour

    def __init__(
        self,
        logger_name: str,
        ble_device: BLEDevice,
        reconnect: bool = False,
    ) -> None:
        """Intialize the BMS.

        notification_handler: the callback function used for notifications from 'uuid_rx()'
            characteristic. Not defined as abstract in this base class, as it can be both,
            a normal or async function

        Args:
            logger_name (str): name of the logger for the BMS instance (usually file name)
            ble_device (BLEDevice): the Bleak device to connect to
            reconnect (bool): if true, the connection will be closed after each update

        """
        assert (
            getattr(self, "_notification_handler", None) is not None
        ), "BMS class must define _notification_handler method"
        self._ble_device: Final[BLEDevice] = ble_device
        self._reconnect: Final[bool] = reconnect
        self.name: Final[str] = self._ble_device.name or "undefined"
        self._log: Final[logging.Logger] = logging.getLogger(
            f"{logger_name.replace('.plugins', '')}::{self.name}:"
            f"{self._ble_device.address[-5:].replace(':','')})"
        )

        self._log.debug(
            "initializing %s, BT address: %s", self.device_id(), ble_device.address
        )
        self._client: BleakClient = BleakClient(
            self._ble_device,
            disconnected_callback=self._on_disconnect,
            services=[*self.uuid_services()],
        )
        self._data: bytearray = bytearray()
        self._data_event: Final[asyncio.Event] = asyncio.Event()

    @staticmethod
    @abstractmethod
    def matcher_dict_list() -> list[AdvertisementPattern]:
        """Return a list of Bluetooth advertisement matchers."""

    @staticmethod
    @abstractmethod
    def device_info() -> dict[str, str]:
        """Return a dictionary of device information.

        keys: manufacturer, model
        """

    @classmethod
    def device_id(cls) -> str:
        """Return device information as string."""
        return " ".join(cls.device_info().values())

    @staticmethod
    @abstractmethod
    def uuid_services() -> list[str]:
        """Return list of 128-bit UUIDs of services required by BMS."""

    @staticmethod
    @abstractmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""

    @staticmethod
    @abstractmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""

    @staticmethod
    def _calc_values() -> frozenset[BMSvalue]:
        """Return values that the BMS cannot provide and need to be calculated.

        See _add_missing_values() function for the required input to actually do so.
        """
        return frozenset()

    @staticmethod
    def _add_missing_values(data: BMSsample, values: frozenset[BMSvalue]) -> None:
        """Calculate missing BMS values from existing ones.

        Args:
            data: data dictionary with values received from BMS
            values: list of values to calculate and add to the dictionary

        Returns:
            None

        """
        if not values or not data:
            return

        def can_calc(value: BMSvalue, using: frozenset[BMSvalue]) -> bool:
            """Check value to add does not exist, is requested, and needed data is available."""
            return (value in values) and (value not in data) and using.issubset(data)

        cell_voltages: Final[list[float]] = data.get("cell_voltages", [])
        design_capacity: Final[int | float] = data.get("design_capacity", 0)
        battery_level: Final[int | float] = data.get("battery_level", 0)
        voltage: Final[float] = data.get("voltage", 0)
        cycle_charge: Final[int | float] = data.get("cycle_charge", 0)
        current: Final[float] = data.get("current", 0)

        calculations: dict[BMSvalue, tuple[set[BMSvalue], Callable[[], Any]]] = {
            "voltage": ({"cell_voltages"}, lambda: round(sum(cell_voltages), 3)),
            "delta_voltage": (
                {"cell_voltages"},
                lambda: round(max(cell_voltages) - min(cell_voltages), 3),
            ),
            "cycle_charge": (
                {"design_capacity", "battery_level"},
                lambda: (design_capacity * battery_level) / 100,
            ),
            "cycle_capacity": (
                {"voltage", "cycle_charge"},
                lambda: voltage * cycle_charge,
            ),
            "power": ({"voltage", "current"}, lambda: round(voltage * current, 3)),
            "battery_charging": ({"current"}, lambda: current > 0),
            "runtime": (
                {"current", "cycle_charge"},
                lambda: (
                    int(cycle_charge / abs(current) * BaseBMS._HRS_TO_SECS)
                    if current < 0
                    else None
                ),
            ),
            "temperature": (
                {"temp_values"},
                lambda: round(fmean(data.get("temp_values", [])), 3),
            ),
        }

        for attr, (required, calc_func) in calculations.items():
            if can_calc(attr, frozenset(required)):
                data[attr] = calc_func()

        # do sanity check on values to set problem state
        data["problem"] = any(
            [
                data.get("problem", False),
                data.get("problem_code", False),
                voltage <= 0,
                any(v <= 0 or v > BaseBMS._MAX_CELL_VOLT for v in cell_voltages),
                data.get("delta_voltage", 0) > BaseBMS._MAX_CELL_VOLT,
                cycle_charge <= 0,
                battery_level > 100,
            ]
        )

    def _on_disconnect(self, _client: BleakClient) -> None:
        """Disconnect callback function."""

        self._log.debug("disconnected from BMS")

    async def _init_connection(self) -> None:
        # reset any stale data from BMS
        self._data.clear()
        self._data_event.clear()

        await self._client.start_notify(
            self.uuid_rx(), getattr(self, "_notification_handler")
        )

    async def _connect(self) -> None:
        """Connect to the BMS and setup notification if not connected."""

        if self._client.is_connected:
            self._log.debug("BMS already connected")
            return

        self._log.debug("connecting BMS")
        self._client = await establish_connection(
            client_class=BleakClient,
            device=self._ble_device,
            name=self._ble_device.address,
            disconnected_callback=self._on_disconnect,
            services=[*self.uuid_services()],
        )

        try:
            await self._init_connection()
        except Exception as err:
            self._log.info(
                "failed to initialize BMS connection (%s)", type(err).__name__
            )
            await self.disconnect()
            raise

    async def _await_reply(
        self,
        data: bytes,
        char: BleakGATTCharacteristic | int | str | None = None,
        wait_for_notify: bool = True,
    ) -> None:
        """Send data to the BMS and wait for valid reply notification."""

        self._log.debug("TX BLE data: %s", data.hex(" "))
        self._data_event.clear()  # clear event before requesting new data
        await self._client.write_gatt_char(char or self.uuid_tx(), data, response=False)
        if wait_for_notify:
            await asyncio.wait_for(self._wait_event(), timeout=self.TIMEOUT)

    async def disconnect(self) -> None:
        """Disconnect the BMS, includes stoping notifications."""

        if self._client.is_connected:
            self._log.debug("disconnecting BMS")
            try:
                self._data_event.clear()
                await self._client.disconnect()
            except BleakError:
                self._log.warning("disconnect failed!")

    async def _wait_event(self) -> None:
        """Wait for data event and clear it."""
        await self._data_event.wait()
        self._data_event.clear()

    @abstractmethod
    async def _async_update(self) -> BMSsample:
        """Return a dictionary of BMS values (keys need to come from the SENSOR_TYPES list)."""

    async def async_update(self, raw: bool = False) -> BMSsample:
        """Retrieve updated values from the BMS using method of the subclass.

        Args:
            raw (bool): if true, the raw data from the BMS is returned without
                any calculations or missing values added

        Returns:
            BMSsample: dictionary with BMS values

        """
        await self._connect()

        data: BMSsample = await self._async_update()
        if not raw:
            self._add_missing_values(data, self._calc_values())

        if self._reconnect:
            # disconnect after data update to force reconnect next time (slow!)
            await self.disconnect()

        return data


def crc_modbus(data: bytearray) -> int:
    """Calculate CRC-16-CCITT MODBUS."""
    crc: int = 0xFFFF
    for i in data:
        crc ^= i & 0xFF
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc % 2 else (crc >> 1)
    return crc & 0xFFFF


def crc_xmodem(data: bytearray) -> int:
    """Calculate CRC-16-CCITT XMODEM."""
    crc: int = 0x0000
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = (crc << 1) ^ 0x1021 if (crc & 0x8000) else (crc << 1)
    return crc & 0xFFFF


def crc8(data: bytearray) -> int:
    """Calculate CRC-8/MAXIM-DOW."""
    crc: int = 0x00  # Initialwert für CRC

    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8C if crc & 0x1 else crc >> 1

    return crc & 0xFF


def crc_sum(frame: bytearray) -> int:
    """Calculate frame CRC."""
    return sum(frame) & 0xFF
