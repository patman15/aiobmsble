"""Test the V-TAC TBESS BMS implementation."""

from collections.abc import Awaitable, Callable
from typing import Final, cast
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
import pytest

from aiobmsble import BMSConfig, BMSSample, TempSensor as TS
from aiobmsble.bms.tbess_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import BMSBasicTests

_PROTO_DEFS: Final[dict[str, bytes]] = {
    "sum": (
        b"\xef\x01\x73\x46\x38\x35\x42\x31\x42\x36\x32\x33\x33\x42\x43\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x55\x00\x02\x02\x02\x14\xaa\xff\x5a\x15\xe0\x16\x57\x0f\xbe\x1b\x86\x27\x10\x08\x48"
        b"\x16\xd0\x0b\x54\x11\xd0\x0c\xed\x0c\xe8\x01\x0b\x02\x0d\x0b\x94\x0b\x8d\x01\x02\x02\x04"
        b"\x0b\xa2\x0b\x9d\x01\x01\x02\x01\x0b\xa9\x0b\xa8\x02\x01\x01\x01\x00\x1b\x00\x1a\xc0\x00"
        b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x30\xfb\x00\x00\x30\x00\xec"
        b"\x84\x16"
    ),
    "pack1": (
        b"\xef\x01\xdb\x35\x31\x34\x31\x31\x30\x39\x32\x32\x36\x30\x35\x30\x31\x30\x30\x35\x38\x34"
        b"\x00\x61\x00\x14\xac\xfd\x7d\x02\xbb\x4e\x46\x10\x0c\xec\x0c\xeb\x0c\xec\x0c\xec\x0c\xeb"
        b"\x0c\xed\x0c\xea\x0c\xec\x0c\xeb\x0c\xec\x0c\xee\x0c\xec\x0c\xea\x0c\xec\x0c\xec\x0c\xeb"
        b"\x04\x00\xe7\x00\xe9\x00\xe7\x00\xe7\x00\xfd\x00\xf7\x00\x1b\x18\x6f\x18\xd6\x07\x4d\x00"
        b"\x00\x00\x00\x03\xe8\x6f\xf2\x6d\x60\x0c\xee\x0b\x0c\xea\x07\x00\x04\x00\xe9\x02\x00\xe7"
        b"\x01\x00\x02\x00\x00\x18\xd6\x00\x00\x18\x6f\xd8\x04\x16"
    ),
    "pack2": (
        b"\xef\x02\xdb\x35\x31\x34\x31\x31\x30\x39\x32\x32\x36\x30\x35\x30\x31\x30\x31\x32\x33\x32"
        b"\x00\x61\x00\x14\xac\xfc\xf4\x02\xc4\x4e\xfd\x10\x0c\xec\x0c\xea\x0c\xed\x0c\xed\x0c\xea"
        b"\x0c\xec\x0c\xea\x0c\xed\x0c\xea\x0c\xeb\x0c\xee\x0c\xec\x0c\xea\x0c\xec\x0c\xed\x0c\xea"
        b"\x04\x00\xe5\x00\xe6\x00\xe4\x00\xe2\x00\xfe\x00\xf2\x00\x1a\x17\x91\x18\x25\x06\x13\x00"
        b"\x00\x00\x00\x03\xe8\x6f\x7d\x6d\x60\x0c\xee\x0b\x0c\xea\x02\x00\x04\x00\xe6\x02\x00\xe2"
        b"\x04\x00\x04\x00\x00\x18\x25\x00\x00\x17\x91\xd8\xc2\x16"
    ),
    "config": (
        b"\xef\x01\xdc\x35\x31\x34\x31\x31\x30\x39\x32\x32\x36\x30\x35\x30\x31\x30\x30\x35\x38\x34"
        b"\x00\x2d\x00\x10\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x04\x00"
        b"\x00\x00\x00\x00\x00\x00\x06\x40\x00\x00\x00\x00\x02\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\xfa\xd4\x16"
    ),
    "info": (
        b"\xef\x01\xd0\x35\x31\x34\x31\x31\x30\x39\x32\x32\x36\x30\x35\x30\x31\x30\x30\x35\x38\x34"
        b"\x00\x88\x00\x6d\x60\x34\x35\x30\x33\x30\x30\x38\x39\x37\x00\x00\x00\x35\x31\x34\x31\x31"
        b"\x30\x39\x31\x20\x32\x36\x30\x35\x30\x37\x30\x30\x36\x37\x00\x35\x31\x34\x31\x31\x30\x39"
        b"\x32\x32\x36\x30\x35\x30\x31\x30\x30\x35\x38\x34\x00\x53\x54\x4d\x33\x32\x46\x31\x30\x33"
        b"\x56\x45\x54\x36\x00\x00\x43\x4e\x32\x30\x30\x47\x41\x30\x36\x2d\x34\x38\x32\x30\x30\x2d"
        b"\x31\x30\x41\x00\x2a\x30\x01\x00\x00\x01\x43\x4e\x31\x30\x34\x38\x32\x30\x30\x31\x36\x53"
        b"\x5a\x54\x42\x32\x35\x30\x33\x30\x33\x30\x30\x31\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x00\x00\x00\xe3\xac\x16"
    ),
}

