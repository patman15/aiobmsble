"""Test the Gobel Power BLE BMS implementation."""

from collections.abc import Buffer
from typing import Final
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.uuids import normalize_uuid_str
import pytest

from aiobmsble import BMSSample
from aiobmsble.basebms import crc_modbus
from aiobmsble.bms.gobel_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient

# Service and characteristic UUIDs for Gobel Power BMS
SERVICE_UUID = "00002760-08c2-11e1-9073-0e8ac72e1001"
TX_CHAR_UUID = "00002760-08c2-11e1-9073-0e8ac72e0001"
RX_CHAR_UUID = "00002760-08c2-11e1-9073-0e8ac72e0002"


def ref_value() -> BMSSample:
    """Return reference value for mock Gobel Power BMS.

    Based on actual device response analysis.
    """
    return {
        "voltage": 13.32,  # 1332 / 100
        "current": 0.0,  # 0 / 100
        "battery_level": 97,  # SOC % (Reg 2)
        "battery_health": 100,  # SOH % (Reg 3)
        "cycle_charge": 315.62,  # 31562 * 10 / 1000 Ah (Reg 4)
        "design_capacity": 324,  # 32493 // 100 Ah (Reg 5, int)
        "cycles": 1,  # Reg 7
        "cell_count": 4,
        "temp_sensors": 1,  # Reg 46
        "cell_voltages": [3.329, 3.332, 3.332, 3.331],  # mV / 1000
        "temp_values": [20.9, 20.9],  # T1 and Tmos
        "power": 0.0,
        "battery_charging": False,
        "chrg_mosfet": True,
        "dischrg_mosfet": True,
        "delta_voltage": 0.003,
    }


def build_gobel_response() -> bytearray:
    """Build a mock Gobel Power BMS response frame.

    Based on actual device capture:
    Read 59 registers from 0x0000 -> 118 bytes of data
    """
    # Build response data (59 registers = 118 bytes)
    data = bytearray(118)

    # Byte 0-1 (Reg 0): Current = 0 (0.00A)
    data[0:2] = (0).to_bytes(2, "big")

    # Byte 2-3 (Reg 1): Pack voltage = 1332 (13.32V)
    data[2:4] = (1332).to_bytes(2, "big")

    # Byte 4-5 (Reg 2): SOC = 97%
    data[4:6] = (97).to_bytes(2, "big")

    # Byte 6-7 (Reg 3): SOH = 100%
    data[6:8] = (100).to_bytes(2, "big")

    # Byte 8-9 (Reg 4): Remaining capacity = 31562 (*10 mAh = 315620 mAh)
    data[8:10] = (31562).to_bytes(2, "big")

    # Byte 10-11 (Reg 5): Full capacity = 32493 (*10 mAh = 324930 mAh)
    data[10:12] = (32493).to_bytes(2, "big")

    # Byte 12-13 (Reg 6): Unknown
    data[12:14] = (0).to_bytes(2, "big")

    # Byte 14-15 (Reg 7): Cycles = 1
    data[14:16] = (1).to_bytes(2, "big")

    # Bytes 16-27: Alarm/Protection/Fault and other flags (zeros)
    data[16:28] = bytes(12)

    # Byte 28-29 (Reg 14): MOS status = 0xC000 (both charge and discharge ON)
    data[28:30] = (0xC000).to_bytes(2, "big")

    # Byte 30-31 (Reg 15): Cell count = 4
    data[30:32] = (4).to_bytes(2, "big")

    # Bytes 32-39: Cell voltages (4 cells in mV)
    # Cell 1: 3329 mV, Cell 2: 3332 mV, Cell 3: 3332 mV, Cell 4: 3331 mV
    data[32:34] = (3329).to_bytes(2, "big")
    data[34:36] = (3332).to_bytes(2, "big")
    data[36:38] = (3332).to_bytes(2, "big")
    data[38:40] = (3331).to_bytes(2, "big")

    # Byte 92-93 (Reg 46): Temperature sensor count = 1
    data[92:94] = (1).to_bytes(2, "big")

    # Byte 94-95 (Reg 47): Temperature 1 = 209 (20.9°C)
    data[94:96] = (209).to_bytes(2, "big")

    # Byte 114-115 (Reg 57): MOSFET temperature = 209 (20.9°C)
    data[114:116] = (209).to_bytes(2, "big")

    # Build complete frame: slave_addr + func_code + byte_count + data + crc
    frame = bytearray([0x01, 0x03, len(data)])
    frame.extend(data)

    # Calculate and append CRC
    crc = crc_modbus(frame)
    frame.extend([crc & 0xFF, (crc >> 8) & 0xFF])

    return frame


