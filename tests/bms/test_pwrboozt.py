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
        b":01540100EC000102030405060D360D360D380D3000000000000000000000000000000000000000"
        b"0000000000F00100003D3D3D3D10DD0000320A7FFFFFFF34D4000804003D62000493E00004BDCC0"
        b"00493E0000105F0010600010000000000000000000000000000000000000000000000000000EB"
        b"\x00~\x00\x00\x00"
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
        "battery_level": 98,
        "current": 12.81,
        "cycles": 61,
        "design_capacity": 300,
        "voltage": 13.524,
        "cell_voltages": [
            3.382,
            3.382,
            3.384,
            3.376,
        ],
        "temp_values": [TS(21.0)] * 4,
        "battery_charging": True,
        "cell_count": 4,
        "delta_voltage": 0.008,
        "temperature": 21.0,
        "cycle_charge": 294.0,
        "power": 173.242,
        "cycle_capacity": 3976.056,
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

    monkeypatch.setattr(
        MockPwrBBleakClient, "_MSG", wrong_response
    )

    patch_bleak_client(MockPwrBBleakClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = {}
    with pytest.raises(TimeoutError):
        result = await bms.async_update()

    assert not result
    await bms.disconnect()
