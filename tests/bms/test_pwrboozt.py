"""Test the PowerBoozt batteries implementation."""

from collections.abc import Buffer
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSConfig, TempSensor as TS
from aiobmsble.bms.pwrboozt_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import BMSBasicTests

BT_FRAME_SIZE = 20


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


class MockPwrBBleakClient(MockBleakClient):
    """Emulate a PowerBoozt BleakClient."""

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
    ) -> bytearray:
        if isinstance(char_specifier, str) and normalize_uuid_str(
            char_specifier
        ) != normalize_uuid_str("0000fff2-0000-1000-8000-00805f9b34fb"):
            return bytearray()
        return bytearray(
            b":01540100EC000102030405060D2D0D2A0D2B0D2C00000000000000000000000000000000000000"
            b"0000000000F00000004343434310E8000000007FFFFFFF34AE000304003D63000493E00004C8650"
            b"00493E0000105F0000600010000000000000000000000000000000000000000000000000000B2~"
        )  # cells 3.373V, 3.370V, 3.371V, 3.372 V, pack 13.486 V, temp 27 °C, cycles 61, 300 Ah

    async def write_gatt_char(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        data: Buffer,
        response: bool | None = None,
    ) -> None:
        """Issue write command to GATT."""
        await super().write_gatt_char(char_specifier, data, response)
        assert self._notify_callback is not None
        self._notify_callback("MockPwrBBleakClient", bytearray(b"AT\r\n"))
        self._notify_callback("MockPwrBBleakClient", bytearray(b"AT\r\nillegal"))
        for notify_data in [
            self._response(char_specifier, data)[i : i + BT_FRAME_SIZE]
            for i in range(0, len(self._response(char_specifier, data)), BT_FRAME_SIZE)
        ]:
            self._notify_callback("MockPwrBBleakClient", notify_data)


async def test_update(patch_bleak_client, keep_alive_fixture: bool) -> None:
    """Test E&J technology BMS data update."""

    patch_bleak_client(MockPwrBBleakClient)

    bms = BMS(generate_ble_device(), BMSConfig(keep_alive_fixture))

    assert await bms.async_update() == {
        "battery_level": 99,
        "current": 0.0,
        "cycles": 61,
        "design_capacity": 300,
        "voltage": 13.486,
        "cell_voltages": [
            3.373,
            3.370,
            3.371,
            3.372,
        ],
        "temp_values": [TS(27.0)] * 4,
        "battery_charging": False,
        "cell_count": 4,
        "delta_voltage": 0.003,
        "temperature": 27.0,
        "cycle_charge": 297.0,
        "power": 0.0,
        "cycle_capacity": 4005.342,
        "problem": False,
    }

    # query again to check already connected state
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()