_RESULT_DEFS: Final[BMSSample] = {
    "packs": [
        {
            "voltage": 52.92,
            "current": -6.43,
            "battery_level": 69.9,
            "battery_health": 100.0,
            "cycles": 27,
            "cycle_charge": 6358,
            "cell_voltages": [
                3.308,
                3.307,
                3.308,
                3.308,
                3.307,
                3.309,
                3.306,
                3.308,
                3.307,
                3.308,
                3.31,
                3.308,
                3.306,
                3.308,
                3.308,
                3.307,
            ],
            "temp_values": [
                TS(23.1, TS.T.CELL),
                TS(23.3, TS.T.CELL),
                TS(23.1, TS.T.CELL),
                TS(23.1, TS.T.CELL),
                TS(25.3, TS.T.MOSFET),
                TS(24.7, TS.T.AMBIENT),
            ],
            "cell_count": 16,
            "delta_voltage": 0.004,
        },
        {
            "voltage": 52.92,
            "current": -7.8,
            "battery_level": 70.8,
            "battery_health": 100.0,
            "cycles": 26,
            "cycle_charge": 6181,
            "cell_voltages": [
                3.308,
                3.306,
                3.309,
                3.309,
                3.306,
                3.308,
                3.306,
                3.309,
                3.306,
                3.307,
                3.31,
                3.308,
                3.306,
                3.308,
                3.309,
                3.306,
            ],
            "temp_values": [
                TS(22.9, TS.T.CELL),
                TS(23.0, TS.T.CELL),
                TS(22.8, TS.T.CELL),
                TS(22.6, TS.T.CELL),
                TS(25.4, TS.T.MOSFET),
                TS(24.2, TS.T.AMBIENT),
            ],
            "cell_count": 16,
            "delta_voltage": 0.004,
        },
    ],
    "cell_voltages": [
        3.308,
        3.307,
        3.308,
        3.308,
        3.307,
        3.309,
        3.306,
        3.308,
        3.307,
        3.308,
        3.31,
        3.308,
        3.306,
        3.308,
        3.308,
        3.307,
        3.308,
        3.306,
        3.309,
        3.309,
        3.306,
        3.308,
        3.306,
        3.309,
        3.306,
        3.307,
        3.31,
        3.308,
        3.306,
        3.308,
        3.309,
        3.306,
    ],
    "cell_count": 16,
    "delta_voltage": 0.004,
    "pack_count": 2,
    "voltage": 52.9,
    "current": -16.6,
    "design_capacity": 5600,
    "battery_level": 70.46,
    "cycle_charge": 12539,
    "total_charge": 12288,
    "cycles": 27,
    "battery_health": 100.0,
    "cycle_capacity": 663313.1,
    "power": -878.14,
    "battery_charging": False,
    "runtime": 2719301,
    "problem": False,
}


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


