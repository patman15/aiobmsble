"""Test the Neey BMS implementation."""

import asyncio
from collections.abc import Buffer
from copy import deepcopy
from typing import Final, cast
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
import pytest

from aiobmsble import BMSSample
from aiobmsble.basebms import crc_sum
from aiobmsble.bms.neey_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import BMSBasicTests

BT_FRAME_SIZE = 29

_PROTO_DEFS: Final[dict[str, dict[str, bytearray]]] = {
    "v1": {
        "dev": bytearray(
            b"\x55\xaa\x11\x01\x01\x00\x64\x00\x47\x57\x2d\x32\x34\x53\x34\x45\x42\x00\x00\x00"
            b"\x00\x00\x00\x00\x48\x57\x2d\x32\x2e\x38\x2e\x30\x5a\x48\x2d\x31\x2e\x32\x2e\x33"
            b"\x56\x31\x2e\x30\x2e\x30\x00\x00\x32\x30\x32\x32\x30\x35\x33\x31\x05\x00\x00\x00"
            b"\x01\x91\x0a\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xab\xff"
        ),
        "ack": bytearray(
            b"\xaa\x55\x90\xeb\xc8\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x44\x41"
            b"\x54\x0d\x0a"
        ),  # ACKnowledge message with attached AT\r\n message (needs to be filtered)
        "cell": bytearray(
            b"\x55\xaa\x11\x01\x02\x00\x2c\x01\x38\xe7\xfa\x50\x40\xb6\x04\x51\x40\x85\x0e\x51"
            b"\x40\xf0\x05\x51\x40\xb6\x04\x51\x40\x75\x1e\x51\x40\x7f\x4f\x51\x40\x43\x02\x51"
            b"\x40\x1c\x3d\x51\x40\x78\x6a\x51\x40\xfe\x82\x51\x40\x16\x7e\x51\x40\xbc\x76\x51"
            b"\x40\x16\x7e\x51\x40\x8b\x80\x51\x40\xca\x66\x51\x40\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x35\x93\x24\x3e\x68\x94\x26\x3e\x3d\x25\x1b\x3e\x90\x8e\x1b"
            b"\x3e\xb3\xf3\x23\x3e\x2e\x91\x25\x3e\xc6\x1b\x1a\x3e\x4a\x7c\x1c\x3e\x6f\x1b\x1a"
            b"\x3e\xc2\x43\x1b\x3e\x85\x1e\x18\x3e\x4b\x27\x19\x3e\x5e\xdf\x18\x3e\xd0\xeb\x1a"
            b"\x3e\xe6\xd4\x18\x3e\x0c\xfe\x18\x3e\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\xde\x40\x51\x42\xde\x40\x51\x40\x00\x17\x08\x3c\x0a\x00\x0f\x05\x19\xa1\x82"
            b"\xc0\xc3\xf5\x48\x42\xc3\xf5\x48\x42\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x76\x2e\x09\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xb6\xff"
        ),
    },
    "v2": {
        "dev": bytearray(
            b"\x55\xaa\x11\x01\x01\x00\x64\x00\x45\x4b\x2d\x42\x32\x34\x53\x38\x45\x32\x30\x30"
            b"\x41\x00\x00\x00\x48\x57\x2d\x32\x2e\x30\x2e\x30\x53\x57\x2d\x32\x2e\x30\x2e\x30"
            b"\x56\x31\x2e\x33\x2e\x33\x36\x00\x32\x30\x32\x35\x31\x30\x31\x35\x10\x00\x00\x00"
            b"\xb3\xcf\x02\x00\x34\x34\x30\x35\x30\x31\x30\x34\x33\x39\x33\x33\x31\x32\x33\x34"
            b"\x35\x36\x45\x4b\x2d\x32\x34\x53\x32\x30\x30\x41\x00\x00\x00\x00\x00\x00\x82\xff"
        ),  # EK-B24S8E200A, HW-2.0.0, SW-2.0.0, V1.3.36
        "settings": bytearray(
            b"\x55\xaa\x11\x01\x04\x00\x96\x00\x02\x10\x00\x00\xa0\x43\xa6\x9b\x44\x3b\x6f\x12"
            b"\x83\x3a\x00\x00\x50\x40\x99\x99\x49\x40\x00\x00\x00\x41\x9a\x99\x69\x40\xcd\xcc"
            b"\x5c\x40\x66\x66\x26\x40\x9a\x99\x39\x40\x00\x00\x80\x3f\x33\x33\x33\x3f\x00\x00"
            b"\x00\x40\x00\x00\xc8\x42\x05\x00\x2c\x01\x00\x00\x48\x43\x05\x00\x78\x00\x00\x00"
            b"\xc8\x43\xe8\x03\x78\x00\x00\x00\x48\x44\xf4\x01\x00\x00\x00\x00\x70\x42\x00\x00"
            b"\x48\x42\x00\x00\x00\xc0\x00\x00\x00\x40\x00\x00\x70\x42\x00\x00\x48\x42\x00\x00"
            b"\x20\xc1\x00\x00\xa0\xc0\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\xe0\xff"
        ),
        "cell": bytearray(
            b"\x55\xaa\x11\x01\x02\x00\x2c\x01\x22\x94\x68\x51\x40\xec\xbd\x51\x40\xf2\x59"
            b"\x51\x40\x86\x7e\x51\x40\xd9\x53\x51\x40\x49\xaf\x51\x40\x3b\xc5\x51\x40\x49"
            b"\xaf\x51\x40\xe8\x96\x51\x40\x9e\x2b\x51\x40\xe1\xa1\x51\x40\x70\xf8\x51\x40"
            b"\x57\xf2\x51\x40\x01\x9d\x51\x40\x32\xa9\x51\x40\xde\xd3\x51\x40\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x59\xdb\xad\x3d\xf7\x37\xa4\x3d\xf2"
            b"\x28\x92\x3d\xa8\xa0\x9f\x3d\xd1\xb4\xa8\x3d\x6a\x56\x89\x3d\x83\xc3\x9f\x3d"
            b"\x2c\x54\x9e\x3d\xb6\xfa\x9d\x3d\x71\xe8\xa5\x3d\x48\xd3\x91\x3d\x43\xde\xa2"
            b"\x3d\x7c\x3b\x96\x3d\x57\x73\x9f\x3d\x39\xee\xb4\x3d\x60\x2c\x98\x3d\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xfd\x9d\x51\x42\xfd\x9d\x51\x40"
            b"\x00\xd2\x4c\x3c\x0b\x09\x0f\x05\x02\x66\xe0\x00\xc1\x3c\xa7\x01\x40\x68\x91"
            b"\xe1\x41\x52\xb8\xe0\x41\x33\x33\xfb\x41\xb2\x9d\x77\x42\x00\x00\xa0\x43\x31"
            b"\x68\x31\x43\x3d\xc2\x5d\x42\x00\x00\xa0\x43\x00\x00\x00\x00\xc0\x8c\xab\x40"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x40\x02\x00\x00\x00\x00\x00\x05\xff"
        ),
    },
}


