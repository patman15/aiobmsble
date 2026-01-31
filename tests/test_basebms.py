"""Test the BLE Battery Management System base class functions."""

from collections.abc import Buffer, Callable
from logging import DEBUG
from typing import Any, Final, Literal, NoReturn
from uuid import UUID

from bleak import BleakClient
from bleak.assigned_numbers import CharacteristicPropertyName
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.backends.service import BleakGATTServiceCollection
from bleak.exc import BleakDeviceNotFoundError, BleakError
from bleak.uuids import normalize_uuid_str
import pytest

from aiobmsble import BMSDp, BMSInfo, BMSSample, BMSValue, MatcherPattern
from aiobmsble.basebms import (
    BaseBMS,
    b2str,
    crc8,
    crc_modbus,
    crc_sum,
    crc_xmodem,
    lrc_modbus,
)
from aiobmsble.bms.dummy_bms import BMS as DummyBMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient


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

    INFO: BMSInfo = {
        "default_manufacturer": "Test Manufacturer",
        "default_model": "minimal BMS for test",
    }

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [{"local_name": "Test", "connectable": True}]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return (normalize_uuid_str("afe0"),)

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

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        await self._await_msg(b"mock_command", wait_for_notify=False)  # do not wait
        return {"problem_code": 21}


class DataTestBMS(MinTestBMS):
    """BMS providing simple data to test, e.g. value calculation."""

    @staticmethod
    def _calc_values() -> frozenset[BMSValue]:
        return frozenset({"power", "battery_charging"})

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        await self._await_msg(b"mock_command", wait_for_notify=False)  # do not wait
        return {
            "voltage": 13,
            "current": 1.7,
            "cycle_charge": 19,
            "cycles": 23,
            "problem_code": 21,
        }


class WMTestBMS(MinTestBMS):
    """Write mode mock BMS implementation."""

    def __init__(
        self,
        char_tx_properties: list[str],
        ble_device: BLEDevice,
        keep_alive: bool = True,
    ) -> None:
        """Initialize BMS."""
        super().__init__(ble_device, keep_alive)
        self._char_tx_properties: list[str] = char_tx_properties

    def _wr_response(self, char: int | str) -> bool:
        return bool("write" in self._char_tx_properties)

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        self._log.debug("RX BLE data: %s", data)
        self._data = data
        self._msg_event.set()

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        await self._await_msg(b"mock_command")

        return {"problem_code": int.from_bytes(self._data, "big", signed=False)}


async def verify_device_info(
    patch_bleak_client,
    bleak_client: type[BleakClient],
    bms_class: type[BaseBMS],
    result_patch: dict[str, str] = {},
) -> None:
    """Test function for subclasses that the BMS returns device info from default characteristics."""
    patch_bleak_client(bleak_client)
    bms: BaseBMS = bms_class(generate_ble_device())
    assert (
        await bms.device_info()
        == {
            "fw_version": "mock_FW_version",
            "hw_version": "mock_HW_version",
            "sw_version": "mock_SW_version",
            "manufacturer": "mock_manufacturer",
            "model": "mock_model",
            "serial_number": "mock_serial_number",
        }
        | result_patch
    )


@pytest.mark.parametrize(
    ("bt_patch", "result_patch"),
    [
        ({"2a28": b"mock_SW_version"}, {"sw_version": "mock_SW_version"}),
        ({"2a28": b""}, {}),
        ({}, {}),
    ],
    ids=["defaults", "empty", "no_char"],
)
async def test_device_info(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client: Callable[..., None],
    bt_patch: dict[str, bytes],
    result_patch: dict[str, str],
) -> None:
    """Verify that device_info reads BLE characteristic 180A and provides default values."""
    defaults: dict[str, bytes] = MockBleakClient.BT_INFO.copy()
    del defaults["2a28"]
    monkeypatch.setattr(MockBleakClient, "BT_INFO", defaults | bt_patch)
    patch_bleak_client()
    bms: MinTestBMS = MinTestBMS(generate_ble_device())
    assert (
        await bms.device_info()
        == {
            "fw_version": "mock_FW_version",
            "model": "mock_model",
            "serial_number": "mock_serial_number",
            "hw_version": "mock_HW_version",
            "manufacturer": "mock_manufacturer",
        }
        | result_patch
    )


