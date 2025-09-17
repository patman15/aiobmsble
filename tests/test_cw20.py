import pytest
from aiobmsble.bms.cw20_bms import BMS

# We use real CW20 packets captured from the device.
# Each test vector contains:
#   - voltage (V)
#   - current (A)
#   - capacity (Ah)
#   - energy (kWh)
#
# Note:
# - Energy is a cumulative field and may vary slightly between frames,
#   so we allow a wider absolute tolerance (±0.5).
# - Voltage, current, and capacity should match very closely, so we
#   use a strict relative tolerance (1e-3) and a small absolute tolerance.


@pytest.mark.parametrize(
    "hex_packet, expected",
    [
        (
            # Example 1: Voltage ≈ 339.6 V, Current ≈ 3.575 A,
            # Capacity ≈ 8.333 Ah, Energy ≈ 28.63 kWh
            "ff550102000d44000df700208d00000b2f000064000000000020003b1c1d3c0000000023",
            {"voltage": 339.6, "current": 3.575, "capacity": 8.333, "energy": 28.63},
        ),
        (
            # Example 2: Voltage ≈ 348.0 V, Current ≈ 3.545 A,
            # Capacity ≈ 8.333 Ah, Energy ≈ 28.63 kWh
            "ff550102000d98000dd900208d00000b2f000064000000000020003b1c213c0000000023",
            {"voltage": 348.0, "current": 3.545, "capacity": 8.333, "energy": 28.63},
        ),
        (
            # Example 3: Voltage ≈ 344.0 V, Current ≈ 3.572 A,
            # Capacity ≈ 8.334 Ah, Energy ≈ 28.63 kWh
            "ff550102000d70000df400208e00000b2f000064000000000021003b1c263c0000000023",
            {"voltage": 344.0, "current": 3.572, "capacity": 8.334, "energy": 28.63},
        ),
    ],
)
def test_cw20_decode(hex_packet, expected):
    """Test decoding of real CW20 frames."""
    # Convert the hex string into raw bytes
    frame = bytearray.fromhex(hex_packet)

    # Decode using the CW20 BMS plugin definition
    data = BMS._decode_data(BMS._FIELDS, frame)

    # Verify each expected field
    for key, val in expected.items():
        if key == "energy":
            # Energy is cumulative and drifts slightly → allow wider tolerance
            assert data[key] == pytest.approx(val, rel=1e-3, abs=0.5)
        else:
            # Voltage, current, capacity → strict tolerance
            assert data[key] == pytest.approx(val, rel=1e-3, abs=1e-2)
