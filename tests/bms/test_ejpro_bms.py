"""Test the E&J EJ PRO BMS implementation."""

from collections.abc import Buffer
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic

from aiobmsble import BMSConfig
from aiobmsble.bms.ejpro_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.bms.test_ag_bms import MockAGBleakClient
from tests.test_basebms import BMSBasicTests


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


class MockEJProBleakClient(MockAGBleakClient):
    """Emulate an EJ PRO using the shared E&J protocol frames."""

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
    ) -> bytearray:
        return super()._response("00008001-0000-1000-8000-57616c6b697a", data)


def test_gatt_uuids() -> None:
    """Test the custom GATT UUIDs."""
    assert BMS.uuid_services() == ("00008000-0000-1000-8000-57616c6b697a",)
    assert BMS.uuid_rx() == "00008002-0000-1000-8000-57616c6b697a"
    assert BMS.uuid_tx() == "00008001-0000-1000-8000-57616c6b697a"


async def test_update(patch_bleak_client) -> None:
    """Test EJ PRO data updates over its custom GATT characteristics."""
    patch_bleak_client(MockEJProBleakClient)
    bms = BMS(generate_ble_device(), BMSConfig())

    assert await bms.async_update() == {
        "voltage": 13.185,
        "current": -3.34,
        "battery_level": 60,
        "battery_charging": False,
        "chrg_mosfet": True,
        "cycle_capacity": 777.915,
        "cycle_charge": 59.0,
        "cycles": 63,
        "cell_count": 4,
        "cell_voltages": [3.296, 3.297, 3.295, 3.297],
        "delta_voltage": 0.002,
        "dischrg_mosfet": True,
        "power": -44.038,
        "temperature": 6.0,
        "temp_values": [6.0],
        "problem": False,
        "problem_code": 0,
        "balancer": 0,
        "heater": False,
        "runtime": 63592,
    }

    await bms.disconnect()
