"""Test the Ective BMS implementation."""

from collections.abc import Buffer
from typing import Final
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
import pytest

from aiobmsble import BMSSample
from aiobmsble.bms.lipower_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient

BT_FRAME_SIZE = 32

_RESULT_DEFS: Final[BMSSample] = {
    "voltage": 13.7,
    "current": -0.08,
    "battery_level": 99,
    "cycle_charge": 118,
    "cycle_capacity": 1616.6,
    "power": -1.096,
    "runtime": 5354520,
    "battery_charging": False,
    "problem": False,
}


class MockLiPwrBleakClient(MockBleakClient):
    """Emulate a Ective BMS BleakClient."""

    _RESP: Final[bytearray] = bytearray(
        b"\x22\x03\x10\x00\x76\x00\x63\x05\xcf\x00\x16\x00\x01\x00\x08\x00\x89\x00\x01\x9e\xcf"
    )  # 13.7V, 99%, 5354520s, -0.08A, -1W

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
    ) -> bytearray:
        if not isinstance(char_specifier, str) or char_specifier != "ffe1":
            return bytearray()
        addr: int = int.from_bytes(bytes(data)[3:5])
        if addr == 0x0:
            return MockLiPwrBleakClient._RESP
        return bytearray()

    async def write_gatt_char(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        data: Buffer,
        response: bool | None = None,
    ) -> None:
        """Issue write command to GATT."""
        await super().write_gatt_char(char_specifier, data, response)
        assert self._notify_callback is not None

        for notify_data in [
            self._response(char_specifier, data)[i : i + BT_FRAME_SIZE]
            for i in range(0, len(self._response(char_specifier, data)), BT_FRAME_SIZE)
        ]:
            self._notify_callback("MockLiPwrBleakClient", notify_data)


async def test_update(patch_bleak_client, keep_alive_fixture) -> None:
    """Test Ective BMS data update."""

    patch_bleak_client(MockLiPwrBleakClient)

    bms = BMS(generate_ble_device(), keep_alive_fixture)

    assert await bms.async_update() == _RESULT_DEFS

    # query again to check already connected state
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()


@pytest.mark.parametrize(
    ("wrong_response"),
    [
        b"\x10\x03\x10\x00\x76\x00\x63\x05\xcf\x00\x16\x00\x01\x00\x08\x00\x89\x00\x01\xa8\x73",
        b"\x22\x03\x10\x00\x76\x00\x63\x05\xcf\x00\x16\x00\x01\x00\x08\x00\x89\x00\x01\x00\xcf",
        b"\x22\x03\x11\x00\x76\x00\x63\x05\xcf\x00\x16\x00\x01\x00\x08\x00\x89\x00\x01\xcf\x5f",
        b"",
    ],
    ids=["wrong_SOF", "wrong_CRC", "wrong_len", "empty"],
)
async def test_invalid_response(
    monkeypatch, patch_bleak_client, patch_bms_timeout, wrong_response: bytes
) -> None:
    """Test data up date with BMS returning invalid data."""

    patch_bms_timeout()
    monkeypatch.setattr(MockLiPwrBleakClient, "_RESP", bytearray(wrong_response))
    patch_bleak_client(MockLiPwrBleakClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = {}
    with pytest.raises(TimeoutError):
        result = await bms.async_update()

    assert not result
    await bms.disconnect()
