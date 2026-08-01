"""Test the PowerXtreme BMS implementation."""

from typing import Final

import pytest

from aiobmsble import BMSConfig, BMSSample, TempSensor as TS
from aiobmsble.bms.pwrxtreme_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.bms.test_topband_bms import MockTopbandBleakClient
from tests.test_basebms import BMSBasicTests

BT_FRAME_SIZE = 32

_PROTO_DEFS: Final[dict[int, bytearray]] = {
    0x5E: bytearray(  # PowerXtreme X210
        b"\x5e\x43\x33\x33\x34\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x32\x30\x33\x43\x30"
        b"\x33\x30\x30\x30\x31\x30\x30\x36\x34\x30\x30\x42\x34\x30\x42\x30\x30\x30\x30\x30\x31\x30"
        b"\x30\x31\x30\x30\x44\x33\x43\x30\x44\x33\x44\x30\x44\x33\x41\x30\x44\x30\x30\x30\x30\x30"
        b"\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30"
        b"\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30"
        b"\x33\x37\x32"
    ),
}


_RESULT_DEFS: Final[dict[int, BMSSample]] = {
    0x5E: {
        "voltage": 13.507,
        "current": 0.0,
        "battery_level": 100,
        "cycle_charge": 212.0,
        "cycles": 1,
        "temp_values": [TS(26.45, TS.T.GENERIC)],
        "problem_code": 0,
        "cell_voltages": [3.344, 3.388, 3.389, 3.386],
        "battery_charging": False,
        "cell_count": 4,
        "delta_voltage": 0.045,
        "temperature": 26.45,
        "cycle_capacity": 2863.484,
        "power": 0.0,
        "problem": False,
    }
}


@pytest.fixture(name="protocol_type", params=_PROTO_DEFS.keys())
def proto(request: pytest.FixtureRequest) -> int:
    """Protocol fixture."""
    assert isinstance(request.param, int)
    return request.param


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


async def test_update(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    protocol_type: int,
    keep_alive_fixture: bool,
) -> None:
    """Test Topband BMS data update."""

    monkeypatch.setattr(MockTopbandBleakClient, "_RESP", _PROTO_DEFS[protocol_type])
    patch_bleak_client(MockTopbandBleakClient)

    bms = BMS(generate_ble_device(), BMSConfig(keep_alive_fixture))

    assert await bms.async_update() == _RESULT_DEFS[protocol_type]

    # query again to check already connected state
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()
