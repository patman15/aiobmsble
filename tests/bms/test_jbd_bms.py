"""Test the JBD BMS implementation."""

import asyncio
from collections.abc import Buffer
from typing import Final
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.exc import BleakError
from bleak.uuids import normalize_uuid_str
import pytest

from aiobmsble import BMSSample
from aiobmsble.bms.jbd_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import BMSBasicTests

BT_FRAME_SIZE = 20

_RESULT_DEFS: Final[BMSSample] = {
    "temp_sensors": 3,
    "voltage": 15.6,
    "current": -2.87,
    "battery_level": 100,
    "cycle_charge": 4.98,
    "design_capacity": 5,
    "cycles": 42,
    "temperature": 22.133,
    "cycle_capacity": 77.688,
    "power": -44.772,
    "battery_charging": False,
    "runtime": 6246,
    "cell_count": 4,
    "cell_voltages": [3.43, 3.425, 3.432, 3.417],
    "temp_values": [22.4, 22.3, 21.7],
    "delta_voltage": 0.015,
    "problem": False,
    "problem_code": 0,
    "balancer": 0,
    "chrg_mosfet": True,
    "dischrg_mosfet": True,
}


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


class MockJBDBleakClient(MockBleakClient):
    """Emulate a JBD BMS BleakClient."""

    HEAD_CMD = 0xDD
    CMD_INFO = bytearray(b"\xa5\x03")
    CMD_CELL = bytearray(b"\xa5\x04")
    HW_INFO = bytearray(b"\xa5\x05")

    _tasks: set[asyncio.Task[None]] = set()

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
    ) -> bytearray:

        if (
            isinstance(char_specifier, str)
            and normalize_uuid_str(char_specifier) == normalize_uuid_str("ff02")
            and bytearray(data)[0] == self.HEAD_CMD
        ):
            if bytearray(data)[1:3] == self.CMD_INFO:
                return bytearray(
                    b"\xdd\x03\x00\x1d\x06\x18\xfe\xe1\x01\xf2\x01\xf4\x00\x2a\x2c\x7c\x00\x00\x00"
                    b"\x00\x00\x00\x80\x64\x03\x04\x03\x0b\x8b\x0b\x8a\x0b\x84\xf8\x84\x77"
                )  # {'voltage': 15.6, 'current': -2.87, 'battery_level': 100, 'cycle_charge': 4.98, 'cycles': 42, 'temperature': 22.133333333333347}
            if bytearray(data)[1:3] == self.CMD_CELL:
                return bytearray(
                    b"\xdd\x04\x00\x08\x0d\x66\x0d\x61\x0d\x68\x0d\x59\xfe\x3c\x77"
                )  # {'cell#0': 3.43, 'cell#1': 3.425, 'cell#2': 3.432, 'cell#3': 3.417}
            if bytearray(data)[1:3] == self.HW_INFO:
                return bytearray(
                    b"\xdd\x05\x00\x0a\x30\x31\x32\x33\x34\x35\x36\x37\x38\x39\xfd\xe9\x77"
                )  # hardware version 0123456789
        return bytearray()

    async def _send_data(self, char_specifier, data) -> None:
        assert (
            self._notify_callback
        ), "write to characteristics but notification not enabled"

        # always send two responses, to test timeout behaviour
        for resp in (
            self._response(char_specifier, bytearray(b"\xdd\xa5\x03\x00\xff\xfd\x77")),
            self._response(char_specifier, data),
        ):
            for notify_data in [
                resp[i : i + BT_FRAME_SIZE] for i in range(0, len(resp), BT_FRAME_SIZE)
            ]:
                self._notify_callback("MockJBDBleakClient", notify_data)
            await asyncio.sleep(0.01)

    async def write_gatt_char(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        data: Buffer,
        response: bool | None = None,
    ) -> None:
        """Issue write command to GATT."""

        _task: asyncio.Task[None] = asyncio.create_task(self._send_data(char_specifier, data))
        self._tasks.add(_task)
        _task.add_done_callback(self._tasks.discard)

    async def disconnect(self) -> None:
        """Mock disconnect."""
        await asyncio.gather(*self._tasks)
        await super().disconnect()


_RESULT_CHINS: Final[BMSSample] = {
    "temp_sensors": 1,
    "voltage": 13.3,
    "current": 0.0,
    "battery_level": 65,
    "cycle_charge": 196.3,
    "design_capacity": 300,
    "cycles": 27,
    "temperature": 14.6,
    "cycle_capacity": 2610.79,
    "power": 0.0,
    "battery_charging": False,
    "cell_count": 4,
    "cell_voltages": [3.325, 3.325, 3.33, 3.323],
    "temp_values": [14.6],
    "delta_voltage": 0.007,
    "problem": False,
    "problem_code": 0,
    "balancer": 0,
    # balance_current not present: extended fields echo design_capacity/cycle_charge
    "chrg_mosfet": True,
    "dischrg_mosfet": True,
}


