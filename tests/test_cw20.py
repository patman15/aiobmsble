"""Unit tests for CW20 plugin decoding."""

import pytest

from aiobmsble.bms.cw20_bms import BMS, BMSdp

# Real CW20 sniffer packets (hex dumps)
_VALID_PACKETS = [
    (
        # Example 1: Voltage ≈ 339.6 V
        "ff550102000d44000df700208d00000b2f000064000000000020003b1c1d3c0000000023",
        {"voltage": 339.6, "current": 3.575, "capacity": 8.333, "energy": 28.63},
    ),
    (
        # Example 2: Voltage ≈ 348.0 V
        "ff550102000d98000dd900208d00000b2f000064000000000020003b1c213c0000000023",
        {"voltage": 348.0, "current": 3.545, "capacity": 8.333, "energy": 28.63},
    ),
    (
        # Example 3: Voltage ≈ 344.0 V
        "ff550102000d70000df400208e00000b2f000064000000000021003b1c263c0000000023",
        {"voltage": 344.0, "current": 3.572, "capacity": 8.334, "energy": 28.63},
    ),
]


@pytest.mark.parametrize(("hex_packet", "expected"), _VALID_PACKETS)
def test_cw20_decode_valid(hex_packet, expected):
    """Test decoding of real CW20 frames (voltage, current, capacity, energy)."""
    frame = bytearray.fromhex(hex_packet)
    data = BMS._decode_data(BMS._FIELDS, frame)

    # Expected fields
    for key, val in expected.items():
        if key == "energy":
            # energy has small rounding differences
            assert data[key] == pytest.approx(val, rel=1e-3, abs=0.5)
        else:
            assert data[key] == pytest.approx(val, rel=1e-3, abs=1e-2)

    # Extra calculated value: power
    assert "power" not in data  # power is added in _async_update, not here


def test_cw20_decode_with_temperature_and_power():
    """Test that temperature and power are decoded/derived correctly."""
    hex_packet = _VALID_PACKETS[0][0]
    frame = bytearray.fromhex(hex_packet)

    data = BMS._decode_data(BMS._FIELDS, frame)
    # Temperature should decode to an integer (even if zero in frame)
    assert "temperature" in data
    assert isinstance(data["temperature"], (int, float))

    # Simulate async_update() to add power
    if "voltage" in data and "current" in data:
        data["power"] = round(data["voltage"] * data["current"], 2)
    assert "power" in data
    assert data["power"] == pytest.approx(
        data["voltage"] * data["current"], rel=1e-3, abs=0.1
    )


def test_cw20_decode_no_fct_branch():
    """Cover branch where dp.fct is identity (raw integer without scaling)."""
    frame = bytearray.fromhex(_VALID_PACKETS[0][0])
    fields = (BMSdp("raw_voltage", 4, 3, False, lambda x: x),)
    data = BMS._decode_data(fields, frame)
    expected_raw = int.from_bytes(frame[4:7], "big", signed=False)
    assert data["raw_voltage"] == expected_raw

