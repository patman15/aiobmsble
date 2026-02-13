"""Test the Saftkiste BMS implementation."""

from collections.abc import Buffer
from typing import Final
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic

from aiobmsble import BMSSample
from aiobmsble.bms.saftkiste_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import BMSBasicTests, verify_device_info

_PROTO_DEFS: Final[dict[int, bytearray]] = {
    0x02: bytearray(
        b"\xf0\xff\x02\xe0\x93\x04\x00\xa7\x8a\x04\x00\x2c\x01\x0c\x36\xf5\xff\x84\x0d\x7f\x0d\x85"
        b"\x0d\x84\x0d\x21\x00\xb1\x02\xfe\x02\x00\x01\x00\x00\x00\x04\x0e\x00\x00\x00\x03\x00\x03"
        b"\x01\x00\x12"
    ),
    0x03: bytearray(
        b"\xf0\xff\x03\x00\x00\x43\x74\x29\x78\x4a\x69\x00\x00\x00\x01\x03\xb0\x32\x42\x47\x01\x00\xc1\x26\xe0"
        b"\x93\x04\x00\x00\x03\x03\x2c\xc5\x02\x00\x06\x00\x00\x00\x00\x00\x00\xff\x6e"
    ),
    0x04: bytearray(
        b"\xf0\xff\x04\x00\x48\xe7\x29\x0a\x63\x38\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xb8"
    ),
    0x05: bytearray(
        b"\xf0\xff\x04\x00\x00\x00\x00\x00\x00\x00\x00\x10\x00\x00\x00\x2d"
    ),
}

_RESULT_DEFS: Final[BMSSample] = {
    "battery_charging": False,
    "cell_count": 4,
    "cell_voltages": [
        3.46,
        3.455,
        3.461,
        3.46,
    ],
    "current": -0.11,
    "cycles": 33,
    "delta_voltage": 0.006,
    "design_capacity": 300,
    "power": -1.522,
    "problem": False,
    "voltage": 13.836,
}


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


class MockSaftkisteBleakClient(MockBleakClient):
    """Emulate a Saftkiste BMS BleakClient."""

    _PROTO: Final[dict[int, bytearray]] = _PROTO_DEFS

    async def write_gatt_char(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        data: Buffer,
        response: bool | None = None,
    ) -> None:
        """Issue write command to GATT."""
        await super().write_gatt_char(char_specifier, data, response)
        assert self._notify_callback is not None

        self._notify_callback(
            "MockSaftkisteBleakClient", self._PROTO.get(bytes(data)[2], bytearray())
        )


async def test_update(patch_bleak_client, keep_alive_fixture: bool) -> None:
    """Test Saftkiste BMS data update."""

    patch_bleak_client(MockSaftkisteBleakClient)

    bms = BMS(generate_ble_device(), keep_alive_fixture)

    assert await bms.async_update() == _RESULT_DEFS

    # query again to check already connected state
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()


async def test_device_info(patch_bleak_client) -> None:
    """Test that the BMS returns initialized dynamic device information."""
    await verify_device_info(patch_bleak_client, MockSaftkisteBleakClient, BMS)
