"""Test the Rolls VB-series BMS implementation."""

from collections.abc import Buffer
from typing import Final
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
import pytest

from aiobmsble import BMSConfig, BMSSample
from aiobmsble.basebms import crc_modbus
from aiobmsble.bms.rollsvb_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import BMSBasicTests

# real device responses, captured with Apple PacketLogger while the vendor's
# "Rolls LFP Connect" app queried the battery over BLE
_RESP: Final[dict[bytes, bytes]] = {
    # cell voltages, reg 0x0000, 16 registers (8 cells, rest zero padding)
    b"\xd2\x03\x00\x00\x00\x10\x57\xa5": (
        b"\xd2\x03\x20\x0c\xf2\x0c\xf2\x0c\xf2\x0c\xed\x0c\xf1\x0c\xf1\x0c\xee\x0c\xf0"
        b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x4c\x08"
    ),
    # pack voltage + current, reg 0x0028, 2 registers -- charging at 0.9A
    b"\xd2\x03\x00\x28\x00\x02\x57\xa0": (
        b"\xd2\x03\x04\x01\x09\x75\x27\xaf\x8a"
    ),
    # state of charge, reg 0x002a, 1 register -- 50.4%
    b"\xd2\x03\x00\x2a\x00\x01\xb6\x61": (b"\xd2\x03\x02\x01\xf8\x3d\x84"),
}

_RESP_IDLE: Final[dict[bytes, bytes]] = _RESP | {
    # pack voltage + current, reg 0x0028, 2 registers -- idle, 0.0A
    b"\xd2\x03\x00\x28\x00\x02\x57\xa0": (b"\xd2\x03\x04\x01\x08\x75\x30\xbe\x44")
}

_RESULT: Final[BMSSample] = {
    "cell_voltages": [3.314, 3.314, 3.314, 3.309, 3.313, 3.313, 3.31, 3.312],
    "voltage": 26.5,
    "current": 0.9,
    "battery_level": 50.4,
    "cell_count": 8,
    "delta_voltage": 0.005,
    "power": 23.85,
    "battery_charging": True,
    "problem": False,
}

_RESULT_IDLE: Final[BMSSample] = _RESULT | {
    "voltage": 26.4,
    "current": 0.0,
    "power": 0.0,
    "battery_charging": False,
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


async def test_update_idle(monkeypatch: pytest.MonkeyPatch, patch_bleak_client) -> None:
    """Test Rolls VB-series BMS data update while idle (no charge/discharge)."""

    monkeypatch.setattr(MockRollsVBBleakClient, "RESP", _RESP_IDLE)
    patch_bleak_client(MockRollsVBBleakClient)

    bms = BMS(generate_ble_device())

    assert await bms.async_update() == _RESULT_IDLE

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