def build_device_info_response() -> bytearray:
    """Build a mock Gobel Power BMS device info response frame.

    READ_CMD_3: Read 35 registers from 0x00AA -> 70 bytes of data
    """
    # Build response data (35 registers = 70 bytes)
    data = bytearray(70)

    # BMS Version: bytes 0-17 (null-terminated string)
    version = b"P4S200A-40569-1.02"
    data[0 : len(version)] = version

    # BMS Serial Number: bytes 20-39 (with trailing spaces)
    serial = b"4056911A1100032P    "
    data[20 : 20 + len(serial)] = serial

    # Pack Serial Number: bytes 40-60
    pack_sn = b"GP-LA12-31420250618"
    data[40 : 40 + len(pack_sn)] = pack_sn

    # Build complete frame: slave_addr + func_code + byte_count + data + crc
    frame = bytearray([0x01, 0x03, len(data)])
    frame.extend(data)

    # Calculate and append CRC
    crc = crc_modbus(frame)
    frame.extend([crc & 0xFF, (crc >> 8) & 0xFF])

    return frame


class MockGobelBleakClient(MockBleakClient):
    """Emulate a Gobel Power BMS BleakClient."""

    RESP: Final[bytearray] = build_gobel_response()
    RESP_DEVICE_INFO: Final[bytearray] = build_device_info_response()

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
    ) -> bytearray:
        # Check if this is a write to the TX characteristic
        if isinstance(char_specifier, str) and normalize_uuid_str(
            char_specifier
        ) == normalize_uuid_str(TX_CHAR_UUID):
            req_data = bytes(data)
            # Verify it's a valid Modbus read request
            if len(req_data) >= 8 and req_data[0] == 0x01 and req_data[1] == 0x03:
                # Check which command is being sent
                start_addr = (req_data[2] << 8) | req_data[3]
                if start_addr == 0x00AA:  # Device info command (READ_CMD_3)
                    return bytearray(MockGobelBleakClient.RESP_DEVICE_INFO)
                return bytearray(MockGobelBleakClient.RESP)  # Return a copy
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


class MockInvalidCRCBleakClient(MockGobelBleakClient):
    """Emulate a Gobel Power BMS with invalid CRC."""

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
    ) -> bytearray:
        response = bytearray(super()._response(char_specifier, data))  # Make a copy
        if response:
            # Corrupt the CRC
            response[-1] ^= 0xFF
        return response


class MockErrorResponseBleakClient(MockGobelBleakClient):
    """Emulate a Gobel Power BMS that returns an error response."""

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
    ) -> bytearray:
        if isinstance(char_specifier, str) and normalize_uuid_str(
            char_specifier
        ) == normalize_uuid_str(TX_CHAR_UUID):
            # Return Modbus error response: slave_addr + (func|0x80) + error_code + crc
            error_frame = bytearray([0x01, 0x83, 0x02])  # Illegal data address
            crc = crc_modbus(error_frame)
            error_frame.extend([crc & 0xFF, (crc >> 8) & 0xFF])
            return error_frame
        return bytearray()


