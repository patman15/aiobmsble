"""Test the Sentorise BMS implementation."""

from collections.abc import Buffer
from typing import Final
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic

from aiobmsble import BMSConfig, TempSensor as TS
from aiobmsble.bms.sentorise_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import BMSBasicTests, verify_device_info

BT_FRAME_SIZE = 20


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


class MockSentoriseBleakClient(MockBleakClient):
    """Emulate a Sentorise BMS BleakClient."""

    _RESP: dict[bytes, bytes] = {
        b"\x01\x03\xc0\x02\x00\x30\xd8\x1e": (
            b"\x01\x03\x60\x31\x32\x31\x30\x30\x4d\x41\x59\x32\x35\x30\x38\x31\x34\x30\x31\x33\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x68\x61\x6e\x73\x74\x61\x72"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x61\x30\x30\x32\x2d\x32\x35\x30\x38\x31\x36\x2d\x63\x30\x38\x35\x2d"
            b"\x34\x73\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x25\x8c"
        ),
        b"\x01\x03\xd0\x00\x00\x26\xfc\xd0": (
            b"\x01\x03\x4c\x0c\xdf\x0c\xdf\x0c\xe0\x0c\xdb\xee\x49\xee\x49\xee\x49\xee\x49\xee\x49"
            b"\xee\x49\xee\x49\xee\x49\xee\x49\xee\x49\xee\x49\xee\x49\xee\x49\xee\x49\xee\x49\xee"
            b"\x49\xee\x49\xee\x49\xee\x49\xee\x49\xee\x49\xee\x49\xee\x49\xee\x49\xee\x49\xee\x49"
            b"\xee\x49\xee\x49\x0c\xe0\x0c\xdb\x00\x03\x00\x04\x00\x05\x05\x25\xe1\x0a"
        ),
        b"\x01\x03\xd0\x26\x00\x19\x5d\x0b": (
            b"\x01\x03\x32\x02\x58\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x02\x6c\x02\x58\x02\x58\x00\x22\x00\x00\x00\x29\x00\x64\x13\x3a\x27\x10\x27\x10\x00"
            b"\x53\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xa4\xef"
        ),
        b"\x01\x03\xd1\x15\x00\x0c\x6d\x37": (
            b"\x01\x03\x18\x24\x0c\x00\x00\x02\xa7\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\xbc\x90"
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

        if char_specifier != "6e400002-b5a3-f393-e0a9-e50e24dcca9e":
            return  # only respond to writes to TX characteristic

        _response: Final[bytearray] = bytearray(self._RESP.get(bytes(data), b""))
        for notify_data in [
            _response[i : i + BT_FRAME_SIZE] for i in range(0, len(_response), BT_FRAME_SIZE)
        ]:
            self._notify_callback("MockSentoriseBleakClient", notify_data)


async def test_update(patch_bleak_client, keep_alive_fixture: bool) -> None:
    """Test Sentorise BMS data update."""

    patch_bleak_client(MockSentoriseBleakClient)

    bms = BMS(generate_ble_device(), BMSConfig(keep_alive_fixture))

    assert await bms.async_update() == {
        "battery_level": 99,
        "battery_health": 100,
        "cycles": 1,
        "chrg_mosfet": True,
        "dischrg_mosfet": True,
        "voltage": 13.69,
        "current": 3.88,
        "temperature": 19.1,
        "battery_charging": True,
        "cycle_capacity": 1133.258,
        "cycle_charge": 82.78,
        "design_capacity": 90,
        "temp_sensors": 1,
        "temp_values": [TS(18.7, TS.T.MOSFET), TS(19.5, TS.T.CELL)],
        "power": 53.117,
        "problem": True,
        "problem_code": 0x480000000,
    }

    # query again to check already connected state
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()


async def test_device_info(patch_bleak_client) -> None:
    """Test that the BMS returns initialized dynamic device information."""
    await verify_device_info(
        patch_bleak_client,
        MockSentoriseBleakClient,
        BMS,
        {
            "model": "hanstar",
            "serial_number": "12100MAY250814013",
            "sw_version": "a002-250816-c085-4s",
        },
    )


# @pytest.mark.parametrize(
#     ("wrong_response"),
#     [
#         b"",
#         b"\x01\x03",
#         (
#             b"\x01\x04\x1a\x01\x84\x05\x59\x00\x63\x00\x64\x20\x56\x20\xa1\x23\x28\x00\x01\x00\x00"
#             b"\x00\x04\x80\x00\x2d\x00\x00\x00\x2d\xdb"
#         ),
#         (
#             b"\x01\x03\x1a\x01\x84\x05\x59\x00\x63\x00\x64\x20\x56\x20\xa1\x23\x28\x00\x01\x00\x00"
#             b"\x00\x04\x80\x00\x2d\x00\x00\x00\xff\xff"
#         ),
#         b"\x01\x03\x0f\x60\xf4",
#     ],
#     ids=[
#         "empty",
#         "minimal",
#         "wrong_SOF",
#         "wrong_CRC",
#         "wrong_length",
#     ],
# )
# async def test_invalid_response(
#     monkeypatch: pytest.MonkeyPatch,
#     patch_bleak_client,
#     patch_bms_timeout,
#     wrong_response: bytes,
# ) -> None:
#     """Test data up date with BMS returning invalid data."""

#     patch_bms_timeout()
#     monkeypatch.setattr(
#         MockSentoriseBleakClient,
#         "_RESP",
#         {b"\x01\x03\x00\x00\x00\x0d\x84\x0f": bytearray(wrong_response)},
#     )
#     patch_bleak_client(MockSentoriseBleakClient)

#     bms = BMS(generate_ble_device())

#     result: BMSSample = {}
#     with pytest.raises(TimeoutError):
#         result = await bms.async_update()

#     assert not result
#     await bms.disconnect()