async def test_device_info_fail(
    monkeypatch: pytest.MonkeyPatch, patch_bleak_client: Callable[..., None]
) -> None:
    """Test only BMS default information is returned if characteristic 0x180a does not exit."""
    monkeypatch.setattr(
        BleakGATTServiceCollection, "get_service", lambda obj, char: None
    )
    patch_bleak_client()
    bms: MinTestBMS = MinTestBMS(generate_ble_device())
    await bms.async_update()  # run update to have connection open
    assert not await bms.device_info()  # if characteristic does not exist, no output
    assert bms.name == "MockBLEDevice"  # name is gathered from BLEDevice
    assert bms._client.is_connected


def test_calc_pwr_chrg_temp(bms_data_fixture: BMSSample) -> None:
    """Check if missing data is correctly calculated."""
    bms_data: BMSSample = bms_data_fixture
    ref: BMSSample = bms_data_fixture.copy()

    BaseBMS._add_missing_values(bms_data)
    ref = ref | {
        "cell_count": 2,
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


@pytest.mark.parametrize(
    ("sample", "expected"),
    [
        (
            {"cell_voltages": [3.456, 3.567]},
            {"cell_count": 2, "delta_voltage": 0.111, "voltage": 7.023},
        ),
        ({"battery_level": 73, "design_capacity": 125}, {"cycle_charge": 91.25}),
        ({"cycle_charge": 421, "design_capacity": 983}, {"battery_level": 42.8}),
        ({"total_charge": 1234567, "design_capacity": 256}, {"cycles": 4822}),
        (
            {"current": -1.3, "cycle_charge": 73},
            {"battery_charging": False, "runtime": 202153},
        ),
        ({"current": 1.3, "cycle_charge": 73}, {"battery_charging": True}),
    ],
    ids=["voltage", "cycle_charge", "battery_level", "cycles", "runtime", "no_runtime"],
)
def test_calc_values(sample: BMSSample, expected: BMSSample) -> None:
    """Check if missing data is correctly calculated."""
    ref: BMSSample = sample.copy()
    BaseBMS._add_missing_values(sample)
    assert sample == ref | expected | {"problem": False}


@pytest.mark.parametrize(
    ("raw"),
    [True, False],
    ids=["raw", "ext"],
)
async def test_async_update(patch_bleak_client: Callable[..., None], raw: bool) -> None:
    """Check update function of the BMS returns values."""
    patch_bleak_client()
    bms: DataTestBMS = DataTestBMS(generate_ble_device())
    base_result: BMSSample = BMSSample(
        {
            "voltage": 13,
            "current": 1.7,
            "cycle_charge": 19,
            "cycles": 23,
            "problem_code": 21,
        }
    )
    if not raw:
        base_result.update(
            {
                "battery_charging": True,
                "cycle_capacity": 247,
                "power": 22.1,
                "problem": True,
            }
        )
    assert await bms.async_update(raw=raw) == base_result


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
def test_problems(problem_sample: tuple[BMSSample, str]) -> None:
    """Check if missing data is correctly calculated."""
    bms_data: BMSSample = problem_sample[0].copy()

    BaseBMS._add_missing_values(bms_data)

    assert ("problem", True) in bms_data.items()


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
            [BleakDeviceNotFoundError("mock_device")],
            [False],
            [BleakDeviceNotFoundError("mock_device")],
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
        "no-retry-exc",
        "unhandled_exc",
    ],
)
async def test_write_mode(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client: Callable[..., None],
    patch_bms_timeout: Callable[..., None],
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
        generate_ble_device(),
        False,
    )

    # NOTE: output must reflect the end result after one call, as init of HA resets the whole BMS!
    for output in exp_output:
        if isinstance(output, Exception):
            with pytest.raises(type(output)):
                await bms.async_update()
        else:
            assert await bms.async_update() == {
                "problem": (output != 0),
                "problem_code": output,
            }, f"{request.node.name} failed!"


async def test_wr_mode_reset(
    monkeypatch: pytest.MonkeyPatch, patch_bleak_client: Callable[..., None]
) -> None:
    """Check that write mode selection is reset on disconnect of the BMS."""
    monkeypatch.setattr(MockWriteModeBleakClient, "PATTERN", [b"\x42"])
    monkeypatch.setattr(MockWriteModeBleakClient, "EXP_WRITE_RESPONSE", [False])
    patch_bleak_client(MockWriteModeBleakClient)

    bms: WMTestBMS = WMTestBMS(["write_without"], generate_ble_device())
    assert await bms.async_update() == {"problem": True, "problem_code": 0x42}
    assert bms._inv_wr_mode is False
    await bms.disconnect(True)
    assert bms._inv_wr_mode is None


