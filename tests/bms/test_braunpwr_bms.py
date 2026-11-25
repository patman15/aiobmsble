"""Test the Braun Power BMS implementation."""

import asyncio
from collections.abc import Buffer
from typing import Final
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.uuids import normalize_uuid_str
import pytest

from aiobmsble import BMSConfig, BMSInfo, BMSSample, Limit, TempSensor as TS, Threshold, TSKind
from aiobmsble.bms.braunpwr_bms import BMS
from aiobmsble.exceptions import BMSDataError
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import BMSBasicTests

_RESULT_DEFS: Final[BMSSample] = {
    "voltage": 53.31,
    "current": -11.45,
    "battery_level": 83,
    "battery_health": 100,
    "cell_count": 16,
    "cycle_charge": 250.26,
    "cycles": 8,
    "cell_voltages": [
        3.327,
        3.334,
        3.333,
        3.335,
        3.333,
        3.335,
        3.333,
        3.338,
        3.332,
        3.335,
        3.334,
        3.336,
        3.333,
        3.334,
        3.336,
        3.337,
    ],
    "design_capacity": 300,
    "power": -610.399,
    "temp_count": 4,
    "temperature": [TS(23.0, TSKind.CELL)] * 4,
    "delta_cell_voltage": 0.011,
    "cycle_energy": 13341.361,
    "battery_charging": False,
    "runtime": 78684,
    "problem_code": 0,
    "problem": False,
    "balancer": 32385,
}

_LIMIT_DEFS: Final[dict[Limit, Threshold]] = {
    Limit.CELL_OVP: Threshold(trip=3.65, release=3.38, delay=2.0),
    Limit.CELL_UVP: Threshold(trip=2.5, release=3.0, delay=3.0),
    Limit.PACK_OVP: Threshold(trip=58.4, release=54.4, delay=3.0),
    Limit.PACK_UVP: Threshold(trip=40.0, release=48.0, delay=3.0),
    Limit.CHARGE_OTP: Threshold(trip=55.0, release=50.0, delay=3.0),
    Limit.CHARGE_UTP: Threshold(trip=-1.0, release=5.0, delay=3.0),
    Limit.DISCHARGE_OTP: Threshold(trip=60.0, release=55.0, delay=3.0),
    Limit.DISCHARGE_UTP: Threshold(trip=-20.0, release=-15.0, delay=3.0),
    Limit.CHARGE_OCP: Threshold(trip=215.0, delay=3.0),
    Limit.DISCHARGE_OCP: Threshold(trip=215.0, delay=3.0),
}


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


