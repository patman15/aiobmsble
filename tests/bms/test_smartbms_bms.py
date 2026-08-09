"""Test the 123SmartBMS implementation."""

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.service import BleakGATTService
import pytest

from aiobmsble import BMSConfig, BMSSample, TempSensor as TS
from aiobmsble.bms.smartbms_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import BMSBasicTests, verify_device_info

_NOTIFY_CHAR: BleakGATTCharacteristic = BleakGATTCharacteristic(
    None,
    1,
    BMS.uuid_rx(),
    ["notify"],
    lambda: 512,
    BleakGATTService(None, 0, BMS.uuid_services()[0]),
)


def _frame(
    *,
    cell_nr: int = 0,
    cell_count: int = 16,
    cell_v: int = 0x0272,
    cell_t: int = 0x0128,
    key: int = 0,
    kv: int = 0,
    current_sign: int = ord("+"),
    current: int = 0x0040,
    status: int = 0x03,
    soc: int = 75,
    energy: int = 0x0FA0,
    capacity: int = 0x00A0,
) -> bytes:
    """Build a valid 58 byte status frame, checksum appended."""
    frame: bytearray = bytearray(58)
    frame[0:3] = (0x0105FF).to_bytes(3, "big")  # battery voltage 335.355 V
    frame[3] = ord("+")  # charge current sign
    frame[4:6] = (0x0000).to_bytes(2, "big")  # charge current
    frame[6] = ord("X")  # discharge current sign (unknown)
    frame[7:9] = (0x0000).to_bytes(2, "big")  # discharge current
    frame[9] = current_sign  # total current sign
    frame[10:12] = current.to_bytes(2, "big")  # total current (8.0 A)
    frame[12:14] = (0x0272).to_bytes(2, "big")  # min cell voltage 3.13 V
    frame[14] = 1  # min cell number
    frame[15:17] = (0x0280).to_bytes(2, "big")  # max cell voltage 3.2 V
    frame[17] = cell_count  # max cell number
    frame[18:20] = (0x0128).to_bytes(2, "big")  # min cell temp 20 degC
    frame[20] = 1  # min temp cell number
    frame[21:23] = (0x0128).to_bytes(2, "big")  # max cell temp 20 degC
    frame[23] = cell_count  # max temp cell number
    frame[24] = cell_nr  # number of cell whose data is transferred
    frame[25] = cell_count  # cell count
    frame[26:28] = cell_v.to_bytes(2, "big")  # specific cell voltage
    frame[28:30] = cell_t.to_bytes(2, "big")  # specific cell temperature
    frame[30] = status  # status byte 1
    frame[34:37] = energy.to_bytes(3, "big")  # stored energy in Wh
    frame[40] = soc  # SoC in %
    frame[47] = key + 25  # key/value pair key
    frame[48] = kv  # key/value pair value
    frame[49:51] = capacity.to_bytes(2, "big")  # capacity in 0.1 kWh
    frame[51:57] = b"\x00\x00\x00\x00\x00\x00"  # V-min/max/balance settings
    frame[57] = sum(frame[:57]) & 0xFF  # checksum
    return bytes(frame)


def _stream() -> bytes:
    """Build a notification stream with all cells and key/value pairs."""
    frames: list[bytes] = [
        _frame(cell_nr=nr, cell_v=0x0270 + nr - 1) for nr in range(1, 17)
    ]
    frames += [
        _frame(key=0, kv=98),  # SoH
        _frame(key=4, kv=0x02),  # nominal cell voltage high byte
        _frame(key=5, kv=0x80),  # nominal cell voltage low byte (3.2 V)
        _frame(key=8, kv=0x04),  # charge cycles high byte
        _frame(key=9, kv=0xD2),  # charge cycles low byte (1234)
        _frame(key=16, kv=0x00),  # status byte 2 (no alarms)
    ]
    return b"".join(frames)


