"""Test the Wattstunde Nova BMS implementation."""

from collections.abc import Buffer
from typing import Final, cast
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
import pytest

from aiobmsble import BMSSample
from aiobmsble.bms.ws_nova_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import BMSBasicTests

BT_FRAME_SIZE = 20

_PROTO_DEFS: Final[bytearray] = bytearray(
    b"\x3a\x32\x31\x37\x34\x32\x31\x32\x30\x43\x43\x32\x30\x32\x31\x32\x32\x34\x39\x33"
    b"\x38\x38\x30\x43\x31\x32\x43\x39\x35\x32\x43\x39\x35\x32\x43\x39\x39\x32\x43\x39"
    b"\x34\x32\x30\x32\x30\x32\x30\x32\x30\x32\x30\x32\x30\x32\x30\x32\x30\x32\x30\x32"
    b"\x30\x32\x30\x32\x30\x32\x30\x32\x30\x32\x30\x32\x30\x32\x30\x32\x30\x32\x30\x32"
    b"\x30\x32\x30\x32\x30\x32\x30\x32\x30\x44\x30\x32\x32\x32\x30\x32\x30\x31\x31\x31"
    b"\x31\x31\x31\x31\x31\x33\x30\x45\x38\x41\x30\x32\x30\x32\x35\x44\x30\x35\x46\x44"
    b"\x46\x44\x46\x44\x46\x31\x32\x46\x37\x32\x30\x32\x35\x32\x34\x32\x30\x32\x35\x31"
    b"\x34\x32\x30\x32\x33\x32\x44\x36\x30\x32\x30\x32\x31\x39\x31\x32\x31\x32\x30\x32"
    b"\x33\x32\x44\x36\x30\x32\x30\x32\x31\x32\x35\x44\x30\x32\x32\x32\x36\x37\x37\x37"
    b"\x33\x36\x45\x31\x35\x31\x35\x31\x30\x31\x30\x31\x37\x31\x32\x31\x34\x31\x32\x31"
    b"\x31\x31\x31\x31\x30\x31\x39\x31\x33\x32\x30\x32\x30\x32\x30\x32\x30\x32\x30\x32"
    b"\x30\x32\x30\x32\x30\x32\x43\x33\x34\x32\x33\x32\x37\x33\x38\x41\x41\x7e"
)

_RESULT_DEFS: Final[BMSSample] = {
    "voltage": 13.015,
    "current": -1.52,
    "battery_level": 52,
    "delta_voltage": 0.005,
    "power": -19.783,
    "runtime": 262537,
    "battery_charging": False,
    "cycle_charge": 110.849,
    "cycles": 5,
    "design_capacity": 200,
    "temp_values": [9.0, 9.0, 9.0, 9.0],
    "temperature": 9.0,
    "cell_voltages": [
        3.253,
        3.253,
        3.257,
        3.252,
    ],
    "cell_count": 4,
    "cycle_capacity": 1442.7,
    "heater": False,
    "problem": False,
    "problem_code": 0,
}


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


class MockWSNovaBleakClient(MockBleakClient):
    """Emulate a Wattstunde Nova BMS BleakClient."""

    _RESP: bytearray = _PROTO_DEFS

    async def write_gatt_char(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        data: Buffer,
        response: bool | None = None,
    ) -> None:
        """Issue write command to GATT."""
        await super().write_gatt_char(char_specifier, data, response)
        assert self._notify_callback is not None
        if char_specifier != "FFF1":
            return
        for notify_data in [
            self._RESP[i : i + BT_FRAME_SIZE]
            for i in range(0, len(self._RESP), BT_FRAME_SIZE)
        ]:
            self._notify_callback("MockStreamBleakClient", notify_data)


class MockStreamBleakClient(MockWSNovaBleakClient):
    """Emulate a Wattstunde Nova BMS BleakClient sending data in stream mode."""

    _RESP_NOTIFY: bytearray = _PROTO_DEFS

    async def _notify(self) -> None:
        assert self._notify_callback is not None
        for notify_data in [
            self._RESP_NOTIFY[i : i + BT_FRAME_SIZE]
            for i in range(0, len(self._RESP_NOTIFY), BT_FRAME_SIZE)
        ]:
            self._notify_callback("MockStreamBleakClient", notify_data)


