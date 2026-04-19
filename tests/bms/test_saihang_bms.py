"""Test the Saihang BMS implementation."""

import asyncio
from collections.abc import Awaitable, Callable
import contextlib
from typing import Final
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic

from aiobmsble.bms.saihang_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import BMSBasicTests


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


class MockSaihangBleakClient(MockBleakClient):
    """Emulate a Saihang BMS BleakClient."""

    _RESP: Final[bytes] = (
        b"\xa5\xa5\x00\x03\x90\x00\x00\x00\x00\x00\x00\x0a\xa8\x00\x60\x00\x64\x00\x00\x25\xa6\x00"
        b"\x00\x27\x10\x00\x00\x27\x10\x00\x02\xff\xff\x00\x01\x00\x00\x06\x00\x00\x00\x00\x00\x00"
        b"\x08\x0d\xa9\x0d\x6a\x0d\x28\x0d\x3d\x0d\x2c\x0d\x6b\x0d\x4d\x0d\x38\xff\xff\xff\xff\xff"
        b"\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\x00\x02\x0b"
        b"\x43\x0b\x46\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\x0b\x56\x0b"
        b"\xa4\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\x00\x00\x6d\x60\x00\x00\x72"
        b"\x10\x00\x00\x68\x10\x00\x0a\x0d\xac\x0e\x42\x0d\x02\x00\x0a\x00\x00\x9a\x5a"
    )
    _task: asyncio.Task[None] | None = None

    async def _notify(self) -> None:
        """Notify function."""

        assert (
            self._notify_callback
        ), "write to characteristics but notification not enabled"

        while True:
            self._notify_callback("MockECOWBleakClient", self._RESP)
            await asyncio.sleep(1e-6)

    async def start_notify(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        callback: Callable[
            [BleakGATTCharacteristic, bytearray], None | Awaitable[None]
        ],
        **kwargs,
    ) -> None:
        """Issue write command to GATT."""
        await super().start_notify(char_specifier, callback, **kwargs)

        self._task = asyncio.create_task(self._notify())

    async def disconnect(self) -> None:
        """Mock disconnect and wait for send task."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        await super().disconnect()


async def test_update(patch_bleak_client, keep_alive_fixture: bool) -> None:
    """Test Saihang BMS data update."""

    patch_bleak_client(MockSaihangBleakClient)

    bms = BMS(generate_ble_device(), keep_alive_fixture)

    assert await bms.async_update() == {
        "voltage": 27.28,
        "temperature": 15.35,
        "battery_charging": False,
        "battery_health": 100,
        "battery_level": 96,
        "cell_count": 8,
        "current": 0.0,
        "cycles": 2,
        "temp_sensors": 2,
        "temp_values": [15.2, 15.5],
        "cell_voltages": [
            3.497,
            3.434,
            3.368,
            3.389,
            3.372,
            3.435,
            3.405,
            3.384,
        ],
        "cycle_capacity": 2629.246,
        "cycle_charge": 96.38,
        "delta_voltage": 0.129,
        "design_capacity": 100,
        "problem": False,
        "problem_code": 0,
        "power": 0.0,
    }

    # query again to check already connected state
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()

def test_uuid_tx_not_used() -> None:
    """Test that TX UUID is intentionally not used."""
    assert BMS.uuid_tx() == "fffb"

# async def test_device_info(patch_bleak_client) -> None:
#     """Test that the BMS returns initialized dynamic device information."""
#     patch_bleak_client(MockSaihangBleakClient)
#     bms = BMS(generate_ble_device())
#     assert {"default_manufacturer", "default_model"}.issubset(await bms.device_info())