def test_get_bms_module() -> None:
    """Check that basebms and dummy_bms return correct module name."""
    assert BaseBMS.get_bms_module() == "aiobmsble.basebms"
    assert DummyBMS.get_bms_module() == "aiobmsble.bms.dummy_bms"


async def test_no_notify(
    patch_bleak_client: Callable[..., None], caplog: pytest.LogCaptureFixture
) -> None:
    """Test BMS update without waiting for notification event."""
    patch_bleak_client(MockBleakClient)

    bms: MinTestBMS = MinTestBMS(generate_ble_device(), keep_alive=False)
    with caplog.at_level(DEBUG):
        result: BMSSample = await bms.async_update()
    assert "MockBleakClient write_gatt_char afe2, data: b'mock_command'" in caplog.text
    assert result == {"problem": True, "problem_code": 21}
    assert not bms._client.is_connected


async def test_disconnect_fail(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client: Callable[..., None],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Check that exceptions in connect function for guarding disconnect are ignored."""

    async def _raise_bleak_error(*args: Any) -> NoReturn:
        raise BleakError

    monkeypatch.setattr(MockBleakClient, "disconnect", _raise_bleak_error)
    patch_bleak_client(MockBleakClient)

    bms: MinTestBMS = MinTestBMS(generate_ble_device(), keep_alive=False)
    with caplog.at_level(DEBUG):
        result: BMSSample = await bms.async_update()
    assert result == {"problem": True, "problem_code": 21}
    assert "failed to disconnect stale connection (BleakError)" in caplog.text
    assert "disconnect failed!" in caplog.text


async def test_init_connect_fail(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client: Callable[..., None],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Check that exceptions in connect function for guarding disconnect are ignored."""

    async def _raise_value_error(*args: Any) -> NoReturn:
        raise ValueError("MockValueError")

    patch_bleak_client(MockBleakClient)
    monkeypatch.setattr(MinTestBMS, "_init_connection", _raise_value_error)

    bms: MinTestBMS = MinTestBMS(generate_ble_device())
    with caplog.at_level(DEBUG), pytest.raises(ValueError, match="MockValueError"):
        await bms.async_update()


async def test_context_mgr(
    patch_bleak_client: Callable[..., None],
) -> None:
    """Test that context manager provides data."""
    patch_bleak_client(MockBleakClient)

    async with DataTestBMS(generate_ble_device(), keep_alive=True) as bms:
        assert await bms.async_update() == {
            "voltage": 13,
            "current": 1.7,
            "battery_charging": True,
            "power": 22.1,
            "cycle_capacity": 247,
            "cycle_charge": 19,
            "cycles": 23,
            "problem": True,
            "problem_code": 21,
        }


async def test_context_mgr_fail(
    patch_bleak_client: Callable[..., None],
) -> None:
    """Check that context manager enforces `keep_alive=True`."""

    patch_bleak_client(MockBleakClient)

    with pytest.raises(ValueError, match="usage of context manager*"):
        async with MinTestBMS(generate_ble_device(), keep_alive=False) as bms:
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
        (b"\x0d\x80\x0d\xf7", 2, 0, 2, "big", 1000, [3.456, 3.575]),
        # Two cells, little endian, default divider
        (b"\x80\x0d\xf7\x0d", 2, 0, 2, "little", 1000, [3.456, 3.575]),
        # One cell, big endian, custom divider
        (b"\x30\x34", 1, 0, 2, "big", 10000, [1.234]),
        # Three cells, big endian, offset start
        (
            b"\x00\x00\x0d\x80\x0d\xf7\x0d\xa7",
            3,
            2,
            2,
            "big",
            1000,
            [3.456, 3.575, 3.495],
        ),
        # Not enough data for all cells
        (b"\x0d\x80", 2, 0, 2, "big", 1000, [3.456]),
        # Zero cells
        (b"\x0d\x80", 0, 0, 2, "big", 1000, []),
        # Divider = 1 (raw values)
        (b"\x01\x02\x03\x04", 2, 0, 2, "big", 1, [258, 772]),
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
def test_cell_voltages(
    data: bytes,
    cells: int,
    start: int,
    size: int,
    byteorder: Literal["little", "big"],
    divider: int,
    expected: list[float],
) -> None:
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
        (b"\xff\xec\x00\x64", 2, 0, 2, "big", True, 0, 1, [-20, 100]),
        # Two unsigned little endian values, offset=0, divider=10
        (b"\x10\x00\x20\x00", 2, 0, 2, "little", False, 0, 10, [1.6, 3.2]),
        # One signed big endian value, offset=273.15, divider=1
        (b"\x0b\x98", 1, 0, 2, "big", False, 2731, 10, [23.7]),
        # Three signed little endian values, offset=0, divider=100
        (
            b"\x64\x00\xc8\xff\x2c\x01",
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
        (b"\x00\x7d", 2, 0, 2, "big", True, 0, 1, [125]),
        # Zero values requested
        (b"\x00\x7d", 0, 0, 2, "big", True, 0, 1, []),
        # Divider = 1, offset = 7
        (b"\x00\x14", 1, 0, 2, "big", True, 7, 1, [13]),
        # no offset, div = 10
        (b"\x65\x64\x00\x40", 4, 0, 1, "big", True, 0, 10, [10.1, 10.0, 0.0, 6.4]),
        # offset -40, div = 10
        (b"\x65\x64\x00\x40", 4, 0, 1, "big", True, 40, 10, [6.1, 6.0, 2.4]),
        # offset -25, div = 1
        (b"\x65\x64\x00\x40", 4, 0, 1, "big", True, 25, 1, [76, 75, 39]),
    ],
    ids=[
        "two_signed_big_endian",
        "two_unsigned_little_endian_div10",
        "one_signed_big_endian_kelvin_offset",
        "three_signed_little_endian_div100",
        "not_enough_data",
        "zero_values",
        "divider1_offset10",
        "no offset",
        "offset-40",
        "div-1",
    ],
)
def test_temp_values(
    data: bytes,
    values: int,
    start: int,
    size: int,
    byteorder: Literal["little", "big"],
    signed: bool,
    offset: float,
    divider: int,
    expected: list[int | float],
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
    ("fields", "data", "byteorder", "start", "expected"),
    [
        # Test with big endian and multiple data points
        (
            (
                BMSDp("voltage", 0, size=2, signed=False),
                BMSDp("current", 2, size=2, signed=True),
            ),
            b"\x0d\x80\xff\xec",
            "big",
            0,
            {"voltage": 3456.0, "current": -20},
        ),
        # Test with dict data, little endian
        (
            (BMSDp("voltage", 0, size=2, signed=False, fct=lambda x: x / 10, idx=1),),
            {1: b"\x64\x00"},
            "little",
            0,
            {"voltage": 10},
        ),
        # Test with missing dict data
        (
            (BMSDp("voltage", 0, size=2, signed=False, idx=2),),
            {1: b"\x64\x00"},
            "little",
            0,
            {},
        ),
        # Test with start
        (
            (BMSDp("battery_level", 1, size=1, signed=False),),
            b"\x00\x7d",
            "big",
            0,
            {"battery_level": 125},
        ),
        # Test with start shifting the slice
        (
            (BMSDp("voltage", 0, size=2, signed=False),),
            b"\x00\x00\x12\x34",
            "big",
            2,
            {"voltage": 0x1234},
        ),
    ],
    ids=[
        "be_multiple_dps",
        "le_dict_single_dp_lambda",
        "le_dict_missing_idx",
        "be_with_start",
        "be_start_shift_slice",
    ],
)
def test_decode_data(
    fields: tuple[BMSDp, ...],
    data: bytes | dict[int, bytes],
    byteorder: Literal["little", "big"],
    start: int,
    expected: BMSSample,
) -> None:
    """Test the _decode_data method of BaseBMS with various input parameters."""
    result: BMSSample = BaseBMS._decode_data(
        fields, data, byteorder=byteorder, start=start
    )
    assert result == expected


@pytest.mark.parametrize(
    ("data", "expected"),
    [(b"", ""), (b"\x00 ", ""), (b"test\x00 ", "test"), (b"test  \t\r ", "test")],
    ids=["empty", "hex", "text_hex", "test_space"],
)
def test_b2str(data: bytes, expected: str) -> None:
    """Test bytearray to string conversion function."""
    assert b2str(data) == expected
