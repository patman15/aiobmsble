"""Test the Buknuwo BMS implementation."""

from collections.abc import Buffer
from typing import Final
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
import pytest

from aiobmsble import BMSSample
from aiobmsble.bms.buknuwo_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import BMSBasicTests, verify_device_info

BT_FRAME_SIZE = 20


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


class MockBuknuwoBleakClient(MockBleakClient):
    """Emulate a Buknuwo BMS BleakClient."""

    _RESP: dict[bytes, bytearray] = {
        b"\x01\x03\x00\x0b\x00\x01\xf5\xc8": bytearray(
            b"\x01\x03\x02\x0c\x00\xbd\x44"
        ),  #  info
        b"\x01\x03\x00\x2f\x00\x0a\xf4\x04": bytearray(
            b"\x01\x03\x14\x00\xc3\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\xdb\x32"
        ),  #  cell temperatures
        b"\x01\x03\x00\x2e\x00\x01\xe4\x03": bytearray(
            b"\x01\x03\x02\x00\x01\x79\x84"
        ),  #  info
        b"\x01\x03\x00\x39\x00\x01\x54\x07": bytearray(
            b"\x01\x03\x02\x00\xbb\xf8\x37"
        ),  #  MOS FET temperature
        b"\x01\x03\x00\x09\x00\x03\xd5\xc9": bytearray(
            b"\x01\x03\x06\x00\x00\x00\x00\x0c\x00\x24\x75"
        ),  #  info
        b"\x01\x03\x00\x02\x00\x01\x25\xca": bytearray(
            b"\x01\x03\x02\x00\x61\x79\xac"
        ),  #  SoC
        b"\x01\x03\x00\x01\x00\x01\xd5\xca": bytearray(
            b"\x01\x03\x02\x05\x46\x3a\xe6"
        ),  #  voltage
        b"\x01\x03\x00\x00\x00\x01\x84\x0a": bytearray(
            b"\x01\x03\x02\xde\x78\xe1\xc6"
        ),  #  current
        b"\x01\x03\x00\xa2\x00\x01\x25\xe8": bytearray(b"\x01\x03\x02\x23\x28\xa1\x6a"),
        b"\x01\x03\x00\x00\x00\x0d\x84\x0f": bytearray(
            b"\x01\x03\x1a\x01\x84\x05\x59\x00\x63\x00\x64\x20\x56\x20\xa1\x23\x28\x00\x01\x00\x00"
            b"\x00\x04\x80\x00\x2d\x00\x00\x00\x21\x9b"
        ),  # not used by app
        b"\x01\x03\x00\x2e\x00\x0b\x64\x04": bytearray(
            b"\x01\x03\x16\x00\x01\x00\xc3\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\xc8\xe7"
        ),  #  temp count + temperatures
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

        if char_specifier != "00002760-08c2-11e1-9073-0e8ac72e0001":
            return  # only respond to writes to TX characteristic

        _response: Final[bytearray] = self._RESP.get(bytes(data), bytearray())
        for notify_data in [
            _response[i : i + BT_FRAME_SIZE]
            for i in range(0, len(_response), BT_FRAME_SIZE)
        ]:
            self._notify_callback("MockBuknuwoBleakClient", notify_data)


async def test_update(patch_bleak_client, keep_alive_fixture: bool) -> None:
    """Test Dummy BMS data update."""

    patch_bleak_client(MockBuknuwoBleakClient)

    bms = BMS(generate_ble_device(), keep_alive_fixture)

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
        "temp_values": [18.7, 19.5],
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
    await verify_device_info(patch_bleak_client, MockBleakClient, BMS)


@pytest.mark.parametrize(
    ("wrong_response"),
    [
        b"",
        b"\x01\x03",
        b"\x01\x04\x1a\x01\x84\x05\x59\x00\x63\x00\x64\x20\x56\x20\xa1\x23\x28\x00\x01\x00\x00\x00"
        b"\x04\x80\x00\x2d\x00\x00\x00\x2d\xdb",
        b"\x01\x03\x1a\x01\x84\x05\x59\x00\x63\x00\x64\x20\x56\x20\xa1\x23\x28\x00\x01\x00\x00\x00"
        b"\x04\x80\x00\x2d\x00\x00\x00\xff\xff",
        b"\x01\x03\x0f\x60\xf4",
    ],
    ids=[
        "empty",
        "minimal",
        "wrong_SOF",
        "wrong_CRC",
        "wrong_length",
    ],
)
async def test_invalid_response(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    patch_bms_timeout,
    wrong_response: bytes,
) -> None:
    """Test data up date with BMS returning invalid data."""

    patch_bms_timeout()
    monkeypatch.setattr(
        MockBuknuwoBleakClient,
        "_RESP",
        {b"\x01\x03\x00\x00\x00\x0d\x84\x0f": bytearray(wrong_response)},
    )
    patch_bleak_client(MockBuknuwoBleakClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = {}
    with pytest.raises(TimeoutError):
        result = await bms.async_update()

    assert not result
    await bms.disconnect()