class MockShortResponseBleakClient(MockGobelBleakClient):
    """Emulate a Gobel Power BMS that returns a short response."""

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
    ) -> bytearray:
        if isinstance(char_specifier, str) and normalize_uuid_str(
            char_specifier
        ) == normalize_uuid_str(TX_CHAR_UUID):
            # Return a valid but short response (only 20 bytes of data instead of 118)
            short_data = bytearray(20)
            short_data[2:4] = (1332).to_bytes(2, "big")  # voltage
            frame = bytearray([0x01, 0x03, len(short_data)])
            frame.extend(short_data)
            crc = crc_modbus(frame)
            frame.extend([crc & 0xFF, (crc >> 8) & 0xFF])
            return frame
        return bytearray()


class MockFragmentedResponseBleakClient(MockGobelBleakClient):
    """Emulate a Gobel Power BMS that sends fragmented responses."""

    def __init__(self, *args, **kwargs):
        """Initialize with fragment tracking."""
        super().__init__(*args, **kwargs)
        self._fragment_idx = 0

    async def write_gatt_char(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        data: Buffer,
        response: bool | None = None,
    ) -> None:
        """Issue write command to GATT and send fragmented response."""
        await MockBleakClient.write_gatt_char(self, char_specifier, data, response)
        assert self._notify_callback is not None

        full_response = build_gobel_response()
        # Send in 20-byte chunks to simulate BLE fragmentation
        chunk_size = 20
        for i in range(0, len(full_response), chunk_size):
            chunk = full_response[i : i + chunk_size]
            self._notify_callback("MockFragmentedBleakClient", bytearray(chunk))


async def test_update(
    patch_bleak_client,
    keep_alive_fixture: bool,
) -> None:
    """Test Gobel Power BMS data update."""
    patch_bleak_client(MockGobelBleakClient)

    bms = BMS(generate_ble_device(), keep_alive_fixture)

    result = await bms.async_update()
    expected = ref_value()

    # Check key values
    assert result.get("voltage") == expected["voltage"]
    assert result.get("current") == expected["current"]
    assert result.get("battery_level") == expected["battery_level"]
    assert result.get("battery_health") == expected["battery_health"]
    assert result.get("cycles") == expected["cycles"]
    assert result.get("cell_count") == expected["cell_count"]
    assert result.get("temp_sensors") == expected["temp_sensors"]
    assert result.get("chrg_mosfet") == expected["chrg_mosfet"]
    assert result.get("dischrg_mosfet") == expected["dischrg_mosfet"]

    # Check capacity values
    assert abs(result.get("cycle_charge", 0) - expected["cycle_charge"]) < 0.01
    assert result.get("design_capacity") == expected["design_capacity"]  # int value

    # Check cell voltages
    cell_voltages = result.get("cell_voltages", [])
    assert len(cell_voltages) == 4
    for i, v in enumerate(cell_voltages):
        assert abs(v - expected["cell_voltages"][i]) < 0.001

    # Check temperatures
    temperatures = result.get("temp_values", [])
    assert len(temperatures) == 2
    assert abs(temperatures[0] - 20.9) < 0.1
    assert abs(temperatures[1] - 20.9) < 0.1

    # Query again to check already connected state
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()


async def test_fragmented_response(patch_bleak_client) -> None:
    """Test handling of fragmented BLE responses."""
    patch_bleak_client(MockFragmentedResponseBleakClient)

    bms = BMS(generate_ble_device())
    result = await bms.async_update()

    # Should still parse correctly (same data as build_gobel_response)
    assert result.get("voltage") == 13.32
    assert result.get("battery_level") == 97  # SOC from reg 2

    await bms.disconnect()


async def test_invalid_crc(
    patch_bleak_client,
    patch_bms_timeout,
) -> None:
    """Test handling of invalid CRC."""
    patch_bms_timeout()
    patch_bleak_client(MockInvalidCRCBleakClient)

    bms = BMS(generate_ble_device())

    with pytest.raises(TimeoutError):
        await bms.async_update()

    await bms.disconnect()


async def test_error_response(
    patch_bleak_client,
    patch_bms_timeout,
) -> None:
    """Test handling of Modbus error response."""
    patch_bms_timeout()
    patch_bleak_client(MockErrorResponseBleakClient)

    bms = BMS(generate_ble_device())

    with pytest.raises(TimeoutError):
        await bms.async_update()

    await bms.disconnect()


