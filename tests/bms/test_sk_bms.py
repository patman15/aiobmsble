"""Test the SOK SK BMS implementation."""

from collections.abc import Buffer
from typing import Final
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
import pytest

from aiobmsble import BMSConfig, BMSSample, TempSensor as TS
from aiobmsble.bms.sk_bms import BMS
from aiobmsble.test_data import adv_dict_to_advdata
from aiobmsble.utils import bms_supported
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import BMSBasicTests, verify_device_info

_REQUEST: Final[bytes] = b"\x01\x03\x00\x80\x00\x7a\xc5\xc1"
BT_FRAME_SIZE: Final[int] = 205
_PROTO_DEFS: Final[bytes] = (
    b"\x01\x03\xf4\x05\x8e\x05\x40\x00\x40\x00\x64\x54\xe4\x83\xb3\x83\xb3\x00\x03\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x01\x26\x00\x05\x00\x00\x00\x00\x00\x8e\x00\x04\x0d\x22\x0d\x1f\x00\x02\x00"
    b"\xdc\x00\xd3\x00\xd0\x00\xe6\x00\x00\xff\xff\x0d\x21\x0d\x1f\x0d\x21\x0d\x22\xff\xff\xff\xff"
    b"\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff"
    b"\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff"
    b"\xff\xff\xff\xff\xff\xff\x00\xd3\x00\xdc\x80\x00\x80\x00\x80\x00\x80\x00\x80\x00\x80\x00\xff"
    b"\xff\xff\xff\xff\xff\xff\xff\xff\xff\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff"
    b"\xff\xff\xff\x58\x54\x34\x53\x32\x30\x30\x41\x2d\x45\x31\x36\x37\x2d\x33\x2e\x33\x00\x00\x00"
    b"\x45\x31\x36\x37\x31\x35\x32\x36\x30\x33\x30\x32\x31\x32\x5a\x20\x20\x20\x20\x20\x20\x20\x20"
    b"\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x9e\xb5"
)

_RESULT_DEFS: Final[BMSSample] = {
    "voltage": 13.44,
    "current": 14.22,
    "battery_level": 64,
    "cycle_charge": 217.32,
    "design_capacity": 337,
    "battery_health": 100,
    "cycles": 3,
    "cell_count": 4,
    "temp_sensors": 2,
    "chrg_mosfet": True,
    "dischrg_mosfet": True,
    "cell_voltages": [3.361, 3.359, 3.361, 3.362],
    "delta_voltage": 0.003,
    "temp_values": [
        TS(21.1, TS.T.CELL),
        TS(22.0, TS.T.CELL),
        TS(20.8, TS.T.MOSFET),
        TS(23.0, TS.T.AMBIENT),
    ],
    "temperature": 21.725,
    "battery_charging": True,
    "cycle_capacity": 2920.781,
    "power": 191.117,
    "problem": False,
}


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


def test_matcher_excludes_topband_48v_models() -> None:
    """Do not match SK 48 V models that use the Topband protocol."""
    advertisement = adv_dict_to_advdata({"local_name": "SK48V100N"})
    assert not bms_supported(BMS(generate_ble_device()), advertisement, "")


class MockSKBleakClient(MockBleakClient):
    """Replay the recorded SK BMS response notifications."""

    _RESP: bytes = _PROTO_DEFS

    async def write_gatt_char(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        data: Buffer,
        response: bool | None = None,
    ) -> None:
        """Issue write command to GATT."""
        await super().write_gatt_char(char_specifier, data, response)
        assert bytes(data) == _REQUEST
        assert self._notify_callback is not None
        for chunk in [
            self._RESP[index : index + BT_FRAME_SIZE]
            for index in range(0, len(self._RESP), BT_FRAME_SIZE)
        ]:
            self._notify_callback("MockSKBleakClient", bytearray(chunk))


async def test_update(patch_bleak_client, keep_alive_fixture: bool) -> None:
    """Decode the exact recorded response split across two notifications."""
    patch_bleak_client(MockSKBleakClient)
    bms = BMS(generate_ble_device(), BMSConfig(keep_alive_fixture))

    assert await bms.async_update() == _RESULT_DEFS
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture
    await bms.disconnect()


async def test_device_info(patch_bleak_client) -> None:
    """Test model and serial number decoding from status registers."""
    await verify_device_info(
        patch_bleak_client,
        MockSKBleakClient,
        BMS,
        {"model": "XT4S200A-E167-3.3", "serial_number": "E1671526030212Z"},
    )


@pytest.mark.parametrize(
    ("wrong_response"),
    [
        b"",
        b"\x02" + _PROTO_DEFS[1:],
        _PROTO_DEFS[:-1],
        _PROTO_DEFS + b"\x00",
        _PROTO_DEFS[:-1] + bytes([_PROTO_DEFS[-1] ^ 0x01]),
    ],
    ids=["empty", "wrong_header", "too_short", "oversized", "wrong_crc"],
)
async def test_invalid_response(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    patch_bms_timeout,
    wrong_response: bytes,
) -> None:
    """Test update with invalid recorded response variants."""
    patch_bms_timeout("sk_bms")
    monkeypatch.setattr(MockSKBleakClient, "_RESP", wrong_response)
    patch_bleak_client(MockSKBleakClient)

    bms = BMS(generate_ble_device())
    result: BMSSample = {}
    with pytest.raises(TimeoutError):
        result = await bms.async_update()

    assert not result
    await bms.disconnect()
