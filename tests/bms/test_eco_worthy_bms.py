"""Tests for ECO-WORTHY BMS plugin.

All frames are real captures from ECO-WORTHY 12V 150AH LiFePO4 (ECOE934)
obtained via Android HCI btsnoop log.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

import fnmatch
import struct
from unittest.mock import MagicMock

import pytest
from bleak.backends.device import BLEDevice

from aiobmsble.bms.eco_worthy_bms import BMS

# ── Real captured frames ──────────────────────────────────────────────────────

# 0x20: standby, 0 A current
FRAME_BASIC_STANDBY = bytearray.fromhex(
    "AA200F000000008000800000000000000000" "2F01"
)

# 0x21: 14.080 V, 99 % SOC, 149160 mAh remain, 150000 mAh full
FRAME_PACK = bytearray.fromhex(
    "AA211A003700000000000063" "64A8460200F04902"
)

# 0x22: cells 3530, 3520, 3502, 3531 mV
FRAME_CELLS = bytearray.fromhex(
    "AA2230CA0DC00DAE0DCB0D"
    "00000000000000000000000000000000000000000000"
    "000000000000000000008E03"
)

# Charging: +5000 mA = 5.0 A
FRAME_BASIC_CHARGING = bytearray(FRAME_BASIC_STANDBY)
FRAME_BASIC_CHARGING[3] = 0x88
FRAME_BASIC_CHARGING[4] = 0x13

# Discharging: -3000 mA = -3.0 A
FRAME_BASIC_DISCHARGING = bytearray(FRAME_BASIC_STANDBY)
_val = (-3000) & 0xFFFF
FRAME_BASIC_DISCHARGING[3] = _val & 0xFF
FRAME_BASIC_DISCHARGING[4] = (_val >> 8) & 0xFF


# ── Matcher tests ─────────────────────────────────────────────────────────────

def test_matcher_pattern() -> None:
    """Verify device name pattern matches ECOExxx devices."""
    matchers = BMS.matcher_dict_list()
    assert len(matchers) == 1
    pattern = str(matchers[0].get("local_name", ""))
    assert fnmatch.fnmatch("ECOE934", pattern)
    assert fnmatch.fnmatch("ECOE1B0", pattern)
    assert not fnmatch.fnmatch("JBD-SP1", pattern)
    assert not fnmatch.fnmatch("DL-001", pattern)


def test_uuid_services() -> None:
    """Verify correct service UUID."""
    services = BMS.uuid_services()
    assert len(services) == 1
    assert "0001" in services[0]


def test_uuid_rx_tx() -> None:
    """Verify RX and TX characteristic UUIDs."""
    assert BMS.uuid_rx() == "0003"
    assert BMS.uuid_tx() == "0002"


# ── Parse 0x20 tests ──────────────────────────────────────────────────────────

def test_parse_basic_standby() -> None:
    """Verify current = 0 A at standby."""
    result = BMS._parse_basic(bytes(FRAME_BASIC_STANDBY))
    assert result["current"] == pytest.approx(0.0, abs=0.001)


def test_parse_basic_charging() -> None:
    """Verify positive current when charging."""
    result = BMS._parse_basic(bytes(FRAME_BASIC_CHARGING))
    assert result["current"] == pytest.approx(5.0, abs=0.001)


def test_parse_basic_discharging() -> None:
    """Verify negative current when discharging."""
    result = BMS._parse_basic(bytes(FRAME_BASIC_DISCHARGING))
    assert result["current"] == pytest.approx(-3.0, abs=0.001)


# ── Parse 0x21 tests ──────────────────────────────────────────────────────────

def test_parse_pack_voltage() -> None:
    """Verify pack voltage = 14.080 V."""
    result = BMS._parse_pack(bytes(FRAME_PACK))
    assert result["voltage"] == pytest.approx(14.080, abs=0.001)


def test_parse_pack_soc() -> None:
    """Verify SOC = 99 %."""
    result = BMS._parse_pack(bytes(FRAME_PACK))
    assert result["battery_level"] == 99


def test_parse_pack_remain_capacity() -> None:
    """Verify remaining capacity = 149 Ah."""
    result = BMS._parse_pack(bytes(FRAME_PACK))
    assert result["cycle_charge"] == 149


def test_parse_pack_full_capacity() -> None:
    """Verify full design capacity = 150 Ah."""
    result = BMS._parse_pack(bytes(FRAME_PACK))
    assert result["design_capacity"] == 150


# ── Parse 0x22 tests ──────────────────────────────────────────────────────────

def test_parse_cells_count() -> None:
    """Verify 4 cells are parsed."""
    result = BMS._parse_cells(bytes(FRAME_CELLS))
    assert "cell_voltages" in result
    assert len(result["cell_voltages"]) == 4  # type: ignore[arg-type]


def test_parse_cells_values() -> None:
    """Verify cell voltages match captured values."""
    result = BMS._parse_cells(bytes(FRAME_CELLS))
    cells = result["cell_voltages"]  # type: ignore[literal-required]
    assert cells[0] == pytest.approx(3.530, abs=0.001)  # type: ignore[index]
    assert cells[1] == pytest.approx(3.520, abs=0.001)  # type: ignore[index]
    assert cells[2] == pytest.approx(3.502, abs=0.001)  # type: ignore[index]
    assert cells[3] == pytest.approx(3.531, abs=0.001)  # type: ignore[index]


def test_parse_cells_delta() -> None:
    """Verify delta voltage = max - min cell voltages."""
    result = BMS._parse_cells(bytes(FRAME_CELLS))
    assert result["delta_voltage"] == pytest.approx(3.531 - 3.502, abs=0.001)


# ── Edge case tests ───────────────────────────────────────────────────────────

def test_notification_handler_invalid_sof() -> None:
    """Verify frames with wrong SOF are ignored."""
    device = MagicMock(spec=BLEDevice)
    device.address = "15:05:D5:A1:E9:34"
    device.name = "ECOE934"
    bms = BMS(ble_device=device)
    bad_frame = bytearray([0xBB, 0x21, 0x1A, 0x00])
    bms._notification_handler(MagicMock(), bad_frame)
    assert bms._raw_pack == b""


def test_parse_cells_empty_frame() -> None:
    """Verify empty cell frame returns no cell data."""
    result = BMS._parse_cells(bytes([0xAA, 0x22, 0x00]))
    assert "cell_voltages" not in result
    assert "delta_voltage" not in result


def test_parse_pack_short_frame() -> None:
    """Verify short pack frame raises expected error."""
    short = bytes(FRAME_PACK[:10])
    with pytest.raises((IndexError, struct.error)):
        BMS._parse_pack(short)


def test_advertisement_name_pattern() -> None:
    """Verify real device name matches the matcher pattern."""
    pattern = str(BMS.matcher_dict_list()[0].get("local_name", ""))
    assert fnmatch.fnmatch("ECOE934", pattern)


# ── Notification handler coverage ────────────────────────────────────────────

def _make_bms() -> BMS:
    """Create a BMS instance for testing notification handler."""
    device = MagicMock(spec=BLEDevice)
    device.address = "15:05:D5:A1:E9:34"
    device.name = "ECOE934"
    return BMS(ble_device=device)


def test_notification_handler_stores_basic() -> None:
    """Verify valid 0x20 frame is stored in _raw_basic."""
    bms = _make_bms()
    bms._notification_handler(MagicMock(), bytearray(FRAME_BASIC_STANDBY))
    assert bms._raw_basic == bytes(FRAME_BASIC_STANDBY)


def test_notification_handler_stores_pack() -> None:
    """Verify valid 0x21 frame is stored in _raw_pack."""
    bms = _make_bms()
    bms._notification_handler(MagicMock(), bytearray(FRAME_PACK))
    assert bms._raw_pack == bytes(FRAME_PACK)


def test_notification_handler_stores_cells() -> None:
    """Verify valid 0x22 frame is stored in _raw_cells."""
    bms = _make_bms()
    bms._notification_handler(MagicMock(), bytearray(FRAME_CELLS))
    assert bms._raw_cells == bytes(FRAME_CELLS)


def test_notification_handler_too_short() -> None:
    """Verify frames shorter than 3 bytes are ignored."""
    bms = _make_bms()
    bms._notification_handler(MagicMock(), bytearray([0xAA, 0x20]))
    assert bms._raw_basic == b""


def test_notification_handler_basic_too_short() -> None:
    """Verify 0x20 frame shorter than MIN_LEN_BASIC is not stored."""
    bms = _make_bms()
    short = bytearray(FRAME_BASIC_STANDBY[:5])  # valid SOF, correct cmd, too short
    bms._notification_handler(MagicMock(), short)
    assert bms._raw_basic == b""


def test_notification_handler_pack_too_short() -> None:
    """Verify 0x21 frame shorter than MIN_LEN_PACK is not stored."""
    bms = _make_bms()
    short = bytearray(FRAME_PACK[:10])
    bms._notification_handler(MagicMock(), short)
    assert bms._raw_pack == b""


def test_notification_handler_cells_too_short() -> None:
    """Verify 0x22 frame shorter than MIN_LEN_CELLS is not stored."""
    bms = _make_bms()
    short = bytearray(FRAME_CELLS[:5])
    bms._notification_handler(MagicMock(), short)
    assert bms._raw_cells == b""


def test_notification_handler_unknown_cmd() -> None:
    """Verify unknown command byte does not set msg_event."""
    bms = _make_bms()
    unknown = bytearray([0xAA, 0x99, 0x00, 0x00, 0x00, 0x00, 0x00,
                         0x00, 0x00, 0x00, 0x00, 0x00])
    bms._notification_handler(MagicMock(), unknown)
    assert bms._raw_basic == b""
    assert bms._raw_pack == b""
    assert bms._raw_cells == b""


def test_raw_values_excludes_runtime() -> None:
    """Verify runtime is in the set of raw (never-calculated) values."""
    assert "runtime" in BMS._raw_values()


# ── Async update coverage ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_async_update_all_frames() -> None:
    """Verify _async_update correctly parses all three frame types."""
    bms = _make_bms()

    async def fake_await(cmd: bytes) -> None:
        if cmd == BMS._CMD_BASIC:
            bms._notification_handler(MagicMock(), bytearray(FRAME_BASIC_CHARGING))
        elif cmd == BMS._CMD_PACK:
            bms._notification_handler(MagicMock(), bytearray(FRAME_PACK))
        elif cmd == BMS._CMD_CELLS:
            bms._notification_handler(MagicMock(), bytearray(FRAME_CELLS))

    bms._await_msg = fake_await  # type: ignore[method-assign]
    result = await bms._async_update()

    assert result["voltage"] == pytest.approx(14.080, abs=0.001)
    assert result["battery_level"] == 99
    assert result["current"] == pytest.approx(5.0, abs=0.001)
    assert result["battery_charging"] is True
    assert "cell_voltages" in result
    assert len(result["cell_voltages"]) == 4  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_async_update_charging_flag_false() -> None:
    """Verify battery_charging is False when current is negative."""
    bms = _make_bms()

    async def fake_await(cmd: bytes) -> None:
        if cmd == BMS._CMD_BASIC:
            bms._notification_handler(MagicMock(), bytearray(FRAME_BASIC_DISCHARGING))
        elif cmd == BMS._CMD_PACK:
            bms._notification_handler(MagicMock(), bytearray(FRAME_PACK))
        elif cmd == BMS._CMD_CELLS:
            bms._notification_handler(MagicMock(), bytearray(FRAME_CELLS))

    bms._await_msg = fake_await  # type: ignore[method-assign]
    result = await bms._async_update()
    assert result["battery_charging"] is False


@pytest.mark.asyncio
async def test_async_update_no_frames() -> None:
    """Verify _async_update handles missing frames gracefully."""
    bms = _make_bms()

    async def noop(_cmd: bytes) -> None:
        pass

    bms._await_msg = noop  # type: ignore[method-assign]
    result = await bms._async_update()
    assert isinstance(result, dict)
    
def test_parse_cells_truncated_payload() -> None:
    """Verify cell parsing stops when payload is truncated mid-cell."""
    # 3-byte header + 3 bytes data = odd length, triggers offset+1 >= len(payload)
    truncated = bytes([0xAA, 0x22, 0x03, 0xCA, 0x0D, 0xFF])
    result = BMS._parse_cells(truncated)
    assert len(result.get("cell_voltages", [])) == 1  # type: ignore[arg-type]


def test_parse_cells_out_of_range_mv() -> None:
    """Verify cell mv values outside 2000-5000 range are skipped."""
    # cell 1: 1000 mV (too low, skipped), then zero terminator
    out_of_range = bytes([0xAA, 0x22, 0x04, 0xE8, 0x03, 0x00, 0x00])
    result = BMS._parse_cells(out_of_range)
    assert "cell_voltages" not in result


@pytest.mark.asyncio
async def test_async_update_no_basic_frame() -> None:
    """Verify battery_charging branch skipped when no basic frame received."""
    bms = _make_bms()

    async def fake_await(cmd: bytes) -> None:
        # Only provide pack and cells, no basic — so 'current' won't be in data
        if cmd == BMS._CMD_PACK:
            bms._notification_handler(MagicMock(), bytearray(FRAME_PACK))
        elif cmd == BMS._CMD_CELLS:
            bms._notification_handler(MagicMock(), bytearray(FRAME_CELLS))

    bms._await_msg = fake_await  # type: ignore[method-assign]
    result = await bms._async_update()
    assert "current" not in result
    assert result["voltage"] == pytest.approx(14.080, abs=0.001)

def test_parse_cells_full_16_cells() -> None:
    """Verify parsing completes full loop of 16 cells without break."""
    # Build a frame with 16 valid cells at 3500 mV each
    header = bytes([0xAA, 0x22, 0x20])
    cells = (3500).to_bytes(2, byteorder="little") * 16
    frame = header + cells
    result = BMS._parse_cells(frame)
    assert len(result["cell_voltages"]) == 16  # type: ignore[arg-type]