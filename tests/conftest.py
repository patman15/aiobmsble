"""Common fixtures for the aiobmsble library tests.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
"""

from collections.abc import Awaitable, Buffer, Callable, Iterable
import logging
from types import ModuleType
from typing import Any, Final
from uuid import UUID

from _pytest.config import Notset
from bleak import BleakClient
from bleak.assigned_numbers import CharacteristicPropertyName
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.backends.service import BleakGATTService, BleakGATTServiceCollection
from bleak.exc import BleakCharacteristicNotFoundError
from bleak.uuids import normalize_uuid_str
from hypothesis import HealthCheck, settings
import pytest

from aiobmsble import BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS
from aiobmsble.utils import load_bms_plugins
from tests.bluetooth import generate_ble_device

logging.basicConfig(level=logging.INFO)
LOGGER: logging.Logger = logging.getLogger(__package__)

pytest_plugins: list[str] = ["aiobmsble.test_data"]


def pytest_addoption(parser) -> None:
    """Add custom command-line option for max_examples."""
    parser.addoption(
        "--max-examples",
        action="store",
        type=int,
        default=1000,
        help="Set the maximum number of examples for Hypothesis tests.",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Configure pytest with custom settings."""
    max_examples: int | Notset = config.getoption("--max-examples")
    settings.register_profile(
        "default",
        max_examples=max_examples,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    settings.load_profile("default")


@pytest.fixture(
    params=sorted(
        load_bms_plugins(), key=lambda plugin: getattr(plugin, "__name__", "")
    ),
    ids=lambda param: param.__name__.rsplit(".", 1)[-1],
)
def plugin_fixture(request: pytest.FixtureRequest) -> ModuleType:
    """Return module of a BMS."""
    return request.param


@pytest.fixture(params=[False, True])
def bool_fixture(request) -> bool:
    """Return False, True for tests."""
    return request.param


class MockBleakClient(BleakClient):
    """Mock bleak client."""

    BT_INFO: Final[dict[str, bytes]] = {
        "2a24": b"mock_model",
        "2a25": b"mock_serial_number",
        "2a26": b"mock_FW_version",
        "2a27": b"mock_HW_version",
        "2a28": b"mock_SW_version",
        "2a29": b"mock_manufacturer",
    }

    def __init__(
        self,
        address_or_ble_device: BLEDevice,
        disconnected_callback: Callable[[BleakClient], None] | None,
        services: Iterable[str] | None = None,
        **kwargs,
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
        _services: BleakGATTServiceCollection = BleakGATTServiceCollection()
        _services.add_service(BleakGATTService(None, 0, normalize_uuid_str("180a")))
        return _services

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
        """Mock read GATT characteristics."""

        LOGGER.debug("MockBleakClient read_gatt_char %s", char_specifier)
        assert self._connected, "read_gatt_char called, but client not connected."

        if isinstance(char_specifier, str):
            char_specifier = normalize_uuid_str(char_specifier)[4:8]
            if char_specifier not in MockBleakClient.BT_INFO:
                raise BleakCharacteristicNotFoundError(char_specifier)
            return bytearray(MockBleakClient.BT_INFO[char_specifier])

        return bytearray()

    async def disconnect(self) -> None:
        """Mock disconnect."""

        LOGGER.debug("MockBleakClient disconnecting %s", self._ble_device.address)
        self._connected = False
        if self._disconnect_callback is not None:
            self._disconnect_callback(self)


class MockBMS(BaseBMS):
    """Mock Battery Management System."""

    INFO: BMSInfo = {"manufacturer": "Mock Manufacturer", "model": "mock model"}

    def __init__(
        self, exc: Exception | None = None, ret_value: BMSSample | None = None
    ) -> None:
        """Initialize BMS."""
        super().__init__(generate_ble_device(address="", details={"path": None}), False)
        LOGGER.debug("%s init(), Test except: %s", self.bms_id(), str(exc))
        self._exception: Exception | None = exc
        self._ret_value: BMSSample = (
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

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        await self._connect()

        if self._exception:
            raise self._exception

        return self._ret_value


@pytest.fixture(params=[-13, 0, 21], ids=["neg_current", "zero_current", "pos_current"])
def bms_data_fixture(request) -> BMSSample:
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


@pytest.fixture(params=[True, False], ids=["keep_alive", "reconnect"])
def keep_alive_fixture(request: pytest.FixtureRequest) -> bool:
    """Return True, False for keep_alive test."""
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