class MockChinsBleakClient(MockJBDBleakClient):
    """Emulate a CHINS BMS BleakClient with extended fields."""

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
    ) -> bytearray:

        if (
            isinstance(char_specifier, str)
            and normalize_uuid_str(char_specifier) == normalize_uuid_str("ff02")
            and bytearray(data)[0] == self.HEAD_CMD
        ):
            if bytearray(data)[1:3] == self.CMD_INFO:
                return bytearray(
                    b"\xdd\x03\x00\x22\x05\x32\x00\x00\x4c\xae\x75\x30\x00\x1b\x31\x2c"
                    b"\x00\x00\x00\x00\x00\x00\x29\x41\x03\x04\x01\x0b\x3d\x00\x00\x00"
                    b"\x75\x30\x4c\xae\x00\x00\xfb\x37\x77"
                )  # CHINS 12V 300Ah: extended fields with balance_current
            if bytearray(data)[1:3] == self.CMD_CELL:
                return bytearray(
                    b"\xdd\x04\x00\x08\x0c\xfd\x0c\xfd\x0d\x02\x0c\xfb\xfc\xd0\x77"
                )  # 4 cells: 3.325V, 3.325V, 3.330V, 3.323V
            if bytearray(data)[1:3] == self.HW_INFO:
                return bytearray(
                    b"\xdd\x05\x00\x12\x4a\x2d\x31\x32\x33\x30\x30\x2d\x32\x34\x31\x31"
                    b"\x31\x38\x2d\x30\x36\x39\xfc\x57\x77"
                )  # J-12300-241118-069
        return bytearray()


class MockChinsRealBalCurBleakClient(MockChinsBleakClient):
    """Emulate a CHINS BMS whose extended fields differ from standard fields."""

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
    ) -> bytearray:
        resp = super()._response(char_specifier, data)
        if (
            isinstance(char_specifier, str)
            and normalize_uuid_str(char_specifier) == normalize_uuid_str("ff02")
            and bytearray(data)[0] == self.HEAD_CMD
            and bytearray(data)[1:3] == self.CMD_INFO
        ):
            # patch balance_current (ext_start+5:+7) to differ from cycle_charge
            resp = bytearray(resp)
            resp[34] = 0x00  # balance_current = 0x0064 = 1.00 A
            resp[35] = 0x64
            # recalculate CRC: 0x10000 - sum(msg[2:-3])
            body = resp[2:-3]
            crc = 0x10000 - sum(body) & 0xFFFF
            resp[-3] = (crc >> 8) & 0xFF
            resp[-2] = crc & 0xFF
        return resp


class MockOversizedBleakClient(MockJBDBleakClient):
    """Emulate a JBD BMS BleakClient returning wrong data length."""

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
    ) -> bytearray:
        if (
            isinstance(char_specifier, str)
            and normalize_uuid_str(char_specifier) == normalize_uuid_str("ff02")
            and bytearray(data)[0] == self.HEAD_CMD
        ):
            if bytearray(data)[1:3] == self.CMD_INFO:
                return bytearray(
                    b"\xdd\x03\x00\x1d\x06\x18\xfe\xe1\x01\xf2\x01\xf4\x00\x2a\x2c\x7c\x00\x00\x00"
                    b"\x00\x00\x00\x80\x64\x03\x04\x03\x0b\x8b\x0b\x8a\x0b\x84\xf8\x84\x77"
                    b"\00\00\00\00\00\00"  # oversized response
                )  # {'voltage': 15.6, 'current': -2.87, 'battery_level': 100, 'cycle_charge': 4.98, 'cycles': 42, 'temperature': 22.133333333333347}
            if bytearray(data)[1:3] == self.CMD_CELL:
                return bytearray(
                    b"\xdd\x04\x00\x08\x0d\x66\x0d\x61\x0d\x68\x0d\x59\xfe\x3c\x77"
                    b"\00\00\00\00\00\00\00\00\00\00\00\00"  # oversized response
                )  # {'cell#0': 3.43, 'cell#1': 3.425, 'cell#2': 3.432, 'cell#3': 3.417}

        return bytearray()

    async def disconnect(self) -> None:
        """Mock disconnect to raise BleakError."""
        if self._tasks:
            await asyncio.wait(self._tasks)
        raise BleakError


def test_matcher_dict_list() -> None:
    """Test that the JBD BMS provides matcher definitions."""
    matchers = BMS.matcher_dict_list()
    assert len(matchers) > 0


async def test_update(patch_bleak_client, keep_alive_fixture: bool) -> None:
    """Test JBD BMS data update."""

    patch_bleak_client(MockJBDBleakClient)

    bms = BMS(generate_ble_device(), keep_alive_fixture)

    assert await bms.async_update() == _RESULT_DEFS

    # query again to check already connected state
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()


async def test_chins_update(patch_bleak_client, keep_alive_fixture: bool) -> None:
    """Test CHINS BMS data update with extended fields."""

    patch_bleak_client(MockChinsBleakClient)

    bms = BMS(generate_ble_device(), keep_alive_fixture)

    assert await bms.async_update() == _RESULT_CHINS

    await bms.disconnect()


