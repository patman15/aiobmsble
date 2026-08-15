"""Test the Dörr Power BMS implementation."""

from collections.abc import Buffer
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSConfig, TempSensor as TS
from aiobmsble.bms.doerrpwr_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import BMSBasicTests

BT_FRAME_SIZE = 20


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


class MockDoerrPBleakClient(MockBleakClient):
    """Emulate a PowerBoozt BleakClient."""

    _MSG: bytes = (
        b":01540100EC000102030405060D450D480D430D4100000000000000000000000000000000000000000000000"
        b"0F00000004646464610EE000000007FFFFFFF3511000704000163000249F0000262B7000249F0000105F0000"
        b"6000100000000000000000000000000000000000000000000000000009F~"
    )

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
    ) -> bytearray:
        if isinstance(char_specifier, str) and normalize_uuid_str(
            char_specifier
        ) != normalize_uuid_str("0000fff6-0000-1000-8000-00805f9b34fb"):
            return bytearray()
        return bytearray(self._MSG)

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
            self._notify_callback("MockPwrBBleakClient", notify_data)


async def test_update(patch_bleak_client, keep_alive_fixture: bool) -> None:
    """Test E&J technology BMS data update."""

    patch_bleak_client(MockDoerrPBleakClient)

    bms = BMS(generate_ble_device(), BMSConfig(keep_alive_fixture))

    assert await bms.async_update() == {
        "battery_level": 99,
        "current": 0.0,
        "cycles": 1,
        "design_capacity": 150,
        "voltage": 13.585,
        "cell_voltages": [3.397, 3.4, 3.395, 3.393],
        "temp_values": [TS(30.0)] * 4,
        "battery_charging": False,
        "cell_count": 4,
        "delta_voltage": 0.007,
        "temperature": 30.0,
        "cycle_charge": 148.5,
        "power": 0.0,
        "cycle_capacity": 2017.373,
        "problem": False,
    }

    # query again to check already connected state
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()
