"""Tests for Pro BMS plugin.

Note: Test values updated on 2025-08-06 to match corrected field offsets:
- All field offsets validated against 987 Pro BMS packets
- Power field: Confirmed at data_section offset 28 (packet bytes 32-35)
- Power values cross-validated with V×I calculation (0.019% average error)
"""

import asyncio
import contextlib
import logging

from bleak.backends.device import BLEDevice
import pytest

from aiobmsble import BMSSample
from aiobmsble.bms.pro_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import verify_device_info

# Actual recorded packets from device logs
RECORDED_PACKETS: dict[str, bytearray] = {
    "init_response": bytearray.fromhex(
        "55aa080380aa01040000002c52"
    ),  # Initialization response packet fct. 0x04
    "data_discharging": bytearray.fromhex(
        "55aa2d0480aa01701c05000096090080e2000000ad19000033000000ca050000890c0000770b0000044e000082648e684000"
    ),  # fct. 0x70, 13.08V, -2.454A, 22.6°C, 51% SOC
    "data_charging": bytearray.fromhex(
        "55aa2d0480aa01703b05000066340000da00000057100000200000008601000029460000580a0000eb4600000bd98c68afff"
    ),  # fct. 0x70, 13.39V, 13.414A, 21.8°C, 32% SOC
    "data_with_protection": bytearray.fromhex(
        "55aa2d0480aa01701c05000096090081e2000000ad19000033000000ca050000890c0000770b0000044e000082648e684000"
    ),  # fct. 0x70, Same as discharging but with protection bit
    "data_zero_soc": bytearray.fromhex(
        "55aa2d0480aa01703b05000066340000da00000057100000000000008601000029460000580a0000eb4600000bd98c68afff"
    ),  # fct. 0x70, Same as charging but with 0% SOC
    "basic_machine_info": bytearray.fromhex(
        "55aa200380aa0140008000000002000000f7040000c800000004010000065eaf7a4ee0f700"
    ),  # fct. 0x40, SW version 0x0104 => 1.4
}


class MockProBMSBleakClient(MockBleakClient):
    """Mock Pro BMS BleakClient for testing."""

    _init_packet: bytearray = RECORDED_PACKETS["init_response"]

    def __init__(
        self, address_or_ble_device, disconnected_callback=None, **kwargs
    ) -> None:
        """Initialize the mock client."""
        super().__init__(address_or_ble_device, disconnected_callback, **kwargs)
        self._test_packet: bytearray = RECORDED_PACKETS["data_discharging"]
        self._streaming_task: asyncio.Task[None] | None = None
        self._stop_streaming: bool = False

    def set_test_packet(self, packet: bytearray) -> None:
        """Set the packet to return."""
        self._test_packet = packet

    async def _stream_data(self) -> None:
        """Continuously stream data packets like a real device."""
        # Wait for initialization to complete and the 1-second sleep

        while not self._stop_streaming:
            if self._notify_callback and self._test_packet:
                self._notify_callback(None, self._test_packet)
            await asyncio.sleep(0.5)  # Send data every 500ms

    async def write_gatt_char(self, char_specifier, data, response=None):
        """Mock write to handle initialization and data requests."""
        await super().write_gatt_char(char_specifier, data, response)

        if data == BMS._HEAD + BMS._CMD_INIT:
            # Send initialization response
            if self._notify_callback:
                self._notify_callback(None, self._init_packet)

        elif data == BMS._HEAD + BMS._CMD_TRIGGER_DATA:
            # Start streaming data packets
            if not self._streaming_task:
                self._stop_streaming = False
                self._streaming_task = asyncio.create_task(self._stream_data())

    async def disconnect(self) -> None:
        """Stop streaming on disconnect."""
        self._stop_streaming = True
        if self._streaming_task:
            self._streaming_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._streaming_task
        await super().disconnect()


@pytest.mark.asyncio
async def test_async_update_discharging(patch_bleak_client) -> None:
    """Test async update with discharging data."""
    device: BLEDevice = generate_ble_device("AA:BB:CC:DD:EE:FF", "Pro BMS")
    mock_client: MockProBMSBleakClient = MockProBMSBleakClient(device)
    mock_client.set_test_packet(RECORDED_PACKETS["data_discharging"])
    patch_bleak_client(lambda *args, **kwargs: mock_client)

    bms = BMS(device)

    assert await bms.async_update() == {
        "voltage": 13.08,
        "current": -2.454,  # 0x96090080: discharge
        "temperature": 22.6,
        "battery_level": 51,
        "battery_charging": False,
        "cycle_charge": 65.73,
        "cycle_capacity": 859.748,
        "power": -32.09,
        "runtime": 96425,
        "problem_code": 0,
        "problem": False,
    }

    await bms.disconnect()


@pytest.mark.asyncio
async def test_async_update_charging(patch_bleak_client) -> None:
    """Test async update with charging data."""
    device: BLEDevice = generate_ble_device("AA:BB:CC:DD:EE:FF", "Pro BMS")
    mock_client: MockProBMSBleakClient = MockProBMSBleakClient(device)
    mock_client.set_test_packet(RECORDED_PACKETS["data_charging"])
    patch_bleak_client(lambda *args, **kwargs: mock_client)

    bms = BMS(device)

    assert await bms.async_update() == {
        "voltage": 13.39,
        "current": 13.414,
        "temperature": 21.8,
        "battery_level": 32,
        "battery_charging": True,
        "cycle_charge": 41.83,
        "cycle_capacity": 560.104,
        "power": 179.61,
        "problem_code": 0,
        "problem": False,
    }
    await bms.disconnect()