async def test_chins_real_balance_current(patch_bleak_client) -> None:
    """Test CHINS BMS with genuine (non-echoed) balance_current in extended fields."""

    patch_bleak_client(MockChinsRealBalCurBleakClient)

    bms = BMS(generate_ble_device())

    result = await bms.async_update()
    assert result["balance_current"] == 1.0

    await bms.disconnect()


async def test_chins_device_info(patch_bleak_client) -> None:
    """Test that the CHINS BMS returns correct device information."""
    patch_bleak_client(MockChinsBleakClient)
    bms = BMS(generate_ble_device())
    assert await bms.device_info() == {"hw_version": "J-12300-241118-069"}
    await bms.disconnect()


async def test_device_info(patch_bleak_client) -> None:
    """Test that the BMS returns initialized dynamic device information."""
    patch_bleak_client(MockJBDBleakClient)
    bms = BMS(generate_ble_device())
    assert await bms.device_info() == {"hw_version": "0123456789"}


@pytest.fixture(
    name="wrong_response",
    params=[
        (
            bytearray(
                b"\xdd\x03\x00\x1d\x06\x18\xfe\xe1\x01\xf2\x01\xf4\x00\x2a\x2c\x7c\x00\x00\x00"
                b"\x00\x00\x00\x80\x64\x03\x04\x03\x0b\x8b\x0b\x8a\x0b\x84\xf8\x84\xdd"
            ),
            "wrong end",
        ),
        (bytearray(b"\xdd\x04\x00\x1d" + b"\x00" * 31 + b"\x77"), "wrong CRC"),
    ],
    ids=lambda param: param[1],
)
def fix_response(request: pytest.FixtureRequest) -> bytearray:
    """Return faulty response frame."""
    assert isinstance(request.param[0], bytearray)
    return request.param[0]


async def test_invalid_response(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    patch_bms_timeout,
    wrong_response: bytearray,
) -> None:
    """Test data update with BMS returning invalid data (wrong CRC)."""

    patch_bms_timeout()

    monkeypatch.setattr(
        MockJBDBleakClient, "_response", lambda _s, _c, _d: wrong_response
    )

    patch_bleak_client(MockJBDBleakClient)

    bms = BMS(generate_ble_device())

    with pytest.raises(TimeoutError):
        _result: BMSSample = await bms.async_update()

    await bms.disconnect()


async def test_oversized_response(patch_bleak_client) -> None:
    """Test data update with BMS returning oversized data, result shall still be ok."""
    patch_bleak_client(MockOversizedBleakClient)
    bms = BMS(generate_ble_device())
    assert await bms.async_update() == _RESULT_DEFS
    await bms.disconnect()


@pytest.fixture(
    name="problem_response",
    params=[
        (
            bytearray(
                b"\xdd\x03\x00\x1d\x06\x18\xfe\xe1\x01\xf2\x01\xf4\x00\x2a\x2c\x7c\x00\x00\x00"
                b"\x00\x00\x01\x80\x64\x03\x04\x03\x0b\x8b\x0b\x8a\x0b\x84\xf8\x83\x77"
            ),
            "first_bit",
        ),
        (
            bytearray(
                b"\xdd\x03\x00\x1d\x06\x18\xfe\xe1\x01\xf2\x01\xf4\x00\x2a\x2c\x7c\x00\x00\x00"
                b"\x00\x80\x00\x80\x64\x03\x04\x03\x0b\x8b\x0b\x8a\x0b\x84\xf8\x04\x77"
            ),
            "last_bit",
        ),
    ],
    ids=lambda param: param[1],
)
def prb_response(request: pytest.FixtureRequest) -> tuple[bytearray, str]:
    """Return faulty response frame."""
    assert isinstance(request.param, tuple)
    return request.param


async def test_problem_response(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    problem_response: tuple[bytearray, str],
) -> None:
    """Test data update with BMS returning invalid data (wrong CRC)."""

    def _response(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        data: Buffer,
        resp: bytearray = problem_response[0],
    ) -> bytearray:
        if (
            isinstance(char_specifier, str)
            and normalize_uuid_str(char_specifier) == normalize_uuid_str("ff02")
            and bytearray(data)[0] == self.HEAD_CMD
        ):
            if bytearray(data)[1:3] == self.CMD_INFO:
                return resp
            if bytearray(data)[1:3] == self.CMD_CELL:
                return bytearray(
                    b"\xdd\x04\x00\x08\x0d\x66\x0d\x61\x0d\x68\x0d\x59\xfe\x3c\x77"
                )  # {'cell#0': 3.43, 'cell#1': 3.425, 'cell#2': 3.432, 'cell#3': 3.417}

        return bytearray()

    monkeypatch.setattr(MockJBDBleakClient, "_response", _response)
    patch_bleak_client(MockJBDBleakClient)
    bms = BMS(generate_ble_device())

    assert await bms.async_update() == _RESULT_DEFS | {
        "problem": True,
        "problem_code": 1 << (0 if problem_response[1] == "first_bit" else 15),
    }

    await bms.disconnect()
