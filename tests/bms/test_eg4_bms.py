"""Test the EG4 BMS implementation."""

from collections.abc import Awaitable, Callable
from typing import Final
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
import pytest

from aiobmsble.basebms import BMSSample
from aiobmsble.bms.eg4_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient

BT_FRAME_SIZE = 200

_RESULT_DEFS: Final[BMSSample] = {
    "voltage": 13.3,
    "current": 0.0,
    "battery_level": 92,
    "cell_count": 4,
    "cycles": 5,
    "cycle_charge": 369.8,
    "cell_voltages": [3.326, 3.327, 3.327, 3.323],
    "delta_voltage": 0.004,
    "temperature": 14,
    "cycle_capacity": 4918.34,
    "power": 0.0,
    # "runtime": 54770,
    "battery_charging": False,
    "problem_code": 0,
    "problem": False,
}


class MockEG4BleakClient(MockBleakClient):
    """Emulate a EG4 BMS BleakClient."""

    _RESP: bytearray = bytearray(
        b"\x01\x03\x4e\x05\x32\x00\x00\x0c\xfe\x0c\xff\x0c\xff\x0c\xfb\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x0e\x00\x0e\x00"
        b"\x0e\x0e\x72\x08\x98\x00\x64\x00\x5c\x03\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x05\x55"
        b"\xd4\xa8\x00\x0e\x0e\x00\x00\x00\x00\x00\x04\x0f\xa0\x00\x00\xe0\x65"
    )

    def _send_info(self) -> None:
        assert self._notify_callback is not None
        for notify_data in [
            self._RESP[i : i + BT_FRAME_SIZE]
            for i in range(0, len(self._RESP), BT_FRAME_SIZE)
        ]:
            self._notify_callback("MockEG4BleakClient", notify_data)

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


async def test_update(patch_bleak_client, keep_alive_fixture) -> None:
    """Test EG4 BMS data update."""

    patch_bleak_client(MockEG4BleakClient)

    bms = BMS(generate_ble_device(), keep_alive_fixture)

    assert await bms.async_update() == _RESULT_DEFS

    # query again to check already connected state
    await bms.async_update()
    assert bms._client and bms._client.is_connected is keep_alive_fixture

    await bms.disconnect()


async def test_device_info(patch_bleak_client) -> None:
    """Test that the BMS returns initialized dynamic device information."""
    patch_bleak_client(MockEG4BleakClient)
    bms = BMS(generate_ble_device())
    assert await bms.device_info() == {
        "fw_version": "mock_FW_version",
        "hw_version": "mock_HW_version",
        "sw_version": "mock_SW_version",
        "manufacturer": "mock_manufacturer",
        "model": "mock_model",
        "serial_number": "mock_serial_number",
    }


async def test_tx_notimplemented(patch_bleak_client) -> None:
    """Test EG4 BMS uuid_tx not implemented for coverage."""

    patch_bleak_client(MockEG4BleakClient)

    bms = BMS(generate_ble_device(), False)

    with pytest.raises(NotImplementedError):
        _ret = bms.uuid_tx()


@pytest.mark.parametrize(
    "wrong_response",
    [
        b"\x02\x03\x4e\x05\x32\x00\x00\x0c\xfe\x0c\xff\x0c\xff\x0c\xfb\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x0e\x00\x0e\x00"
        b"\x0e\x0e\x72\x08\x98\x00\x64\x00\x5c\x03\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x05\x55"
        b"\xd4\xa8\x00\x0e\x0e\x00\x00\x00\x00\x00\x04\x0f\xa0\x00\x00\x2c\x1d",
        b"\x01\x03\x4e\x05\x32\x00\x00\x0c\xfe\x0c\xff\x0c\xff\x0c\xfb\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x0e\x00\x0e\x00"
        b"\x0e\x0e\x72\x08\x98\x00\x64\x00\x5c\x03\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x05\x55"
        b"\xd4\xa8\x00\x0e\x0e\x00\x00\x00\x00\x00\x04\x0f\xa0\x00\x00\xe1\x65",
        b"\x01\x03\x4e\x05\x32\x00\x00\x0c\xfe\x0c\xff\x0c\xff\x0c\xfb\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x0e\x00\x0e\x00"
        b"\x0e\x0e\x72\x08\x98\x00\x64\x00\x5c\x03\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x05\x55"
        b"\xd4\xa8\x00\x0e\x0e\x00\x00\x00\x00\x00\x04\x0f\xa0\x00\x00\xe0\x65\x00",
        b"\x01\03"
    ],
    ids=["wrong_SOF", "wrong_CRC", "wrong_LEN", "too_short"],
)
async def test_invalid_response(
    monkeypatch: pytest.MonkeyPatch, patch_bleak_client, patch_bms_timeout, wrong_response: bytes
) -> None:
    """Test data up date with BMS returning invalid data."""

    patch_bms_timeout("eg4_bms")
    monkeypatch.setattr(MockEG4BleakClient, "_RESP", bytearray(wrong_response))
    patch_bleak_client(MockEG4BleakClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = {}
    with pytest.raises(TimeoutError):
        result = await bms.async_update()

    assert not result
    await bms.disconnect()


@pytest.mark.parametrize(
    "problem_response",
    [
        b"\x01\x03\x4e\x05\x32\x00\x00\x0c\xfe\x0c\xff\x0c\xff\x0c\xfb\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x0e\x00\x0e\x00"
        b"\x0e\x0e\x72\x08\x98\x00\x64\x00\x5c\x03\x00\x80\x00\x00\x00\x00\x00\x00\x00\x00\x05\x55"
        b"\xd4\xa8\x00\x0e\x0e\x00\x00\x00\x00\x00\x04\x0f\xa0\x00\x00\x4A\x19",
        b"\x01\x03\x4e\x05\x32\x00\x00\x0c\xfe\x0c\xff\x0c\xff\x0c\xfb\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x0e\x00\x0e\x00"
        b"\x0e\x0e\x72\x08\x98\x00\x64\x00\x5c\x03\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x05\x55"
        b"\xd4\xa8\x00\x0e\x0e\x00\x00\x00\x00\x00\x04\x0f\xa0\x00\x00\xf0\xb4"
    ],
    ids=["last_bit", "first_bit"],
)
async def test_problem_response(
    monkeypatch, patch_bleak_client, problem_response, request
) -> None:
    """Test data update with BMS returning error flags."""
    monkeypatch.setattr(MockEG4BleakClient, "_RESP", bytearray(problem_response))
    patch_bleak_client(MockEG4BleakClient)
    bms = BMS(generate_ble_device())

    assert await bms.async_update() == _RESULT_DEFS | {
        "problem": True,
        "problem_code": (1 if request.node.callspec.id == "first_bit" else 2**47),
    }

    await bms.disconnect()
