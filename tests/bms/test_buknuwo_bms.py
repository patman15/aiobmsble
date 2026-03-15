"""Test the Buknuwo BMS implementation."""

from collections.abc import Buffer
from typing import Final
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic

from aiobmsble.bms.buknuwo_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import BMSBasicTests, verify_device_info

BT_FRAME_SIZE = 20


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


class MockBuknuwoBleakClient(MockBleakClient):
    """Emulate a Buknuwo BMS BleakClient."""

    RESP: dict[bytes, bytearray] = {
        b"\x01\x03\x00\x0b\x00\x01\xf5\xc8": bytearray(
            b"\x01\x03\x02\x0c\x00\xbd\x44"
        ),  #  info
        b"\x01\x03\x00\x2f\x00\x0a\xf4\x04": bytearray(
            b"\x01\x03\x14\x00\xc3\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xdb\x32"
        ),  #  info
        b"\x01\x03\x00\x2e\x00\x01\xe4\x03": bytearray(
            b"\x01\x03\x02\x00\x01\x79\x84"
        ),  #  info
        b"\x01\x03\x00\x39\x00\x01\x54\x07": bytearray(
            b"\x01\x03\x02\x00\xbb\xf8\x37"
        ),  #  info
        b"\x01\x03\x00\x09\x00\x03\xd5\xc9": bytearray(
            b"\x01\x03\x06\x00\x00\x00\x00\x0c\x00\x24\x75"
        ),  #  info
        b"\x01\x03\x00\x02\x00\x01\x25\xca": bytearray(
            b"\x01\x03\x02\x00\x61\x79\xac"
        ),  #  SoC
        b"\x01\x03\x00\x01\x00\x01\xd5\xca": bytearray(
            b"\x01\x03\x02\x05\x46\x3a\xe6"
        ),  #  voltage
        b"\x01\x03\x00\x00\x00\x01\x84\x0a": bytearray(
            b"\x01\x03\x02\xde\x78\xe1\xc6"
        ),  #  current
        b"\x01\x03\x00\xa2\x00\x01\x25\xe8": bytearray(b"\x01\x03\x02\x23\x28\xa1\x6a"),
    }

    async def write_gatt_char(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        data: Buffer,
        response: bool | None = None,
    ) -> None:
        """Issue write command to GATT."""
        await super().write_gatt_char(char_specifier, data, response)
        assert self._notify_callback is not None

        if char_specifier != "00002760-08c2-11e1-9073-0e8ac72e0001":
            return  # only respond to writes to TX characteristic

        _response: Final[bytearray] = self.RESP.get(bytes(data), bytearray())
        for notify_data in [
            _response[i : i + BT_FRAME_SIZE]
            for i in range(0, len(_response), BT_FRAME_SIZE)
        ]:
            self._notify_callback("MockBuknuwoBleakClient", notify_data)


async def test_update(patch_bleak_client, keep_alive_fixture: bool) -> None:
    """Test Dummy BMS data update."""

    patch_bleak_client(MockBuknuwoBleakClient)

    bms = BMS(generate_ble_device(), keep_alive_fixture)

    assert await bms.async_update() == {
        "voltage": 12,
        "current": 1.5,
        "temperature": 27.182,
        "battery_charging": True,
        "power": 18,
        "problem": False,
    }

    # query again to check already connected state
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()


async def test_device_info(patch_bleak_client) -> None:
    """Test that the BMS returns initialized dynamic device information."""
    await verify_device_info(patch_bleak_client, MockBleakClient, BMS)