async def test_short_response(patch_bleak_client) -> None:
    """Test handling of short response."""
    patch_bleak_client(MockShortResponseBleakClient)

    bms = BMS(generate_ble_device())
    result = await bms.async_update()

    # Should return empty dict due to insufficient data
    assert not result

    await bms.disconnect()


def test_matcher() -> None:
    """Test BMS matcher definition."""
    matchers = BMS.matcher_dict_list()
    assert len(matchers) == 1
    assert matchers[0]["local_name"] == "BMS-*"
    assert matchers[0]["connectable"] is True
    assert matchers[0]["service_uuid"] == SERVICE_UUID


def test_uuid_methods() -> None:
    """Test UUID method returns."""
    assert BMS.uuid_services() == [SERVICE_UUID]
    assert BMS.uuid_rx() == RX_CHAR_UUID
    assert BMS.uuid_tx() == TX_CHAR_UUID


def test_bms_info() -> None:
    """Test BMS info definition."""
    assert BMS.INFO["default_manufacturer"] == "Gobel Power"
    assert BMS.INFO["default_model"] == "BLE BMS"


def test_build_read_cmd() -> None:
    """Test Modbus read command building."""
    # Build command to read 59 registers starting at address 0
    cmd = BMS._build_read_cmd(0x0000, 0x003B)

    # Expected: 01 03 00 00 00 3B + CRC
    assert cmd[0] == 0x01  # Slave address
    assert cmd[1] == 0x03  # Function code (read)
    assert cmd[2:4] == b"\x00\x00"  # Start address
    assert cmd[4:6] == b"\x00\x3b"  # Number of registers (59 = 0x3B)
    assert len(cmd) == 8  # 6 bytes + 2 CRC

    # Verify CRC
    calculated_crc = crc_modbus(bytearray(cmd[:-2]))
    received_crc = int.from_bytes(cmd[-2:], "little")
    assert calculated_crc == received_crc


def test_parse_mos_status() -> None:
    """Test MOS status parsing.

    Bit 14 = charge, bit 15 = discharge.
    """
    # Both off
    charge, discharge = BMS._parse_mos_status(0x0000)
    assert charge is False
    assert discharge is False

    # Charge on only (bit 14)
    charge, discharge = BMS._parse_mos_status(0x4000)
    assert charge is True
    assert discharge is False

    # Discharge on only (bit 15)
    charge, discharge = BMS._parse_mos_status(0x8000)
    assert charge is False
    assert discharge is True

    # Both on (0xC000)
    charge, discharge = BMS._parse_mos_status(0xC000)
    assert charge is True
    assert discharge is True


def test_convert_signed_temp() -> None:
    """Test signed temperature conversion."""
    # Positive temperature: 25.0°C = 250
    assert BMS._convert_signed_temp(250) == 25.0

    # Zero temperature
    assert BMS._convert_signed_temp(0) == 0.0

    # Negative temperature: -10.0°C
    # In 2's complement 16-bit: 0xFFFF - 100 + 1 = 0xFF9C
    assert abs(BMS._convert_signed_temp(0xFF9C) - (-10.0)) < 0.01

    # Negative temperature: -5.5°C = -55 in raw
    # In 2's complement: 0xFFFF - 55 + 1 = 0xFFC9
    assert abs(BMS._convert_signed_temp(0xFFC9) - (-5.5)) < 0.01


async def test_device_info(patch_bleak_client) -> None:
    """Test fetching device info from BMS via Modbus."""
    patch_bleak_client(MockGobelBleakClient)

    bms = BMS(generate_ble_device())
    info = await bms.device_info()

    # Should have extracted the version, serial number, and model_id from the response
    assert info.get("sw_version") == "P4S200A-40569-1.02"
    assert info.get("serial_number") == "4056911A1100032P"
    assert info.get("model_id") == "GP-LA12-31420250618"

    await bms.disconnect()


