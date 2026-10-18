"""Test the D-powercore BMS implementation."""

from collections.abc import Buffer
from typing import Final
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.exc import BleakError
from bleak.uuids import normalize_uuid_str
import pytest

from aiobmsble import BMSConfig, BMSSample, TempSensor as TS
from aiobmsble.bms.dpwrcore_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import BMSBasicTests


@pytest.fixture(
    name="dev_name",
    params=["TBA-MockBLEDevice_C0FE", "DXB-MockBLEDevice_C0FE", "invalid"],
    ids=["TBA", "DXB", "wrong"],
)
def patch_dev_name(request: pytest.FixtureRequest) -> str:
    """Provide device name variants."""
    assert isinstance(request.param, str)
    return request.param


_RESULT_DEFS: Final[BMSSample] = {
    "voltage": 52.5,
    "current": 23.5,
    "battery_level": 45,
    "cycles": 18,
    "cycle_charge": 18.67,
    "cell_voltages": [
        3.749,
        3.761,
        3.748,
        3.759,
        3.75,
        3.757,
        3.75,
        3.759,
        3.75,
        3.757,
        3.748,
        3.763,
        3.75,
        3.752,
    ],
    "cell_count": 14,
    "delta_voltage": 0.015,
    "temperature": 21.05,
    "temp_values": [TS(21.05)],
    "cycle_capacity": 980.175,
    "power": 1233.75,
    "battery_charging": True,
    "problem": False,
    "problem_code": 0,
}


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


class MockDPwrcoreBleakClient(MockBleakClient):
    """Emulate a D-powercore BMS BleakClient."""

    PAGE_LEN = 20

    _RESP: dict[int, bytes] = {
        0x60: (
            b"\x12\x12\x3a\x05\x03\x60\x00\x0a\x02\x0d\x00\xeb\xa0\x7e\x48\xee\x2d\x00\x03\xed"
            b"\x02\x22\x0d\x0a\x03\x60\x00\x0a\x02\x0d\x00\xeb\xa0\x7e\x48\xee\x2d\x00\x03\xed"
        ),  # 2nd line only 4 bytes valid! TODO: put numbers
        0x61: (
            b"\x12\x12\x3a\x05\x03\x61\x00\x0c\x00\x12\x00\x12\x6d\x60\x0b\x7e\x8f\xdb\x18\x20"
            b"\x04\x22\x03\x91\x0d\x0a\x00\x0c\x00\x12\x00\x12\x6d\x60\x0b\x7e\x8f\xdb\x18\x20"
        ),  # 2nd line only 6 bytes valid! TODO: put numbers
        0x62: (
            b"\x12\x13\x3a\x05\x03\x62\x00\x1d\x0e\x0e\xa5\x0e\xb1\x0e\xa4\x0e\xaf\x0e\xa6\x0e"
            b"\x12\x23\xad\x0e\xa6\x0e\xaf\x0e\xa6\x0e\xad\x0e\xa4\x0e\xb3\x0e\xa6\x0e\xa8\x0a"
            b"\x03\x33\xa2\x0d\x0a\x0e\xaf\x0e\xa6\x0e\xad\x0e\xa4\x0e\xb3\x0e\xa6\x0e\xa8\x0a"
        ),  # 2nd line only 5 bytes valid TODO: put numbers
    }

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
    ) -> bytearray:
        if isinstance(char_specifier, str) and normalize_uuid_str(
            char_specifier
        ) != normalize_uuid_str("fff3"):
            return bytearray()
        cmd: int = bytes(data)[5]

        if cmd == 0x64:
            assert bytearray(data)[8:10] == bytes.fromhex("C0FE"), "incorrect password"
            assert bytearray(data)[0] == 0xE, "incorrect unlock CMD length"
            resp = bytearray(data)
            return bytearray(resp[0] | 0x80) + resp[1:]

        return bytearray(self._RESP.get(cmd, b""))

    async def write_gatt_char(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        data: Buffer,
        response: bool | None = None,
    ) -> None:
        """Issue write command to GATT."""
        data_ba = bytearray(data)
        await super().write_gatt_char(char_specifier, data, response)
        if data_ba[0] & 0x80:  # ignore ACK messages # TODO: verify those?
            return
        assert self._notify_callback is not None
        resp: bytearray = self._response(char_specifier, data)
        await self._notify_callback(  # send acknowledge
            "MockPwrcoreBleakClient", bytearray([data_ba[0] | 0x80]) + data_ba[1:]
        )
        for pos in range(1 + int((len(resp) - 1) / self.PAGE_LEN)):
            await self._notify_callback(
                "MockPwrcoreBleakClient", resp[pos * 20 :][: self.PAGE_LEN]
            )


