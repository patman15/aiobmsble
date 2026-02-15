"""Test the Humsienk BMS implementation."""

from collections.abc import Buffer
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
import pytest

from aiobmsble import BMSSample
from aiobmsble.bms.humsienk_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import BMSBasicTests

_RESULT_DEFS: BMSSample = {
    "battery_level": 42,
    "battery_health": 100,
    "voltage": 13.130,
    "current": -1.15,
    "cycle_charge": 63.46,
    "design_capacity": 150,
    "cycles": 3,
    "cell_count": 4,
    "cell_voltages": [3.281, 3.291, 3.284, 3.28],
    "battery_charging": False,
    "power": -15.099,
    "cycle_capacity": 833.23,
    "runtime": 198657,
    "delta_voltage": 0.011,
    "temperature": 30.5,
    "temp_values": [
        35.0,
        26.0,
        26.0,
        26.0,
        44.0,
        26.0,
    ],
    "chrg_mosfet": True,
    "dischrg_mosfet": True,
    "balancer": False,
    "problem_code": 0,
    "problem": False,
}


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


class MockHumsienkBleakClient(MockBleakClient):
    """Emulate a Humsienk BMS BleakClient."""

    _RESP: dict[bytes, bytearray] = {
        b"\xaa\x00\x00\x00\x00": bytearray(b"\xaa\x00\x00\x00\x00"),  # init
        b"\xaa\x10\x00\x10\x00": bytearray(
            b"\xaa\x10\x03\x42\x4d\x43\xe5\x00"
        ),  # device type: BMC
        b"\xaa\x11\x00\x11\x00": bytearray(
            b"\xaa\x11\x0a\x42\x4d\x43\x2d\x30\x34\x53\x30\x30\x31\x62\x02"
        ),  # model: BMC-04S001
        b"\xaa\x20\x00\x20\x00": bytearray(
            b"\xaa\x20\x0f\x00\x00\x00\x00\x80\x00\x80\x00\x00\x00\x00\x00\x00\x00\x00\x2f\x01"
        ),  # MOSFET status [7], [9], balancer [8]
        b"\xaa\x21\x00\x21\x00": bytearray(
            b"\xaa\x21\x1a\x4a\x33\x00\x00\x82\xfb\xff\xff\x2a\x64\xe4\xf7\x00\x00\xf0\x49\x02\x00"
            b"\x03\x00\x23\x1a\x1a\x1a\x2c\x1a\x91\x08"
        ),  # 13.130V, ...
        b"\xaa\x22\x00\x22\x00": bytearray(
            b"\xaa\x22\x30\xd1\x0c\xdb\x0c\xd4\x0c\xd0\x0c\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\xd2\x03"
        ),  # cell voltages
        b"\xaa\x23\x00\x23\x00": bytearray(
            b"\xaa\x23\x04\xdc\xfb\xff\xff\xfc\x03"
        ),  # current redundant with 0x21
        b"\xaa\x58\x00\x58\x00": bytearray(
            b"\xaa\x58\x30\x04\x00\x98\x3a\x42\x0e\x02\x0d\x04\x00\xc4\x09\xf0\x0a\x04\x00\xf8\x2a"
            b"\x10\x00\x30\x75\x14\x00\x66\x02\x50\x00\x03\x0d\xd1\x0c\xab\x0a\xdd\x0a\x35\x0d\x03"
            b"\x0d\xe3\x09\x15\x0a\xc5\x0d\x1e\x00\x05\x0b"
        ),
        b"\xaa\xf5\x00\xf5\x00": bytearray(
            b"\xaa\xf5\x0c\x56\x30\x32\x00\x00\x00\x00\x00\x00\x00\x00\x00\xb9\x01"
        ),  # version info
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
            "MockHumsienkBleakClient", self._RESP.get(bytes(data), bytearray())
        )


async def test_update(patch_bleak_client, keep_alive_fixture: bool) -> None:
    """Test Humsienk BMS data update."""

    patch_bleak_client(MockHumsienkBleakClient)

    bms = BMS(generate_ble_device(), keep_alive_fixture)

    assert await bms.async_update() == _RESULT_DEFS

    # query again to check already connected state
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()


async def test_device_info(patch_bleak_client) -> None:
    """Test that the BMS returns initialized dynamic device information."""
    patch_bleak_client(MockHumsienkBleakClient)
    bms = BMS(generate_ble_device())
    assert await bms.device_info() == {"hw_version": "V02", "model": "BMC-04S001"}


@pytest.mark.parametrize(
    ("wrong_response"),
    [
        b"\xbb\x00\x00\x00\x00",
        b"\xaa\x00\x00\x00\x01",
        b"\xaa\x00\x00\x00\x00\x00",
        b"\xaa\x10\x00\x10\x00",
        b"\xaa",
        b"",
    ],
    ids=["wrong_SOF", "wrong_CRC", "wrong_len", "wrong_type", "only_SOF", "empty"],
)
async def test_invalid_response(
    monkeypatch: pytest.MonkeyPatch, patch_bleak_client, patch_bms_timeout, wrong_response: bytes
) -> None:
    """Test data up date with BMS returning invalid data."""

    patch_bms_timeout()

    monkeypatch.setattr(
        MockHumsienkBleakClient,
        "_RESP",
        MockHumsienkBleakClient._RESP | {b"\xaa\x00\x00\x00\x00": wrong_response},
    )

    patch_bleak_client(MockHumsienkBleakClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = {}
    with pytest.raises(TimeoutError):
        result = await bms.async_update()

    assert not result
    await bms.disconnect()


@pytest.mark.parametrize(
    ("problem_response", "expected"),
    [
        (b"\x00\x00\x00\x00\x80\x00\x80\x00\x00\x00\x00\x00\x00\x80\x00\xaf\x01", 0x0),
        (b"\x00\x00\x00\x00\x80\x00\x80\x00\x00\x00\x00\x01\x00\x00\x00\x30\x01", 0x0),
        (
            b"\x00\x00\x00\x00\x80\x00\x80\x80\x00\x00\x00\x00\x00\x00\x00\xaf\x01",
            2**31,
        ),
        (b"\x00\x00\x00\x00\x81\x00\x80\x00\x00\x00\x00\x00\x00\x00\x00\x30\x01", 0x1),
    ],
    ids=["disc_highcon", "discon_low", "high", "low"],
)
async def test_problem_response(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    problem_response: bytes,
    expected: int,
) -> None:
    """Test data update with BMS returning error flags."""

    monkeypatch.setattr(
        MockHumsienkBleakClient,
        "_RESP",
        MockHumsienkBleakClient._RESP
        | {b"\xaa\x20\x00\x20\x00": bytearray(b"\xaa\x20\x0f" + problem_response)},
    )

    patch_bleak_client(MockHumsienkBleakClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = await bms.async_update()
    assert result == _RESULT_DEFS | {"problem": True, "problem_code": expected}

    await bms.disconnect()