class MockUnexpectedFuncCodeBleakClient(MockGobelBleakClient):
    """Emulate a Gobel Power BMS that returns unexpected function code."""

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
    ) -> bytearray:
        if isinstance(char_specifier, str) and normalize_uuid_str(
            char_specifier
        ) == normalize_uuid_str(TX_CHAR_UUID):
            # Return response with unexpected function code (0x10 = write instead of 0x03)
            return bytearray([0x01, 0x10, 0x00, 0x00, 0x00, 0x3B])
        return bytearray()


async def test_unexpected_function_code(
    patch_bleak_client,
    patch_bms_timeout,
) -> None:
    """Test handling of unexpected function code in response."""
    patch_bms_timeout()
    patch_bleak_client(MockUnexpectedFuncCodeBleakClient)

    bms = BMS(generate_ble_device())

    with pytest.raises(TimeoutError):
        await bms.async_update()

    await bms.disconnect()


class MockUnexpectedDataBleakClient(MockGobelBleakClient):
    """Emulate a Gobel Power BMS that sends unexpected data without prior frame."""

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
        # but no frame was started - this should be ignored
        self._notify_callback("MockUnexpectedDataBleakClient", bytearray([0xFF, 0xFF]))
        # Then send the valid response
        self._notify_callback(
            "MockUnexpectedDataBleakClient",
            bytearray(MockGobelBleakClient.RESP),
        )


async def test_unexpected_data_ignored(patch_bleak_client) -> None:
    """Test that unexpected data without a started frame is ignored."""
    patch_bleak_client(MockUnexpectedDataBleakClient)

    bms = BMS(generate_ble_device())
    result = await bms.async_update()

    # Should still parse correctly after ignoring unexpected data
    assert result.get("voltage") == 13.32

    await bms.disconnect()


async def test_alarm_protection_fault_flags(patch_bleak_client) -> None:
    """Test parsing of alarm/protection/fault status flags."""

    class MockAlarmBleakClient(MockGobelBleakClient):
        """Mock client with alarm flags set."""

        def _response(
            self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
        ) -> bytearray:
            if isinstance(char_specifier, str) and normalize_uuid_str(
                char_specifier
            ) == normalize_uuid_str(TX_CHAR_UUID):
                req_data = bytes(data)
                if len(req_data) >= 8 and req_data[0] == 0x01 and req_data[1] == 0x03:
                    # Build response with alarm flags set
                    response_data = bytearray(118)
                    response_data[2:4] = (1332).to_bytes(2, "big")  # voltage
                    response_data[4:6] = (97).to_bytes(2, "big")  # SOC
                    response_data[30:32] = (4).to_bytes(2, "big")  # cell count
                    response_data[28:30] = (0xC000).to_bytes(2, "big")  # MOS status
                    # Set alarm, protection, fault flags
                    response_data[16:18] = (0x0001).to_bytes(2, "big")  # alarm
                    response_data[18:20] = (0x0002).to_bytes(2, "big")  # protection
                    response_data[20:22] = (0x0003).to_bytes(2, "big")  # fault

                    frame = bytearray([0x01, 0x03, len(response_data)])
                    frame.extend(response_data)
                    crc = crc_modbus(frame)
                    frame.extend([crc & 0xFF, (crc >> 8) & 0xFF])
                    return frame
            return bytearray()

    patch_bleak_client(MockAlarmBleakClient)

    bms = BMS(generate_ble_device())
    result = await bms.async_update()

    # Check that problem_code is set when alarm/protection/fault are non-zero
    # problem_code = (alarm << 16) | (protection << 8) | fault
    # = (0x0001 << 16) | (0x0002 << 8) | 0x0003 = 0x010203 = 66051
    assert result.get("problem_code") == 66051

    await bms.disconnect()