@pytest.mark.asyncio
async def test_async_update_with_protection(patch_bleak_client) -> None:
    """Test async update with protection status."""
    device: BLEDevice = generate_ble_device("AA:BB:CC:DD:EE:FF", "Pro BMS")
    mock_client: MockProBMSBleakClient = MockProBMSBleakClient(device)
    mock_client.set_test_packet(RECORDED_PACKETS["data_with_protection"])
    patch_bleak_client(lambda *args, **kwargs: mock_client)

    bms = BMS(device)

    assert await bms.async_update() == {
        "voltage": 13.08,
        "current": -2.454,  # 0x96090080: discharge
        "temperature": 22.6,
        "battery_level": 51,
        "battery_charging": False,
        "cycle_charge": 65.73,
        "cycle_capacity": 859.748,
        "power": -32.09,
        "runtime": 96425,
        "problem_code": 1,  # 0x81 & 0x7F = 1
        "problem": True,
    }
    await bms.disconnect()


async def test_device_info(patch_bleak_client) -> None:
    """Test that the BMS returns initialized dynamic device information."""
    await verify_device_info(patch_bleak_client, MockProBMSBleakClient, BMS)


@pytest.mark.asyncio
async def test_async_update_incomplete_data(
    patch_bleak_client, patch_bms_timeout
) -> None:
    """Test handling of incomplete data packet."""
    device: BLEDevice = generate_ble_device("AA:BB:CC:DD:EE:FF", "Pro BMS")
    mock_client: MockProBMSBleakClient = MockProBMSBleakClient(device)
    # Set incomplete data (too short)
    mock_client.set_test_packet(bytearray.fromhex("55aa0d0480aa0170"))
    patch_bms_timeout("pro_bms")
    patch_bleak_client(lambda *args, **kwargs: mock_client)

    bms = BMS(device)

    result: BMSSample = {}
    with pytest.raises(TimeoutError):
        await bms.async_update()  # Should return empty dict for incomplete data
    assert not result

    await bms.disconnect()


@pytest.mark.asyncio
async def test_async_update_already_streaming(patch_bleak_client) -> None:
    """Test async update when already streaming (second update)."""
    device: BLEDevice = generate_ble_device("AA:BB:CC:DD:EE:FF", "Pro BMS")
    mock_client: MockProBMSBleakClient = MockProBMSBleakClient(device)
    mock_client.set_test_packet(RECORDED_PACKETS["data_charging"])
    patch_bleak_client(lambda *args, **kwargs: mock_client)

    bms = BMS(device, keep_alive=True)

    # First update to initialize
    await bms.async_update()

    # Second update should reuse existing connection
    assert await bms.async_update() == {
        "voltage": 13.39,
        "current": 13.414,
        "temperature": 21.8,
        "battery_level": 32,
        "battery_charging": True,
        "cycle_charge": 41.83,
        "cycle_capacity": 560.104,
        "power": 179.61,
        "problem_code": 0,
        "problem": False,
    }

    await bms.disconnect()


@pytest.mark.asyncio
async def test_async_update_no_data_after_init(
    monkeypatch: pytest.MonkeyPatch, patch_bleak_client, patch_bms_timeout
) -> None:
    """Test when initialization completes but no valid data is received."""

    # Replace write_gatt_char to send init response after trigger command
    # This will set the event but not _streaming
    # FIXME! put into class
    async def mock_write(self, char, data, response=None) -> None:
        await MockBleakClient.write_gatt_char(self, char, data, response)
        assert self._notify_callback is not None
        if data == BMS._CMD_INIT:
            # Send initialization response
            self._notify_callback(None, RECORDED_PACKETS["init_response"])
        elif data == BMS._CMD_TRIGGER_DATA:
            # Wait for the 1-second sleep and event clear to complete
            async def send_wrong_packet() -> None:
                # Send another init response instead of data
                self._notify_callback(None, RECORDED_PACKETS["init_response"])

            # Store task reference to prevent garbage collection
            self._streaming_task = asyncio.create_task(send_wrong_packet())

    monkeypatch.setattr(MockProBMSBleakClient, "write_gatt_char", mock_write)

    patch_bms_timeout()
    patch_bleak_client(MockProBMSBleakClient)

    bms = BMS(generate_ble_device(name="Pro BMS"))

    result: BMSSample = {}
    with pytest.raises(TimeoutError):
        result = await bms.async_update()

    assert not result
    assert (
        not bms._client.is_connected
    ), "BMS should be disconnected if streaming is not working."


@pytest.mark.parametrize(
    ("wrong_response"),
    [
        b"\x55\xaa\x07\x03\x80\xaa\x01\x04\x00\x00\x00\x2c\x52",
        RECORDED_PACKETS["data_zero_soc"],
        b"\x00\xaa\x08\x03\x80\xaa\x01\x04\x00\x00\x00\x2c\x52",
        b"\x55\xaa\x08\x03",
        b"",
    ],
    ids=[
        "wrong_length",
        "unexpected_RT_data",
        "invalid_header",
        "short_packet",
        "empty_packet",
    ],
)
async def test_invalid_response(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    patch_bms_timeout,
    wrong_response,
    caplog,
) -> None:
    """Test data up date with BMS returning invalid data."""

    patch_bms_timeout()
    monkeypatch.setattr(MockProBMSBleakClient, "_init_packet", wrong_response)
    patch_bleak_client(MockProBMSBleakClient)

    bms = BMS(generate_ble_device())

    logging.getLogger(__name__)
    result: BMSSample = {}
    with caplog.at_level(logging.DEBUG), pytest.raises(TimeoutError):
        result = await bms.async_update()
    assert not result
    assert "failed to initialize BMS connection" in caplog.text

    await bms.disconnect()
