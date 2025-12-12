"""Test the Daly BMS implementation."""

from collections.abc import Buffer
from typing import Final
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.exc import BleakError
from bleak.uuids import normalize_uuid_str
import pytest

from aiobmsble import BMSSample
from aiobmsble.bms.daly_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient


def ref_value() -> BMSSample:
    """Return reference value for mock Daly BMS."""
    return {
        "voltage": 14.0,
        "current": 3.0,
        "battery_level": 90.0,
        "cycles": 57,
        "cycle_charge": 345.6,
        "cell_voltages": [4.127, 4.137, 4.147, 4.157],
        "cell_count": 4,
        "delta_voltage": 0.321,
        "temp_sensors": 4,
        "cycle_capacity": 4838.4,
        "power": 42.0,
        "battery_charging": True,
        "problem": False,
        "problem_code": 0,
        "chrg_mosfet": False,
        "dischrg_mosfet": True,
        "balancer": True,
    }


class MockDalyBleakClient(MockBleakClient):
    """Emulate a Daly BMS BleakClient."""

    HEAD_READ: Final[bytes] = b"\xd2\x03"
    CMD_INFO: Final[bytes] = b"\x00\x00\x00\x3e\xd7\xb9"
    MOS_INFO: Final[bytes] = b"\x00\x3e\x00\x09\xf7\xa3"
    VER_INFO: Final[bytes] = b"\x00\xa9\x00\x20\x87\x91"
    MOS_AVAIL: bool = True
    RESP: Final[dict[bytes, bytearray]] = {
        CMD_INFO: bytearray(
            b"\xd2\x03\x7c\x10\x1f\x10\x29\x10\x33\x10\x3d\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x3c\x00\x3d\x00\x3e\x00\x3f\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x8c\x75\x4e\x03\x84\x10\x3d\x10\x1f\x00\x00\x00\x00\x00\x00\x0d"
            b"\x80\x00\x04\x00\x04\x00\x39\x00\x01\x00\x00\x00\x01\x10\x2e\x01\x41\x00\x2a\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\xa0\xdf"
        ),  # 'voltage': 14.0, 'current': 3.0, 'battery_level': 90.0, 'cycles': 57,
            # 'cycle_charge': 345.6, 'numTemp': 4, 'temperature': 21.5, 'cycle_capacity': 4838.400000000001,
            # 'power': 42.0, 'battery_charging': True, 'runtime': none!, 'delta_voltage': 0.321
        MOS_INFO: bytearray(
            b"\xd2\x03\x12\x00\x00\x00\x00\x75\x30\x00\x00\x00\x4e\xff\xff\xff\xff\xff\xff\xff"
            b"\xff\x0b\x4e"
        ),
        VER_INFO: bytearray(
            b"\xd2\x03\x40\x54\x30\x30\x4b\x5f\x33\x32\x31\x30\x34\x32\x5f\x31\x31\x00\x00\x48"
            b"\x32\x2e\x30\x5f\x31\x30\x33\x52\x5f\x33\x30\x39\x46\x39\x46\x32\x30\x32\x34\x30"
            b"\x32\x32\x39\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x55\x41"
        ),
    }

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
    ) -> bytearray:
        if (
            isinstance(char_specifier, str)
            and normalize_uuid_str(char_specifier) == normalize_uuid_str("fff2")
            and bytes(data)[0:2] == self.HEAD_READ
        ):
            if bytes(data)[2:] == self.MOS_INFO and not self.MOS_AVAIL:
                raise TimeoutError
            return MockDalyBleakClient.RESP.get(bytes(data)[2:], bytearray())

        return bytearray()

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
            "MockDalyBleakClient", self._response(char_specifier, data)
        )


class MockInvalidBleakClient(MockDalyBleakClient):
    """Emulate a Daly BMS BleakClient."""

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
    ) -> bytearray:
        if isinstance(char_specifier, str) and normalize_uuid_str(
            char_specifier
        ) == normalize_uuid_str("fff2"):
            return bytearray(
                b"\xd2\x03\x11\x10\x1f\x10\x29\x10\x33\x10\x3d\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                b"\x5d\x0f"
            )

        return bytearray()

    async def disconnect(self) -> None:
        """Mock disconnect to raise BleakError."""
        raise BleakError


@pytest.mark.parametrize("mos_sensor_avail", [True, False])
async def test_update(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    mos_sensor_avail: bool,
    keep_alive_fixture: bool,
) -> None:
    """Test Daly BMS data update."""

    monkeypatch.setattr(  # patch recoginiation of MOS request to fail
        MockDalyBleakClient, "MOS_AVAIL", mos_sensor_avail
    )

    patch_bleak_client(MockDalyBleakClient)

    bms = BMS(generate_ble_device(), keep_alive_fixture)

    assert await bms.async_update() == ref_value() | (
        {
            "temperature": 24.8,
            "temp_values": [38.0, 20.0, 21.0, 22.0, 23.0],
        }
        if mos_sensor_avail
        else {
            "temperature": 21.5,
            "temp_values": [20.0, 21.0, 22.0, 23.0],
        }
    )

    # query again to check already connected state
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()