class MockBraunPWRBleakClient(MockBleakClient):
    """Emulate a Braun Power BMS BleakClient."""

    RESP: dict[int, bytes] = {
        0x01: (
            b"\x7b\x01\x20\x00\x53\x14\xd3\x00\xd2\x00\xb4\x00\xbe\xfb\x87\x61\xc2\x75\x30\x00\x00"
            b"\x00\x00\x00\x08\x7e\x81\x00\x00\x00\x0e\x00\x00\x00\x64\x7d"
        ),
        0x02: (
            b"\x7b\x02\x21\x10\x0c\xff\x0d\x06\x0d\x05\x0d\x07\x0d\x05\x0d\x07\x0d\x05\x0d\x0a\x0d"
            b"\x04\x0d\x07\x0d\x06\x0d\x08\x0d\x05\x0d\x06\x0d\x08\x0d\x09\x7d"
        ),
        0x03: b"\x7b\x03\x09\x04\x0b\x91\x0b\x91\x0b\x91\x0b\x91\x7d",
        0x05: (
            b"\x7b\x05\x18\x0e\x42\x0d\x34\x07\xd0\x09\xc4\x0b\xb8\x0b\xb8\x16\xd0\x15\x40\x0b\xb8"
            b"\x0f\xa0\x12\xc0\x0b\xb8\x7d"
        ),
        0x06: (
            b"\x7b\x06\x18\x0c\xd1\x0c\x9f\x0b\xb8\x0a\xa1\x0a\xdd\x0b\xb8\x0d\x03\x0c\xd1\x0b\xb8"
            b"\x09\xe3\x0a\x15\x0b\xb8\x7d"
        ),
        0x07: b"\x7b\x07\x0c\x53\xfc\x0b\xb8\x00\x00\x53\xfc\x0b\xb8\x00\x00\x7d",
        0x08: (
            b"\x7b\x08\x16\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x7d"
        ),
        0x09: b"\x7b\x09\x03\xff\xff\xff\x7d",
        0x0A: b"\x7b\x0a\x00\x7d",
        0x0B: b"\x7b\x0b\x0e\x42\x4c\x2d\x32\x35\x30\x2d\x31\x30\x30\x2d\x31\x30\x30\x7d",
        0x0C: (
            b"\x7b\x0c\x14\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff"
            b"\xff\xff\x7d"
        ),
        0x74: (
            b"\x7b\x74\x1d\x4b\x53\x5f\x42\x4c\x45\x5f\x57\x49\x46\x49\x5f\x56"
            b"\x65\x72\x31\x2e\x30\x2e\x30\x5f\x32\x30\x32\x34\x30\x33\x31\x33\x7d"
        ),
        0x78: b"\x7b\x78\x02\x00\x23\x7d",
        0xF4: b"\x7b\xf4\x03\x02\x03\x01\x7d",
        0xF5: b"\x7b\xf5\x02\x02\x39\x7d",
    }

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str | UUID, cmd: int
    ) -> bytearray:
        if isinstance(char_specifier, str) and normalize_uuid_str(
            char_specifier
        ) != normalize_uuid_str("ff02"):
            return bytearray()

        return bytearray(self.RESP.get(cmd, b""))

    async def write_gatt_char(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        data: Buffer,
        response: bool | None = None,
    ) -> None:
        """Issue write command to GATT."""
        await super().write_gatt_char(char_specifier, data, response)

        assert self._notify_callback is not None

        self._notify_callback("MockABCBleakClient", self._response(char_specifier, bytes(data)[1]))
        await asyncio.sleep(0)


async def test_update(patch_bleak_client, keep_alive_fixture: bool) -> None:
    """Test ABC BMS data update."""

    patch_bleak_client(MockBraunPWRBleakClient)

    bms = BMS(generate_ble_device(), BMSConfig(keep_alive_fixture))

    assert await bms.update() == _RESULT_DEFS

    # query again to check already connected state
    await bms.update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()


async def test_limits(patch_bleak_client) -> None:
    """Test decoding of the protection limit blocks."""
    patch_bleak_client(MockBraunPWRBleakClient)
    bms = BMS(generate_ble_device())
    assert await bms.limits() == _LIMIT_DEFS
    await bms.disconnect()


async def test_device_info(patch_bleak_client) -> None:
    """Test that the BMS returns initialized dynamic device information."""
    patch_bleak_client(MockBraunPWRBleakClient)
    bms = BMS(generate_ble_device())
    assert await bms.device_info() == MockBleakClient.default_info | {
        "hw_version": "KS_BLE_WIFI_Ver1.0.0_20240313",
        "sw_version": "2.3.1",
        "serial_number": "BL-250-100-100",
    }


async def test_device_info_model_only(monkeypatch: pytest.MonkeyPatch, patch_bleak_client) -> None:
    """Test that a reported model is decoded while an unset (all-FF) serial is omitted."""
    monkeypatch.setattr(
        MockBraunPWRBleakClient,
        "RESP",
        MockBraunPWRBleakClient.RESP
        | {
            0x0A: b"\x7b\x0a\x05KS-16\x7d",
            0x0B: b"\x7b\x0b\x04\xff\xff\xff\xff\x7d",
        },
    )
    patch_bleak_client(MockBraunPWRBleakClient)
    bms = BMS(generate_ble_device())
    info: BMSInfo = await bms.device_info()
    assert info.get("model_id") == "KS-16"
    assert info.get("serial_number") == "mock_serial_number"
    await bms.disconnect()


