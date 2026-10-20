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

_SUMMARY: Final[bytes] = bytes.fromhex(
    "ef01734638354231423632333342430000000000000000550002020214aaff5a"
    "15e016570fbe1b862710084816d00b5411d00ced0ce8010b020d0b940b8d0102"
    "02040ba20b9d010102010ba90ba802010101001b001ac0000000000000000000"
    "0000000000000030fb00003000ec8416"
)
_PACK1: Final[bytes] = bytes.fromhex(
    "ef01db3531343131303932323630353031303035383400610014acfd7d02bb4e"
    "46100cec0ceb0cec0cec0ceb0ced0cea0cec0ceb0cec0cee0cec0cea0cec0cec"
    "0ceb0400e700e900e700e700fd00f7001b186f18d6074d0000000003e86ff26d"
    "600cee0b0cea07000400e90200e7010002000018d60000186fd80416"
)
_PACK2: Final[bytes] = bytes.fromhex(
    "ef02db3531343131303932323630353031303132333200610014acfcf402c44e"
    "fd100cec0cea0ced0ced0cea0cec0cea0ced0cea0ceb0cee0cec0cea0cec0ced"
    "0cea0400e500e600e400e200fe00f2001a1791182506130000000003e86f7d6d"
    "600cee0b0cea02000400e60200e20400040000182500001791d8c216"
)
_CONFIG: Final[bytes] = bytes.fromhex(
    "ef01dc35313431313039323236303530313030353834002d0010000000000000"
    "0000000000000000000004000000000000000640000000000200000000000000"
    "0000000000fad416"
)
_INFO: Final[bytes] = bytes.fromhex(
    "ef01d0353134313130393232363035303130303538340088006d603435303330"
    "3038393700000035313431313039312032363035303730303637003531343131"
    "30393232363035303130303538340053544d333246313033564554360000434e"
    "323030474130362d34383230302d313041002a3001000001434e313034383230"
    "303136535a544232353033303330303100000000000000000000000000000000"
    "e3ac16"
)

_EXPECTED_PACKS = [
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
]


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
            "MockTBESSBleakClient", bytearray(_SUMMARY + _PACK1[:47])
        )
        self._notify_callback(
            "MockTBESSBleakClient",
            bytearray(_PACK1[47:] + _CONFIG + _INFO + _PACK2),
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
        callback: Callable[
            [BleakGATTCharacteristic, bytearray], None | Awaitable[None]
        ],
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
    assert result["packs"] == _EXPECTED_PACKS
    assert result["pack_count"] == 2
    assert result["voltage"] == 52.9
    assert result["current"] == -16.6
    assert result["design_capacity"] == 5600
    assert result["battery_level"] == 70.46
    assert result["cycle_charge"] == 12539
    assert result["total_charge"] == 12288
    assert result["cycles"] == 27
    assert result["battery_health"] == 100.0
    assert result["problem"] is False

    assert await bms.async_update() == result
    assert bms.is_connected is keep_alive_fixture
    await bms.disconnect()


async def test_fragmented_and_concatenated_frames() -> None:
    """Assemble summary and pack frames split across notifications."""
    bms = BMS(generate_ble_device(), BMSConfig(False))
    bms._notification_handler(
        cast(BleakGATTCharacteristic, None), bytearray(_SUMMARY + _PACK1[:3])
    )
    assert len(bms._frame) == 3

    bms._notification_handler(
        cast(BleakGATTCharacteristic, None),
        bytearray(_PACK1[3:] + _PACK2),
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
    frame = bytearray(_PACK1)
    frame[offset] = value

    bms._process_frame(_SUMMARY)
    bms._notification_handler(cast(BleakGATTCharacteristic, None), frame)

    assert not bms._pending_packs
    assert not bms._ready_samples
    assert not bms._msg_event.is_set()


@pytest.mark.parametrize(
    "frame",
    [
        _PACK1[:-1],
        bytes([0x00]) + _PACK1[1:],
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
    summary = bytearray(_SUMMARY)
    summary[26] = 1
    summary[27] = 1

    bms._notification_handler(cast(BleakGATTCharacteristic, None), summary)
    bms._notification_handler(cast(BleakGATTCharacteristic, None), bytearray(_PACK1))

    result: BMSSample = await bms._async_update()

    assert result["pack_count"] == 1
    assert result["design_capacity"] == 5600
    assert result["packs"][0]["voltage"] == _EXPECTED_PACKS[0]["voltage"]
    assert result["packs"][0]["cell_voltages"] == _EXPECTED_PACKS[0]["cell_voltages"]
    assert len(result["packs"]) == 1
    assert "current" in result
    assert "cell_voltages" not in result


def test_invalid_summary_is_ignored() -> None:
    """Ignore a summary from another address or one reporting zero packs."""
    bms = BMS(generate_ble_device(), BMSConfig(False))
    invalid_address = bytearray(_SUMMARY)
    invalid_address[1] = 2
    empty_summary = bytearray(_SUMMARY)
    empty_summary[26] = 0

    bms._process_frame(bytes(invalid_address))
    bms._process_frame(bytes(empty_summary))
    bms._process_frame(_PACK1)

    assert bms._summary is None
    assert bms._pack_count == 0
    assert not bms._pending_packs


def test_unrecognized_command_and_non_detail_frames_are_ignored() -> None:
    """Ignore unknown commands and valid status/configuration frames."""
    bms = BMS(generate_ble_device(), BMSConfig(False))
    bms._notification_handler(
        cast(BleakGATTCharacteristic, None),
        bytearray(b"\xef\x01\x99" + _SUMMARY + _CONFIG + _INFO),
    )

    assert bms._summary is None
    assert not bms._ready_samples
    assert not bms._msg_event.is_set()
    assert not bms._frame


async def test_buffered_samples_are_consumed_in_order() -> None:
    """Consume multiple complete pairs queued before the caller requests them."""
    bms = BMS(generate_ble_device(), BMSConfig(False))
    stream: bytes = _SUMMARY + _PACK1 + _CONFIG + _INFO + _PACK2
    bms._notification_handler(
        cast(BleakGATTCharacteristic, None), bytearray(stream + stream)
    )

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