async def test_no_cells_no_temps(patch_bleak_client) -> None:
    """Test parsing when cell count and temp count are zero."""

    class MockNoCellsBleakClient(MockGobelBleakClient):
        """Mock client with zero cells and temps."""

        def _response(
            self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
        ) -> bytearray:
            if isinstance(char_specifier, str) and normalize_uuid_str(
                char_specifier
            ) == normalize_uuid_str(TX_CHAR_UUID):
                req_data = bytes(data)
                if len(req_data) >= 8 and req_data[0] == 0x01 and req_data[1] == 0x03:
                    # Build response with zero cells and temps
                    response_data = bytearray(118)
                    response_data[2:4] = (1332).to_bytes(2, "big")  # voltage
                    response_data[4:6] = (97).to_bytes(2, "big")  # SOC
                    response_data[28:30] = (0xC000).to_bytes(2, "big")  # MOS status
                    # cell_count = 0
                    response_data[30:32] = (0).to_bytes(2, "big")
                    # temp_sensors = 0
                    response_data[92:94] = (0).to_bytes(2, "big")
                    # MOSFET temp = 0 (invalid, should be skipped)
                    response_data[114:116] = (0).to_bytes(2, "big")

                    frame = bytearray([0x01, 0x03, len(response_data)])
                    frame.extend(response_data)
                    crc = crc_modbus(frame)
                    frame.extend([crc & 0xFF, (crc >> 8) & 0xFF])
                    return frame
            return bytearray()

    patch_bleak_client(MockNoCellsBleakClient)

    bms = BMS(generate_ble_device())
    result = await bms.async_update()

    # Should not have cell_voltages or delta_voltage
    assert "cell_voltages" not in result
    assert "delta_voltage" not in result
    # Should not have temp_values when count is 0 and MOSFET temp is invalid
    assert "temp_values" not in result

    await bms.disconnect()


async def test_mos_temp_ffff_invalid(patch_bleak_client) -> None:
    """Test that MOSFET temperature of 0xFFFF is treated as invalid."""

    class MockInvalidMosTempBleakClient(MockGobelBleakClient):
        """Mock client with invalid MOSFET temperature."""

        def _response(
            self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
        ) -> bytearray:
            if isinstance(char_specifier, str) and normalize_uuid_str(
                char_specifier
            ) == normalize_uuid_str(TX_CHAR_UUID):
                req_data = bytes(data)
                if len(req_data) >= 8 and req_data[0] == 0x01 and req_data[1] == 0x03:
                    response_data = bytearray(118)
                    response_data[2:4] = (1332).to_bytes(2, "big")  # voltage
                    response_data[4:6] = (97).to_bytes(2, "big")  # SOC
                    response_data[28:30] = (0xC000).to_bytes(2, "big")  # MOS status
                    response_data[30:32] = (4).to_bytes(2, "big")  # cell count
                    # One temp sensor
                    response_data[92:94] = (1).to_bytes(2, "big")
                    response_data[94:96] = (250).to_bytes(2, "big")  # 25.0°C
                    # MOSFET temp = 0xFFFF (invalid)
                    response_data[114:116] = (0xFFFF).to_bytes(2, "big")

                    frame = bytearray([0x01, 0x03, len(response_data)])
                    frame.extend(response_data)
                    crc = crc_modbus(frame)
                    frame.extend([crc & 0xFF, (crc >> 8) & 0xFF])
                    return frame
            return bytearray()

    patch_bleak_client(MockInvalidMosTempBleakClient)

    bms = BMS(generate_ble_device())
    result = await bms.async_update()

    # Should only have one temperature (not the invalid MOSFET temp)
    temps = result.get("temp_values", [])
    assert len(temps) == 1
    assert abs(temps[0] - 25.0) < 0.1

    await bms.disconnect()