def test_ble_metadata() -> None:
    """Return the advertisement and GATT identifiers for this protocol."""
    assert BMS.matcher_dict_list() == [
        {"service_uuid": "0000e0ff-0000-1000-8000-00805f9b34fb", "connectable": True}
    ]
    assert BMS.uuid_services() == ("0000fff0-0000-1000-8000-00805f9b34fb",)
    assert BMS.uuid_rx() == "fff1"
    assert BMS.uuid_tx() == "fff1"


class MockTBESSBleakClient(MockBleakClient):
    """Emulate the TBESS notification stream with captured frames."""

    def _send_info(self) -> None:
        assert self._notify_callback is not None
        self._notify_callback(
            "MockTBESSBleakClient",
            bytearray(_PROTO_DEFS["sum"] + _PROTO_DEFS["pack1"][:47]),
        )
        self._notify_callback(
            "MockTBESSBleakClient",
            bytearray(
                _PROTO_DEFS["pack1"][47:]
                + _PROTO_DEFS["config"]
                + _PROTO_DEFS["info"]
                + _PROTO_DEFS["pack2"]
            ),
        )

    @property
    def is_connected(self) -> bool:
        """Provide a new captured stream for each update on a kept connection."""
        if self._connected and self._notify_callback is not None:
            self._send_info()
        return self._connected

    async def start_notify(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        callback: Callable[[BleakGATTCharacteristic, bytearray], None | Awaitable[None]],
        **kwargs,
    ) -> None:
        """Start notifications and deliver the recorded data stream."""
        await super().start_notify(char_specifier, callback)
        self._send_info()


async def test_update(
    patch_bleak_client,
    keep_alive_fixture: bool,
) -> None:
    """Decode two captured pack frames and update an existing connection."""
    patch_bleak_client(MockTBESSBleakClient)
    bms = BMS(generate_ble_device(), BMSConfig(keep_alive_fixture))

    result: BMSSample = await bms.async_update()
    assert result == _RESULT_DEFS

    assert await bms.async_update() == result
    assert bms.is_connected is keep_alive_fixture
    await bms.disconnect()


async def test_fragmented_and_concatenated_frames() -> None:
    """Assemble summary and pack frames split across notifications."""
    bms = BMS(generate_ble_device(), BMSConfig(False))
    bms._notification_handler(
        cast(BleakGATTCharacteristic, None),
        bytearray(_PROTO_DEFS["sum"] + _PROTO_DEFS["pack1"][:3]),
    )
    assert len(bms._frame) == 3

    bms._notification_handler(
        cast(BleakGATTCharacteristic, None),
        bytearray(_PROTO_DEFS["pack1"][3:] + _PROTO_DEFS["pack2"]),
    )
    assert bms._msg_event.is_set()
    assert len(bms._ready_samples) == 1
    result: BMSSample = await bms._async_update()
    assert result["pack_count"] == 2
    assert [pack["current"] for pack in result["packs"]] == [-6.43, -7.8]
    assert result["voltage"] == 52.9


@pytest.mark.parametrize(
    ("offset", "value"),
    [
        (1, 0x03),
        (22, 0x01),
        (123, 0x00),
    ],
    ids=["unknown-pack", "wrong-tag", "wrong-terminator"],
)
def test_invalid_detail_frame_is_ignored(offset: int, value: int) -> None:
    """Reject frames with an invalid pack address, tag, or terminator."""
    bms = BMS(generate_ble_device(), BMSConfig(False))
    frame = bytearray(_PROTO_DEFS["pack1"])
    frame[offset] = value

    bms._process_frame(_PROTO_DEFS["sum"])
    bms._notification_handler(cast(BleakGATTCharacteristic, None), frame)

    assert not bms._pending_packs
    assert not bms._ready_samples
    assert not bms._msg_event.is_set()


