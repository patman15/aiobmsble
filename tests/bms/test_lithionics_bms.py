"""Test the Lithionics BMS implementation."""

import asyncio
from collections.abc import Awaitable, Callable
import contextlib
from typing import Final
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
import pytest

from aiobmsble import BMSConfig, BMSSample, TempSensor as TS
from aiobmsble.bms.lithionics_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import BMSBasicTests

BT_FRAME_SIZE = 20

_PROTO_DEFS: Final[dict[str, bytes]] = {
    "stream": (
        b"ERROR\r\n"
        b"1399,350,350,350,349,55,48,-3,99,000000\r\n"
        b"&,1,319,006391,0136,2300,FF05,8700\r\n"
    ),
    "fixed_stream": (
        b"1,01594,0525,048,048,0,00000,000000,080,000100\r\n"
        b"&,1,0525,0525,078,2,075845,0576,3300,FF03,0000,00,327,328,328\r\n"
    ),
}

_RESULT_DEFS: Final[dict[str, BMSSample]] = {
    "stream": {
        "voltage": 13.99,
        "current": -3.0,
        "battery_level": 99,
        "problem_code": 0,
        "cell_count": 4,
        "cell_voltages": [3.5, 3.5, 3.5, 3.49],
        "temp_values": [TS(12.778), TS(8.889)],
        "temperature": 10.834,
        "cycle_charge": 319.0,
        "total_charge": 6391,
        "cycle_capacity": 4462.81,
        "delta_voltage": 0.01,
        "power": -41.97,
        "battery_charging": False,
        "runtime": 382800,
        "problem": False,
    },
    "fixed_stream": {
        "voltage": 52.5,
        "current": 0.0,
        "power": 0.0,
        "battery_level": 48,
        "battery_charging": False,
        "cycle_charge": 159.4,
        "cycle_capacity": 8368.5,
        "temp_values": [TS(26.667)],
        "temperature": 26.667,
        "problem_code": 0,
        "problem": False,
    },
}


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


class MockLithionicsBleakClient(MockBleakClient):
    """Emulate a Lithionics BMS BleakClient."""

    _RESP: bytes = _PROTO_DEFS["stream"]
    _task: asyncio.Task[None] | None = None

    async def _notify(self) -> None:
        """Notify function."""
        assert (
            self._notify_callback
        ), "write to characteristics but notification not enabled"

        while True:
            for notify_data in [
                self._RESP[i : i + BT_FRAME_SIZE]
                for i in range(0, len(self._RESP), BT_FRAME_SIZE)
            ]:
                self._notify_callback(
                    "MockLithionicsBleakClient", bytearray(notify_data)
                )
            await asyncio.sleep(0)

    async def start_notify(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        callback: Callable[
            [BleakGATTCharacteristic, bytearray], None | Awaitable[None]
        ],
        **kwargs,
    ) -> None:
        """Mock start_notify."""
        await super().start_notify(char_specifier, callback)
        self._task = asyncio.create_task(self._notify(), name="send_loop")
        await asyncio.sleep(0)  # yield control to allow task to start

    async def disconnect(self) -> None:
        """Mock disconnect and wait for send task."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        await super().disconnect()


@pytest.fixture(name="protocol_type", params=_PROTO_DEFS.keys())
def fixture_protocol_type(request: pytest.FixtureRequest) -> str:
    """Return each supported Lithionics protocol variant."""
    return request.param


async def test_update(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    keep_alive_fixture: bool,
    protocol_type: str,
) -> None:
    """Test Lithionics BMS data update for both stream variants."""
    monkeypatch.setattr(MockLithionicsBleakClient, "_RESP", _PROTO_DEFS[protocol_type])
    patch_bleak_client(MockLithionicsBleakClient)

    device_name = "Lithionics" if protocol_type == "stream" else "Li3-022724009"
    bms = BMS(generate_ble_device(name=device_name), BMSConfig(keep_alive_fixture))

    assert await bms.async_update() == _RESULT_DEFS[protocol_type]

    # query again to check already connected state
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()


@pytest.fixture(
    name="invalid_stream",
    params=[
        b"",
        b"\r\n",
        b"ERROR\r\n",
        b"1,2,3\r\n",
        b"&,\r\n",
        b"&,1,2\r\n",
        b"text\r\n",
    ],
    ids=[
        "empty",
        "blank_line",
        "error_only",
        "short_primary",
        "short_status",
        "status_only",
        "unknown_line",
    ],
)
def fixture_invalid_stream(request: pytest.FixtureRequest) -> bytes:
    """Return invalid stream data payload."""
    assert isinstance(request.param, bytes)
    return request.param


# def test_decode_data_stream_fields() -> None:
#     """Test the Lithionics stream field decoder for primary and status data."""
#     primary = ["1399", "350", "350", "350", "349", "55", "48", "-3", "99", "000000"]
#     status = ["&,", "1", "319", "006391", "0136", "2300", "FF05", "8700"]

#     assert BMS._decode_data(BMS._FIELDS, {0: primary})["voltage"] == 13.99
#     assert BMS._decode_data(BMS._FIELDS, {1: status})["cycle_charge"] == 319.0
#     assert BMS._decode_data(BMS._FIELDS, {1: status})["total_charge"] == 6391


async def test_invalid_response(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    patch_bms_timeout,
    invalid_stream: bytes,
) -> None:
    """Test data update with invalid stream data."""
    patch_bms_timeout("lithionics_bms")
    monkeypatch.setattr(MockLithionicsBleakClient, "_RESP", invalid_stream)
    patch_bleak_client(MockLithionicsBleakClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = {}
    with pytest.raises(TimeoutError):
        result = await bms.async_update()

    assert not result
    await bms.disconnect()


async def test_invalid_frame_length(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    patch_bms_timeout,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test handling of frames exceeding BLE_MAX_ATTR_SIZE in notification handler."""
    patch_bms_timeout("lithionics_bms")
    monkeypatch.setattr(
        MockLithionicsBleakClient, "_RESP", b"A" * (BMS.BLE_MAX_ATTR_SIZE + 1)
    )
    patch_bleak_client(MockLithionicsBleakClient)

    bms = BMS(generate_ble_device())
    caplog.clear()
    result: BMSSample = {}

    with pytest.raises(TimeoutError):
        result = await bms.async_update()

    assert not result
    assert len(bms._frame) == 0
    assert "invalid frame" in caplog.text

    await bms.disconnect()


