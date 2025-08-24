"""Test the BLE Battery Management System base class functions."""

from collections.abc import Buffer, Callable
from logging import DEBUG
from typing import Final, NoReturn
from uuid import UUID

from bleak.assigned_numbers import CharacteristicPropertyName
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak.uuids import normalize_uuid_str
import pytest

from aiobmsble.basebms import (
    AdvertisementPattern,
    BaseBMS,
    BMSdp,
    BMSsample,
    crc8,
    crc_modbus,
    crc_sum,
    crc_xmodem,
    lrc_modbus,
)

from .bluetooth import generate_ble_device
from .conftest import MockBleakClient


class MockWriteModeBleakClient(MockBleakClient):
    """Emulate a BleakClient with selectable write mode response."""

    # The following attributes are used to simulate the behavior of the BleakClient
    # They need to be set via monkeypatching in the test since init() is called by the BMS
    PATTERN: list[bytes | Exception | None] = []  # data that is set to problem_code
    VALID_WRITE_MODES: list[CharacteristicPropertyName] = [
        "write-without-response",
        "write",
    ]
    EXP_WRITE_RESPONSE: list[bool] = []

    async def write_gatt_char(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        data: Buffer,
        response: bool | None = None,
    ) -> None:
        """Issue write command to GATT."""
        await super().write_gatt_char(char_specifier, data, response)

        assert self._notify_callback is not None
        if self.PATTERN:
            # check if we have a pattern to return
            pattern: bytes | Exception | None = self.PATTERN.pop(0)
            exp_wr_mode: Final[bool] = self.EXP_WRITE_RESPONSE.pop(0)
            if isinstance(pattern, Exception):
                raise pattern

            req_wr_mode: Final[str] = "write" if response else "write-without-response"
            assert response == exp_wr_mode, "write response mismatch"

            if isinstance(pattern, bytes) and req_wr_mode in self.VALID_WRITE_MODES:
                # check if we have a dict to return
                self._notify_callback("rx_char", bytearray(pattern))
                return

            # if None was selected do not return (trigger timeout) and wait for next pattern
            return

        # no pattern left, raise exception
        raise ValueError


class MinTestBMS(BaseBMS):
    """Minimal Test BMS implementation."""

    @staticmethod
    def matcher_dict_list() -> list[AdvertisementPattern]:
        """Provide BluetoothMatcher definition."""
        return [{"local_name": "Test", "connectable": True}]

    @staticmethod
    def device_info() -> dict[str, str]:
        """Return device information for the battery management system."""
        return {"manufacturer": "Test Manufacturer", "model": "minimal BMS for test"}

    @staticmethod
    def uuid_services() -> list[str]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return [normalize_uuid_str("afe0")]

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "afe1"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        return "afe2"

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        self._log.debug("RX BLE data: %s", data)
        # do not set event to make tests fail if wait_for_notify is not set

    async def _async_update(self) -> BMSsample:
        """Update battery status information."""
        await self._await_reply(b"mock_command", wait_for_notify=False)  # do not wait
        return {"problem_code": 21}


class WMTestBMS(MinTestBMS):
    """Test BMS implementation."""

    def __init__(
        self,
        char_tx_properties: list[str],
        ble_device: BLEDevice,
        reconnect: bool = False,
    ) -> None:
        """Initialize BMS."""
        super().__init__(ble_device, reconnect)
        self._char_tx_properties: list[str] = char_tx_properties

    def _wr_response(self, char: int | str) -> bool:
        return bool("write" in self._char_tx_properties)

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        self._log.debug("RX BLE data: %s", data)
        self._data = data
        self._data_event.set()

    async def _async_update(self) -> BMSsample:
        """Update battery status information."""
        await self._await_reply(b"mock_command")

        return {"problem_code": int.from_bytes(self._data, "big", signed=False)}


def test_calc_missing_values(bms_data_fixture: BMSsample) -> None:
    """Check if missing data is correctly calculated."""
    bms_data: BMSsample = bms_data_fixture
    ref: BMSsample = bms_data_fixture.copy()

    BaseBMS._add_missing_values(
        bms_data,
        frozenset(
            {
                "battery_charging",
                "cycle_capacity",
                "power",
                "runtime",
                "delta_voltage",
                "temperature",
                "voltage",  # check that not overwritten
            }
        ),
    )
    ref = ref | {
        "cycle_capacity": 238,
        "delta_voltage": 0.111,
        "power": (
            -91
            if bms_data.get("current", 0) < 0
            else 0 if bms_data.get("current") == 0 else 147
        ),
        # battery is charging if current is positive
        "battery_charging": bms_data.get("current", 0) > 0,
        "temperature": -34.396,
        "problem": False,
    }
    if bms_data.get("current", 0) < 0:
        ref |= {"runtime": 9415}

    assert bms_data == ref


