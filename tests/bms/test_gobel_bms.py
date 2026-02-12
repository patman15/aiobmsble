"""Test the Gobel Power BLE BMS implementation."""

from collections.abc import Buffer
from typing import Final
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.uuids import normalize_uuid_str
import pytest

from aiobmsble import BMSInfo, BMSSample
from aiobmsble.basebms import crc_modbus
from aiobmsble.bms.gobel_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import BMSBasicTests

# Service and characteristic UUIDs for Gobel Power BMS
SERVICE_UUID = "00002760-08c2-11e1-9073-0e8ac72e1001"
TX_CHAR_UUID = "00002760-08c2-11e1-9073-0e8ac72e0001"
RX_CHAR_UUID = "00002760-08c2-11e1-9073-0e8ac72e0002"

BT_FRAME_SIZE = 20

_FRAME_MAIN_DATA: Final[bytearray] = bytearray(
    b"\x01\x03\x76\x00\x00\x05\x33\x00\x61\x00\x64\x7b\x11\x7e\xed\x7a"
    b"\xa8\x00\x01\x00\x00\x00\x00\x00\x00\x0c\x00\x00\x00\x00\x00\xc0"
    b"\x00\x00\x04\x0c\xff\x0d\x02\x0d\x02\x0d\x01\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x01\x00\xd1\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\xd3\xff\xff\x01\xd6"
)

_FRAME_DEVICE_INFO: Final[bytearray] = bytearray(
    b"\x01\x03\x46\x50\x34\x53\x32\x30\x30\x41\x2d\x34\x30\x35\x36\x39"
    b"\x2d\x31\x2e\x30\x32\x00\x00\x34\x30\x35\x36\x39\x31\x31\x41\x31"
    b"\x31\x30\x30\x30\x33\x32\x50\x20\x20\x20\x20\x47\x50\x2d\x4c\x41"
    b"\x31\x32\x2d\x33\x31\x34\x32\x30\x32\x35\x30\x36\x31\x38\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x82\xa3"
)

# Expected result from parsing _FRAME_MAIN_DATA
_RESULT_MAIN_DATA: Final[BMSSample] = {
    "battery_charging": False,
    "battery_health": 100,
    "battery_level": 97,
    "cell_count": 4,
    "cell_voltages": [3.327, 3.33, 3.33, 3.329],
    "chrg_mosfet": True,
    "current": 0.0,
    "cycle_capacity": 4193.316,
    "cycle_charge": 315.05,
    "cycles": 1,
    "delta_voltage": 0.003,
    "design_capacity": 324,
    "dischrg_mosfet": True,
    "power": 0.0,
    "problem": False,
    "problem_code": 0,
    "temp_sensors": 1,
    "temp_values": [20.9, 21.1],
    "temperature": 21.0,
    "voltage": 13.31,
}


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


class MockGobelBleakClient(MockBleakClient):
    """Emulate a Gobel Power BMS BleakClient."""

    _RESP: bytearray = _FRAME_MAIN_DATA
    _RESP_DEVICE_INFO: bytearray = _FRAME_DEVICE_INFO

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
    ) -> bytearray:
        """Generate response based on command."""
        if isinstance(char_specifier, str) and normalize_uuid_str(
            char_specifier
        ) == normalize_uuid_str(TX_CHAR_UUID):
            req_data = bytes(data)
            # Verify it's a valid Modbus read request
            if len(req_data) >= 8 and req_data[0] == 0x01 and req_data[1] == 0x03:
                # Check which command is being sent
                start_addr = (req_data[2] << 8) | req_data[3]
                if start_addr == 0x00AA:  # Device info command (READ_CMD_3)
                    return bytearray(self._RESP_DEVICE_INFO)
                return bytearray(self._RESP)
        return bytearray()

    async def write_gatt_char(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        data: Buffer,
        response: bool | None = None,
    ) -> None:
        """Issue write command to GATT."""
        await super().write_gatt_char(char_specifier, data, response)
        assert self._notify_callback is not None
        self._notify_callback(
            "MockGobelBleakClient", self._response(char_specifier, data)
        )