async def test_zero_capacity_values(patch_bleak_client) -> None:
    """Test that zero capacity values are not included in result."""

    class MockZeroCapBleakClient(MockGobelBleakClient):
        """Mock client with zero capacity values."""

        def _response(
            self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
        ) -> bytearray:
            if isinstance(char_specifier, str) and normalize_uuid_str(
                char_specifier
            ) == normalize_uuid_str(TX_CHAR_UUID):
                req_data = bytes(data)
                if len(req_data) >= 8 and req_data[0] == 0x01 and req_data[1] == 0x03:
                    response_data = bytearray(118)
                    response_data[2:4] = (1332).to_bytes(2, "big")  # voltage
                    response_data[4:6] = (97).to_bytes(2, "big")  # SOC
                    response_data[28:30] = (0xC000).to_bytes(2, "big")  # MOS status
                    response_data[30:32] = (1).to_bytes(2, "big")  # cell count = 1
                    # Zero capacity values
                    response_data[8:10] = (0).to_bytes(2, "big")  # remain_cap = 0
                    response_data[10:12] = (0).to_bytes(2, "big")  # full_cap = 0

                    frame = bytearray([0x01, 0x03, len(response_data)])
                    frame.extend(response_data)
                    crc = crc_modbus(frame)
                    frame.extend([crc & 0xFF, (crc >> 8) & 0xFF])
                    return frame
            return bytearray()

    patch_bleak_client(MockZeroCapBleakClient)

    bms = BMS(generate_ble_device())
    result = await bms.async_update()

    # Zero capacity values should not be included
    assert "cycle_charge" not in result
    assert "design_capacity" not in result

    await bms.disconnect()


async def test_single_cell_delta_zero(patch_bleak_client) -> None:
    """Test that delta_voltage is 0 for single cell (base class calculates it)."""

    class MockSingleCellBleakClient(MockGobelBleakClient):
        """Mock client with single cell."""

        def _response(
            self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
        ) -> bytearray:
            if isinstance(char_specifier, str) and normalize_uuid_str(
                char_specifier
            ) == normalize_uuid_str(TX_CHAR_UUID):
                req_data = bytes(data)
                if len(req_data) >= 8 and req_data[0] == 0x01 and req_data[1] == 0x03:
                    response_data = bytearray(118)
                    response_data[2:4] = (1332).to_bytes(2, "big")  # voltage
                    response_data[4:6] = (97).to_bytes(2, "big")  # SOC
                    response_data[28:30] = (0xC000).to_bytes(2, "big")  # MOS status
                    response_data[30:32] = (1).to_bytes(2, "big")  # cell count = 1
                    response_data[32:34] = (3329).to_bytes(2, "big")  # one cell

                    frame = bytearray([0x01, 0x03, len(response_data)])
                    frame.extend(response_data)
                    crc = crc_modbus(frame)
                    frame.extend([crc & 0xFF, (crc >> 8) & 0xFF])
                    return frame
            return bytearray()

    patch_bleak_client(MockSingleCellBleakClient)

    bms = BMS(generate_ble_device())
    result = await bms.async_update()

    # Should have cell_voltages, delta_voltage is 0 for 1 cell (calculated by base class)
    assert len(result.get("cell_voltages", [])) == 1
    assert result.get("delta_voltage") == 0

    await bms.disconnect()


class MockMinFrameBleakClient(MockGobelBleakClient):
    """Emulate a Gobel Power BMS that sends very short initial data."""

    async def write_gatt_char(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        data: Buffer,
        response: bool | None = None,
    ) -> None:
        """Issue write command and send short initial frame then complete frame."""
        await MockBleakClient.write_gatt_char(self, char_specifier, data, response)
        assert self._notify_callback is not None
        # First send a very short frame (less than MIN_FRAME_LEN=5)
        self._notify_callback("MockMinFrameBleakClient", bytearray([0x01, 0x03, 0x76]))
        # Then send the rest
        full_response = build_gobel_response()
        self._notify_callback("MockMinFrameBleakClient", bytearray(full_response[3:]))


async def test_short_initial_frame(patch_bleak_client) -> None:
    """Test handling of short initial frame that needs more data."""
    patch_bleak_client(MockMinFrameBleakClient)

    bms = BMS(generate_ble_device())
    result = await bms.async_update()

    # Should still parse correctly after receiving more data
    assert result.get("voltage") == 13.32

    await bms.disconnect()


