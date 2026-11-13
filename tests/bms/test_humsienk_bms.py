"""Test the Humsienk BMS implementation."""

from collections.abc import Buffer
from typing import Final
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
import pytest

from aiobmsble import BMSConfig, BMSInfo, BMSLimits, BMSSample, Limit, TempSensor as TS, Threshold
from aiobmsble.bms.humsienk_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import BMSBasicTests

_PROTO_DEFS: Final[dict[str, dict[bytes, bytes]]] = {
    "150Ah": {  # 12V 150Ah pack, BMC-04S001, V02
        b"\xaa\x00\x00\x00\x00": b"\xaa\x00\x00\x00\x00",  # init
        b"\xaa\x10\x00\x10\x00": b"\xaa\x10\x03\x42\x4d\x43\xe5\x00",  # device type: BMC
        b"\xaa\x11\x00\x11\x00": (
            b"\xaa\x11\x0a\x42\x4d\x43\x2d\x30\x34\x53\x30\x30\x31\x62\x02"
        ),  # model: BMC-04S001
        b"\xaa\x20\x00\x20\x00": (
            b"\xaa\x20\x0f\x00\x00\x00\x00\x80\x00\x80\x00\x00\x00\x00\x00\x00\x00\x00\x2f\x01"
        ),  # switch bits: charge [7], heater [8], discharge [9]
        b"\xaa\x21\x00\x21\x00": (
            b"\xaa\x21\x1a\x4a\x33\x00\x00\x82\xfb\xff\xff\x2a\x64\xe4\xf7\x00\x00\xf0\x49\x02\x00"
            b"\x03\x00\x23\x1a\x1a\x1a\x2c\x1a\x91\x08"
        ),  # 13.130V, ...
        b"\xaa\x22\x00\x22\x00": (
            b"\xaa\x22\x30\xd1\x0c\xdb\x0c\xd4\x0c\xd0\x0c\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\xd2\x03"
        ),  # cell voltages
        b"\xaa\x23\x00\x23\x00": (
            b"\xaa\x23\x04\xdc\xfb\xff\xff\xfc\x03"
        ),  # current redundant with 0x21
        b"\xaa\x58\x00\x58\x00": (
            b"\xaa\x58\x30\x04\x00\x98\x3a\x42\x0e\x02\x0d\x04\x00\xc4\x09\xf0\x0a\x04\x00\xf8\x2a"
            b"\x10\x00\x30\x75\x14\x00\x66\x02\x50\x00\x03\x0d\xd1\x0c\xab\x0a\xdd\x0a\x35\x0d\x03"
            b"\x0d\xe3\x09\x15\x0a\xc5\x0d\x1e\x00\x05\x0b"
        ),  # configuration (protection thresholds)
        b"\xaa\xf5\x00\xf5\x00": (
            b"\xaa\xf5\x0c\x56\x30\x32\x00\x00\x00\x00\x00\x00\x00\x00\x00\xb9\x01"
        ),  # version info
    },
    "640Ah": {  # 12V 640Ah pack, BMC-04S001, BMC4S-20251021-OTAV14
        b"\xaa\x00\x00\x00\x00": b"\xaa\x00\x00\x00\x00",  # init
        b"\xaa\x10\x00\x10\x00": b"\xaa\x10\x03\x42\x4d\x43\xe5\x00",  # device type: BMC
        b"\xaa\x11\x00\x11\x00": (
            b"\xaa\x11\x0a\x42\x4d\x43\x2d\x30\x34\x53\x30\x30\x31\x62\x02"
        ),  # model: BMC-04S001
        b"\xaa\x20\x00\x20\x00": (
            b"\xaa\x20\x0f\x00\x00\x00\x00\x80\x00\x80\x00\x00\x00\x00\x00\x00\x00\x00\x2f\x01"
        ),  # switch bits: charge [7], heater [8], discharge [9]
        b"\xaa\x21\x00\x21\x00": (
            b"\xaa\x21\x1a\x34\x35\x00\x00\xae\x06\x00\x00\x63\x63\x4c\x82\x09\x00\x9a\x8e\x09\x00"
            b"\x14\x00\x11\x1a\x1a\x1a\x12\x1a\xc5\x04"
        ),  # 13.620V, 1.71A charging, ...
        b"\xaa\x22\x00\x22\x00": (
            b"\xaa\x22\x30\x51\x0d\x50\x0d\x54\x0d\x42\x0d\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\xbd\x01"
        ),  # cell voltages
        b"\xaa\x23\x00\x23\x00": (
            b"\xaa\x23\x04\x9e\x07\x00\x00\xcc\x00"
        ),  # current redundant with 0x21
        b"\xaa\x40\x00\x40\x00": (
            b"\xaa\x40\x10\x00\x00\x00\x00\x00\x00\x00\x00\x20\x95\x09\x00\x04\x01\x01\x00"
            b"\x14\x01"
        ),  # pack info (not decoded): 628 Ah, 4 cells, LiFePO4
        b"\xaa\x58\x00\x58\x00": (
            b"\xaa\x58\x30\x04\x00\xa9\xf4\x42\x0e\x16\x0d\x04\x00\xc4\x09\x86\x0b\x04\x00\xb8\x0b"
            b"\x10\x00\xb8\x0b\xa0\x00\xc6\x11\x00\x50\xd1\x0c\x9f\x0c\xab\x0a\xbf\x0a\x03\x0d\xd1"
            b"\x0c\xe3\x09\x15\x0a\x7a\x0d\x1e\x00\x02\x0d"
        ),  # configuration (protection thresholds)
        b"\xaa\xf5\x00\xf5\x00": (
            b"\xaa\xf5\x15\x42\x4d\x43\x34\x53\x2d\x32\x30\x32\x35\x31\x30\x32\x31\x2d\x4f\x54"
            b"\x41\x56\x31\x34\xe9\x05"
        ),  # version info
    },
}