_RESULT_DEFS: BMSSample = {
    "voltage": 335.355,
    "current": 8.0,
    "battery_level": 75,
    "cell_count": 16,
    "chrg_mosfet": True,
    "dischrg_mosfet": True,
    "problem_code": 0,
    "delta_voltage": 0.07,
    "temp_values": [TS(20, TS.T.CELL_MIN), TS(20, TS.T.CELL_MAX)]
    + [TS(20, TS.T.CELL) for _ in range(16)],
    "cell_voltages": [(0x0270 + nr - 1) / 200 for nr in range(1, 17)],
    "battery_health": 98,
    "cycles": 1234,
    "design_capacity": 312,
    "cycle_capacity": 4000,
    "battery_charging": True,
    "power": 2682.84,
    "cycle_charge": 234.0,
    "temperature": 20.0,
    "problem": False,
}


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


class MockSmartBMSBleakClient(MockBleakClient):
    """Emulate a 123SmartBMS BLE UART bridge BleakClient."""

    STREAM: bytes = _stream()

    async def start_notify(self, char_specifier, callback, **kwargs) -> None:
        """Mock start_notify."""
        await super().start_notify(char_specifier, callback, **kwargs)
        assert self._notify_callback is not None
        if self.STREAM:
            self._notify_callback("MockSmartBMSBleakClient", bytearray(self.STREAM))


async def test_update(patch_bleak_client, keep_alive_fixture: bool) -> None:
    """Test 123SmartBMS data update."""

    patch_bleak_client(MockSmartBMSBleakClient)

    bms = BMS(generate_ble_device(), BMSConfig(keep_alive_fixture))

    assert await bms.async_update() == _RESULT_DEFS

    # query again to check already connected state
    if keep_alive_fixture:
        bms._notification_handler(
            _NOTIFY_CHAR, bytearray(MockSmartBMSBleakClient.STREAM)
        )
    assert await bms.async_update() == _RESULT_DEFS
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()


