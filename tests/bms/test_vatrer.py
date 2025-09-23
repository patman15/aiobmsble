"""Test the E&J technology BMS implementation."""

from collections.abc import Buffer
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic

from aiobmsble.bms.vatrer_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient


class MockVatrerBleakClient(MockBleakClient):
    """Emulate a Vatrer BMS BleakClient."""

    RESP: dict[bytes, bytearray] = {
        b"\x02\x03\x00\x34\x00\x12\x84\x3a": bytearray(
            b"\x02\x03\x24\x00\x04\x00\x12\x00\x14\x00\x13\x00\x14\x00\x14\x00\x14\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x34\x02\x40\x00\x00\x00\x00\x46\x43"
        ),
        b"\x02\x03\x00\x00\x00\x14\x45\xf6": bytearray(
            b"\x02\x03\x28\x14\x93\x00\x00\x00\x00\x00\x28\x0f\x82\x27\x10\x00\x1b\x00\x64\x00\x01"
            b"\x00\x00\x00\x01\x0c\xe0\x0c\xdd\x00\x03\x00\x0f\x00\x10\x00\x14\x00\x12\x00\x02\x00"
            b"\x04\x9f\xfd"
        ),
        b"\x02\x03\x00\x15\x00\x1f\x15\xf5": bytearray(
            b"\x02\x03\x3e\x00\x10\x0c\xdf\x0c\xdf\x0c\xe0\x0c\xe0\x0c\xe0\x0c\xe0\x0c\xe0\x0c\xe0"
            b"\x0c\xe0\x0c\xe0\x0c\xe0\x0c\xe0\x0c\xe0\x0c\xe0\x0c\xe0\x0c\xdd\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\xcb\x54"
        ),
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
        self._notify_callback(
            "MockVatrerBleakClient", self.RESP.get(bytes(data), bytearray())
        )


async def test_update(patch_bleak_client, keep_alive_fixture) -> None:
    """Test Vatrer BMS data update."""

    patch_bleak_client(MockVatrerBleakClient)

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
    assert bms._client and bms._client.is_connected is keep_alive_fixture

    await bms.disconnect()
