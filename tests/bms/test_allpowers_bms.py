"""Test the Allpowers portable power station BMS implementation."""

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from typing import Any, Final
from uuid import UUID

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
import pytest

from aiobmsble import BMSConfig, BMSSample
from aiobmsble.bms.allpowers_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import BMSBasicTests

# Reference frames (captured from a real Allpowers R1500 V2.0)
_PROTO_DEFS: Final[dict[str, bytes]] = {
    "discharging": b"\xa5\x65\xb1\x01\x01\x00\x00\x03\x48\x00\x55\x00\x78\x00\xf0",
    "charging": b"\xa5\x65\xb1\x01\x01\x00\x00\x06\x2d\x03\x84\x00\x00\xff\xff",
    "idle": b"\xa5\x65\xb1\x01\x01\x00\x00\x10\x64\x00\x00\x00\x00\xff\xff",
    "settings": b"\xa5\x65\xb1\x00\x01\x06\x03\x02\x01\xab\x00",
}

_RESULT_DEFS: Final[dict[str, BMSSample]] = {
    "discharging": {
        "battery_level": 72,
        "power": float(85 - 120),
        "chrg_mosfet": True,
        "dischrg_mosfet": True,
        "runtime": 240 * 60,
        "problem": False,
    },
    "charging": {
        "battery_level": 45,
        "power": float(900 - 0),
        "chrg_mosfet": True,
        "dischrg_mosfet": False,
        "problem": False,
    },
    "idle": {
        "battery_level": 100,
        "power": 0.0,
        "chrg_mosfet": False,
        "dischrg_mosfet": False,
        "problem": False,
    },
}


class TestBasicBMS(BMSBasicTests):
    """Run the standard suite of BaseBMS conformance checks."""

    bms_class = BMS


class MockAllpowersBleakClient(MockBleakClient):
    """Emulate an Allpowers BLE device.

    The device pushes status frames autonomously after the notification
    subscription is set up — no TX command is ever sent.  The mock simulates
    this by scheduling a frame push immediately after start_notify() returns.
    """

    FRAME: bytes = _PROTO_DEFS["discharging"]

    _tasks: set[asyncio.Task[None]] = set()

    def __init__(
        self,
        address_or_ble_device: BLEDevice,
        disconnected_callback: Callable[[BleakClient], None] | None,
        services: Iterable[str] | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize mock client."""
        super().__init__(
            address_or_ble_device, disconnected_callback, services, **kwargs
        )

    async def _push_frames(self) -> None:
        """Push frames periodically like the real device, stop when disconnected."""
        for _ in range(50):  # cap iterations to avoid infinite loops in tests
            notify_callback = self._notify_callback
            if notify_callback is None or not self._connected:
                return
            notify_callback("MockAllpowers", bytearray(self.FRAME))
            await asyncio.sleep(0)

    async def start_notify(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        callback: Callable[
            [BleakGATTCharacteristic, bytearray], None | Awaitable[None]
        ],
        **kwargs: Any,
    ) -> None:
        """Subscribe to notifications and start pushing frames."""
        await super().start_notify(char_specifier, callback, **kwargs)
        task: asyncio.Task[None] = asyncio.create_task(self._push_frames())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def disconnect(self) -> None:
        """Await pending tasks before disconnecting."""
        if self._tasks:
            await asyncio.gather(*self._tasks)
        await super().disconnect()


class MockAllpowersSettingsOnlyClient(MockAllpowersBleakClient):
    """Mock client that first sends a settings frame, then the real status frame.

    Used to verify that settings (short) frames are correctly ignored and the
    BMS plugin waits for a valid status frame.
    """

    _sent_settings: bool = False

    async def _push_frames(self) -> None:
        notify_callback = self._notify_callback
        assert notify_callback is not None
        for _ in range(50):
            await asyncio.sleep(0)
            if not self._connected:
                return
            if not self._sent_settings:
                notify_callback("MockAllpowers", bytearray(_PROTO_DEFS["settings"]))
                self._sent_settings = True
            notify_callback("MockAllpowers", bytearray(_PROTO_DEFS["discharging"]))
            await asyncio.sleep(0)


async def test_update_discharging(
    patch_bleak_client: Callable[..., None], keep_alive_fixture: bool
) -> None:
    """Test Allpowers BMS data update while discharging."""
    patch_bleak_client(MockAllpowersBleakClient)
    bms = BMS(generate_ble_device(), BMSConfig(keep_alive=keep_alive_fixture))

    result = await bms.async_update()
    assert result == _RESULT_DEFS["discharging"]

    # Second call exercises the already-connected path.
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()


async def test_update_charging(
    monkeypatch: pytest.MonkeyPatch, patch_bleak_client: Callable[..., None]
) -> None:
    """Test Allpowers BMS data update while charging (no runtime expected)."""
    monkeypatch.setattr(MockAllpowersBleakClient, "FRAME", _PROTO_DEFS["charging"])
    patch_bleak_client(MockAllpowersBleakClient)
    bms = BMS(generate_ble_device())

    assert await bms.async_update() == _RESULT_DEFS["charging"]

    await bms.disconnect()


async def test_update_idle(
    monkeypatch: pytest.MonkeyPatch, patch_bleak_client: Callable[..., None]
) -> None:
    """Test Allpowers BMS data update while idle (torch on, no outputs, no runtime)."""
    monkeypatch.setattr(MockAllpowersBleakClient, "FRAME", _PROTO_DEFS["idle"])
    patch_bleak_client(MockAllpowersBleakClient)
    bms = BMS(generate_ble_device())

    assert await bms.async_update() == _RESULT_DEFS["idle"]

    await bms.disconnect()


async def test_settings_frame_ignored(
    patch_bleak_client: Callable[..., None],
) -> None:
    """Test that settings (short) frames are silently ignored.

    The mock pushes a settings frame first and then a valid status frame.
    The BMS plugin should skip the settings frame and successfully parse the
    status frame.
    """
    patch_bleak_client(MockAllpowersSettingsOnlyClient)
    # Reset class-level state between tests.
    MockAllpowersSettingsOnlyClient._sent_settings = False

    bms = BMS(generate_ble_device())
    assert await bms.async_update() == _RESULT_DEFS["discharging"]

    await bms.disconnect()


def test_uuid_tx_not_implemented() -> None:
    """Test that TX UUID is intentionally not implemented for stream-only protocol."""
    with pytest.raises(NotImplementedError):
        BMS.uuid_tx()


@pytest.mark.parametrize(
    ("bad_frame"),
    [
        (b"\x00" + bytes(14)),
        (b"\xa5\x65\xb1" + bytes(10)),
        (b""),
    ],
    ids=["wrong_SOF", "too_short", "empty"],
)
async def test_invalid_frame_ignored(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client: Callable[..., None],
    patch_bms_timeout: Callable[..., None],
    bad_frame: bytes,
) -> None:
    """Test that malformed frames are rejected and trigger a timeout."""
    patch_bms_timeout("allpowers_bms")
    monkeypatch.setattr(MockAllpowersBleakClient, "FRAME", bad_frame)
    patch_bleak_client(MockAllpowersBleakClient)

    bms = BMS(generate_ble_device())
    with pytest.raises(TimeoutError):
        await bms.async_update()

    await bms.disconnect()
