r"""Test the 123\\SmartBMS implementation."""

import asyncio
from collections.abc import Buffer, Callable, Iterable
from typing import Any, Final
from uuid import UUID

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
import pytest

from aiobmsble import BMSConfig, BMSSample, TempSensor as TS
from aiobmsble.bms.x123smart_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import BMSBasicTests

# one full data cycle of a 4s pack (4 cells @ 3.5 V, 25.0 C, SoC 100 %)
_FRAME: Final[bytes] = (
    b"U_0AF0_+0014_+0014_+000A\r"  # pack 14.0 V, current 1.0 A
    b"C_01_04_2BC_12C_03_30\r"  # cell 1: 3.5 V, 25.0 C
    b"C_02_04_2BC_12C_03_30\r"
    b"C_03_04_2BC_12C_03_30\r"
    b"C_04_04_2BC_12C_03_30\r"
    b"E_000000_000000_000000_64\r"  # SoC 100 %
)

_RESULT_DEFS: Final[BMSSample] = {
    "voltage": 14.0,
    "current": 1.0,
    "battery_level": 100,
    "cell_count": 4,
    "cell_voltages": [3.5, 3.5, 3.5, 3.5],
    "temp_values": [TS(25.0, TS.T.CELL)] * 4,
    "delta_voltage": 0.0,
    "temperature": 25.0,
    "power": 14.0,
    "battery_charging": True,
    "problem": False,
}


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


class Mock123SmartBleakClient(MockBleakClient):
    r"""Emulate a 123\\SmartBMS gen3 BleakClient (Nordic UART, ping-driven stream)."""

    SECRET: bytes = b"8182"
    REQUIRE_PASS: bool = False  # if True, streaming requires a valid PIN first

    _tasks: set[asyncio.Task[None]] = set()

    def __init__(
        self,
        address_or_ble_device: BLEDevice,
        disconnected_callback: Callable[[BleakClient], None] | None,
        services: Iterable[str] | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize MockBleakClient."""
        super().__init__(
            address_or_ble_device, disconnected_callback, services, **kwargs
        )
        self._services = ["6e400001-b5a3-f393-e0a9-e50e24dcca9e"]
        self._authorized: bool = not self.REQUIRE_PASS

    def _reply(self, data: bytes) -> bytes:
        """Return the notification payload for a given write."""
        if data == b"$":  # keep-alive poll -> stream data (only once authorized)
            return _FRAME if self._authorized else b""
        if data.startswith(b"PW") and data.endswith(b"!\r"):
            if data[2:-2] == self.SECRET:
                self._authorized = True
                return b"OK\r"
            return b"NA\r"
        if data == b"E!\r":
            return b"OK\r" if self._authorized else b"NA\r"
        return b""

    async def _send(self, data: bytes) -> None:
        assert self._notify_callback, "write before notifications enabled"
        if payload := self._reply(data):
            self._notify_callback(BMS.uuid_rx(), bytearray(payload))
        await asyncio.sleep(0)

    async def write_gatt_char(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        data: Buffer,
        response: bool | None = None,
    ) -> None:
        """Issue write command to GATT and push the emulated response."""
        task: asyncio.Task[None] = asyncio.create_task(self._send(bytes(data)))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def disconnect(self) -> None:
        """Mock disconnect, awaiting pending notifications."""
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        await super().disconnect()


@pytest.fixture(autouse=True)
def _fast_timings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Speed up ping/warm-up/cycle timings for tests."""
    monkeypatch.setattr(BMS, "_WARMUP", 0.0)
    monkeypatch.setattr(BMS, "_PING_INTERVAL", 0.01)
    monkeypatch.setattr(BMS, "_CYCLE_TIMEOUT", 2.0)
    monkeypatch.setattr(BMS, "_CMD_TIMEOUT", 2.0)


async def test_update(patch_bleak_client, keep_alive_fixture: bool) -> None:
    r"""Test 123\\SmartBMS data update."""
    patch_bleak_client(Mock123SmartBleakClient)

    bms = BMS(generate_ble_device(), BMSConfig(keep_alive_fixture, secret="8182"))

    assert await bms.async_update() == _RESULT_DEFS

    await bms.async_update()  # second query to cover already-connected path
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()


@pytest.mark.parametrize(
    "secret", ["8182", "0000", ""], ids=["correct", "wrong", "missing"]
)
async def test_update_secret(
    monkeypatch: pytest.MonkeyPatch, patch_bleak_client, secret: str
) -> None:
    """Test that a wrong or missing PIN raises during connect."""
    monkeypatch.setattr(Mock123SmartBleakClient, "REQUIRE_PASS", True)
    patch_bleak_client(Mock123SmartBleakClient)

    bms = BMS(generate_ble_device(), BMSConfig(secret=secret))
    if secret == "8182":
        assert await bms.async_update() == _RESULT_DEFS
    else:
        with pytest.raises((ConnectionError, TimeoutError)):
            await bms.async_update()

    await bms.disconnect()