_RESULT_DEFS: Final[dict[str, BMSSample]] = {
    "150Ah": {
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
        "delta_cell_voltage": 0.011,
        "temperature": [TS(v, TS.T.CELL) for v in (35.0, 26.0, 26.0, 26.0)]
        + [TS(44.0, TS.T.MOSFET), TS(26.0, TS.T.AMBIENT)],
        "chrg_mosfet": True,
        "dischrg_mosfet": True,
        "heater": False,
        "balancer": 0,
        "problem_code": 0,
        "problem": False,
    },
    "640Ah": {
        "battery_level": 99,
        "battery_health": 99,
        "voltage": 13.62,
        "current": 1.71,
        "cycle_charge": 623.18,
        "design_capacity": 626,
        "cycles": 20,
        "cell_count": 4,
        "cell_voltages": [3.409, 3.408, 3.412, 3.394],
        "battery_charging": True,
        "power": 23.29,
        "cycle_capacity": 8487.712,
        "delta_cell_voltage": 0.018,
        "temperature": [TS(v, TS.T.CELL) for v in (17.0, 26.0, 26.0, 26.0)]
        + [TS(18.0, TS.T.MOSFET), TS(26.0, TS.T.AMBIENT)],
        "chrg_mosfet": True,
        "dischrg_mosfet": True,
        "heater": False,
        "balancer": 0,
        "problem_code": 0,
        "problem": False,
    },
}

_INFO_DEFS: Final[dict[str, BMSInfo]] = {
    "150Ah": {"hw_version": "V02", "model": "BMC-04S001"},
    "640Ah": {"hw_version": "BMC4S-20251021-OTAV14", "model": "BMC-04S001"},
}

_LIMIT_DEFS: Final[dict[str, BMSLimits]] = {
    "150Ah": {
        Limit.CELL_OVP: Threshold(trip=3.65, release=3.33),
        Limit.CELL_UVP: Threshold(trip=2.5, release=2.8),
        Limit.CHARGE_OCP: Threshold(trip=1100.0),
        Limit.DISCHARGE_OCP: Threshold(trip=3000.0),
        Limit.CHARGE_OTP: Threshold(trip=60.0, release=55.0),
        Limit.CHARGE_UTP: Threshold(trip=0.0, release=5.0),
        Limit.DISCHARGE_OTP: Threshold(trip=65.0, release=60.0),
        Limit.DISCHARGE_UTP: Threshold(trip=-20.0, release=-15.0),
    },
    "640Ah": {
        Limit.CELL_OVP: Threshold(trip=3.65, release=3.35),
        Limit.CELL_UVP: Threshold(trip=2.5, release=2.95),
        Limit.CHARGE_OCP: Threshold(trip=300.0),
        Limit.DISCHARGE_OCP: Threshold(trip=300.0),
        Limit.CHARGE_OTP: Threshold(trip=55.0, release=50.0),
        Limit.CHARGE_UTP: Threshold(trip=0.0, release=2.0),
        Limit.DISCHARGE_OTP: Threshold(trip=60.0, release=55.0),
        Limit.DISCHARGE_UTP: Threshold(trip=-20.0, release=-15.0),
    },
}


