"""Test the E&J technology BMS implementation."""

from collections.abc import Buffer
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic

from aiobmsble.bms.dummy_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient


class MockDummyBleakClient(MockBleakClient):
    """Emulate a Dummy BMS BleakClient."""

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
            "MockDummyBleakClient", bytearray(f"response to '{data!s}'", "UTF-8")
        )


async def test_update(patch_bleak_client, keep_alive_fixture) -> None:
    """Test Dummy BMS data update."""

    patch_bleak_client(MockDummyBleakClient)

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
