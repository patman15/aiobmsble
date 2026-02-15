"""Test the Super-B BMS implementation."""

from collections.abc import Awaitable, Callable
from typing import Final
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
import pytest

from aiobmsble import BMSSample
from aiobmsble.bms.superb_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import BMSBasicTests, verify_device_info

BT_FRAME_SIZE = 32

_PROTO_DEFS: Final[bytearray] = bytearray(
    b"\x00\x75\x5e\x64\x00\x00\x01\xa4\xbe\xcc\xcc\xcd\x41\x62\x89\xc5\x00\x00\x00\x00"
)

_RESULT_DEFS: Final[BMSSample] = {
    "voltage": 14.159,
    "current": -0.4,
    "battery_level": 94,
    "power": -5.664,
    "runtime": 420,
    "battery_charging": False,
    "balancer": False,
    "problem": False,
    "problem_code": 0,
}


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS

class MockSuperBBleakClient(MockBleakClient):
    """Emulate a Super-B BMS BleakClient."""

    _RESP: bytearray = _PROTO_DEFS

    def _send_info(self) -> None:
        assert self._notify_callback is not None
        for notify_data in [
            self._RESP[i : i + BT_FRAME_SIZE]
            for i in range(0, len(self._RESP), BT_FRAME_SIZE)
        ]:
            self._notify_callback("MockSuperBBleakClient", notify_data)

    @property
    def is_connected(self) -> bool:
        """Mock connected."""
        if self._connected:
            self._send_info()  # patch to provide data when not reconnecting
        return self._connected

    async def start_notify(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        callback: Callable[
            [BleakGATTCharacteristic, bytearray], None | Awaitable[None]
        ],
        **kwargs,
    ) -> None:
        """Mock start_notify."""
        await super().start_notify(char_specifier, callback)
        self._send_info()


async def test_update(monkeypatch, patch_bleak_client, keep_alive_fixture) -> None:
    """Test Super-B BMS data update."""

    monkeypatch.setattr(MockSuperBBleakClient, "_RESP", _PROTO_DEFS)
    patch_bleak_client(MockSuperBBleakClient)

    bms = BMS(generate_ble_device(), keep_alive_fixture)

    assert await bms.async_update() == _RESULT_DEFS

    # query again to check already connected state
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()


async def test_update_chrg(monkeypatch, patch_bleak_client) -> None:
    """Test Super-B BMS data update with positive current (charging)."""

    monkeypatch.setattr(
        MockSuperBBleakClient,
        "_RESP",
        bytearray(
            b"\x00\x75\x5e\x64\x00\x00\x01\xa4\x3e\xcc\xcc\xcd\x41\x62\x89\xc5\x00\x00\x00\x00"
        ),
    )
    patch_bleak_client(MockSuperBBleakClient)

    bms = BMS(generate_ble_device())

    result = _RESULT_DEFS.copy() | {
        "current": 0.4,
        "battery_charging": True,
        "power": 5.664,
    }
    del result["runtime"]
    assert await bms.async_update() == result


async def test_device_info(patch_bleak_client) -> None:
    """Test that the BMS returns initialized dynamic device information."""
    await verify_device_info(patch_bleak_client, MockSuperBBleakClient, BMS)


async def test_tx_notimplemented(patch_bleak_client) -> None:
    """Test Super-B BMS uuid_tx not implemented for coverage."""

    patch_bleak_client(MockSuperBBleakClient)

    bms = BMS(generate_ble_device(), False)

    with pytest.raises(NotImplementedError):
        _ret = bms.uuid_tx()


@pytest.mark.parametrize(
    ("wrong_response"),
    [
        b"",
        b"\x00\x72\x5e\x64\x00\x00\x01\xa4\xbe\xcc\xcc\xcd\x41\x62\x89\xc5\x00\x00\x00",
    ],
    ids=["empty", "too_short"],
)
async def test_invalid_response(
    monkeypatch, patch_bleak_client, patch_bms_timeout, wrong_response: bytes
) -> None:
    """Test data up date with BMS returning invalid data."""

    patch_bms_timeout("superb_bms")
    monkeypatch.setattr(MockSuperBBleakClient, "_RESP", bytearray(wrong_response))
    patch_bleak_client(MockSuperBBleakClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = {}
    with pytest.raises(TimeoutError):
        result = await bms.async_update()

    assert not result
    await bms.disconnect()


@pytest.mark.parametrize(
    ("problem_response"),
    [
        b"\x00\x74\x5e\x64\x00\x00\x01\xa4\xbe\xcc\xcc\xcd\x41\x62\x89\xc5\x00\x00\x00\x00",
        b"\x00\x72\x5e\x64\x00\x00\x01\xa4\xbe\xcc\xcc\xcd\x41\x62\x89\xc5\x00\x00\x00\x00",
    ],
    ids=["chrg_warning", "dischrg_warning"],
)
async def test_problem_response(
    monkeypatch, patch_bleak_client, problem_response
) -> None:
    """Test data update with BMS returning error flags."""

    monkeypatch.setattr(MockSuperBBleakClient, "_RESP", bytearray(problem_response))

    patch_bleak_client(MockSuperBBleakClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = await bms.async_update()
    assert result == _RESULT_DEFS | {"problem": True, "problem_code": 1}

    await bms.disconnect()
