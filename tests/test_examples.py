"""Test classes for package examples."""

from collections.abc import Callable
from typing import Any, NoReturn

from bleak.backends.device import BLEDevice
import pytest

from aiobmsble import BMSAuthError, BMSConnectionError, BMSError
import examples.minimal
from tests.bluetooth import generate_ble_device


@pytest.fixture(name="patch_find_device_by_name")
def fixture_find_device_by_name(monkeypatch: pytest.MonkeyPatch) -> Callable[[], None]:
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
        name: str, timeout: float = 10.0, **kwargs: Any
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
            "BMS data: {'battery_level': 73,\n\t'current': 1.5,\n\t'voltage': 12.0,\n\t"
            "'battery_charging': True,\n\t'power': 18.0,\n\t'problem': False}\n" in caplog.text
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
    @pytest.mark.parametrize(
        ("exc", "msg"),
        [
            (BMSConnectionError, "Failed to update BMS: BMSConnectionError"),
            (BMSAuthError, "BMS authentication failed; provide a valid secret."),
        ],
        ids=["connection", "auth"],
    )
    async def test_main_bms_err(
        monkeypatch: pytest.MonkeyPatch,
        patch_find_device_by_name: Callable[[], None],
        patch_bleak_client: Callable,
        caplog: pytest.LogCaptureFixture,
        exc: type[BMSError],
        msg: str,
    ) -> None:
        """Test that minimal example handles BMS errors."""

        def _raise_bms_error(self: Any) -> NoReturn:
            raise exc

        patch_find_device_by_name()
        # Ensure BMS attribute exists on the examples.minimal module before monkeypatching
        assert hasattr(examples.minimal, "BMS")
        monkeypatch.setattr(examples.minimal.BMS, "update", _raise_bms_error)
        patch_bleak_client()
        await examples.minimal.main("Dummy device")
        assert msg in caplog.text