@pytest.fixture(name="protocol_type", params=_PROTO_DEFS.keys())
def proto(request: pytest.FixtureRequest) -> str:
    """Protocol fixture."""
    assert isinstance(request.param, str)
    return request.param


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


class MockHumsienkBleakClient(MockBleakClient):
    """Emulate a Humsienk BMS BleakClient."""

    _RESP: dict[bytes, bytes] = _PROTO_DEFS["150Ah"]

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
            "MockHumsienkBleakClient", bytearray(self._RESP.get(bytes(data), b""))
        )


async def test_update(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    protocol_type: str,
    keep_alive_fixture: bool,
) -> None:
    """Test Humsienk BMS data update."""

    monkeypatch.setattr(MockHumsienkBleakClient, "_RESP", _PROTO_DEFS[protocol_type])
    patch_bleak_client(MockHumsienkBleakClient)

    bms = BMS(generate_ble_device(), BMSConfig(keep_alive_fixture))

    assert await bms.async_update() == _RESULT_DEFS[protocol_type]

    # query again to check already connected state
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()


async def test_device_info(
    monkeypatch: pytest.MonkeyPatch, patch_bleak_client, protocol_type: str
) -> None:
    """Test that the BMS returns initialized dynamic device information."""
    monkeypatch.setattr(MockHumsienkBleakClient, "_RESP", _PROTO_DEFS[protocol_type])
    patch_bleak_client(MockHumsienkBleakClient)
    bms = BMS(generate_ble_device())
    assert await bms.device_info() == _INFO_DEFS[protocol_type]


async def test_limits(
    monkeypatch: pytest.MonkeyPatch, patch_bleak_client, protocol_type: str
) -> None:
    """Test that the BMS returns the protection thresholds from the 0x58 frame."""
    monkeypatch.setattr(MockHumsienkBleakClient, "_RESP", _PROTO_DEFS[protocol_type])
    patch_bleak_client(MockHumsienkBleakClient)
    bms = BMS(generate_ble_device(), BMSConfig(keep_alive=False))
    assert await bms.limits() == _LIMIT_DEFS[protocol_type]
    assert not bms.is_connected


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
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    patch_bms_timeout,
    protocol_type: str,
    wrong_response: bytes,
) -> None:
    """Test data up date with BMS returning invalid data."""

    patch_bms_timeout()

    monkeypatch.setattr(
        MockHumsienkBleakClient,
        "_RESP",
        _PROTO_DEFS[protocol_type] | {b"\xaa\x00\x00\x00\x00": wrong_response},
    )

    patch_bleak_client(MockHumsienkBleakClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = {}
    with pytest.raises(TimeoutError):
        result = await bms.async_update()

    assert not result
    await bms.disconnect()


async def test_switch_states(
    monkeypatch: pytest.MonkeyPatch, patch_bleak_client, protocol_type: str
) -> None:
    """Test that switch bits and the cell balancing bitmap are reported correctly.

    operation_status bits 7/15/23 (charge FET, heater, discharge FET) are all set,
    and cells 1 and 3 are balancing. None of the switch bits may raise a problem.
    """

    monkeypatch.setattr(
        MockHumsienkBleakClient,
        "_RESP",
        _PROTO_DEFS[protocol_type]
        | {
            b"\xaa\x20\x00\x20\x00": (
                b"\xaa\x20\x0f\x00\x00\x00\x00\x80\x80\x80\x00\x05\x00\x00\x00\x00\x00"
                b"\x00\xb4\x01"
            )
        },
    )

    patch_bleak_client(MockHumsienkBleakClient)

    bms = BMS(generate_ble_device())

    assert await bms.async_update() == _RESULT_DEFS[protocol_type] | {
        "chrg_mosfet": True,
        "dischrg_mosfet": True,
        "heater": True,
        "balancer": 0x5,  # cells 1 and 3
        "problem_code": 0,
        "problem": False,
    }

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
    protocol_type: str,
    problem_response: bytes,
    expected: int,
) -> None:
    """Test data update with BMS returning error flags."""

    monkeypatch.setattr(
        MockHumsienkBleakClient,
        "_RESP",
        _PROTO_DEFS[protocol_type] | {b"\xaa\x20\x00\x20\x00": b"\xaa\x20\x0f" + problem_response},
    )

    patch_bleak_client(MockHumsienkBleakClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = await bms.async_update()
    assert result == _RESULT_DEFS[protocol_type] | {
        "problem": True,
        "problem_code": expected,
    }

    await bms.disconnect()