class MockFragmentedBleakClient(MockGobelBleakClient):
    """Emulate a Gobel Power BMS that sends fragmented responses."""

    async def write_gatt_char(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        data: Buffer,
        response: bool | None = None,
    ) -> None:
        """Issue write command to GATT and send fragmented response."""
        await MockBleakClient.write_gatt_char(self, char_specifier, data, response)
        assert self._notify_callback is not None
        full_response = self._response(char_specifier, data)
        # Send in BT_FRAME_SIZE-byte chunks to simulate BLE fragmentation
        for i in range(0, len(full_response), BT_FRAME_SIZE):
            chunk = full_response[i : i + BT_FRAME_SIZE]
            self._notify_callback("MockFragmentedBleakClient", chunk)


async def test_update(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    keep_alive_fixture: bool,
) -> None:
    """Test Gobel Power BMS data update."""

    monkeypatch.setattr(MockGobelBleakClient, "_RESP", _FRAME_MAIN_DATA)
    patch_bleak_client(MockGobelBleakClient)

    bms = BMS(generate_ble_device(), keep_alive_fixture)

    assert await bms.async_update() == _RESULT_MAIN_DATA

    # Query again to check already connected state
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()


async def test_fragmented_response(
    monkeypatch: pytest.MonkeyPatch, patch_bleak_client
) -> None:
    """Test handling of fragmented BLE responses."""

    monkeypatch.setattr(MockFragmentedBleakClient, "_RESP", _FRAME_MAIN_DATA)
    patch_bleak_client(MockFragmentedBleakClient)

    bms = BMS(generate_ble_device())

    assert await bms.async_update() == _RESULT_MAIN_DATA

    await bms.disconnect()


async def test_device_info(monkeypatch: pytest.MonkeyPatch, patch_bleak_client) -> None:
    """Test fetching device info from BMS via Modbus."""

    monkeypatch.setattr(MockGobelBleakClient, "_RESP_DEVICE_INFO", _FRAME_DEVICE_INFO)
    patch_bleak_client(MockGobelBleakClient)

    bms = BMS(generate_ble_device())
    info: Final[BMSInfo] = await bms.device_info()

    assert info.get("sw_version") == "P4S200A-40569-1.02"
    assert info.get("serial_number") == "4056911A1100032P"
    assert info.get("model_id") == "GP-LA12-31420250618"

    await bms.disconnect()


def _corrupt_crc(frame: bytearray) -> bytearray:
    """Corrupt the CRC of a Modbus frame."""
    result = bytearray(frame)
    result[-1] ^= 0xFF
    return result


def _modbus_error_response() -> bytearray:
    """Build a Modbus error response."""
    error_frame = bytearray([0x01, 0x83, 0x02])  # Illegal data address
    error_frame.extend(crc_modbus(error_frame).to_bytes(2, "little"))
    return error_frame


def _short_response() -> bytearray:
    """Build a valid but short response (insufficient data)."""
    short_data = bytearray(20)
    short_data[2:4] = (1332).to_bytes(2, "big")  # voltage
    frame: bytearray = bytearray([0x01, 0x03, len(short_data)]) + short_data
    frame.extend(crc_modbus(frame).to_bytes(2, "little"))
    return frame


def _wrong_function_code() -> bytearray:
    """Build response with wrong function code."""
    return bytearray([0x01, 0x10, 0x00, 0x00, 0x00, 0x3B])


