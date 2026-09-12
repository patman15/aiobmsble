r"""Test the 123\\SmartBMS implementation."""

import asyncio
from collections.abc import Buffer, Callable, Iterable
from typing import Any, Final
from uuid import UUID

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
import pytest

from aiobmsble import BMSConfig, BMSDp, BMSSample, TempSensor as TS
from aiobmsble.bms.x123smart_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import BMSBasicTests

# one full data cycle of a 4s pack (4 cells @ 3.5 V, 24.0 C, SoC 100 %)
_PROTO_DEFS: Final[bytes] = (
    b"U_0AF0_+0014_+0014_+000A\r"  # pack 14.0 V, current 1.0 A
    b"C_01_04_2BC_12C_03_30\r"  # cell 1: 3.5 V, 24.0 C
    b"C_02_04_2BC_12C_03_30\r"
    b"C_03_04_2BC_12C_03_30\r"
    b"C_04_04_2BC_12C_03_30\r"
    b"E_000000_000000_000000_64\r"  # SoC 100 %
    b"H_5F_08E8_08FC_63_0005E9_0005DE\r"  # health 95 % (not recorded)
)

_RESULT_DEFS: Final[BMSSample] = {
    "chrg_mosfet": True,
    "dischrg_mosfet": True,
    "problem_code": 0,
    "voltage": 14.0,
    "current": 1.0,
    "battery_level": 100,
    "battery_health": 95,
    "cell_count": 4,
    "cell_voltages": [3.5, 3.5, 3.5, 3.5],
    "temp_values": [TS(24.0, TS.T.CELL)] * 4,
    "delta_voltage": 0.0,
    "temperature": 24.0,
    "power": 14.0,
    "battery_charging": True,
    "problem": False,
}


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


