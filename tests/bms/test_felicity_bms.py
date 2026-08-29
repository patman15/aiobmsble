"""Test the Felicity implementation."""

from collections.abc import Buffer
from typing import Final
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.uuids import normalize_uuid_str
import pytest

from aiobmsble import BMSConfig, BMSSample, TempSensor as TS
from aiobmsble.bms.felicity_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import BMSBasicTests

BT_FRAME_SIZE = 35

RESP_VALUE: Final[dict[str, bytes]] = {
    "dat": (
        b'{"CommVer":1,"wifiSN":"F100011002424470238","iotType":3,"dateTime":"20210101010459",'
        b'"timeZMin":480}'
    ),
    "rt": (
        b'{"CommVer":1,"wifiSN":"F075704831426030796","modID":3,'
        b'"date":"20260813120925","DevSN":"075704831426030796","Type":112,'
        b'"SubType":7353,"Estate":9152,"Bfault":0,"Bwarn":0,"Bstate":9152,'
        b'"BBfault":0,"BBwarn":0,"BTemp":[[340,330],[256,514]],'
        b'"Batt":[[54100],[1977],[null]],"Batsoc":[[7860,943,1050000]],'
        b'"Templist":[[340,340],[0,0],[65535,65535],[65535,65535]],'
        b'"BattList":[[54070,65535],[647,-1]],"BatsocList":[[7800,1000,350000]],'
        b'"BatcelList":[[3378,3380,3379,3380,3379,3380,3380,3382,3389,3381,'
        b"3380,3381,3380,3380,3379,3380],[65535,65535,65535,65535,65535,65535,"
        b"65535,65535,65535,65535,65535,65535,65535,65535,65535,65535]],"
        b'"EMSpara":[[3,14]],"BMaxMin":[[3389,3378],[8,0]],'
        b'"LVolCur":[[576,480],[4320,4800]],"BMSpara":[[3,14]],'
        b'"BLVolCu":[[576,480],[1600,1600]],'
        b'"BtemList":[[340,340,340,340,32767,32767,32767,32767]]}'
    ),
    "bas": (
        b'{"CommVer":1,"version":"2.06","wifiSN":"F100011002424470238","COM":3,"iotType":3,'
        b'"modID":1,"DevSN":"100011002424470238","Type":112,"SubType":7300,"DSwVer":65535,'
        b'"M1SwVer":519,"M2SwVer":16,"DHwVer":0,"CtHwVer":0,"PwHwVer":65535}'
    ),
}


def ref_value() -> BMSSample:
    """Return reference value for mock Seplos BMS."""
    return {
        "voltage": 54.07,
        "current": 64.7,
        "battery_level": 78.0,
        "cycle_charge": 273.0,
        "temperature": 34.0,
        "cycle_capacity": 14761.11,
        "power": 3498.329,
        "battery_charging": True,
        "cell_count": 16,
        "cell_voltages": [
            3.378,
            3.38,
            3.379,
            3.38,
            3.379,
            3.38,
            3.38,
            3.382,
            3.389,
            3.381,
            3.38,
            3.381,
            3.38,
            3.38,
            3.379,
            3.38,
        ],
        "temp_values": [TS(34.0)] * 4,
        "delta_voltage": 0.011,
        "problem": False,
        "problem_code": 0,
    }


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


class MockFelicityBleakClient(MockBleakClient):
    """Emulate a Felicity BMS BleakClient."""

    HEAD_CMD: Final[int] = 0x7B
    TAIL_CMD: Final[int] = 0x7D
    CMDS: Final[dict[str, bytes]] = {
        "dat": b"wifilocalMonitor:get Date",
        "bas": b"wifilocalMonitor:get dev basice infor",
        "rt": b"wifilocalMonitor:get dev real infor",
    }
    RESP: Final[dict[str, bytes]] = RESP_VALUE

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
    ) -> bytes:

        if isinstance(char_specifier, str) and normalize_uuid_str(
            char_specifier
        ) == normalize_uuid_str("49535258-184d-4bd9-bc61-20c647249616"):
            for k, v in self.CMDS.items():
                if bytes(data).startswith(v):
                    return self.RESP[k]

        return b""

    async def write_gatt_char(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        data: Buffer,
        response: bool | None = None,
    ) -> None:
        """Issue write command to GATT."""
        await super().write_gatt_char(char_specifier, data)

        assert (
            self._notify_callback
        ), "write to characteristics but notification not enabled"

        resp: bytes = self._response(char_specifier, data)
        for notify_data in [
            resp[i : i + BT_FRAME_SIZE] for i in range(0, len(resp), BT_FRAME_SIZE)
        ]:
            self._notify_callback("MockFelicityBleakClient", bytearray(notify_data))


async def test_update(patch_bleak_client, keep_alive_fixture: bool) -> None:
    """Test Felicity BMS data update."""

    patch_bleak_client(MockFelicityBleakClient)

    bms = BMS(generate_ble_device(), BMSConfig(keep_alive_fixture))

    assert await bms.async_update() == ref_value()

    # query again to check already connected state
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()


async def test_device_info(patch_bleak_client) -> None:
    """Test that the BMS returns initialized dynamic device information."""
    patch_bleak_client(MockFelicityBleakClient)
    bms = BMS(generate_ble_device())
    assert await bms.device_info() == {
        "fw_version": "519",
        "sw_version": "2.06",
        "model_id": "112",
        "serial_number": "100011002424470238",
    }


async def test_problem_response(
    monkeypatch: pytest.MonkeyPatch, patch_bleak_client
) -> None:
    """Test Felicity BMS data update with problem response."""

    prb_resp: dict[str, bytes] = RESP_VALUE.copy()
    prb_resp["rt"] = RESP_VALUE["rt"].replace(
        b'"Bfault":0,"Bwarn":0', b'"Bfault":1,"Bwarn":10'
    )  # patch problem codes

    patch_bleak_client(MockFelicityBleakClient)

    monkeypatch.setattr(MockFelicityBleakClient, "RESP", prb_resp)

    bms = BMS(generate_ble_device(), BMSConfig(False))

    assert await bms.async_update() == ref_value() | {
        "problem": True,
        "problem_code": 11,
    }

    await bms.disconnect()


@pytest.fixture(
    name="wrong_response",
    params=[
        (b'"CommVer":1,"wifiSN":"F100011002424470238"}', "invalid frame start"),
        (b'{"CommVer":1,"wifiSN":"F100011002424470238"', "invalid frame end"),
        (b'{"CommVer":2,"wifiSN":"F100011002424470238"}', "invalid protocol"),
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
        MockFelicityBleakClient, "_response", lambda _s, _c_, d: wrong_response
    )
    patch_bleak_client(MockFelicityBleakClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = {}
    with pytest.raises(TimeoutError):
        result = await bms.async_update()

    assert not result
    await bms.disconnect()


async def test_malformed_json_raises_value_error(
    monkeypatch: pytest.MonkeyPatch, patch_bleak_client
) -> None:
    """Test that structurally invalid (but valid JSON) data raises the documented ValueError."""

    bad_resp: dict[str, bytes] = RESP_VALUE.copy()
    bad_resp["rt"] = RESP_VALUE["rt"].replace(
        b'"BattList":[[54070,65535],[647,-1]]', b'"BattList":[]'
    )

    patch_bleak_client(MockFelicityBleakClient)
    monkeypatch.setattr(MockFelicityBleakClient, "RESP", bad_resp)

    bms = BMS(generate_ble_device())

    with pytest.raises(ValueError, match="BMS data incomplete"):
        await bms.async_update()

    await bms.disconnect()