async def test_update(
    monkeypatch: pytest.MonkeyPatch, patch_bleak_client, keep_alive_fixture: bool
) -> None:
    """Test Wattstunde Nova BMS data update."""

    monkeypatch.setattr(MockWSNovaBleakClient, "_RESP", _PROTO_DEFS)
    patch_bleak_client(MockWSNovaBleakClient)

    bms = BMS(generate_ble_device(), keep_alive_fixture)

    assert await bms.async_update() == _RESULT_DEFS

    # query again to check already connected state
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()


async def test_stream_update(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test Wattstunde Nova BMS stream data update."""

    patch_bleak_client(MockStreamBleakClient)

    bms = BMS(generate_ble_device())

    assert await bms.async_update() == _RESULT_DEFS
    assert bms._msg_event.is_set() is False, "BMS does not request fresh data"
    assert "requesting BMS data" in caplog.text

    _client: MockStreamBleakClient = cast(MockStreamBleakClient, bms._client)
    caplog.clear()
    _frame: bytearray = _PROTO_DEFS.copy()
    _frame[135:139] = b"2029"  # change cycles from 5 to 9
    monkeypatch.setattr(_client, "_RESP_NOTIFY", _frame)
    await _client._notify()

    # query again to see if updated streaming data is used
    assert await bms.async_update() == _RESULT_DEFS | {"cycles": 0x9}
    assert "requesting BMS data" not in caplog.text, "BMS did not use streaming data"

    caplog.clear()
    # do not automatically send data this time
    _frame = _PROTO_DEFS.copy()
    _frame[135:139] = b"2429"  # change cycles from 9 to 73
    monkeypatch.setattr(_client, "_RESP_NOTIFY", _frame)

    # query again to see if BMS recovers if no data is sent
    assert await bms.async_update() == _RESULT_DEFS
    assert "requesting BMS data" in caplog.text, "BMS did not use streaming data"


async def test_device_info(patch_bleak_client) -> None:
    """Test that the BMS returns initialized dynamic device information."""
    patch_bleak_client(MockWSNovaBleakClient)
    bms = BMS(generate_ble_device())
    assert await bms.device_info() == {
        "serial_number": "5500724211093",
    }


@pytest.mark.parametrize(
    ("wrong_response"),
    [
        b"",
        b":~",
        b"-" + _PROTO_DEFS[1:],
        _PROTO_DEFS[:-2] + b"#",
        b":" + _PROTO_DEFS[2:],
        b":z" + _PROTO_DEFS[2:],
        b":2175" + _PROTO_DEFS[5:],
    ],
    ids=[
        "empty",
        "minimal",
        "wrong_SOF",
        "wrong_EOF",
        "wrong_length",
        "wrong_encoding",
        "wrong_type",
    ],
)
async def test_invalid_response(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    patch_bms_timeout,
    wrong_response: bytes,
) -> None:
    """Test data up date with BMS returning invalid data."""

    patch_bms_timeout()
    monkeypatch.setattr(MockWSNovaBleakClient, "_RESP", bytearray(wrong_response))
    patch_bleak_client(MockWSNovaBleakClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = {}
    with pytest.raises(TimeoutError):
        result = await bms.async_update()

    assert not result
    await bms.disconnect()


@pytest.mark.parametrize(
    ("problem_response", "expected"),
    [
        (b"\x43\x38\x32\x30", 0x0800),
        (b"\x45\x30\x33\x30", 0x0010),
        (b"\x46\x30\x32\x34", 0x0004),
        (b"\x43\x30\x32\x38", 0x0008),
    ],
    ids=["lowT_dischrg", "overC_chrg", "high", "low"],
)
async def test_problem_response(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    problem_response: bytes,
    expected: int,
) -> None:
    """Test data update with BMS returning error flags."""

    _resp: bytearray = _PROTO_DEFS.copy()
    _resp[89:93] = problem_response
    monkeypatch.setattr(MockWSNovaBleakClient, "_RESP", _resp)

    patch_bleak_client(MockWSNovaBleakClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = await bms.async_update()
    assert result == _RESULT_DEFS | {"problem": True, "problem_code": expected}

    await bms.disconnect()
