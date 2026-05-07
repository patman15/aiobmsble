"""Test the MyVolta BMS implementation."""

import asyncio
from collections.abc import Awaitable, Callable, Iterable
import contextlib
from typing import Any, Final
from uuid import UUID

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
import pytest

from aiobmsble import BMSSample
from aiobmsble.bms.myvolta_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import BMSBasicTests

_PROTO_DEFS: Final[bytes] = (
    b"\x55\x55\x83\x00\x08\x01\x74\x04\x04"
    b"\x55\x55\x01\x00\x02\x00\x00\x00\x08\x01\xe0\xc8\xff\x14\xe0\xae\x03\xa8\x04\x04"
    b"\x55\x55\x01\x01\x02\x00\x00\x00\x08\x03\x00\x00\x17\x00\x00c\xe0\x97\x04\x04"
    b"\x55\x55\x01\x11\x02\x00\x00\x00\x08\x08\x10\x08\x10\x08\x10\x08\x10\x84\x04\x04"
    b"\x55\x55\x01\x12\x02\x00\x00\x00\x08\x08\x10\x08\x10\x03\x10\x08\x10\x88\x04\x04"
    b"\x55\x55\x01\x13\x02\x00\x00\x00\x08\xff\x0f\x08\x10\x08\x10\x08\x10\x8c\x04\x04"
    b"\x55\x55\x01\x14\x02\x00\x00\x00\x08\x08\x10\x08\x10\x00\x00\x01\x00\xb0\x04\x04"
    b"\x55\x55\x01!\x02\x00\x00\x00\x08\x00\x80\x00\x80\x00\x80\x00\x80\xd4\x04\x04"
    b"\x55\x55\x01\x22\x02\x00\x00\x00\x08\x00\x80\x00\x80\x00\x00%\x03\xab\x04\x04"
    b"\x55\x55\x01\x22\x02\x00\x00\x00\x08\x00\x80\x00\x80\x00\x00%\x03\xab\x04\x04"
    b"\x55\x55\x01$\x02\x00\x00\x00\x08\xab\x00\xac\x00\xac\x00\xad\x00!\x04\x04"
    b"\x55\x55\x01%\x02\x00\x00\x00\x08\xac\x00\xac\x00\xa6\x00\xa8\x00*\x04\x04"
    b"\x55\x55\x01&\x02\x00\x00\x00\x08\xa7\x00\xa6\x00\xa9\x00\xa6\x003\x04\x04"
    b"\x55\x55\x01'\x02\x00\x00\x00\x08\xdc\xfd\xdc\xfd\xdc\xfd\xdc\xfdj\x04\x04"
    b"\x55\x55\x01(\x02\x00\x00\x00\x08\xdc\xfd\xdc\xfd\xdc\xfd\xdc\xfdi\x04\x04"
    b"\x55\x55\x01)\x02\x00\x00\x00\x08\xdc\xfd\xdc\xfd\xdc\xfd\xdc\xfdh\x04\x04"
)


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


class MockMyVoltaBleakClient(MockBleakClient):
    """Emulate a MyVolta BMS BleakClient."""

    _chunk_sizes: Final[bytes] = (
        b"\x01\x03\x05\x07\x13\x01\x03\x05\x07\x01\x03\x05\x01\x03\x01"
    )
    _RESP: bytes = _PROTO_DEFS

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
            chunk_size: int = self._chunk_sizes[self._iterator]
            self._notify_callback(
                "MockMyVoltaBleakClient", self._RESP[self._pos : self._pos + chunk_size]
            )
            self._pos = (self._pos + chunk_size) % len(self._RESP)
            self._iterator = (self._iterator + 1) % len(self._chunk_sizes)
            await asyncio.sleep(0)

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
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        await super().disconnect()


async def test_update(patch_bleak_client, keep_alive_fixture: bool) -> None:
    """Test MyVolta BMS data update."""

    patch_bleak_client(MockMyVoltaBleakClient)

    bms = BMS(generate_ble_device(), keep_alive_fixture)

    assert await bms.async_update() == {
        "voltage": 57.345,
        "cell_count": 15,
        "cell_voltages": [
            4.104,
            4.104,
            4.104,
            4.104,
            4.104,
            4.104,
            4.099,
            4.104,
            4.095,
            4.104,
            4.104,
            4.104,
            4.104,
            4.104,
            0.001,
        ],
        "current": -0.56,
        "delta_voltage": 4.103,
        "battery_level": 94.2,
        "heater": False,
        "problem_code": 0,
        "power": -32.113,
        "battery_charging": False,
        "problem": False,
        "temp_values": [
            17.1,
            17.2,
            17.2,
            17.3,
            17.2,
            17.2,
            16.6,
            16.8,
            16.7,
            16.6,
            16.9,
            16.6,
        ],
        "temperature": 16.95,
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


@pytest.mark.parametrize(
    ("wrong_response"),
    [
        b"\x55\x55\x01\x00\x02\x00\x00\x00\x08\x01\xe0\xc8\xff\x14\xe0\xae\x03\xff\x04\x04",
        b"\x55\x55\x01\x00\x02\x00\x00\x00\x0a\x01\xe0\xc8\xff\x14\xe0\xae\x03\xa6\x04\x04",
        b"",
    ],
    ids=["wrong_CRC", "wrong_len", "empty"],
)
async def test_invalid_response(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    patch_bms_timeout,
    wrong_response: bytes,
) -> None:
    """Test data up date with BMS returning invalid data."""

    patch_bms_timeout("myvolta_bms")
    monkeypatch.setattr(
        MockMyVoltaBleakClient, "_RESP", wrong_response + _PROTO_DEFS[29:]
    )
    patch_bleak_client(MockMyVoltaBleakClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = {}
    with pytest.raises(TimeoutError):
        result = await bms.async_update()

    assert not result
    await bms.disconnect()