def test_calc_voltage() -> None:
    """Check if missing data is correctly calculated."""
    bms_data: BMSsample = {"cell_voltages": [3.456, 3.567]}
    ref: BMSsample = bms_data.copy()
    BaseBMS._add_missing_values(bms_data, frozenset({"voltage"}))
    assert bms_data == ref | {"voltage": 7.023, "problem": False}


def test_calc_cycle_chrg() -> None:
    """Check if missing data is correctly calculated."""
    bms_data: BMSsample = {"battery_level": 73, "design_capacity": 125}
    ref: BMSsample = bms_data.copy()
    BaseBMS._add_missing_values(bms_data, frozenset({"cycle_charge"}))
    assert bms_data == ref | {"cycle_charge": 91.25, "problem": False}


def test_calc_battery_level() -> None:
    """Check if missing battery_level is correctly calculated."""
    bms_data: BMSsample = {"cycle_charge": 421, "design_capacity": 983}
    ref: BMSsample = bms_data.copy()
    BaseBMS._add_missing_values(bms_data, frozenset({"battery_level"}))
    assert bms_data == ref | {"battery_level": 42.8, "problem": False}


@pytest.mark.parametrize(
    ("problem_sample"),
    [
        ({"voltage": -1}, "negative overall voltage"),
        ({"cell_voltages": [5.907]}, "high cell voltage"),
        ({"cell_voltages": [-0.001]}, "negative cell voltage"),
        ({"delta_voltage": 5.907}, "doubtful delta voltage"),
        ({"cycle_charge": 0}, "doubtful cycle charge"),
        ({"battery_level": 101}, "doubtful SoC"),
        ({"problem_code": 0x1}, "BMS problem code"),
        ({"problem": True}, "BMS problem report"),
    ],
    ids=lambda param: param[1],
)
def test_problems(problem_sample: tuple[BMSsample, str]) -> None:
    """Check if missing data is correctly calculated."""
    bms_data: BMSsample = problem_sample[0].copy()

    BaseBMS._add_missing_values(bms_data, frozenset({"runtime"}))

    assert bms_data == problem_sample[0] | {"problem": True}


@pytest.mark.parametrize(
    ("replies", "exp_wr_response", "exp_output"),
    [
        ([b"\x12"], [True], [0x12]),
        (
            [None] * 2 * (BaseBMS.MAX_RETRY),
            [True] * (BaseBMS.MAX_RETRY) + [False] * (BaseBMS.MAX_RETRY),
            [TimeoutError()],
        ),
        (
            [None] * (BaseBMS.MAX_RETRY - 1) + [b"\x13"],
            [True] * (BaseBMS.MAX_RETRY),
            [0x13],
        ),
        (
            [None] * (BaseBMS.MAX_RETRY) + [b"\x14"],
            [True] * (BaseBMS.MAX_RETRY) + [False],
            [0x14],
        ),
        (
            [BleakError()]
            + [None] * (BaseBMS.MAX_RETRY - 1)
            + [b"\x15"]
            + [None] * (BaseBMS.MAX_RETRY - 1)
            + [b"\x16"],
            [True] + [False] * BaseBMS.MAX_RETRY + [False] * BaseBMS.MAX_RETRY,
            [0x15, 0x16],
        ),
        (
            [None] * (BaseBMS.MAX_RETRY - 1) + [ValueError()],
            [True] * (BaseBMS.MAX_RETRY),
            [ValueError()],
        ),
    ],
    ids=[
        "basic_test",
        "no_response",
        "retry_count-1",
        "retry_count",
        "mode_switch",
        "unhandled_exc",
    ],
)
async def test_write_mode(
    monkeypatch,
    patch_bleak_client,
    patch_bms_timeout,
    replies: list[bytearray | Exception | None],
    exp_wr_response: list[bool],
    exp_output: list[int | Exception],
    request: pytest.FixtureRequest,
) -> None:
    """Check if write mode selection works correctly."""

    assert len(replies) == len(
        exp_wr_response
    ), "Replies and expected responses must match in length!"
    patch_bms_timeout()
    monkeypatch.setattr(MockWriteModeBleakClient, "PATTERN", replies)
    monkeypatch.setattr(MockWriteModeBleakClient, "EXP_WRITE_RESPONSE", exp_wr_response)

    patch_bleak_client(MockWriteModeBleakClient)

    bms = WMTestBMS(
        ["write-no-response", "write"],
        generate_ble_device("cc:cc:cc:cc:cc:cc", "MockBLEDevice", None, -73),
        False,
    )

    # NOTE: output must reflect the end result after one call, as init of HA resets the whole BMS!
    for output in exp_output:
        if isinstance(output, Exception):
            with pytest.raises(type(output)):
                await bms.async_update()
        else:
            assert await bms.async_update() == {
                "problem_code": output
            }, f"{request.node.name} failed!"