async def test_partial_update(monkeypatch, patch_bleak_client) -> None:
    """Test data update if not all cells have been received yet."""

    partial: bytes = b"".join(
        _frame(cell_nr=nr, cell_v=0x0270 + nr - 1, key=99, kv=0) for nr in (1, 2, 3)
    ) + _frame(key=99, kv=0)
    monkeypatch.setattr(MockSmartBMSBleakClient, "STREAM", partial)
    patch_bleak_client(MockSmartBMSBleakClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = await bms.async_update()
    assert "cell_voltages" not in result
    assert "battery_health" not in result
    assert "cycles" not in result
    assert "design_capacity" not in result
    assert result["temperature"] == 20.0
    assert result["cycle_capacity"] == 4000

    await bms.disconnect()


async def test_fragmented_stream(monkeypatch, patch_bleak_client) -> None:
    """Test data update with the stream split into chunks across notifications."""

    monkeypatch.setattr(MockSmartBMSBleakClient, "STREAM", b"")
    patch_bleak_client(MockSmartBMSBleakClient)

    bms = BMS(generate_ble_device())
    await bms._connect()

    stream: bytes = _stream()
    for i in range(0, len(stream), 70):  # odd chunk size, frames split mid-way
        bms._notification_handler(_NOTIFY_CHAR, bytearray(stream[i : i + 70]))

    assert await bms.async_update() == _RESULT_DEFS
    await bms.disconnect()


@pytest.mark.parametrize(
    ("current_sign", "expected_current", "expected_power", "expected_charging"),
    [
        (ord("-"), -8.0, -2682.84, False),
        (ord("X"), 0.0, 0.0, False),
    ],
    ids=["discharge", "unknown"],
)
async def test_current_signs(
    monkeypatch,
    patch_bleak_client,
    current_sign: int,
    expected_current: float,
    expected_power: float,
    expected_charging: bool,
) -> None:
    """Test current decoding with discharge and unknown sign."""

    monkeypatch.setattr(
        MockSmartBMSBleakClient, "STREAM", _frame(current_sign=current_sign)
    )
    patch_bleak_client(MockSmartBMSBleakClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = await bms.async_update()
    assert result["current"] == expected_current
    assert result["battery_charging"] is expected_charging
    assert result["power"] == expected_power

    await bms.disconnect()


@pytest.mark.parametrize(
    ("status", "status2", "expected"),
    [
        (0x03, 0x00, 0x00),
        (0x2C, 0x00, 0x0B),
        (0x03, 0x0E, 0x0E),
        (0x2C, 0x0A, 0x0B),
    ],
    ids=["ok", "status1_alarm", "status2_alarm", "both_alarm"],
)
async def test_problem_response(
    monkeypatch,
    patch_bleak_client,
    status: int,
    status2: int,
    expected: int,
) -> None:
    """Test data update with BMS returning error flags."""

    monkeypatch.setattr(
        MockSmartBMSBleakClient,
        "STREAM",
        _frame(status=status, key=16, kv=status2),
    )
    patch_bleak_client(MockSmartBMSBleakClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = await bms.async_update()
    assert result["problem_code"] == expected
    assert result["problem"] is (expected != 0)

    await bms.disconnect()


async def test_battery_health_guard(monkeypatch, patch_bleak_client) -> None:
    """Test that out-of-range SoH is ignored."""

    stream: bytes = b"".join(
        [_frame(key=4, kv=0x02), _frame(key=5, kv=0x80), _frame(key=0, kv=101)]
    )
    monkeypatch.setattr(MockSmartBMSBleakClient, "STREAM", stream)
    patch_bleak_client(MockSmartBMSBleakClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = await bms.async_update()
    assert "battery_health" not in result
    assert result["design_capacity"] == 312

    await bms.disconnect()


async def test_zero_nominal_voltage(monkeypatch, patch_bleak_client) -> None:
    """Test that design capacity is skipped if the nominal voltage is zero."""

    stream: bytes = b"".join(
        [_frame(key=0, kv=98), _frame(key=4, kv=0x00), _frame(key=5, kv=0x00)]
    )
    monkeypatch.setattr(MockSmartBMSBleakClient, "STREAM", stream)
    patch_bleak_client(MockSmartBMSBleakClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = await bms.async_update()
    assert result["battery_health"] == 98
    assert "design_capacity" not in result

    await bms.disconnect()


@pytest.mark.parametrize(
    ("cell_nr", "id_"),
    [(0, "zero"), (17, "too_high")],
    ids=["zero", "too_high"],
)
async def test_out_of_range_cell(
    monkeypatch, patch_bleak_client, cell_nr: int, id_: str
) -> None:
    """Test that out-of-range cell info is ignored."""

    monkeypatch.setattr(
        MockSmartBMSBleakClient,
        "STREAM",
        _frame(cell_nr=cell_nr, key=99, kv=0),
    )
    patch_bleak_client(MockSmartBMSBleakClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = await bms.async_update()
    assert "cell_voltages" not in result
    assert "battery_health" not in result

    await bms.disconnect()


@pytest.mark.parametrize(
    ("invalid_stream"),
    [
        b"",
        _frame()[:40],
        bytes(_frame()[:-1]) + b"\x00",
    ],
    ids=["empty", "truncated", "wrong_checksum"],
)
async def test_invalid_frame(
    monkeypatch,
    patch_bleak_client,
    patch_bms_timeout,
    invalid_stream: bytes,
) -> None:
    """Test data update with the BMS returning invalid data."""

    patch_bms_timeout("smartbms_bms")
    monkeypatch.setattr(MockSmartBMSBleakClient, "STREAM", invalid_stream)
    patch_bleak_client(MockSmartBMSBleakClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = {}
    with pytest.raises(TimeoutError):
        result = await bms.async_update()

    assert not result
    await bms.disconnect()


async def test_device_info(patch_bleak_client) -> None:
    """Test that the BMS returns initialized dynamic device information."""
    await verify_device_info(patch_bleak_client, MockSmartBMSBleakClient, BMS)


def test_uuid_tx() -> None:
    """Test that the TX UUID of the Nordic UART service is returned."""
    assert BMS.uuid_tx() == "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