@pytest.mark.parametrize(
    "frame",
    [
        _PROTO_DEFS["pack1"][:-1],
        bytes([0x00]) + _PROTO_DEFS["pack1"][1:],
        b"",
    ],
    ids=["short-frame", "bad-start", "empty-frame"],
)
def test_process_frame_rejects_invalid_length_or_start(frame: bytes) -> None:
    """Reject malformed complete-frame candidates before storing them."""
    bms = BMS(generate_ble_device(), BMSConfig(False))

    bms._process_frame(frame)

    assert not bms._pending_packs
    assert not bms._ready_samples
    assert not bms._msg_event.is_set()


async def test_summary_pack_count_controls_detail_collection() -> None:
    """Collect the reported one pack and keep system data from its summary."""
    bms = BMS(generate_ble_device(), BMSConfig(False))
    summary = bytearray(_PROTO_DEFS["sum"])
    summary[26] = 1
    summary[27] = 1

    bms._notification_handler(cast(BleakGATTCharacteristic, None), summary)
    bms._notification_handler(
        cast(BleakGATTCharacteristic, None),
        bytearray(_PROTO_DEFS["pack1"]),
    )

    result: BMSSample = await bms._async_update()

    assert result["pack_count"] == 1
    assert result["design_capacity"] == 5600
    assert result["packs"][0]["voltage"] == _RESULT_DEFS["packs"][0]["voltage"]
    assert result["packs"][0]["cell_voltages"] == _RESULT_DEFS["packs"][0]["cell_voltages"]
    assert len(result["packs"]) == 1
    assert "current" in result
    assert "cell_voltages" not in result


def test_invalid_summary_is_ignored() -> None:
    """Ignore a summary from another address or one reporting zero packs."""
    bms = BMS(generate_ble_device(), BMSConfig(False))
    invalid_address = bytearray(_PROTO_DEFS["sum"])
    invalid_address[1] = 2
    empty_summary = bytearray(_PROTO_DEFS["sum"])
    empty_summary[26] = 0

    bms._process_frame(bytes(invalid_address))
    bms._process_frame(bytes(empty_summary))
    bms._process_frame(_PROTO_DEFS["pack1"])

    assert bms._summary is None
    assert bms._pack_count == 0
    assert not bms._pending_packs


def test_unrecognized_command_and_non_detail_frames_are_ignored() -> None:
    """Ignore unknown commands and valid status/configuration frames."""
    bms = BMS(generate_ble_device(), BMSConfig(False))
    bms._notification_handler(
        cast(BleakGATTCharacteristic, None),
        bytearray(
            b"\xef\x01\x99" + _PROTO_DEFS["sum"] + _PROTO_DEFS["config"] + _PROTO_DEFS["info"]
        ),
    )

    assert bms._summary is None
    assert not bms._ready_samples
    assert not bms._msg_event.is_set()
    assert not bms._frame


async def test_buffered_samples_are_consumed_in_order() -> None:
    """Consume multiple complete pairs queued before the caller requests them."""
    bms = BMS(generate_ble_device(), BMSConfig(False))
    stream: bytes = (
        _PROTO_DEFS["sum"]
        + _PROTO_DEFS["pack1"]
        + _PROTO_DEFS["config"]
        + _PROTO_DEFS["info"]
        + _PROTO_DEFS["pack2"]
    )
    bms._notification_handler(cast(BleakGATTCharacteristic, None), bytearray(stream + stream))

    assert len(bms._ready_samples) == 2
    first: BMSSample = await bms._async_update()
    second: BMSSample = await bms._async_update()

    assert first == second
    assert not bms._msg_event.is_set()


async def test_update_times_out_without_both_pack_frames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Propagate the timeout if a complete pair of pack frames is unavailable."""
    monkeypatch.setattr(BMS, "TIMEOUT", 0.001)
    bms = BMS(generate_ble_device(), BMSConfig(False))

    with pytest.raises(TimeoutError):
        await bms._async_update()
