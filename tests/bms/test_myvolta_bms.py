"""Test the MyVolta BMS implementation."""

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from typing import Any, Final
from uuid import UUID

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
import pytest

from aiobmsble.bms.myvolta_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import BMSBasicTests


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


class MockMyVoltaBleakClient(MockBleakClient):
    """Emulate a MyVolta BMS BleakClient."""

    _chunk_sizes: Final[bytes] = (
        b"\x01\x03\x05\x07\x13\x01\x03\x05\x07\x01\x03\x05\x01\x03\x01"
    )
    _RESP: bytes = (
        b"\x55\x55\x83\x00\x08\x01\x74\x04\x04"
        b"\x55\x55\x01\x00\x02\x00\x00\x00\x08\x06\xe1\xcd\xff\x0e\xe1\xba\x03\x96\x04\x04"
        b"\x55\x55\x01\x01\x02\x00\x00\x00\x08\x03\x00\x00\x17\x00\x00\x4e\xe1\xab\x04\x04"
        b"\x55\x55\x01\x11\x02\x00\x00\x00\x08\x17\x10\x1c\x10\x17\x10\x18\x10\x42\x04\x04"
        b"\x55\x55\x01\x12\x02\x00\x00\x00\x08\x17\x10\x18\x10\x17\x10\x1a\x10\x43\x04\x04"
        b"\x55\x55\x01\x13\x02\x00\x00\x00\x08\x12\x10\x19\x10\x17\x10\x1c\x10\x44\x04\x04"
        b"\x55\x55\x01\x14\x02\x00\x00\x00\x08\x17\x10\x18\x10\x00\x00\x01\x00\x91\x04\x04"
        b"\x55\x55\x01\x21\x02\x00\x00\x00\x08\x00\x80\x00\x80\x00\x80\x00\x80\xd4\x04\x04"
        b"\x55\x55\x01\x22\x02\x00\x00\x00\x08\x00\x80\x00\x80\x00\x00\x1c\x03\xb4\x04\x04"
        b"\x55\x55\x01\x22\x02\x00\x00\x00\x08\x00\x80\x00\x80\x00\x00\x1c\x03\xb4\x04\x04"
        b"\x55\x55\x01\x24\x02\x00\x00\x00\x08\x8e\x00\x8f\x00\x90\x00\x91\x00\x93\x04\x04"
        b"\x55\x55\x01\x25\x02\x00\x00\x00\x08\x8f\x00\x8f\x00\x8a\x00\x8b\x00\x9d\x04\x04"
        b"\x55\x55\x01\x26\x02\x00\x00\x00\x08\x8b\x00\x8a\x00\x8c\x00\x8a\x00\xa4\x04\x04"
        b"\x55\x55\x01\x27\x02\x00\x00\x00\x08\xdc\xfd\xdc\xfd\xdc\xfd\xdc\xfd\x6a\x04\x04"
    )

    _task: asyncio.Task[None] | None = None

    def __init__(
        self,
        address_or_ble_device: BLEDevice,
        disconnected_callback: Callable[[BleakClient], None] | None,
        services: Iterable[str] | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the MockMyVoltaBleakClient."""
        super().__init__(
            address_or_ble_device, disconnected_callback, services, **kwargs
        )
        self._iterator: int = 0
        self._pos: int = 0

    async def _stream_data(self) -> None:
        assert self._notify_callback, "send confirm called but notification not enabled"
        while True:
            await asyncio.sleep(0.01)
            chunk_size: int = self._chunk_sizes[self._iterator]
            self._notify_callback(
                "MockMyVoltaBleakClient", self._RESP[self._pos : self._pos + chunk_size]
            )
            self._pos = (self._pos + chunk_size) % len(self._RESP)
            self._iterator = (self._iterator + 1) % len(self._chunk_sizes)

    async def start_notify(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        callback: Callable[
            [BleakGATTCharacteristic, bytearray], None | Awaitable[None]
        ],
        **kwargs: Any,
    ) -> None:
        """Mock start_notify."""
        await super().start_notify(char_specifier, callback, **kwargs)
        self._task = asyncio.create_task(self._stream_data())

    async def disconnect(self) -> None:
        """Mock disconnect and wait for send task."""
        if self._task and not self._task.done():
            await asyncio.wait_for(self._task, 0.1)
            assert self._task.done(), "send task still running!"
        await super().disconnect()


async def test_update(patch_bleak_client, keep_alive_fixture: bool) -> None:
    """Test MyVolta BMS data update."""

    patch_bleak_client(MockMyVoltaBleakClient)

    bms = BMS(generate_ble_device(), keep_alive_fixture)

    assert await bms.async_update() == {
        "voltage": 57.606,
        "current": -0.51,
        "battery_level": 95.4,
        "power": -29.379,
        "battery_charging": False,
        "problem": False,
    }

    # query again to check already connected state
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()


async def test_tx_notimplemented(patch_bleak_client) -> None:
    """Test MyVolta BMS uuid_tx not implemented for coverage."""

    patch_bleak_client(MockMyVoltaBleakClient)

    bms = BMS(generate_ble_device(), False)

    with pytest.raises(NotImplementedError):
        _ret: str = bms.uuid_tx()
