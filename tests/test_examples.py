"""Test clases for package exaples."""

from collections.abc import Callable
from typing import NoReturn

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
import pytest

import examples.minimal
from tests.bluetooth import generate_ble_device


@pytest.fixture(name="patch_find_device_by_name")
def fixture_find_device_by_name(monkeypatch: pytest.MonkeyPatch):
    """Fixture to patch BleakClient with a given MockClient."""

    def _patch() -> None:
        monkeypatch.setattr(
            "examples.minimal.BleakScanner.find_device_by_name",
            TestMinimal.mock_find_device_by_name,
        )

    return _patch


class TestMinimal:
    """Test the minimal.py example."""

    @staticmethod
    async def mock_find_device_by_name(
        name: str, timeout: float = 10.0, **_kwargs
    ) -> BLEDevice | None:
        """Mock function that returns a BleakDevice for 'Dummy device'."""
        assert timeout > 0
        if name == "Dummy device":
            return generate_ble_device("11:22:33:44:55:66", name)
        return None

    @staticmethod
    async def test_main(
        patch_find_device_by_name: Callable[[], None],
        patch_bleak_client: Callable,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that minimal example returns BMS data."""
        patch_find_device_by_name()
        patch_bleak_client()
        await examples.minimal.main("Dummy device")
        assert "Found device: Dummy device (11:22:33:44:55:66)" in caplog.text
        assert (
            "BMS data: {'voltage': 12,\n\t'current': 1.5,\n\t'temperature': 27.182,\n"
            "\t'power': 18.0,\n\t'battery_charging': True,\n\t'problem': False}\n"
            in caplog.text
        )

    @staticmethod
    async def test_main_no_dev(
        patch_find_device_by_name: Callable[[], None],
        patch_bleak_client: Callable,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that minimal example handles if the device with given name is not found."""

        patch_find_device_by_name()
        patch_bleak_client()
        await examples.minimal.main("wrong_name")
        assert "Device 'wrong_name' not found." in caplog.text

    @staticmethod
    async def test_main_bt_err(
        monkeypatch: pytest.MonkeyPatch,
        patch_find_device_by_name: Callable[[], None],
        patch_bleak_client: Callable,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that minimal example handles if a Bleak error occurs."""

        def _raise_bleak_error(_self) -> NoReturn:
            raise BleakError

        patch_find_device_by_name()
        monkeypatch.setattr(examples.minimal.BMS, "async_update", _raise_bleak_error)
        patch_bleak_client()
        await examples.minimal.main("Dummy device")
        assert "Failed to update BMS: BleakError" in caplog.text
