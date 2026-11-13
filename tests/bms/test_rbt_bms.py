"""Test the Changfa / RBT BMS implementation."""

from collections.abc import Buffer
from typing import Final
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
import pytest

from aiobmsble import BMSConfig, BMSSample, TempSensor as TS
from aiobmsble.bms.rbt_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import BMSBasicTests

BT_FRAME_SIZE = 29

_PROTO_DEFS: Final[dict[int, bytes]] = {
    0x41: (  # telemetry block
        b"\x3b\x9d\x21\x01\x41\x42\x00\x13\x14\x00\x02\x00\xb8\x0b\x15\x02"
        b"\x92\x00\x05\x05\x73\x00\x00\x00\xb6\x03\x88\x13\x03\x04\x03\x08"
        b"\x98\x0b\xe3\x0a\x03\x01\xea\x0a\xe3\x0a\xe3\x0a\x98\x0b\x8f\x0c"
        b"\x8d\x0c\x04\x02\x02\x00\x8e\x0c\x8d\x0c\x8f\x0c\x8f\x0c\x00\x00"
        b"\x07\x00\x00\x00\x00\x00\x00\x00\xc6"
    ),
    0x51: (  # device information block
        b"\x3b\x9d\x21\x01\x51\x3e\x02\x00\xd3\x03\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x00\x00\x00\x01\xfa\x21\x13\x00\x00\x00\x15\x02\x00"
        b"\x05\x04\x20\x78\xc6\x10\x08\x55\x23\x36\x10\x03\x32\x38\x32\x5a"
        b"\x34\x50\x41\x00\x00\xc4\x5d\xd0\x0a\x88\x35\x07\x00\x07\x5f\x53"
        b"\x4d\x42\x5f\x46\x43\x08\xb9"
    ),
    0x5A: (  # status block
        b"\x3b\x9d\xf0\x01\x5a\x30\x21\x10\x11\x10\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x03\x00\x00\x00\x07"
        b"\x00\x00\x00\x6e\x04\x00\x00\x67\x00\x00\x00\x0c\x00\x00\x00\x00"
        b"\x00\x00\x00\xe3\x07\x00\x00\x9e"
    ),
    0xA3: b"\x3b\x9d\x21\x02\xa3\x01\x00\xbf",  # acknowledge block
}

_RESULT_DEFS: Final[BMSSample] = {
    "battery_level": 19,
    "cycles": 2,
    "design_capacity": 30,
    "voltage": 12.85,
    "current": -1.15,
    "temperature": [TS(6.3), TS(5.6), TS(5.6), TS(23.7)],
    "cell_voltages": [3.214, 3.213, 3.215, 3.215],
    "cell_count": 4,
    "delta_cell_voltage": 0.002,
    "battery_charging": False,
    "cycle_charge": 5.7,
    "cycle_capacity": 73.245,
    "power": -14.777,
    "problem": False,
    "runtime": 17843,
}


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


class MockRBTBleakClient(MockBleakClient):
    """Emulate a Changfa / RBT BMS BleakClient."""

    _RESP: bytes = _PROTO_DEFS[0x41]

    async def write_gatt_char(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        data: Buffer,
        response: bool | None = None,
    ) -> None:
        """Issue write command to GATT."""
        await super().write_gatt_char(char_specifier, data, response)
        assert self._notify_callback is not None

        if bytes(data) != BMS._cmd(0x41, 0x00):
            return  # ignore unexpected requests

        for chunk in [
            self._RESP[i : i + BT_FRAME_SIZE] for i in range(0, len(self._RESP), BT_FRAME_SIZE)
        ]:
            self._notify_callback("MockRBTBleakClient", bytearray(chunk))


@pytest.fixture(name="protocol_type", params=_PROTO_DEFS.keys())
def proto(request: pytest.FixtureRequest) -> int:
    """Protocol fixture."""
    assert isinstance(request.param, int)
    return request.param


async def test_update(
    patch_bleak_client,
    keep_alive_fixture: bool,
) -> None:
    """Test Changfa / RBT BMS data update."""

    patch_bleak_client(MockRBTBleakClient)

    bms = BMS(generate_ble_device(), BMSConfig(keep_alive_fixture))

    assert await bms.async_update() == _RESULT_DEFS

    # query again to check already connected state
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()


@pytest.mark.parametrize(
    "response",
    [
        _PROTO_DEFS[0x41][:-1] + b"\x00",
        _PROTO_DEFS[0x41][:-5],
        _PROTO_DEFS[0x5A],
        b"",
    ],
    ids=["bad_checksum", "truncated", "wrong_register", "no_response"],
)
async def test_invalid_frame(
    patch_bleak_client,
    patch_bms_timeout,
    monkeypatch: pytest.MonkeyPatch,
    response: bytes,
) -> None:
    """Test that invalid telemetry frames are discarded and never yield a sample."""
    patch_bms_timeout()
    monkeypatch.setattr(MockRBTBleakClient, "_RESP", response)
    patch_bleak_client(MockRBTBleakClient)

    bms = BMS(generate_ble_device(), BMSConfig(keep_alive=False))
    with pytest.raises(TimeoutError):
        await bms.async_update()
    await bms.disconnect()
