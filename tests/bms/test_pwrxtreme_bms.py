"""Test the PowerXtreme BMS implementation."""

import asyncio
from collections.abc import Buffer
from typing import Final
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
import pytest

from aiobmsble import BMSConfig, BMSInfo, BMSSample, TempSensor as TS
from aiobmsble.bms.pwrxtreme_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import BMSBasicTests

BT_FRAME_SIZE = 200

_PROTO_DEFS: Final[dict[int, bytes]] = {
    0x5E: (  # PowerXtreme X210
        b"\x5e\x32\x43\x33\x34\x30\x30\x30\x30\x45\x30\x46\x46\x46\x46\x46\x46\x32\x30\x33\x43\x30"
        b"\x33\x30\x30\x30\x32\x30\x30\x36\x33\x30\x30\x37\x38\x30\x42\x30\x30\x30\x30\x30\x31\x30"
        b"\x30\x30\x43\x30\x44\x30\x42\x30\x44\x30\x43\x30\x44\x30\x39\x30\x44\x30\x30\x30\x30\x30"
        b"\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30"
        b"\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30"
        b"\x35\x45\x35"
    ),
}


_RESULT_DEFS: Final[dict[int, BMSSample]] = {
    0x5E: {
        "voltage": 13.356,
        "current": -3.2,
        "battery_level": 99,
        "cycle_charge": 212.0,
        "cycles": 2,
        "temp_values": [TS(20.45, TS.T.GENERIC)],
        "problem_code": 0,
        "cell_voltages": [3.34, 3.339, 3.34, 3.337],
        "battery_charging": False,
        "cell_count": 4,
        "delta_voltage": 0.003,
        "temperature": 20.45,
        "cycle_capacity": 2831.472,
        "power": -42.739,
        "problem": False,
        "runtime": 238500,
    }
}

_DEV_INFO_DEFS: Final[BMSInfo] = {
    "fw_version": "mock_FW_version",
    "hw_version": "mock_HW_version",
    "sw_version": "mock_SW_version",
    "manufacturer": "mock_manufacturer",
    "model": "X210-24092528",
    "serial_number": "EM01234567890123",
}


@pytest.fixture(name="protocol_type", params=_PROTO_DEFS.keys())
def proto(request: pytest.FixtureRequest) -> int:
    """Protocol fixture."""
    assert isinstance(request.param, int)
    return request.param


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


class MockPwrXtremeBleakClient(MockBleakClient):
    """Emulate a PowerXtreme BMS BleakClient."""

    _RESP: bytes = _PROTO_DEFS[0x5E]

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
    ) -> bytearray:
        assert char_specifier == "fff2"

        return bytearray(self._RESP)

    async def write_gatt_char(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        data: Buffer,
        response: bool | None = None,
    ) -> None:
        """Issue write command to GATT."""

        assert (
            self._notify_callback
        ), "write to characteristics but notification not enabled"

        match bytes(data):
            case b"<N:NA>":
                self._notify_callback("MockPwrXtremeBleakClient", b"<N:X210-24092528>")
            case b"<M:SR>":
                self._notify_callback(
                    "MockPwrXtremeBleakClient", b"<M:EM01234567890123>"
                )
            case b"<B:ST>":
                self._notify_callback("MockPwrXtremeBleakClient", b"<B:AN>")
            case b"<H:ST>":
                self._notify_callback("MockPwrXtremeBleakClient", b"<H:NO>")

        await asyncio.sleep(0)
        resp: Final[bytearray] = self._response(char_specifier, data)
        for notify_data in [
            resp[i : i + BT_FRAME_SIZE] for i in range(0, len(resp), BT_FRAME_SIZE)
        ]:
            self._notify_callback("MockPwrXtremeBleakClient", notify_data)


async def test_device_info(patch_bleak_client) -> None:
    """Test that the BMS returns initialized dynamic device information."""
    patch_bleak_client(MockPwrXtremeBleakClient)
    bms = BMS(generate_ble_device())
    assert await bms.device_info() == _DEV_INFO_DEFS


async def test_device_info_timeout(
    monkeypatch: pytest.MonkeyPatch, patch_bleak_client
) -> None:
    """Test that a timeout fetching dynamic device information is ignored."""
    patch_bleak_client(MockPwrXtremeBleakClient)
    bms = BMS(generate_ble_device())

    async def await_msg(data: bytes) -> None:
        if data == b"<M:SR>":
            raise TimeoutError
        bms._msg = b"N:X210-24092528"

    monkeypatch.setattr(bms, "_await_msg", await_msg)

    assert await bms.device_info() == _DEV_INFO_DEFS | {
        "serial_number": "mock_serial_number"
    }


async def test_device_info_decode_error(
    monkeypatch: pytest.MonkeyPatch, patch_bleak_client
) -> None:
    """Test that invalid dynamic device information is ignored."""
    patch_bleak_client(MockPwrXtremeBleakClient)
    bms = BMS(generate_ble_device())

    async def await_msg(data: bytes) -> None:
        bms._msg = b"M:\xff" if data == b"<M:SR>" else b"N:X210-24092528"

    monkeypatch.setattr(bms, "_await_msg", await_msg)

    assert await bms.device_info() == _DEV_INFO_DEFS | {
        "serial_number": "mock_serial_number"
    }


async def test_alive(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that the keep-alive request resets its control state."""
    bms = BMS(generate_ble_device())

    async def await_msg(_data: bytes) -> None:
        return

    bms._msg_event.set()
    monkeypatch.setattr(bms, "_await_msg", await_msg)
    await bms._alive()

    assert bms._ctrl_proto == b""
    assert not bms._msg_event.is_set()


async def test_alive_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that a keep-alive timeout is suppressed."""
    bms = BMS(generate_ble_device())

    async def await_msg(_data: bytes) -> None:
        raise TimeoutError

    monkeypatch.setattr(bms, "_await_msg", await_msg)
    await bms._alive()


async def test_update(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    protocol_type: int,
    keep_alive_fixture: bool,
) -> None:
    """Test PowerXtreme BMS data update."""

    monkeypatch.setattr(MockPwrXtremeBleakClient, "_RESP", _PROTO_DEFS[protocol_type])
    patch_bleak_client(MockPwrXtremeBleakClient)

    bms = BMS(generate_ble_device(), BMSConfig(keep_alive_fixture))

    assert await bms.async_update() == _RESULT_DEFS[protocol_type]

    # query again to check already connected state
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()
