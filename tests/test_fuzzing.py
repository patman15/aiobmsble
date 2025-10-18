"""Test aiobmsble library via fuzzing."""

from asyncio import iscoroutinefunction
from collections.abc import Callable
from types import ModuleType
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.service import BleakGATTService
from hypothesis import given, strategies as st
import pytest

from aiobmsble.basebms import BaseBMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient


@given(
    data=st.binary(min_size=0, max_size=513)
)  # ATT is not allowed larger than 512 bytes
async def test_notification_handler(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    pytestconfig: pytest.Config,
    plugin_fixture: ModuleType,
    data: bytearray,
) -> None:
    """Test the notification handler."""

    # fuzzing can run from VScode (no coverage) or command line with option --no-cov
    if {"vscode_pytest"}.issubset(
        set(pytestconfig.invocation_params.args)
    ) or (
        "vscode_pytest" not in pytestconfig.invocation_params.args
        and not pytestconfig.getoption("--no-cov")
    ):
        pytest.skip("Skipping fuzzing tests due to coverage generation!")

    async def patch_init() -> None:
        return

    patch_bleak_client(MockBleakClient)

    bms_instance: BaseBMS = plugin_fixture.BMS(  # char 10 needs to be A|B for OGT
        generate_ble_device(name="MockFuzz-BLE")
    )

    monkeypatch.setattr(
        bms_instance, "_init_connection", patch_init
    )  # required for _init_connection overloads, e.g. JK BMS

    await bms_instance._connect()
    notify_handler: Final[Callable] = bms_instance._notification_handler  # type: ignore[attr-defined]
    notify_characteristics: Final[BleakGATTCharacteristic] = BleakGATTCharacteristic(
        None, 1, "fff4", ["notify"], lambda: 512, BleakGATTService(None, 0, "fff0")
    )

    if iscoroutinefunction(notify_handler):
        await notify_handler(notify_characteristics, data)
    else:
        notify_handler(notify_characteristics, data)