class MockWrongCRCBleakClient(MockDPwrcoreBleakClient):
    """Emulate a D-powercore BMS BleakClient that replies with wrong CRC."""

    _RESP: dict[int, bytes] = {
        0x60: (
            b"\x12\x12\x3a\x05\x03\x60\x00\x0a\x02\x13\x00\x00\x71\xc5\x45\x8e\x3d\x00\x01\xce"
            b"\x02\x22\x0d\x0a\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        ),  # wrong CRC [0x01CE != 0x02CD] in line 1
        0x61: (
            b"\x12\x12\x3a\x05\x03\x61\x00\x0c\x00\x12\x00\x12\x6d\x60\x0b\x7e\x8f\xdb\x18\x20"
            b"\x04\x22\x02\x91\x0d\x0a\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        ),  # wrong CRC [0x02 != 0x03] in line 2
        0x62: (
            b"\x12\x13\x3a\x05\x03\x62\x00\x1d\x0e\x0e\xd7\x0e\xd6\x0e\xd6\x0e\xd5\x0e\xd5\x0e"
            b"\x12\x23\xd6\x0e\xd1\x0e\xd2\x0e\xd5\x0e\xd6\x0e\xd4\x0e\xd8\x0e\xd7\x0e\xdb\x0e"
            b"\x03\x33\x08\x0d\x0a\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        ),  # wrong CRC [0x0E != 0x0D] in line 2
    }


class MockInvalidBleakClient(MockDPwrcoreBleakClient):
    """Emulate a D-powercore BMS BleakClient replying garbage."""

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
    ) -> bytearray:
        if isinstance(char_specifier, str) and normalize_uuid_str(
            char_specifier
        ) == normalize_uuid_str("fff3"):
            return bytearray(b"invalid_value")

        return bytearray()

    async def disconnect(self) -> None:
        """Mock disconnect to raise BleakError."""
        raise BleakError


class MockProblemBleakClient(MockDPwrcoreBleakClient):
    """Emulate a D-powercore BMS BleakClient reporting a problem."""

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
    ) -> bytearray:
        if isinstance(char_specifier, str) and normalize_uuid_str(
            char_specifier
        ) != normalize_uuid_str("fff3"):
            return bytearray()
        if bytearray(data)[5] == 0x60:
            return bytearray(
                b"\x12\x12\x3a\x05\x03\x60\x00\x0a\x02\x0d\x00\xeb\xa0\x7e\x48\xee\x2d\xff\x04\xec"
                b"\x02\x22\x0d\x0a\x03\x60\x00\x0a\x02\x0d\x00\xeb\xa0\x7e\x48\xee\x2d\x00\x04\xec"
            )  # 2nd line only 4 bytes valid!

        return super()._response(char_specifier, data)


async def test_update(
    patch_bleak_client, dev_name: str, keep_alive_fixture: bool
) -> None:
    """Test D-pwercore BMS data update."""

    patch_bleak_client(MockDPwrcoreBleakClient)

    bms = BMS(generate_ble_device("cc:cc:cc:cc:cc:cc", dev_name), BMSConfig(keep_alive_fixture))

    assert await bms.async_update() == _RESULT_DEFS

    # query again to check already connected state
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()


async def test_invalid_response(
    patch_bleak_client, patch_bms_timeout, dev_name: str
) -> None:
    """Test data update with BMS returning invalid data."""

    patch_bms_timeout()
    patch_bleak_client(MockInvalidBleakClient)

    bms = BMS(generate_ble_device("cc:cc:cc:cc:cc:cc", dev_name))

    result: BMSSample = {}
    with pytest.raises(TimeoutError):
        result = await bms.async_update()

    assert not result

    await bms.disconnect()


async def test_wrong_crc(patch_bleak_client, patch_bms_timeout, dev_name: str) -> None:
    """Test data update with BMS returning invalid data."""

    patch_bms_timeout()
    patch_bleak_client(MockWrongCRCBleakClient)

    bms = BMS(generate_ble_device("cc:cc:cc:cc:cc:cc", dev_name))

    result: BMSSample = {}
    with pytest.raises(TimeoutError):
        result = await bms.async_update()

    assert not result

    await bms.disconnect()


async def test_problem_response(patch_bleak_client, dev_name: str) -> None:
    """Test D-pwercore BMS data update."""

    patch_bleak_client(MockProblemBleakClient)

    bms = BMS(generate_ble_device("cc:cc:cc:cc:cc:cc", dev_name), BMSConfig(False))

    assert await bms.async_update() == _RESULT_DEFS | {
        "problem": True,
        "problem_code": 255,
    }

    await bms.disconnect()


async def test_incomplete_msgs(monkeypatch, patch_bleak_client, dev_name: str) -> None:
    """Test D-pwercore BMS data update."""

    def _stuck_response(
        _self,
        _char_specifier: BleakGATTCharacteristic | int | str | UUID,
        _data: Buffer,
    ) -> bytearray:
        return bytearray(
            b"\x12\x12\x3a\x05\x03\x60\x00\x0a\x02\x13\x00\x00\x71\xc5\x45\x8e\x3d\x00\x02\xcd"
            b"\x02\x22\x0d\x0a\x03\x60\x00\x0a\x02\x13\x00\x00\x71\xc5\x45\x8e\x3d\x00\x02\xcd"
        )  # 2nd line only 4 bytes valid! TODO: put numbers

    monkeypatch.setattr(MockDPwrcoreBleakClient, "_response", _stuck_response)
    patch_bleak_client(MockDPwrcoreBleakClient)

    bms = BMS(generate_ble_device("cc:cc:cc:cc:cc:cc", dev_name), BMSConfig(False))

    result: BMSSample = {}
    with pytest.raises(ValueError, match="BMS data incomplete."):
        result = await bms.async_update()

    assert not result

    await bms.disconnect()