async def test_wr_mode_reset(monkeypatch, patch_bleak_client) -> None:

    monkeypatch.setattr(MockWriteModeBleakClient, "PATTERN", [b"\x42"])
    monkeypatch.setattr(MockWriteModeBleakClient, "EXP_WRITE_RESPONSE", [False])
    patch_bleak_client(MockWriteModeBleakClient)

    bms: WMTestBMS = WMTestBMS(
        ["write_without"],
        generate_ble_device("cc:cc:cc:cc:cc:cc", "MockBLEDevice", None, -73),
    )
    assert await bms.async_update() == {"problem_code": 0x42}
    assert bms._inv_wr_mode is False
    await bms.disconnect(True)
    assert bms._inv_wr_mode is None


async def test_no_notify(patch_bleak_client, caplog: pytest.LogCaptureFixture) -> None:
    patch_bleak_client(MockBleakClient)

    bms: MinTestBMS = MinTestBMS(
        generate_ble_device("cc:cc:cc:cc:cc:cc", "MockBLEDevice", None, -73),
        reconnect=True,
    )
    with caplog.at_level(DEBUG):
        result: BMSsample = await bms.async_update()
    assert "MockBleakClient write_gatt_char afe2, data: b'mock_command'" in caplog.text
    assert result == {"problem_code": 21}
    assert not bms._client.is_connected


async def test_disconnect_fail(
    monkeypatch, patch_bleak_client, caplog: pytest.LogCaptureFixture
) -> None:
    """Check that exceptions in connect function for guarding disconnect are ignored."""

    async def _raise_bleak_error(_args) -> NoReturn:
        raise BleakError

    monkeypatch.setattr(MockBleakClient, "disconnect", _raise_bleak_error)
    patch_bleak_client(MockBleakClient)

    bms: MinTestBMS = MinTestBMS(
        generate_ble_device("cc:cc:cc:cc:cc:cc", "MockBLEDevice", None, -73),
        reconnect=True,
    )
    with caplog.at_level(DEBUG):
        result: BMSsample = await bms.async_update()
    assert result == {"problem_code": 21}
    assert "failed to disconnect stale connection (BleakError)" in caplog.text
    assert "disconnect failed!" in caplog.text


async def test_init_connect_fail(
    monkeypatch, patch_bleak_client, caplog: pytest.LogCaptureFixture
) -> None:
    """Check that exceptions in connect function for guarding disconnect are ignored."""

    async def _raise_value_error(_args) -> NoReturn:
        raise ValueError("MockValueError")

    patch_bleak_client(MockBleakClient)
    monkeypatch.setattr(MinTestBMS, "_init_connection", _raise_value_error)

    bms: MinTestBMS = MinTestBMS(
        generate_ble_device("cc:cc:cc:cc:cc:cc", "MockBLEDevice", None, -73)
    )
    with caplog.at_level(DEBUG), pytest.raises(ValueError, match="MockValueError"):
        await bms.async_update()


def test_crc_calculations() -> None:
    """Check if CRC calculations are correct."""
    # Example data for CRC calculation
    data: bytearray = bytearray([0x31, 0x32, 0x33, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39])
    test_fn: list[tuple[Callable[[bytearray], int], int]] = [
        (crc_modbus, 0x4B37),
        (crc8, 0xA1),
        (crc_xmodem, 0x31C3),
        (lrc_modbus, 0xFE23),
        (crc_sum, 0xDD),
    ]

    for crc_fn, expected_crc in test_fn:
        calculated_crc: int = crc_fn(data)
        assert (
            calculated_crc == expected_crc
        ), f"Expected {expected_crc}, got {calculated_crc}"


@pytest.mark.parametrize(
    ("data", "cells", "start", "size", "byteorder", "divider", "expected"),
    [
        # Two cells, big endian, default divider
        (bytearray([0x0D, 0x80, 0x0D, 0xF7]), 2, 0, 2, "big", 1000, [3.456, 3.575]),
        # Two cells, little endian, default divider
        (bytearray([0x80, 0x0D, 0xF7, 0x0D]), 2, 0, 2, "little", 1000, [3.456, 3.575]),
        # One cell, big endian, custom divider
        (bytearray([0x30, 0x34]), 1, 0, 2, "big", 10000, [1.234]),
        (  # Three cells, big endian, offset start
            bytearray([0x00, 0x00, 0x0D, 0x80, 0x0D, 0xF7, 0x0D, 0xA7]),
            3,
            2,
            2,
            "big",
            1000,
            [3.456, 3.575, 3.495],
        ),
        # Not enough data for all cells
        (bytearray([0x0D, 0x80]), 2, 0, 2, "big", 1000, [3.456]),
        # Zero cells
        (bytearray([0x0D, 0x80]), 0, 0, 2, "big", 1000, []),
        # Divider = 1 (raw values)
        (bytearray([0x01, 0x02, 0x03, 0x04]), 2, 0, 2, "big", 1, [258, 772]),
    ],
    ids=[
        "two_cells_big_endian",
        "two_cells_little_endian",
        "one_cell_custom_divider",
        "three_cells_offset_start",
        "not_enough_data",
        "zero_cells",
        "divider_one_raw_values",
    ],
)
def test_cell_voltages(data, cells, start, size, byteorder, divider, expected) -> None:
    """Test the _cell_voltages method of BaseBMS with various input parameters."""
    result: list[float] = BaseBMS._cell_voltages(
        data,
        cells=cells,
        start=start,
        size=size,
        byteorder=byteorder,
        divider=divider,
    )
    assert result == expected