_RESULT_DEFS: Final[dict[str, BMSSample]] = {
    "v1": {
        "delta_voltage": 0.008,
        "temperature": 50.24,
        "voltage": 52.313,
        "balance_current": -4.082,
        "cell_count": 16,
        "cell_voltages": [
            3.265,
            3.266,
            3.267,
            3.266,
            3.266,
            3.267,
            3.27,
            3.266,
            3.269,
            3.272,
            3.274,
            3.273,
            3.273,
            3.273,
            3.273,
            3.272,
        ],
        "balancer": True,
        "temp_values": [50.24, 50.24],
        "problem": False,
        "problem_code": 0,
    },
    "v2": {
        "balance_current": -8.055,
        "balancer": True,
        "battery_charging": True,
        "battery_level": 55.44,
        "cell_count": 16,
        "cell_voltages": [
            3.272,
            3.277,
            3.271,
            3.273,
            3.271,
            3.276,
            3.278,
            3.276,
            3.275,
            3.268,
            3.276,
            3.281,
            3.28,
            3.275,
            3.276,
            3.279,
        ],
        "current": 2.026,
        "cycle_capacity": 9296.836,
        "cycle_charge": 177.407,
        "delta_voltage": 0.013,
        "design_capacity": 320,
        "power": 106.171,
        "problem": False,
        "problem_code": 0,
        "temp_values": [28.2, 28.09, 31.4, 61.9],
        "temperature": 37.398,
        "voltage": 52.404,
    },
}


@pytest.fixture(
    name="protocol_type",
    params=["v1", "v2"],
)
def proto(request: pytest.FixtureRequest) -> str:
    """Protocol fixture."""
    assert isinstance(request.param, str)
    return request.param


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