class Mock123SmartBleakClient(MockBleakClient):
    r"""Emulate a 123\\SmartBMS gen3 BleakClient (Nordic UART, ping-driven stream)."""

    SECRET: Final[str] = "1234"
    REQUIRE_PASS: bool = False  # if True, streaming requires a valid PIN first
    FRAME: bytes = _PROTO_DEFS
    DISABLE_E_RESP: Final[bool] = False  # if True, E! command returns NA instead of OK
    _tasks: set[asyncio.Task[None]] = set()

    def __init__(
        self,
        address_or_ble_device: BLEDevice,
        disconnected_callback: Callable[[BleakClient], None] | None,
        services: Iterable[str] | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize MockBleakClient."""
        super().__init__(
            address_or_ble_device, disconnected_callback, services, **kwargs
        )
        self._services = ["6e400001-b5a3-f393-e0a9-e50e24dcca9e"]
        self._stream: bool = False
        self._authorized: bool = not self.REQUIRE_PASS

    def _reply(self, data: bytes) -> bytes:
        """Return the notification payload for a given write."""
        result: bytes = b""

        if data == b"$":
            result = self.FRAME if self._authorized and self._stream else b""

        elif data.startswith(b"PW") and data.endswith(b"!\r"):
            if data[2:-2].decode("ascii") == self.SECRET:
                self._authorized = True
                result = b"OK\r"
            else:
                result = b"NA\r"

        elif data in (b"E!\r", b"D!\r", b"V@\r"):
            if not self._authorized:
                result = b"NA\r"
            elif data == b"E!\r" and not self.DISABLE_E_RESP:
                self._stream = True
                result = b"OK\r"
            elif data == b"D!\r":
                self._stream = False
                result = b"OK\r"
            elif data == b"V@\r":
                result = b"333_03_05_03_DBB_EF\r"

        return result

    async def _send(self, data: bytes) -> None:
        assert self._notify_callback, "write before notifications enabled"
        if payload := self._reply(data):
            self._notify_callback(BMS.uuid_rx(), bytearray(payload))
        await asyncio.sleep(0)

    async def write_gatt_char(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        data: Buffer,
        response: bool | None = None,
    ) -> None:
        """Issue write command to GATT and push the emulated response."""
        task: asyncio.Task[None] = asyncio.create_task(self._send(bytes(data)))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def disconnect(self) -> None:
        """Mock disconnect, awaiting pending notifications."""
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        await super().disconnect()


@pytest.fixture(autouse=True)
def _fast_timings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Speed up ping/warm-up/cycle timings for tests."""
    monkeypatch.setattr(BMS, "ALIVE_INTERVAL", 0.001)


async def test_update(patch_bleak_client, keep_alive_fixture: bool) -> None:
    r"""Test 123\\SmartBMS data update."""
    patch_bleak_client(Mock123SmartBleakClient)

    bms = BMS(
        generate_ble_device(),
        BMSConfig(keep_alive_fixture, secret=Mock123SmartBleakClient.SECRET),
    )

    assert await bms.async_update() == _RESULT_DEFS
    await asyncio.sleep(bms.ALIVE_INTERVAL or 0)  # wait for keep-alive ping to be sent
    await bms.async_update()  # second query to cover already-connected path
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()


@pytest.mark.parametrize(
    "secret", ["1234", "0000", ""], ids=["correct", "wrong", "missing"]
)
async def test_update_secret(
    monkeypatch: pytest.MonkeyPatch, patch_bleak_client, secret: str
) -> None:
    """Test that a wrong or missing PIN raises during connect."""
    monkeypatch.setattr(Mock123SmartBleakClient, "REQUIRE_PASS", True)
    patch_bleak_client(Mock123SmartBleakClient)

    bms = BMS(generate_ble_device(), BMSConfig(secret=secret))
    if secret == Mock123SmartBleakClient.SECRET:
        assert await bms.async_update() == _RESULT_DEFS
    else:
        with pytest.raises((ConnectionError, TimeoutError)):
            await bms.async_update()

    await bms.disconnect()


@pytest.mark.parametrize(
    ("wrong_response", "expected_exc"),
    [
        (b"", TimeoutError),
        (b"U", TimeoutError),
        (b"X" + _PROTO_DEFS[1:], ValueError),
        (b"U." + _PROTO_DEFS[2:], ValueError),
        (_PROTO_DEFS[:18] + _PROTO_DEFS[24:], ValueError),
    ],
    ids=["empty", "minimal", "wrong_TAG", "wrong_fmt", "invalid_fmt"],
)
async def test_invalid_response(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    patch_bms_timeout,
    wrong_response: bytes,
    expected_exc: type[Exception],
) -> None:
    r"""Test 123\\SmartBMS data update with invalid data."""

    monkeypatch.setattr(Mock123SmartBleakClient, "FRAME", wrong_response)
    patch_bms_timeout("x123smart_bms")
    patch_bleak_client(Mock123SmartBleakClient)

    bms = BMS(generate_ble_device(), BMSConfig(secret=Mock123SmartBleakClient.SECRET))

    result: BMSSample = {}
    with pytest.raises(expected_exc):
        result = await bms.async_update()

    assert not result
    await bms.disconnect()


async def test_no_cmd_response(
    monkeypatch: pytest.MonkeyPatch,
    patch_bms_timeout,
    patch_bleak_client,
) -> None:
    r"""Test 123\\SmartBMS does not crash if command is ignored."""

    patch_bms_timeout()
    monkeypatch.setattr(Mock123SmartBleakClient, "DISABLE_E_RESP", True)
    patch_bleak_client(Mock123SmartBleakClient)

    bms = BMS(generate_ble_device(), BMSConfig(secret=Mock123SmartBleakClient.SECRET))

    result: BMSSample = {}
    with pytest.raises(TimeoutError):
        result = await bms.async_update()

    assert not result
    await bms.disconnect()


@pytest.mark.parametrize(
    ("wrong_response", "result"),
    [
        (b"U_XXXX" + _PROTO_DEFS[6:], BMSSample(voltage=0, power=0, problem=True)),
        (b"U_123X" + _PROTO_DEFS[6:], BMSSample(voltage=0, power=0, problem=True)),
        (_PROTO_DEFS[:43] + _PROTO_DEFS[46:], BMSSample()),
    ],
    ids=["no_number", "inv_hex", "short_cell"],
)
async def test_number_range(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    wrong_response: bytes,
    result: BMSSample,
) -> None:
    r"""Test 123\\SmartBMS data update with invalid data."""

    monkeypatch.setattr(Mock123SmartBleakClient, "FRAME", wrong_response)
    patch_bleak_client(Mock123SmartBleakClient)

    bms = BMS(generate_ble_device(), BMSConfig(secret=Mock123SmartBleakClient.SECRET))

    assert await bms.async_update() == _RESULT_DEFS | result

    await bms.disconnect()


async def test_msg_too_short(
    monkeypatch: pytest.MonkeyPatch,
    patch_bms_timeout,
    patch_bleak_client,
) -> None:
    r"""Test 123\\SmartBMS does not crash if a field is outside the message length."""

    patch_bms_timeout("x123smart_bms")
    patch_bleak_client(Mock123SmartBleakClient)
    monkeypatch.setattr(  # index 5 is longer than the "E" message, so it will be skipped
        BMS, "_FIELDS", (*BMS._FIELDS, BMSDp("heater", 5, 1, False, idx=ord("E") << 8))
    )
    bms = BMS(generate_ble_device(), BMSConfig(secret=Mock123SmartBleakClient.SECRET))

    assert "heater" not in await bms.async_update()

    await bms.disconnect()
