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

# ---------------------------------------------------------------------------
# Reference frames (captured from a real Allpowers R1500 V2.0)
# ---------------------------------------------------------------------------

# Status frame: DC=on, AC=on, torch=off, freq=50Hz
# battery_level=72%, input=85W, output=120W, minutes_remaining=240
# flags byte [7] = 0b00000011 = 0x03  (DC bit0=1, AC bit1=1, freq bit2=0, torch bit4=0)
_FRAME_STATUS_DISCHARGING: Final[bytes] = (
    b"\xa5\x65\xb1\x01\x01\x00\x00\x03\x48\x00\x55\x00\x78\x00\xf0"
)


# Derived expected result for the discharging frame
_RESULT_DISCHARGING: Final[BMSSample] = {
    "battery_level": 72,
    "power": float(85 - 120),
    "chrg_mosfet": True,
    "dischrg_mosfet": True,
    "runtime": 240 * 60,
    "problem": False,
}

# Status frame: AC=on, DC=off, torch=off, freq=60Hz, charging (no discharge runtime)
# battery_level=45%, input=900W, output=0W, minutes_remaining=0xFFFF (sentinel)
# flags byte [7] = 0b00000110 = 0x06  (DC bit0=0, AC bit1=1, freq bit2=1, torch bit4=0)
_FRAME_STATUS_CHARGING: Final[bytes] = (
    b"\xa5\x65\xb1\x01\x01\x00\x00\x06\x2d\x03\x84\x00\x00\xff\xff"
)

_RESULT_CHARGING: Final[BMSSample] = {
    "battery_level": 45,
    "power": float(900 - 0),
    "chrg_mosfet": True,
    "dischrg_mosfet": False,
    "problem": False,
}

# Status frame: all outputs off, torch on, 50Hz, idle (net power = 0)
# battery_level=100%, input=0W, output=0W, minutes_remaining=0xFFFF
# flags byte [7] = 0b00010000 = 0x10  (torch bit4=1)
_FRAME_STATUS_IDLE: Final[bytes] = (
    b"\xa5\x65\xb1\x01\x01\x00\x00\x10\x64\x00\x00\x00\x00\xff\xff"
)

_RESULT_IDLE: Final[BMSSample] = {
    "battery_level": 100,
    "power": 0.0,
    "chrg_mosfet": False,
    "dischrg_mosfet": False,
    "problem": False,
}

# Settings notification (short frame, prefix a565b100010603): should be ignored
_FRAME_SETTINGS: Final[bytes] = bytes.fromhex("a565b100010603") + b"\x02\x01\xab\x00"


# ---------------------------------------------------------------------------
# BMSBasicTests mixin
# ---------------------------------------------------------------------------


class TestBasicBMS(BMSBasicTests):
    """Run the standard suite of BaseBMS conformance checks."""

    bms_class = BMS


# ---------------------------------------------------------------------------
# Mock BleakClient
# ---------------------------------------------------------------------------


class MockAllpowersBleakClient(MockBleakClient):
    """Emulate an Allpowers BLE device.

    The device pushes status frames autonomously after the notification
    subscription is set up — no TX command is ever sent.  The mock simulates
    this by scheduling a frame push immediately after start_notify() returns.
    """

    # Subclasses / parametric tests override this to change what gets pushed.
    FRAME: bytes = _FRAME_STATUS_DISCHARGING

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
            await asyncio.sleep(0)
            notify_callback = self._notify_callback
            if notify_callback is None or not self._connected:
                return
            notify_callback("MockAllpowers", bytearray(self.FRAME))
            await asyncio.sleep(0.05)

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


class MockAllpowersChargingClient(MockAllpowersBleakClient):
    """Mock client that pushes a charging frame."""

    FRAME: bytes = _FRAME_STATUS_CHARGING


class MockAllpowersIdleClient(MockAllpowersBleakClient):
    """Mock client that pushes an idle frame."""

    FRAME: bytes = _FRAME_STATUS_IDLE


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
                notify_callback("MockAllpowers", bytearray(_FRAME_SETTINGS))
                self._sent_settings = True
            notify_callback("MockAllpowers", bytearray(_FRAME_STATUS_DISCHARGING))
            await asyncio.sleep(0)


async def test_update_discharging(
    patch_bleak_client: Callable[..., None], keep_alive_fixture: bool
) -> None:
    """Test Allpowers BMS data update while discharging."""
    patch_bleak_client(MockAllpowersBleakClient)
    bms = BMS(generate_ble_device(), BMSConfig(keep_alive=keep_alive_fixture))

    result = await bms.async_update()
    assert result == _RESULT_DISCHARGING

    # Second call exercises the already-connected path.
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()


async def test_update_charging(patch_bleak_client: Callable[..., None]) -> None:
    """Test Allpowers BMS data update while charging (no runtime expected)."""
    patch_bleak_client(MockAllpowersChargingClient)
    bms = BMS(generate_ble_device())

    assert await bms.async_update() == _RESULT_CHARGING

    await bms.disconnect()


async def test_update_idle(patch_bleak_client: Callable[..., None]) -> None:
    """Test Allpowers BMS data update while idle (torch on, no outputs, no runtime)."""
    patch_bleak_client(MockAllpowersIdleClient)
    bms = BMS(generate_ble_device())

    assert await bms.async_update() == _RESULT_IDLE

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
    assert await bms.async_update() == _RESULT_DISCHARGING

    await bms.disconnect()


def test_uuid_tx_not_implemented() -> None:
    """Test that TX UUID is intentionally not implemented for stream-only protocol."""
    with pytest.raises(NotImplementedError):
        BMS.uuid_tx()


@pytest.mark.parametrize(
    ("bad_frame", "reason"),
    [
        (bytearray(b"\x00" + bytes(14)), "wrong_SOF"),
        (bytearray(b"\xa5\x65\xb1" + bytes(10)), "too_short"),
        (bytearray(b""), "empty"),
    ],
    ids=["wrong_SOF", "too_short", "empty"],
)
async def test_invalid_frame_ignored(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client: Callable[..., None],
    patch_bms_timeout: Callable[..., None],
    bad_frame: bytearray,
    reason: str,
) -> None:
    """Test that malformed frames are rejected and trigger a timeout."""
    patch_bms_timeout()
    monkeypatch.setattr(MockAllpowersBleakClient, "FRAME", bad_frame)
    patch_bleak_client(MockAllpowersBleakClient)

    bms = BMS(generate_ble_device())
    with pytest.raises(TimeoutError):
        await bms.async_update()

    await bms.disconnect()
