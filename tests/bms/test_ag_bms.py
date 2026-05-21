"""Test the AG Automotive (E&J) BMS implementation."""

from collections.abc import Buffer
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.uuids import normalize_uuid_str

from aiobmsble.bms.ag_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import BMSBasicTests

BT_FRAME_SIZE = 20


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


class MockAGBleakClient(MockBleakClient):
    """Emulate a AG Automotive (E&J) BMS BleakClient."""

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
    ) -> bytearray:
        if isinstance(char_specifier, str) and normalize_uuid_str(
            char_specifier
        ) != normalize_uuid_str("00008001-0000-1000-8000-57616c6b697a"):
            return bytearray()
        cmd: int = int(bytearray(data)[3:5], 16)
        if cmd == 0x02:
            return bytearray(
                b"\x3a\x30\x30\x38\x32\x35\x30\x30\x30\x38\x30\x30\x30\x30\x31\x30\x31\x43\x30\x30"
                b"\x30\x30\x30\x38\x38\x30\x43\x45\x30\x30\x43\x45\x31\x30\x43\x44\x46\x30\x43\x45"
                b"\x31\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30"
                b"\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30"
                b"\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x31\x34\x45\x32\x45\x32"
                b"\x41\x32\x41\x32\x41\x46\x30\x30\x32\x30\x30\x30\x30\x30\x30\x30\x30\x33\x46\x30"
                b"\x30\x33\x46\x33\x43\x30\x32\x7e"
            )  # 63 cycles, -3.3A, 60% battery, 4 cells at 3.29V, delta 0.002, temp 6°C
        if cmd == 0x10:
            return bytearray(
                b"\x3a\x30\x30\x39\x30\x33\x31\x30\x30\x31\x45\x30\x30\x30\x30\x30\x32\x34\x45\x30"
                b"\x33\x45\x38\x30\x33\x45\x38\x41\x31\x7e"
            )
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
            self._notify_callback("MockAGBleakClient", notify_data)


async def test_update(patch_bleak_client, keep_alive_fixture: bool) -> None:
    """Test AG Automotive (E&J) BMS data update."""

    patch_bleak_client(MockAGBleakClient)

    bms = BMS(generate_ble_device(), keep_alive_fixture)

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

    # query again to check already connected state
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()
