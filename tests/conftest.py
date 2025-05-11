"""Common fixtures for the BLE Battery Management System integration tests."""

from collections.abc import Awaitable, Buffer, Callable, Iterable
import logging
from typing import Literal
from uuid import UUID

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.descriptor import BleakGATTDescriptor
from bleak.backends.device import BLEDevice
from bleak.backends.service import BleakGATTServiceCollection
from bleak.uuids import normalize_uuid_str, uuidstr_to_str
import pytest

LOGGER: logging.Logger = logging.getLogger(__name__)


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

    async def connect(self, *_args, **_kwargs) -> Literal[True]:
        """Mock connect."""
        assert not self._connected, "connect called, but client already connected."
        LOGGER.debug("MockBleakClient connecting %s", self._ble_device.address)
        self._connected = True
        return True

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
        response: bool = None,  # noqa: RUF013 # same as upstream
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

    async def disconnect(self) -> bool:
        """Mock disconnect."""
        assert self._connected, "Disconnect called, but client not connected."
        LOGGER.debug("MockBleakClient disconnecting %s", self._ble_device.address)
        self._connected = False
        if self._disconnect_callback is not None:
            self._disconnect_callback(self)

        return True


class MockRespChar(BleakGATTCharacteristic):
    """Mock response characteristic."""

    @property
    def service_uuid(self) -> str:
        """The UUID of the Service containing this characteristic."""
        raise NotImplementedError

    @property
    def service_handle(self) -> int:
        """The integer handle of the Service containing this characteristic."""
        raise NotImplementedError

    @property
    def handle(self) -> int:
        """The handle for this characteristic."""
        raise NotImplementedError

    @property
    def uuid(self) -> str:
        """The UUID for this characteristic."""
        return normalize_uuid_str("fff4")

    @property
    def description(self) -> str:
        """Description for this characteristic."""
        return uuidstr_to_str(self.uuid)

    @property
    def properties(self) -> list[str]:
        """Properties of this characteristic."""
        raise NotImplementedError

    @property
    def descriptors(self) -> list[BleakGATTDescriptor]:
        """List of descriptors for this service."""
        raise NotImplementedError

    def get_descriptor(self, specifier: int | str | UUID) -> BleakGATTDescriptor | None:
        """Get a descriptor by handle (int) or UUID (str or uuid.UUID)."""
        raise NotImplementedError

    def add_descriptor(self, descriptor: BleakGATTDescriptor):
        """Add a :py:class:`~BleakGATTDescriptor` to the characteristic.

        Should not be used by end user, but rather by `bleak` itself.
        """
        raise NotImplementedError


@pytest.fixture
def patch_bleak_client(monkeypatch):
    """Fixture to patch BleakClient with a given MockClient."""

    def _patch(mock_client=MockBleakClient) -> None:
        monkeypatch.setattr(
            "aiobmsble.basebms.BleakClient",
            mock_client,
        )

    return _patch

@pytest.fixture
def patch_bms_timeout(monkeypatch):
    """Fixture to patch BMS.TIMEOUT for different BMS classes."""

    def _patch_timeout(bms_class: str, timeout: float = 0.1) -> None:
        monkeypatch.setattr(
            f"aiobmsble.bms.{bms_class}.BMS.TIMEOUT", timeout
        )

    return _patch_timeout

@pytest.fixture(params=[False, True], ids=["persist", "reconnect"])
def reconnect_fixture(request: pytest.FixtureRequest) -> bool:
    """Return False, True for reconnect test."""
    return request.param