class MockNeeyBleakClient(MockBleakClient):
    """Emulate a Neey BMS BleakClient."""

    HEAD_CMD: Final = bytearray(b"\xaa\x55\x11\x01")
    DEV_INFO: Final = bytearray(b"\x01")
    CELL_INFO: Final = bytearray(b"\x02")
    TAIL: Final = 0xFF
    _FRAME: dict[str, bytearray] = {}

    _task: asyncio.Task[None] | None = None

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
    ) -> bytearray:
        frame: Final[bytearray] = bytearray(data)
        if (
            char_specifier != "ffe1"
            or frame[19] != self.TAIL
            or not frame.startswith(self.HEAD_CMD)
        ):
            return bytearray()
        if frame[4:5] == self.CELL_INFO:
            return self._FRAME["cell"]
        if frame[4:5] == self.DEV_INFO:
            return self._FRAME["dev"]

        return bytearray()

    async def _send_confirm(self) -> None:
        assert self._notify_callback, "send confirm called but notification not enabled"
        await asyncio.sleep(0)
        self._notify_callback("MockNeeyBleakClient", self._FRAME["ack"])

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

        resp: Final[bytearray] = self._response(char_specifier, data)
        for notify_data in [
            resp[i : i + BT_FRAME_SIZE] for i in range(0, len(resp), BT_FRAME_SIZE)
        ]:
            self._notify_callback("MockNeeyBleakClient", notify_data)


class MockStreamBleakClient(MockNeeyBleakClient):
    """Mock Neey BMS that already sends battery data (no request required)."""

    async def _send_all(self) -> None:
        assert (
            self._notify_callback
        ), "send_all frames called but notification not enabled"
        for resp in self._FRAME.values():
            self._notify_callback("MockNeeyBleakClient", resp)
            await asyncio.sleep(0)

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
        if bytearray(data).startswith(
            self.HEAD_CMD + self.DEV_INFO
        ):  # send all responses as a series
            self._task = asyncio.create_task(self._send_all())
            await asyncio.sleep(0)  # yield control to allow task to start

    async def disconnect(self) -> None:
        """Mock disconnect and wait for send task."""
        if self._task and not self._task.done():
            await asyncio.wait_for(self._task, 0.1)
            assert self._task.done(), "send task still running!"
        await super().disconnect()


class MockOversizedBleakClient(MockNeeyBleakClient):
    """Emulate a Neey BMS BleakClient returning wrong data length."""

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
    ) -> bytearray:
        return super()._response(char_specifier, data) + bytearray(6)


async def test_update(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    protocol_type: str,
    keep_alive_fixture: bool,
) -> None:
    """Test Neey BMS data update."""

    monkeypatch.setattr(MockNeeyBleakClient, "_FRAME", _PROTO_DEFS[protocol_type])
    patch_bleak_client(MockNeeyBleakClient)
    bms = BMS(generate_ble_device(), keep_alive_fixture)

    assert await bms.async_update() == _RESULT_DEFS[protocol_type]

    # query again to check already connected state
    assert await bms.async_update() == _RESULT_DEFS[protocol_type]
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()


async def test_device_info(
    monkeypatch: pytest.MonkeyPatch, patch_bleak_client, protocol_type: str
) -> None:
    """Test that the BMS returns initialized dynamic device information."""
    monkeypatch.setattr(MockNeeyBleakClient, "_FRAME", _PROTO_DEFS[protocol_type])
    patch_bleak_client(MockNeeyBleakClient)
    bms = BMS(generate_ble_device())
    assert (
        await bms.device_info()
        == {
            "model": "GW-24S4EB",
            "sw_version": "ZH-1.2.3",
            "hw_version": "HW-2.8.0",
        }
        if protocol_type == "v1"
        else {
            "model": "EK-B24S8E200A",
            "sw_version": "SW-2.0.0",
            "hw_version": "HW-2.0.0",
        }
    )