@pytest.mark.parametrize(
    ("wrong_response", "expect_timeout"),
    [
        (b"", True),
        (_corrupt_crc(_FRAME_MAIN_DATA), True),
        (_modbus_error_response(), True),
        (_wrong_function_code(), True),
        (_short_response(), False),  # Returns empty result, no timeout
    ],
    ids=[
        "empty",
        "invalid_crc",
        "modbus_error",
        "wrong_func_code",
        "short_response",
    ],
)
async def test_invalid_response(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    patch_bms_timeout,
    wrong_response: bytes,
    expect_timeout: bool,
) -> None:
    """Test data update with BMS returning invalid data."""

    patch_bms_timeout()
    monkeypatch.setattr(MockGobelBleakClient, "_RESP", bytearray(wrong_response))
    patch_bleak_client(MockGobelBleakClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = {}
    if expect_timeout:
        with pytest.raises(TimeoutError):
            result = await bms.async_update()
    else:
        result = await bms.async_update()

    assert not result
    await bms.disconnect()


def test_bms_info() -> None:
    """Test BMS info definition."""
    assert BMS.INFO.get("default_manufacturer") == "Gobel Power"
    assert BMS.INFO.get("default_model") == "BLE BMS"


def test_cmd() -> None:
    """Test Modbus read command building."""
    assert BMS._cmd(0x01, 0x03, 0x0000, 0x003B) == b"\x01\x03\x00\x00\x00\x3b\x04\x19"


def _build_test_frame(reg_values: dict[int, int]) -> bytearray:
    """Build a test frame with specific register values for edge case testing.

    Args:
        reg_values: Dict mapping register offset to 16-bit value

    Returns:
        Complete Modbus frame with CRC.

    """
    data = bytearray(118)  # 59 registers = 118 bytes
    # Set default valid values
    data[2:4] = (1332).to_bytes(2, "big")  # voltage
    data[4:6] = (97).to_bytes(2, "big")  # SOC
    data[28:30] = (0xC000).to_bytes(2, "big")  # MOS status (both on)

    # Apply custom register values
    for reg, val in reg_values.items():
        data[reg * 2 : reg * 2 + 2] = val.to_bytes(2, "big")

    frame: bytearray = bytearray([0x01, 0x03, len(data)]) + data
    frame.extend(crc_modbus(frame).to_bytes(2, "little"))
    return frame


@pytest.mark.parametrize(
    ("reg_values", "expected_key", "expected_value"),
    [
        # Single cell - delta should be 0
        ({15: 1, 16: 3329}, "delta_voltage", 0),
        # Zero cells - empty cell_voltages list
        ({15: 0}, "cell_voltages", []),
        # Zero temp sensors with invalid MOSFET temp - empty temp_values list
        ({46: 0, 57: 0xFFFF}, "temp_values", []),
        # Alarm flags set (6-byte big-endian: 0x000100020003)
        ({8: 0x0001, 9: 0x0002, 10: 0x0003}, "problem_code", 0x000100020003),
        # Zero capacity values are included as 0 (framework pattern)
        ({4: 0, 5: 0}, "cycle_charge", 0.0),
    ],
    ids=[
        "single_cell_delta_zero",
        "no_cells",
        "no_temps_invalid_mos",
        "alarm_flags",
        "zero_capacity",
    ],
)
async def test_edge_cases(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    reg_values: dict[int, int],
    expected_key: str,
    expected_value,
) -> None:
    """Test various edge cases with parametrized register values."""

    frame: bytearray = _build_test_frame(reg_values)
    monkeypatch.setattr(MockGobelBleakClient, "_RESP", frame)
    patch_bleak_client(MockGobelBleakClient)

    bms = BMS(generate_ble_device())
    result: BMSSample = await bms.async_update()

    assert result.get(expected_key) == expected_value

    await bms.disconnect()


async def test_mos_temp_ffff_invalid(
    monkeypatch: pytest.MonkeyPatch, patch_bleak_client
) -> None:
    """Test that MOSFET temperature of 0xFFFF is treated as invalid."""

    # Frame with 1 temp sensor at 25.0°C and invalid MOSFET temp
    frame: bytearray = _build_test_frame({46: 1, 47: 250, 57: 0xFFFF})
    monkeypatch.setattr(MockGobelBleakClient, "_RESP", frame)
    patch_bleak_client(MockGobelBleakClient)

    bms = BMS(generate_ble_device())
    result: BMSSample = await bms.async_update()

    # Should only have one temperature (not the invalid MOSFET temp)
    assert result.get("temp_values", []) == [25.0]

    await bms.disconnect()


def _build_device_info(length: int) -> bytearray:
    """Build device info frame with less than 60 bytes of data."""
    frame: bytearray = bytearray([0x01, 0x03, length]) + bytes(length)
    frame.extend(crc_modbus(frame).to_bytes(2, "little"))
    return frame


@pytest.mark.parametrize(
    "device_info_frame",
    [
        _build_device_info(40),
        _build_device_info(70),
        bytearray(),  # No response (timeout)
    ],
    ids=[
        "short_data",
        "empty_strings",
        "timeout",
    ],
)
async def test_device_info_edge_cases(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    patch_bms_timeout,
    device_info_frame: bytearray,
) -> None:
    """Test device info handling with various edge cases."""

    patch_bms_timeout()
    monkeypatch.setattr(MockGobelBleakClient, "_RESP_DEVICE_INFO", device_info_frame)
    patch_bleak_client(MockGobelBleakClient)

    bms = BMS(generate_ble_device())
    info: Final[BMSInfo] = await bms.device_info()

    # For short/timeout cases, model_id should not be present
    # For empty_strings case, model_id is present but empty
    if len(device_info_frame) >= 65:
        assert info.get("model_id") == ""
    else:
        assert "model_id" not in info

    await bms.disconnect()


async def test_unexpected_data_ignored(
    monkeypatch: pytest.MonkeyPatch, patch_bleak_client
) -> None:
    """Test that unexpected data without a started frame is ignored."""

    class MockUnexpectedDataBleakClient(MockGobelBleakClient):
        """Send unexpected data before valid response."""

        async def write_gatt_char(
            self,
            char_specifier: BleakGATTCharacteristic | int | str | UUID,
            data: Buffer,
            response: bool | None = None,
        ) -> None:
            """Issue write command and send unexpected continuation data."""
            await MockBleakClient.write_gatt_char(self, char_specifier, data, response)
            assert self._notify_callback is not None
            # Send data that looks like a continuation (doesn't start with slave addr)
            self._notify_callback(
                "MockUnexpectedDataBleakClient", bytearray([0xFF, 0xFF])
            )
            # Then send the valid response
            self._notify_callback(
                "MockUnexpectedDataBleakClient", bytearray(self._RESP)
            )

    monkeypatch.setattr(MockUnexpectedDataBleakClient, "_RESP", _FRAME_MAIN_DATA)
    patch_bleak_client(MockUnexpectedDataBleakClient)

    bms = BMS(generate_ble_device())
    assert await bms.async_update() == _RESULT_MAIN_DATA

    await bms.disconnect()


async def test_short_initial_frame(
    monkeypatch: pytest.MonkeyPatch, patch_bleak_client
) -> None:
    """Test handling of short initial frame that needs more data."""

    class MockMinFrameBleakClient(MockGobelBleakClient):
        """Send very short initial data then complete frame."""

        async def write_gatt_char(
            self,
            char_specifier: BleakGATTCharacteristic | int | str | UUID,
            data: Buffer,
            response: bool | None = None,
        ) -> None:
            """Issue write command and send short initial frame then rest."""
            await MockBleakClient.write_gatt_char(self, char_specifier, data, response)
            assert self._notify_callback is not None
            # First send a very short frame (less than MIN_FRAME_LEN=5)
            full_response = bytearray(self._RESP)
            self._notify_callback("MockMinFrameBleakClient", full_response[:3])
            # Then send the rest
            self._notify_callback("MockMinFrameBleakClient", full_response[3:])

    monkeypatch.setattr(MockMinFrameBleakClient, "_RESP", _FRAME_MAIN_DATA)
    patch_bleak_client(MockMinFrameBleakClient)

    bms = BMS(generate_ble_device())
    assert await bms.async_update() == _RESULT_MAIN_DATA

    await bms.disconnect()
