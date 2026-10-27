"""Test the Rolls VB-series BMS implementation."""

from collections.abc import Buffer
from typing import Final
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
import pytest

from aiobmsble import BMSConfig, BMSSample, TempSensor as TS
from aiobmsble.basebms import crc_modbus
from aiobmsble.bms.rollsvb_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import BMSBasicTests

# real device responses, read from a VB24-150LFP (idle, 78.1 % charged, 17 degrees C)
_RESP: Final[dict[bytes, bytes]] = {
    # cell voltages, reg 0x0000, 16 registers (8 cells, rest zero padding)
    b"\xd2\x03\x00\x00\x00\x10\x57\xa5": (
        b"\xd2\x03\x20\x0d\x07\x0d\x08\x0d\x08\x0d\x05\x0d\x08\x0d\x08\x0d"
        b"\x08\x0d\x07\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\xe8\x8e"
    ),
    # temperatures, voltage, current and state of charge, reg 0x0020, 16 registers
    b"\xd2\x03\x00\x20\x00\x10\x56\x6f": (
        b"\xd2\x03\x20\x00\x39\x00\x39\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x01\x0a\x75\x30\x03\x0d\x0d\x08\x0d\x05\x00\x39\x00"
        b"\x39\x00\x00\x4b\x40"
    ),
    # remaining charge, cell count, temperature sensors, cycles, reg 0x0030, 16 registers
    b"\xd2\x03\x00\x30\x00\x10\x57\xaa": (
        b"\xd2\x03\x20\x04\x93\x00\x08\x00\x02\x00\x02\x00\x00\x00\x01\x00"
        b"\x01\x0d\x07\x00\x03\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x5c\x9e"
    ),
}

_RESULT: Final[BMSSample] = {
    "cell_voltages": [3.335, 3.336, 3.336, 3.333, 3.336, 3.336, 3.336, 3.335],
    "voltage": 26.6,
    "current": 0.0,
    "battery_level": 78.1,
    "cycle_charge": 117.1,
    "cycle_capacity": 3114.86,
    "cycles": 2,
    "temp_values": [TS(17.0, TS.T.GENERIC), TS(17.0, TS.T.GENERIC)],
    "temperature": 17.0,
    "cell_count": 8,
    "delta_voltage": 0.003,
    "power": 0.0,
    "battery_charging": False,
    "problem": False,
}


# real device responses while charging at 25 A (78.5 % charged, 17 degrees C)
_RESP_CHARGING: Final[dict[bytes, bytes]] = {
    # cell voltages, reg 0x0000, 16 registers
    b"\xd2\x03\x00\x00\x00\x10\x57\xa5": (
        b"\xd2\x03\x20\x0d\x44\x0d\x44\x0d\x44\x0d\x42\x0d\x43\x0d\x44\x0d"
        b"\x44\x0d\x43\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\xaa\xb9"
    ),
    # temperatures, voltage, current and state of charge, reg 0x0020, 16 registers
    b"\xd2\x03\x00\x20\x00\x10\x56\x6f": (
        b"\xd2\x03\x20\x00\x39\x00\x39\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x01\x0f\x74\x34\x03\x11\x0d\x44\x0d\x42\x00\x39\x00"
        b"\x39\x00\x01\x79\x91"
    ),
    # remaining charge, cell count, temperature sensors, cycles, reg 0x0030
    b"\xd2\x03\x00\x30\x00\x10\x57\xaa": (
        b"\xd2\x03\x20\x04\x9a\x00\x08\x00\x02\x00\x02\x00\x00\x00\x01\x00"
        b"\x01\x0d\x43\x00\x04\x02\xa0\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\xfb\xee"
    ),
}

_RESULT_CHARGING: Final[BMSSample] = _RESULT | {
    "cell_voltages": [3.396, 3.396, 3.396, 3.394, 3.395, 3.396, 3.396, 3.395],
    "voltage": 27.1,
    "current": 25.2,
    "battery_level": 78.5,
    "cycle_charge": 117.8,
    "cycle_capacity": 3192.38,
    "delta_voltage": 0.002,
    "power": 682.92,
    "battery_charging": True,
}


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


class MockRollsVBBleakClient(MockBleakClient):
    """Emulate a Rolls VB-series BMS BleakClient."""

    RESP: dict[bytes, bytes] = _RESP

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
            "MockRollsVBBleakClient",
            bytearray(self.RESP.get(bytes(data), b"")),
        )


async def test_update(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    keep_alive_fixture: bool,
) -> None:
    """Test Rolls VB-series BMS data update while charging."""

    monkeypatch.setattr(MockRollsVBBleakClient, "RESP", _RESP)
    patch_bleak_client(MockRollsVBBleakClient)

    bms = BMS(generate_ble_device(), BMSConfig(keep_alive_fixture))

    assert await bms.async_update() == _RESULT

    # query again to check already connected state
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()


async def test_update_charging(
    monkeypatch: pytest.MonkeyPatch, patch_bleak_client
) -> None:
    """Test Rolls VB-series BMS data update while charging, current is positive."""

    monkeypatch.setattr(MockRollsVBBleakClient, "RESP", _RESP_CHARGING)
    patch_bleak_client(MockRollsVBBleakClient)

    bms = BMS(generate_ble_device())

    assert await bms.async_update() == _RESULT_CHARGING

    await bms.disconnect()


@pytest.fixture(
    name="wrong_response",
    params=[
        (b"invalid_value", "invalid value"),
        (b"\xd2\x03\x02\x01\xf8\xde\xad", "wrong CRC"),
        (b"\xd2\x03", "too short"),
        (b"\xd2\x03\x02\x01\xf8\x00\x3d\x84", "incorrect length"),
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
    """Test data update with BMS returning invalid data."""

    patch_bms_timeout()

    monkeypatch.setattr(
        MockRollsVBBleakClient,
        "write_gatt_char",
        MockBleakClient.write_gatt_char,
    )

    class _InvalidClient(MockRollsVBBleakClient):
        async def write_gatt_char(
            self,
            char_specifier: BleakGATTCharacteristic | int | str | UUID,
            data: Buffer,
            response: bool | None = None,
        ) -> None:
            await MockBleakClient.write_gatt_char(self, char_specifier, data, response)
            assert self._notify_callback is not None
            self._notify_callback("_InvalidClient", bytearray(wrong_response))

    patch_bleak_client(_InvalidClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = {}
    with pytest.raises(TimeoutError):
        result = await bms.async_update()

    assert not result

    await bms.disconnect()


def test_cmd_crc() -> None:
    """Verify assembled MODBUS request frames match captured device traffic."""
    assert BMS._cmd_modbus(dev_id=0xD2, addr=0x0000, count=16) == (
        b"\xd2\x03\x00\x00\x00\x10"
        + crc_modbus(b"\xd2\x03\x00\x00\x00\x10").to_bytes(2, "little")
    )