async def test_stream_update(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    protocol_type: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test Neey BMS data update."""

    _frames: dict[str, bytearray] = deepcopy(_PROTO_DEFS[protocol_type])
    monkeypatch.setattr(MockStreamBleakClient, "_FRAME", _frames)
    patch_bleak_client(MockStreamBleakClient)

    bms = BMS(generate_ble_device())

    assert await bms.async_update() == _RESULT_DEFS[protocol_type]
    assert bms._msg_event.is_set() is False
    assert "requesting cell info" in caplog.text

    _client: MockStreamBleakClient = cast(MockStreamBleakClient, bms._client)
    _cell_frame: bytearray = _frames["cell"]
    _cell_frame[216] = 0x8  # modify data to ensure new read
    _cell_frame[-2] = crc_sum(_cell_frame[:-2])
    caplog.clear()
    await _client._send_all()

    # query again to see if updated streaming data is used
    assert await bms.async_update() == _RESULT_DEFS[protocol_type] | {
        "problem": True,
        "problem_code": 0x8,
        "balancer": False,
    }
    assert bms._msg_event.is_set() is False, "BMS does not request fresh data"
    assert "requesting cell info" not in caplog.text, "BMS did not use streaming data"


@pytest.fixture(
    name="wrong_response",
    params=[
        (_PROTO_DEFS["v1"]["dev"][:-2] + b"\x00\xff", "wrong_CRC"),
        (bytearray(b"\x55\xaa\xeb\x90\x05") + bytes(295), "wrong_frame_type"),
        (_PROTO_DEFS["v1"]["dev"][:-1] + b"\x00", "wrong_EOF"),
    ],
    ids=lambda param: param[1],
)
def faulty_response(request: pytest.FixtureRequest) -> bytearray:
    """Return faulty response frame."""
    assert isinstance(request.param[0], bytearray)
    return request.param[0]


async def test_invalid_response(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    patch_bms_timeout,
    wrong_response: bytearray,
) -> None:
    """Test data up date with BMS returning invalid data."""

    patch_bms_timeout()
    monkeypatch.setattr(
        MockNeeyBleakClient, "_response", lambda _s, _c, _d: wrong_response
    )
    patch_bleak_client(MockNeeyBleakClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = {}
    with pytest.raises(TimeoutError):
        result = await bms.async_update()

    assert not result
    await bms.disconnect()


async def test_oversized_response(
    monkeypatch: pytest.MonkeyPatch, patch_bleak_client
) -> None:
    """Test data update with BMS returning oversized data, result shall still be ok."""

    monkeypatch.setattr(MockOversizedBleakClient, "_FRAME", _PROTO_DEFS["v1"])

    patch_bleak_client(MockOversizedBleakClient)

    bms = BMS(generate_ble_device())

    assert await bms.async_update() == _RESULT_DEFS["v1"]

    await bms.disconnect()


async def test_non_stale_data(
    monkeypatch: pytest.MonkeyPatch, patch_bleak_client, patch_bms_timeout
) -> None:
    """Test if BMS class is reset if connection is reset."""

    patch_bms_timeout()

    monkeypatch.setattr(MockNeeyBleakClient, "_FRAME", _PROTO_DEFS["v1"])

    orig_response = MockNeeyBleakClient._response
    monkeypatch.setattr(
        MockNeeyBleakClient,
        "_response",
        lambda _s, _c, _d: bytearray(b"\x55\xaa\xeb\x90\x05") + bytearray(10),
    )  # invalid frame type (0x5)

    patch_bleak_client(MockNeeyBleakClient)

    bms = BMS(generate_ble_device())

    # run an update which provides half a valid message and then disconnects
    result: BMSSample = {}
    with pytest.raises(TimeoutError):
        result = await bms.async_update()
    assert not result
    await bms.disconnect()

    # restore working BMS responses and run a test again to see if stale data is kept
    monkeypatch.setattr(MockNeeyBleakClient, "_response", orig_response)

    assert await bms.async_update() == _RESULT_DEFS["v1"]


@pytest.fixture(
    name="problem_response",
    params=[
        (0x01, "Wrong cell count"),
        # (0x02, "AcqLine Res test"),
        (0x03, "AcqLine Res exceed"),
        # (0x04, "Systest Completed"),
        # (0x05, "Balancing"),
        # (0x06, "Balancing finished"),
        (0x07, "Low voltage"),
        (0x08, "System Overtemp"),
        (0x09, "Host fails"),
        (0x0A, "Low battery voltage - balancing stopped"),
        (0x0B, "Temperature too high - balancing stopped"),
        # (0x0C, "Self-test completed"),
    ],
    ids=lambda param: param[1],
)
def prb_response(request: pytest.FixtureRequest) -> tuple[int, str]:
    """Return faulty response frame."""
    assert isinstance(request.param, tuple)
    return request.param


async def test_problem_response(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    problem_response: tuple[int, str],
) -> None:
    """Test data update with BMS returning system problem flags."""

    def frame_update(data: bytearray, update: int) -> None:
        data[-2] = (data[-2] + update - data[216]) & 0xFF
        data[216] = update

    protocol_def: dict[str, bytearray] = deepcopy(_PROTO_DEFS["v1"])
    # set error flags in the copy

    frame_update(protocol_def["cell"], problem_response[0])

    monkeypatch.setattr(MockNeeyBleakClient, "_FRAME", protocol_def)

    patch_bleak_client(MockNeeyBleakClient)

    bms = BMS(generate_ble_device(), False)

    assert await bms.async_update() == _RESULT_DEFS["v1"] | {
        "problem": True,
        "problem_code": problem_response[0],
        "balancer": False,
    }

    await bms.disconnect()