class MockDeviceInfoShortBleakClient(MockGobelBleakClient):
    """Emulate BMS returning short device info (less than 60 bytes)."""

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
    ) -> bytearray:
        if isinstance(char_specifier, str) and normalize_uuid_str(
            char_specifier
        ) == normalize_uuid_str(TX_CHAR_UUID):
            req_data = bytes(data)
            if len(req_data) >= 8 and req_data[0] == 0x01 and req_data[1] == 0x03:
                start_addr = (req_data[2] << 8) | req_data[3]
                if start_addr == 0x00AA:  # Device info command
                    # Return response with less than 60 bytes of data
                    short_data = bytearray(40)  # Less than 60
                    frame = bytearray([0x01, 0x03, len(short_data)])
                    frame.extend(short_data)
                    crc = crc_modbus(frame)
                    frame.extend([crc & 0xFF, (crc >> 8) & 0xFF])
                    return frame
                return bytearray(MockGobelBleakClient.RESP)
        return bytearray()


async def test_device_info_short_data(patch_bleak_client) -> None:
    """Test device info with short data (less than 60 bytes)."""
    patch_bleak_client(MockDeviceInfoShortBleakClient)

    bms = BMS(generate_ble_device())
    # This should not crash - the short data path should just skip parsing
    info = await bms.device_info()

    # We get mock BT info values, but not the Modbus-parsed values
    # model_id is NOT in BT_INFO, so it shouldn't be present
    assert "model_id" not in info

    await bms.disconnect()


class MockDeviceInfoEmptyStringsBleakClient(MockGobelBleakClient):
    """Emulate BMS returning empty strings in device info."""

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
    ) -> bytearray:
        if isinstance(char_specifier, str) and normalize_uuid_str(
            char_specifier
        ) == normalize_uuid_str(TX_CHAR_UUID):
            req_data = bytes(data)
            if len(req_data) >= 8 and req_data[0] == 0x01 and req_data[1] == 0x03:
                start_addr = (req_data[2] << 8) | req_data[3]
                if start_addr == 0x00AA:  # Device info command
                    # Return response with 70 bytes but all nulls (empty strings)
                    empty_data = bytearray(70)
                    frame = bytearray([0x01, 0x03, len(empty_data)])
                    frame.extend(empty_data)
                    crc = crc_modbus(frame)
                    frame.extend([crc & 0xFF, (crc >> 8) & 0xFF])
                    return frame
                return bytearray(MockGobelBleakClient.RESP)
        return bytearray()


async def test_device_info_empty_strings(patch_bleak_client) -> None:
    """Test device info with empty version/serial strings."""
    patch_bleak_client(MockDeviceInfoEmptyStringsBleakClient)

    bms = BMS(generate_ble_device())
    info = await bms.device_info()

    # We get mock BT info values, but the Modbus-parsed values should not override
    # since the strings are empty. model_id is specific to Modbus parsing.
    assert "model_id" not in info

    await bms.disconnect()


class MockDeviceInfoExceptionBleakClient(MockGobelBleakClient):
    """Emulate BMS where device info Modbus read times out."""

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
    ) -> bytearray:
        if isinstance(char_specifier, str) and normalize_uuid_str(
            char_specifier
        ) == normalize_uuid_str(TX_CHAR_UUID):
            req_data = bytes(data)
            if len(req_data) >= 8 and req_data[0] == 0x01 and req_data[1] == 0x03:
                start_addr = (req_data[2] << 8) | req_data[3]
                if start_addr == 0x00AA:  # Device info command
                    # Return no response to trigger timeout
                    return bytearray()
                return bytearray(MockGobelBleakClient.RESP)
        return bytearray()


async def test_device_info_modbus_timeout(
    patch_bleak_client,
    patch_bms_timeout,
) -> None:
    """Test device info handles Modbus timeout gracefully."""
    patch_bms_timeout()
    patch_bleak_client(MockDeviceInfoExceptionBleakClient)

    bms = BMS(generate_ble_device())

    # device_info will attempt Modbus read which times out
    # The exception is caught in _fetch_device_info, so we still get BT info
    info = await bms.device_info()

    # Should have BT info but not Modbus-specific values
    assert info.get("model") == "mock_model"
    assert "model_id" not in info  # model_id comes from Modbus parsing only

    await bms.disconnect()