@pytest.mark.parametrize(
    (
        "data",
        "values",
        "start",
        "size",
        "byteorder",
        "signed",
        "offset",
        "divider",
        "expected",
    ),
    [
        # Two signed big endian values, no offset, divider=1
        (bytearray([0xFF, 0xEC, 0x00, 0x64]), 2, 0, 2, "big", True, 0, 1, [-20, 100]),
        (  # Two unsigned little endian values, offset=0, divider=10
            bytearray([0x10, 0x00, 0x20, 0x00]),
            2,
            0,
            2,
            "little",
            False,
            0,
            10,
            [1.6, 3.2],
        ),
        # One signed big endian value, offset=273.15, divider=1
        (bytearray([0x0B, 0x98]), 1, 0, 2, "big", False, 2731, 10, [23.7]),
        (  # Three signed little endian values, offset=0, divider=100
            bytearray([0x64, 0x00, 0xC8, 0xFF, 0x2C, 0x01]),
            3,
            0,
            2,
            "little",
            True,
            0,
            100,
            [1.0, -0.56, 3.0],
        ),
        # Not enough data for all values
        (bytearray([0x00, 0x7D]), 2, 0, 2, "big", True, 0, 1, [125]),
        # Zero values requested
        (bytearray([0x00, 0x7D]), 0, 0, 2, "big", True, 0, 1, []),
        # Divider = 1, offset = 7
        (bytearray([0x00, 0x14]), 1, 0, 2, "big", True, 7, 1, [13]),
    ],
    ids=[
        "two_signed_big_endian",
        "two_unsigned_little_endian_div10",
        "one_signed_big_endian_kelvin_offset",
        "three_signed_little_endian_div100",
        "not_enough_data",
        "zero_values",
        "divider1_offset10",
    ],
)
def test_temp_values(
    data, values, start, size, byteorder, signed, offset, divider, expected
) -> None:
    """Test the _temp_values method of BaseBMS with various input parameters."""
    result: list[int | float] = BaseBMS._temp_values(
        data,
        values=values,
        start=start,
        size=size,
        byteorder=byteorder,
        signed=signed,
        offset=offset,
        divider=divider,
    )
    assert result == expected


@pytest.mark.parametrize(
    ("fields", "data", "byteorder", "offset", "expected"),
    [
        # Test with big endian and multiple data points
        (
            (
                BMSdp("voltage", 0, size=2, signed=False),
                BMSdp("current", 2, size=2, signed=True),
            ),
            bytearray([0x0D, 0x80, 0xFF, 0xEC]),
            "big",
            0,
            {"voltage": 3456.0, "current": -20},
        ),
        # Test with dict data, little endian
        (
            (BMSdp("voltage", 0, size=2, signed=False, fct=lambda x: x / 10, idx=1),),
            {1: bytearray([0x64, 0x00])},
            "little",
            0,
            {"voltage": 10},
        ),
        # Test with missing dict data
        (
            (BMSdp("voltage", 0, size=2, signed=False, idx=2),),
            {1: bytearray([0x64, 0x00])},
            "little",
            0,
            {},
        ),
        # Test with offset
        (
            (BMSdp("battery_level", 1, size=1, signed=False),),
            bytearray([0x00, 0x7D]),
            "big",
            0,
            {"battery_level": 125},
        ),
        # Test with offset shifting the slice
        (
            (BMSdp("voltage", 0, size=2, signed=False),),
            bytearray([0x00, 0x00, 0x12, 0x34]),
            "big",
            2,
            {"voltage": 0x1234},
        ),
    ],
    ids=[
        "be_multiple_dps",
        "le_dict_single_dp_lambda",
        "le_dict_missing_idx",
        "be_with_offset",
        "be_offset_shift_slice",
    ],
)
def test_decode_data(fields, data, byteorder, offset, expected) -> None:
    """Test the _decode_data method of BaseBMS with various input parameters."""
    result: BMSsample = BaseBMS._decode_data(
        fields, data, byteorder=byteorder, offset=offset
    )
    assert result == expected