def test_uuid_tx_not_implemented() -> None:
    """Test that TX UUID is intentionally not implemented for stream-only protocol."""
    with pytest.raises(NotImplementedError):
        BMS.uuid_tx()


async def test_non_numeric_field_raises_value_error(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
) -> None:
    """Test that a non-numeric (but correctly shaped) primary field raises ValueError."""
    stream: bytes = (
        b"1x,350,350,350,349,55,48,-3,99,000000\r\n"
        b"&,1,319,006391,0136,2300,FF05,8700\r\n"
    )
    monkeypatch.setattr(MockLithionicsBleakClient, "_RESP", stream)
    patch_bleak_client(MockLithionicsBleakClient)

    bms = BMS(generate_ble_device(name="Lithionics"))

    with pytest.raises(ValueError, match="BMS data incomplete"):
        await bms.async_update()

    await bms.disconnect()


@pytest.mark.parametrize(
    ("status_line", "expected"),
    [
        ("&,", {}),
        ("&,1,2", {"cycle_charge": 2.0}),
    ],
    ids=["status_min_fields", "status_remaining_ah_only"],
)
async def test_status_field_variants(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    patch_bms_timeout,
    status_line: str,
    expected: BMSSample,
) -> None:
    """Test status parsing variants with optional fields."""
    stream: bytes = (
        b"1399,350,350,350,349,55,48,-3,99,000000\r\n" + status_line.encode() + b"\r\n"
    )
    monkeypatch.setattr(MockLithionicsBleakClient, "_RESP", stream)
    patch_bleak_client(MockLithionicsBleakClient)

    bms = BMS(generate_ble_device(name="Lithionics"))
    if expected:
        result: BMSSample = await bms.async_update()
    else:
        patch_bms_timeout("lithionics_bms")
        with pytest.raises(TimeoutError):
            await bms.async_update()
        await bms.disconnect()
        return

    for key, value in expected.items():
        assert result.get(key) == value

    await bms.disconnect()


async def test_fixed_length_status_code_masked(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
) -> None:
    """A real fault bit must surface, the benign idle value must not."""
    monkeypatch.setattr(
        MockLithionicsBleakClient,
        "_RESP",
        _PROTO_DEFS["fixed_stream"].replace(b",000100\r\n", b",000020\r\n"),
    )
    patch_bleak_client(MockLithionicsBleakClient)

    bms = BMS(generate_ble_device(name="Li3-022724009"))
    result: BMSSample = await bms.async_update()

    assert result.get("problem_code") == 0x000020  # over-current
    assert result.get("problem") is True

    await bms.disconnect()
