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
from aiobmsble.bms.greenway_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import BMSBasicTests

BT_FRAME_SIZE = 20

_PROTO_DEFS: Final[tuple[bytes, ...]] = (
    b"\x47\x16\x01\x08\x20\x11\x11\x11\x12\x13\x13\x13\x00\x11\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x6b\x6b\x64\x00\x00\x00\x00\x00\x00\x4f",
    b"\x47\x16\x01\x09\x04\x7c\x39\x01\x00\x21",  # voltage 80.252V
    b"\x47\x16\x01\x0a\x04\x7b\x3a\x00\x00\x21",  # current 14971mA
    b"\x47\x16\x01\x0d\x04\x4a\x00\x00\x00\xb9",  # SOC 74%
    b"\x47\x16\x01\x0e\x04\x64\x00\x00\x00\xd4",  # SOH 100%
    b"\x47\x16\x01\x0f\x04\x0c\x6e\x00\x00\xeb",  # cycle charge 28.172Ah
    b"\x47\x16\x01\x10\x04\x80\x93\x00\x00\x85",  # measured capacity?
    b"\x47\x16\x01\x14\x04\x00\x64\xca\x02\xa6",
    b"\x47\x16\x01\x16\x10\x88\x90\x00\x00\x00\x00\x00\x00\x00\x00\x8e\x00\x00\x00\x00\x00\x2a",
    b"\x47\x16\x01\x17\x04\x10\x00\x00\x00\x89",  # cycles 16
    b"\x47\x16\x01\x18\x04\x80\x93\x00\x00\x8d",  # design capacity 37.760Ah
    b"\x47\x16\x01\x19\x04\x40\x19\x01\x00\xd5",  # design voltage 72.000V
    b"\x47\x16\x01\x1a\x08\x3f\x03\x03\x00\x55\x44\x30\x31\xbf",  # SW 3.63, HW 0.63, FW: UD01
    b"\x47\x16\x01\x1b\x04\x19\x03\x0b\x00\xa4",  # manufacturing date 19-03-25
    b"\x47\x16\x01\x1c\x04\x00\x00\x00\x00\x7e",  # warranty date?
    b"\x47\x16\x01\x1d\x06\x1a\x05\x12\x11\x00\x16\xd9",
    b"\x47\x16\x01\x1e\x06\x00\x00\x58\x02\x2f\x00\x0b",
    b"\x47\x16\x01\x20\x10\x47\x52\x45\x45\x4e\x57\x41\x59\x00\x00\x00\x00\x00\x00\x00\x00\xf0",  # GREENWAY
    b"\x47\x16\x01\x21\x20\x44\x4d\x33\x33\x37\x32\x30\x30\x38\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x97",  # DM3372008
    b"\x47\x16\x01\x22\x10\x53\x41\x4d\x53\x55\x4e\x47\x2d\x35\x30\x53\x00\x00\x00\x00\x00\x93",  # cell name: SAMSUNG-50S
    b"\x47\x16\x01\x23\x20\x35\x36\x43\x30\x30\x32\x35\x33\x41\x30\x30\x30\x33\x37\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x84",  # 56C00253A00037
    b"\x47\x16\x01\x24\x20\xb0\x0f\xad\x0f\xae\x0f\xad\x0f\xaf\x0f\xaf\x0f\xab\x0f\xb1\x0f\xb1\x0f\xb2\x0f\xac\x0f\xab\x0f\xaa\x0f\xab\x0f\xaa\x0f\xa9\x0f\x66",  # cellV
    b"\x47\x16\x01\x25\x20\xaa\x0f\xab\x0f\xaa\x0f\xa9\x0f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x87",  # cellV cont.
    b"\x47\x16\x01\x26\x0e\x36\xe4\xfd\xff\x1c\x5c\x00\x00\x7a\x10\xb4\x0c\x2f\x08\xa1",
)


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


class MockGreenwayBleakClient(MockBleakClient):
    """Emulate a Greenway BMS BleakClient."""

    _chunk_sizes: Final[bytes] = (
        b"\x01\x03\x05\x07\x13\x01\x03\x05\x07\x01\x03\x05\x01\x03\x01"
    )
    _RESP: Final[tuple[bytes, ...]] = _PROTO_DEFS
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

    async def _stream_data(self) -> None:
        assert self._notify_callback, "send confirm called but notification not enabled"
        while True:

            for notify_data in [
                self._RESP[self._iterator][i : i + BT_FRAME_SIZE]
                for i in range(0, len(self._RESP[self._iterator]), BT_FRAME_SIZE)
            ]:
                self._notify_callback("MockGreenwayBleakClient", notify_data)
            self._iterator = (self._iterator + 1) % len(self._RESP)
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
        await asyncio.sleep(0)

    async def disconnect(self) -> None:
        """Mock disconnect and wait for send task."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        await super().disconnect()


async def test_update(patch_bleak_client, keep_alive_fixture: bool) -> None:
    """Test MyVolta BMS data update."""

    patch_bleak_client(MockGreenwayBleakClient)

    bms = BMS(generate_ble_device(), keep_alive_fixture)

    assert await bms.async_update() == {
        "voltage": 80.252,
        "battery_charging": True,
        "battery_health": 100,
        "battery_level": 74,
        "cell_count": 20,
        "cell_voltages": [
            4.016,
            4.013,
            4.014,
            4.013,
            4.015,
            4.015,
            4.011,
            4.017,
            4.017,
            4.018,
            4.012,
            4.011,
            4.01,
            4.011,
            4.01,
            4.009,
            4.01,
            4.011,
            4.01,
            4.009,
        ],
        "current": 14.971,
        "cycle_capacity": 2260.859,
        "cycle_charge": 28.172,
        "cycles": 16,
        "delta_voltage": 0.009,
        "design_capacity": 37.76,
        "power": 1201.453,
        "problem": False,
    }
    # query again to check already connected state
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()


async def test_tx_notimplemented(patch_bleak_client) -> None:
    """Test MyVolta BMS uuid_tx not implemented for coverage."""

    patch_bleak_client(MockGreenwayBleakClient)

    bms = BMS(generate_ble_device(), False)

    with pytest.raises(NotImplementedError):
        _ret: str = bms.uuid_tx()


@pytest.mark.parametrize(
    ("wrong_response"),
    [
        b"\x47\x16\x01\x09\x04\x7c\x39\x01\x00\xff",
        b"\x47\x16\x01\x09\x05\x7c\x39\x01\x00\x21",
        b"\xff\x16\x01\x09\x04\x7c\x39\x01\x00\x21",
        b"",
    ],
    ids=["wrong_CRC", "wrong_len", "wrong_SOF", "empty"],
)
async def test_invalid_response(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    patch_bms_timeout,
    wrong_response: bytes,
) -> None:
    """Test data up date with BMS returning invalid data."""

    patch_bms_timeout("greenway_bms")
    monkeypatch.setattr(BMS, "_MSG_SET", frozenset({0x9}))  # only require voltage
    monkeypatch.setattr(MockGreenwayBleakClient, "_RESP", (wrong_response,))
    patch_bleak_client(MockGreenwayBleakClient)

    bms = BMS(generate_ble_device())
    await asyncio.sleep(1e-3)  # wait for notifications to be sent
    result: BMSSample = {}
    with pytest.raises(TimeoutError):
        result = await bms.async_update()

    assert not result
    await bms.disconnect()
