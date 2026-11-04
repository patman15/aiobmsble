"""Test the PowerBoozt batteries implementation."""

from collections.abc import Buffer
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.uuids import normalize_uuid_str
import pytest

from aiobmsble import BMSConfig, BMSSample, TempSensor as TS
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

    _MSG: bytes = (
        b":01540100EC000102030405060D4E0D4C0D510D4700000000000000000000000000000000000000000000000"
        b"0F00200003636363610D1800003167FFFFFFF3532000A0400036300019A280001A48E00019A28000105F0020"
        b"600010000000000000000000000000000000000000000000000000000F0\x00~\x00\x00\x00"
    )

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
    ) -> bytearray:
        if isinstance(char_specifier, str) and normalize_uuid_str(
            char_specifier
        ) != normalize_uuid_str("0000fff2-0000-1000-8000-00805f9b34fb"):
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
        "battery_charging": False,
        "battery_level": 99,
        "current": -0.79,
        "cycles": 3,
        "design_capacity": 105,
        "voltage": 13.618,
        "problem_code": 0,
        "heater": False,
        "cell_voltages": [3.406, 3.404, 3.409, 3.399],
        "temp_values": [TS(14.0)] * 4,
        "cell_count": 4,
        "delta_voltage": 0.01,
        "temperature": 14.0,
        "cycle_charge": 103.95,
        "power": -10.758,
        "runtime": 473696,
        "cycle_capacity": 1415.591,
        "problem": False,
    }

    # query again to check already connected state
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()


@pytest.fixture(
    name="wrong_response",
    params=[
        (b"x015401001E000102030405060077~", "wrong_SOF"),
        (b":015401001E000102030405060077x", "wrong_EOF"),
        (b":015401001D000102030405060077~", "wrong_len"),
        (b":015401001E000102030405060000~", "wrong_CRC"),
        (b":015401001E00010203040506007X~", "wrong_encoding"),
    ],
    ids=lambda param: param[1],
)
def fix_response(request: pytest.FixtureRequest) -> bytes:
    """Return faulty response frame."""
    assert isinstance(request.param[0], bytes)
    return request.param[0]


async def test_invalid_response(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    patch_bms_timeout,
    wrong_response: bytes,
) -> None:
    """Test data up date with BMS returning invalid data."""

    patch_bms_timeout()

    monkeypatch.setattr(MockPwrBBleakClient, "_MSG", wrong_response)

    patch_bleak_client(MockPwrBBleakClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = {}
    with pytest.raises(TimeoutError):
        result = await bms.async_update()

    assert not result
    assert not bms._msg, "invalid frame must not be stored"
    await bms.disconnect()
