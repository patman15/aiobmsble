"""Common fixtures for the BLE Battery Management System integration tests."""

from collections.abc import Awaitable, Buffer, Callable, Iterable
import logging
from typing import Any
from uuid import UUID

from bleak import BleakClient
from bleak.assigned_numbers import CharacteristicPropertyName
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.backends.service import BleakGATTService, BleakGATTServiceCollection
from bleak.uuids import normalize_uuid_str
import pytest

from aiobmsble import BMSsample, MatcherPattern
from aiobmsble.basebms import BaseBMS

from .bluetooth import generate_ble_device

logging.basicConfig(level=logging.INFO)
LOGGER: logging.Logger = logging.getLogger(__package__)

@pytest.fixture(params=[False, True])
def bool_fixture(request) -> bool:
    """Return False, True for tests."""
    return request.param

class MockBleakClient(BleakClient):
    """Mock bleak client."""

    def __init__(
        self,
        address_or_ble_device: BLEDevice,
        disconnected_callback: Callable[[BleakClient], None] | None,
        services: Iterable[str] | None = None,
    ) -> None:
        """Mock init."""
        LOGGER.debug("MockBleakClient init")
        super().__init__(
            address_or_ble_device.address
        )  # call with address to avoid backend resolving
        self._connected: bool = False
        self._notify_callback: Callable | None = None
        self._disconnect_callback: Callable[[BleakClient], None] | None = (
            disconnected_callback
        )
        self._ble_device: BLEDevice = address_or_ble_device
        self._services: Iterable[str] | None = services

    @property
    def address(self) -> str:
        """Return device address."""
        return self._ble_device.address

    @property
    def is_connected(self) -> bool:
        """Mock connected."""
        return self._connected

    @property
    def services(self) -> BleakGATTServiceCollection:
        """Mock GATT services."""
        return BleakGATTServiceCollection()

    async def connect(self, **_kwargs) -> None:
        """Mock connect."""
        assert not self._connected, "connect called, but client already connected."
        LOGGER.debug("MockBleakClient connecting %s", self._ble_device.address)
        self._connected = True

    async def start_notify(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        callback: Callable[
            [BleakGATTCharacteristic, bytearray], None | Awaitable[None]
        ],
        **kwargs,
    ) -> None:
        """Mock start_notify."""
        LOGGER.debug("MockBleakClient start_notify for %s", char_specifier)
        assert self._connected, "start_notify called, but client not connected."
        self._notify_callback = callback

    async def write_gatt_char(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        data: Buffer,
        response: bool | None = None,
    ) -> None:
        """Mock write GATT characteristics."""
        LOGGER.debug(
            "MockBleakClient write_gatt_char %s, data: %s", char_specifier, data
        )
        assert self._connected, "write_gatt_char called, but client not connected."

    async def read_gatt_char(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        **kwargs,
    ) -> bytearray:
        """Mock write GATT characteristics."""
        LOGGER.debug("MockBleakClient read_gatt_char %s", char_specifier)
        assert self._connected, "read_gatt_char called, but client not connected."
        return bytearray()

    async def disconnect(self) -> None:
        """Mock disconnect."""

        LOGGER.debug("MockBleakClient disconnecting %s", self._ble_device.address)
        self._connected = False
        if self._disconnect_callback is not None:
            self._disconnect_callback(self)


class MockBMS(BaseBMS):
    """Mock Battery Management System."""

    def __init__(
        self, exc: Exception | None = None, ret_value: BMSsample | None = None
    ) -> None:  # , ble_device, reconnect: bool = False
        """Initialize BMS."""
        super().__init__(generate_ble_device(address="", details={"path": None}), False)
        LOGGER.debug("%s init(), Test except: %s", self.device_id(), str(exc))
        self._exception: Exception | None = exc
        self._ret_value: BMSsample = (
            ret_value
            if ret_value is not None
            else {
                "voltage": 13,
                "current": 1.7,
                "cycle_charge": 19,
                "cycles": 23,
            }
        )  # set fixed values for dummy battery

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [{"local_name": "mock", "connectable": True}]

    @staticmethod
    def device_info() -> dict[str, str]:
        """Return device information for the battery management system."""
        return {"manufacturer": "Mock Manufacturer", "model": "mock model"}

    @staticmethod
    def uuid_services() -> list[str]:
        """Return list of services required by BMS."""
        return [normalize_uuid_str("cafe")]

    @staticmethod
    def uuid_rx() -> str:
        """Return characteristic that provides notification/read property."""
        return "feed"

    @staticmethod
    def uuid_tx() -> str:
        """Return characteristic that provides write property."""
        return "cafe"

    def _notification_handler(
        self, sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Retrieve BMS data update."""

    async def _async_update(self) -> BMSsample:
        """Update battery status information."""
        await self._connect()

        if self._exception:
            raise self._exception

        return self._ret_value


@pytest.fixture(params=[-13, 0, 21], ids=["neg_current", "zero_current", "pos_current"])
def bms_data_fixture(request) -> BMSsample:
    """Return a fake BMS data dictionary."""

    return {
        "voltage": 7.0,
        "current": request.param,
        "cycle_charge": 34,
        "cell_voltages": [3.456, 3.567],
        "temp_values": [-273.15, 0.01, 35.555, 100.0],
    }


@pytest.fixture
def patch_bms_timeout(monkeypatch):
    """Fixture to patch BMS.TIMEOUT for different BMS classes."""

    def _patch_timeout(bms_class: str | None = None, timeout: float = 0.001) -> None:
        patch_class: str = (
            f"bms.{bms_class}.BMS.TIMEOUT"
            if bms_class
            else "basebms.BaseBMS._RETRY_TIMEOUT"
        )
        monkeypatch.setattr(f"aiobmsble.{patch_class}", timeout)

    return _patch_timeout


@pytest.fixture
def patch_bleak_client(monkeypatch):
    """Fixture to patch BleakClient with a given MockClient."""

    def _patch(mock_client=MockBleakClient) -> None:
        monkeypatch.setattr(
            "aiobmsble.basebms.BleakClient",
            mock_client,
        )

    return _patch


@pytest.fixture(params=[False, True], ids=["persist", "reconnect"])
def reconnect_fixture(request: pytest.FixtureRequest) -> bool:
    """Return False, True for reconnect test."""
    return request.param


class DefGATTChar(BleakGATTCharacteristic):
    """Create BleakGATTCharacteristic with default values."""

    def __init__(
        self,
        handle: int,
        uuid: str,
        obj: Any = None,
        properties: list[CharacteristicPropertyName] | None = None,
        max_write_without_response_size: Callable[[], int] | None = None,
        service: BleakGATTService = BleakGATTService(
            None, 0, normalize_uuid_str("fff0")
        ),
    ) -> None:
        """Add default values for base class.

        Args:
            obj:
                A platform-specific object for this characteristic.
            handle:
                The handle for this characteristic.
            uuid:
                The UUID for this characteristic.
            properties:
                List of properties for this characteristic. Default: 'read'
            max_write_without_response_size:
                The maximum size in bytes that can be written to the characteristic 
                in a single write without response command. Default: 512
            service:
                The service this characteristic belongs to. Default: 'fff0'

        """
        super().__init__(
            obj,
            handle,
            normalize_uuid_str(uuid),
            properties or ["read"],
            max_write_without_response_size or (lambda: 512),
            service,
        )