@pytest.fixture(
    name="wrong_response",
    params=[
        (
            b"!\x03\x09\x04\x0b\x91\x0b\x91\x0b\x91\x0b\x91}",
            "wrong_SOF",
        ),
        (
            b"{\x03\x09\x04\x0b\x91\x0b\x91\x0b\x91\x0b\x91-",
            "wrong_EOF",
        ),
        (
            b"{\x04\x09\x04\x0b\x91\x0b\x91\x0b\x91\x0b\x91}",
            "unknown_CMD",
        ),
        (
            b"{\x02\x09\x04\x0b\x91\x0b\x91\x0b\x91\x0b\x91}",
            "wrong_CMD",
        ),
        (
            b"{\x03\x08\x04\x0b\x91\x0b\x91\x0b\x91\x0b\x91}",
            "wrong_length",
        ),
    ],
    ids=lambda param: param[1],
)
def fix_response(request: pytest.FixtureRequest) -> bytes:
    """Return faulty response frame."""
    assert isinstance(request.param, tuple) and isinstance(request.param[0], bytes)
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
        MockBraunPWRBleakClient,
        "RESP",
        MockBraunPWRBleakClient.RESP | {0x03: wrong_response},
    )

    patch_bleak_client(MockBraunPWRBleakClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = {}
    with pytest.raises(TimeoutError):
        result = await bms.update()

    assert not result
    await bms.disconnect()


@pytest.fixture(
    name="problem_response",
    params=[
        (
            (
                b"\x7b\x01\x20\x00\x53\x14\xd3\x00\xd2\x00\xb4\x00\xbe\xfb\x87\x61\xc2\x75\x30\x00\x00"
                b"\x00\x00\x00\x08\x00\x00\x00\x00\x00\x0e\x80\x00\x00\x64\x7d"
            ),
            0x8000,
            "first_bit",
        ),
        (
            (
                b"\x7b\x01\x20\x00\x53\x14\xd3\x00\xd2\x00\xb4\x00\xbe\xfb\x87\x61\xc2\x75\x30\x00\x00"
                b"\x00\x00\x00\x08\x00\x00\x00\x00\x00\x0e\x00\x02\x00\x64\x7d"
            ),
            0x02,
            "last_bit",
        ),
        (
            (
                b"\x7b\x01\x20\x00\x53\x14\xd3\x00\xd2\x00\xb4\x00\xbe\xfb\x87\x61\xc2\x75\x30\x00\x00"
                b"\x00\x00\x00\x08\x00\x00\x00\x00\x00\x0e\xff\xfe\x00\x64\x7d"
            ),
            0xFFFE,
            "all_bits_set",
        ),
    ],
    ids=lambda param: param[2],
)
def prb_response(request: pytest.FixtureRequest) -> tuple[bytes, int, str]:
    """Return faulty response frame."""
    assert isinstance(request.param, tuple)
    return request.param


async def test_problem_response(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    problem_response: tuple[bytes, int, str],
) -> None:
    """Test data update with BMS returning error flags."""

    monkeypatch.setattr(
        MockBraunPWRBleakClient,
        "RESP",
        MockBraunPWRBleakClient.RESP | {0x1: bytes(problem_response[0])},
    )

    patch_bleak_client(MockBraunPWRBleakClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = await bms.update()
    assert result.get("problem", False)  # expect a problem report
    assert result.get("problem_code", 0) == problem_response[1]

    await bms.disconnect()


async def test_limits_incomplete(monkeypatch: pytest.MonkeyPatch, patch_bleak_client) -> None:
    """Test that a truncated protection limit block raises a data error."""
    monkeypatch.setattr(
        MockBraunPWRBleakClient,
        "RESP",
        MockBraunPWRBleakClient.RESP | {0x05: b"\x7b\x05\x02\x00\x00\x7d"},
    )
    patch_bleak_client(MockBraunPWRBleakClient)
    bms = BMS(generate_ble_device())
    with pytest.raises(BMSDataError):
        await bms.limits()
    await bms.disconnect()