async def test_device_info(patch_bleak_client) -> None:
    """Test that the BMS returns initialized dynamic device information."""
    patch_bleak_client(MockDalyBleakClient)
    bms = BMS(generate_ble_device())
    assert await bms.device_info() == {
        "hw_version": "H2.0_103R_309F9F",
        "sw_version": "T00K_321042_11",
    }


async def test_mos_excl(patch_bleak_client) -> None:
    """Test Daly BMS data update."""

    patch_bleak_client(MockDalyBleakClient)

    for name_no_mos in BMS.MOS_NOT_AVAILABLE:
        bms = BMS(
            generate_ble_device("cc:cc:cc:cc:cc:cc", f"{name_no_mos}MockBLEdevice"),
        )

        assert await bms.async_update() == ref_value() | {
            "temperature": 21.5,
            "temp_values": [20.0, 21.0, 22.0, 23.0],
        }

        await bms.disconnect()


async def test_too_short_frame(patch_bleak_client) -> None:
    """Test data update with BMS returning valid but too short data."""

    patch_bleak_client(MockInvalidBleakClient)

    bms: BMS = BMS(generate_ble_device())

    assert not await bms.async_update()

    await bms.disconnect()


@pytest.fixture(
    name="wrong_response",
    params=[
        (bytearray(b"invalid_value"), "invalid value"),
        (
            bytearray(
                b"\xd2\x03\x7c\x10\x1f\x10\x29\x10\x33\x10\x3d\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                b"\x00\x00\x00\x00\x00\x00\x00\x00\x3c\x00\x3d\x00\x3e\x00\x3f\x00\x00\x00\x00\x00"
                b"\x00\x00\x00\x00\x8c\x75\x4e\x03\x84\x10\x3d\x10\x1f\x00\x00\x00\x00\x00\x00\x0d"
                b"\x80\x00\x04\x00\x04\x00\x39\x00\x01\x00\x00\x00\x01\x10\x2e\x01\x41\x00\x2a\x00"
                b"\x00\x00\x00\x00\x00\x00\x00\xde\xad"
            ),
            "wrong CRC",
        ),
        (bytearray(b"\x00"), "too short"),
    ],
    ids=lambda param: param[1],
)
def fix_response(request) -> tuple[bytearray, str]:
    """Return faulty response frame."""
    return request.param[0]


async def test_invalid_response(
    monkeypatch, patch_bleak_client, patch_bms_timeout, wrong_response
) -> None:
    """Test data update with BMS returning invalid data."""

    patch_bms_timeout()

    monkeypatch.setattr(
        MockDalyBleakClient, "_response", lambda _s, _c, _d: wrong_response
    )

    patch_bleak_client(MockDalyBleakClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = {}
    with pytest.raises(TimeoutError):
        result = await bms.async_update()

    assert not result

    await bms.disconnect()


@pytest.fixture(
    name="problem_response",
    params=[
        (
            bytearray(
                b"\xd2\x03\x7c\x10\x1f\x10\x29\x10\x33\x10\x3d\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                b"\x00\x00\x00\x00\x00\x00\x00\x00\x3c\x00\x3d\x00\x3e\x00\x3f\x00\x00\x00\x00\x00"
                b"\x00\x00\x00\x00\x8c\x75\x4e\x03\x84\x10\x3d\x10\x1f\x00\x00\x00\x00\x00\x00\x0d"
                b"\x80\x00\x04\x00\x04\x00\x39\x00\x01\x00\x00\x00\x01\x10\x2e\x01\x41\x00\x2a\x00"
                b"\x00\x00\x00\x00\x00\x00\x01\x61\x1f"
            ),
            "first_bit",
        ),
        (
            bytearray(
                b"\xd2\x03\x7c\x10\x1f\x10\x29\x10\x33\x10\x3d\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                b"\x00\x00\x00\x00\x00\x00\x00\x00\x3c\x00\x3d\x00\x3e\x00\x3f\x00\x00\x00\x00\x00"
                b"\x00\x00\x00\x00\x8c\x75\x4e\x03\x84\x10\x3d\x10\x1f\x00\x00\x00\x00\x00\x00\x0d"
                b"\x80\x00\x04\x00\x04\x00\x39\x00\x01\x00\x00\x00\x01\x10\x2e\x01\x41\x00\x2a\x80"
                b"\x00\x00\x00\x00\x00\x00\x00\xa8\xbf"
            ),
            "last_bit",
        ),
    ],
    ids=lambda param: param[1],
)
def prb_response(request: pytest.FixtureRequest):
    """Return faulty response frame."""
    return request.param


async def test_problem_response(
    monkeypatch: pytest.MonkeyPatch, patch_bleak_client, problem_response: tuple[bytearray, str]
) -> None:
    """Test data update with BMS returning error flags."""

    monkeypatch.setattr(
        MockDalyBleakClient, "_response", lambda _s, _c, _d: problem_response[0]
    )

    patch_bleak_client(MockDalyBleakClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = await bms.async_update()
    assert result.get("problem", False)  # we expect a problem
    assert result.get("problem_code", 0) == (
        1 << (0 if problem_response[1] == "first_bit" else 63)
    )

    await bms.disconnect()
