"""Test the LULIS BMS implementation."""

from collections.abc import Buffer
from typing import Final
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
import pytest

from aiobmsble import BMSConfig, BMSSample, PrbType as PT, Severity, TempSensor
from aiobmsble.bms.lulis_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import BMSBasicTests

# frames recorded from LULIS 72V 40Ah pack, see BMS_BLE-HA issue #879
_PROTO_DEFS: Final[dict[int, bytes]] = {
    0x02: bytes.fromhex("3b7e010102144c523335395631335f4e303331783630410000002a"),
    0x05: bytes.fromhex("3b7e0101051a41454a4342483130414d423131303032000000000000000000009c"),
    0x1E: bytes.fromhex(
        "3b7e01011e263a1f000060136300040d0000020d0c000200680b0000650b0100000000000000000000009300d3"
    ),
    0x1F: bytes.fromhex("3b7e01011f080300680b650b6e0b41"),
    0x20: bytes.fromhex(
        "3b7e010120351800000000040d040d040d040d040d040d040d040d040d040d040d040d"
        "020d020d020d020d020d020d020d020d020d020d020d010da7"
    ),
    0x09: bytes.fromhex("3b7e01010908b80b1400a00fa00f01"),
}

_RESULT_DEFS: Final[BMSSample] = {
    "voltage": 79.94,
    "current": 0.0,
    "battery_level": 99.2,
    "battery_health": 99,
    "battery_charging": False,
    "power": 0.0,
    "problem": False,
    "problem_code": 0,
    "chrg_mosfet": False,
    "dischrg_mosfet": True,
    "cycles": 20,
    "design_capacity": 40,
    "cycle_charge": 39.68,
    "cell_count": 24,
    "cell_voltages": [3.332] * 12 + [3.330] * 11 + [3.329],
    "delta_cell_voltage": 0.003,
    "cycle_energy": 3172.019,
    "problems": [],
    "temperature": [TempSensor(18.9), TempSensor(18.6), TempSensor(19.5)],
}


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


class MockLulisBleakClient(MockBleakClient):
    """Emulate a LULIS BMS BleakClient."""

    PACK: bytes = _PROTO_DEFS[0x1E]
    CHUNK: int = 0  # 0: send frames unfragmented
    SKIP: set[int] = set()  # commands that are not answered

    async def write_gatt_char(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        data: Buffer,
        response: bool | None = None,
    ) -> None:
        """Issue write command to GATT."""
        await super().write_gatt_char(char_specifier, data, response)
        assert self._notify_callback is not None
        cmd: Final[int] = bytes(data)[4]
        assert bytes(data) == BMS._cmd(cmd)
        if cmd in self.SKIP or cmd not in _PROTO_DEFS:
            return
        reply: bytes = self.PACK if cmd == 0x1E else _PROTO_DEFS[cmd]
        step: Final[int] = self.CHUNK or len(reply)
        for pos in range(0, len(reply), step):
            self._notify_callback("MockLulisBleakClient", bytearray(reply[pos : pos + step]))


def _with_checksum(frame: bytes) -> bytes:
    return frame[:-1] + (sum(frame[:-1]) & 0xFF).to_bytes(1)


def test_cmd() -> None:
    """Test read request construction."""
    assert BMS._cmd(0x1E) == b"\x3a\x7e\x01\x01\x1e\x00\xd8"


@pytest.mark.parametrize("chunk", [0, 7], ids=["complete", "fragmented"])
async def test_update(
    patch_bleak_client, monkeypatch: pytest.MonkeyPatch, keep_alive_fixture: bool, chunk: int
) -> None:
    """Test LULIS BMS data update."""
    patch_bleak_client(MockLulisBleakClient)
    monkeypatch.setattr(MockLulisBleakClient, "CHUNK", chunk)

    bms = BMS(generate_ble_device(), BMSConfig(keep_alive_fixture))
    assert await bms.update() == _RESULT_DEFS

    await bms.update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()


async def test_device_info(patch_bleak_client) -> None:
    """Test that the BMS returns device information."""
    patch_bleak_client(MockLulisBleakClient)
    bms = BMS(generate_ble_device())
    info = await bms.device_info()
    assert info.get("model") == "LR359V13_N031x60A"
    assert info.get("serial_number") == "AEJCBH10AMB11002"
    await bms.disconnect()


async def test_problems(patch_bleak_client, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test decoding of alarm, protection and fault words."""
    pack: bytearray = bytearray(_PROTO_DEFS[0x1E])
    pack[6 + 26 : 6 + 28] = b"\x01\x00"  # alarm: cell overvoltage
    pack[6 + 30 : 6 + 32] = b"\x10\x00"  # protection: discharge overcurrent
    pack[6 + 34 : 6 + 36] = b"\x04\x00"  # fault: EEPROM
    monkeypatch.setattr(MockLulisBleakClient, "PACK", _with_checksum(bytes(pack)))
    patch_bleak_client(MockLulisBleakClient)

    bms = BMS(generate_ble_device())
    result: BMSSample = await bms.update()
    assert result.get("problem")
    assert {(p.kind, p.level) for p in result.get("problems", [])} == {
        (PT.CELL_OV, Severity.WARN),
        (PT.DISCHARGE_OC, Severity.PROTECT),
        (PT.OTHER, Severity.FAULT),
    }
    await bms.disconnect()


@pytest.mark.parametrize(
    "garbage",
    [
        b"\x00\x01\x02",
        _PROTO_DEFS[0x1E][:-1] + b"\x00",
    ],
    ids=["no_header", "bad_checksum"],
)
async def test_invalid_frame(
    patch_bleak_client, monkeypatch: pytest.MonkeyPatch, garbage: bytes
) -> None:
    """Test that invalid data is ignored, a valid frame behind it is decoded."""
    patch_bleak_client(MockLulisBleakClient)
    monkeypatch.setattr(MockLulisBleakClient, "PACK", garbage + _PROTO_DEFS[0x1E])

    bms = BMS(generate_ble_device())
    assert await bms.update() == _RESULT_DEFS
    await bms.disconnect()


def test_short_frame() -> None:
    """Test that an incomplete frame does not signal completion."""
    bms = BMS(generate_ble_device())
    bms._exp_cmd = 0x1E
    bms._notification_handler(None, bytearray(b"\x3b\x7e\x01"))  # type: ignore[arg-type]
    bms._notification_handler(None, bytearray(_PROTO_DEFS[0x1E][3:20]))  # type: ignore[arg-type]
    assert not bms._msg_event.is_set()


def test_unexpected_cmd() -> None:
    """Test that a reply to another command does not signal completion."""
    bms = BMS(generate_ble_device())
    bms._exp_cmd = 0x1F
    bms._notification_handler(None, bytearray(_PROTO_DEFS[0x1E]))  # type: ignore[arg-type]
    assert not bms._msg_event.is_set()
