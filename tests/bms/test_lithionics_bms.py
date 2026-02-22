"""Test the Lithionics BMS implementation."""

from collections.abc import Awaitable, Callable
from typing import Final
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
import pytest

from aiobmsble import BMSSample
from aiobmsble.bms.lithionics_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import BMSBasicTests, verify_device_info

BT_FRAME_SIZE = 20

STREAM_DATA: Final[bytes] = (
    b"ERROR\r\n"
    b"1399,350,350,350,349,55,48,-3,99,000000\r\n"
    b"&,1,319,006391,0136,2300,FF05,8700\r\n"
)


def ref_value() -> BMSSample:
    """Return reference value for mock Lithionics BMS."""
    return {
        "voltage": 13.99,
        "current": -3.0,
        "battery_level": 99,
        "problem_code": 0,
        "temp_sensors": 2,
        "cell_count": 4,
        "cell_voltages": [3.5, 3.5, 3.5, 3.49],
        "temp_values": [12.778, 8.889],
        "temperature": 10.834,
        "cycle_charge": 319.0,
        "total_charge": 6391,
        "cycle_capacity": 4462.81,
        "delta_voltage": 0.01,
        "power": -41.97,
        "battery_charging": False,
        "runtime": 382800,
        "problem": False,
    }


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


class MockLithionicsBleakClient(MockBleakClient):
    """Emulate a Lithionics BMS BleakClient."""

    _RESP: bytes = STREAM_DATA

    def _send_data(self) -> None:
        assert self._notify_callback is not None
        for notify_data in [
            self._RESP[i : i + BT_FRAME_SIZE]
            for i in range(0, len(self._RESP), BT_FRAME_SIZE)
        ]:
            self._notify_callback("MockLithionicsBleakClient", bytearray(notify_data))

    @property
    def is_connected(self) -> bool:
        """Mock connected."""
        if self._connected:
            self._send_data()  # trigger data for subsequent updates while connected
        return self._connected

    async def start_notify(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        callback: Callable[
            [BleakGATTCharacteristic, bytearray], None | Awaitable[None]
        ],
        **kwargs,
    ) -> None:
        """Mock start_notify."""
        await super().start_notify(char_specifier, callback)
        self._send_data()


async def test_update(
    monkeypatch, patch_bleak_client, keep_alive_fixture: bool
) -> None:
    """Test Lithionics BMS data update."""
    monkeypatch.setattr(MockLithionicsBleakClient, "_RESP", STREAM_DATA)
    patch_bleak_client(MockLithionicsBleakClient)

    bms = BMS(generate_ble_device(name="Lithionics"), keep_alive_fixture)

    assert await bms.async_update() == ref_value()

    # query again to check already connected state
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()


async def test_device_info(patch_bleak_client) -> None:
    """Test that the BMS returns initialized dynamic device information."""
    await verify_device_info(patch_bleak_client, MockLithionicsBleakClient, BMS)


@pytest.fixture(
    name="invalid_stream",
    params=[
        b"",
        b"\r\n",
        b"ERROR\r\n",
        b"1,2,3\r\n",
        b"&,\r\n",
        b"&,1,2\r\n",
        b"text\r\n",
    ],
    ids=[
        "empty",
        "blank_line",
        "error_only",
        "short_primary",
        "short_status",
        "status_only",
        "unknown_line",
    ],
)
def fixture_invalid_stream(request: pytest.FixtureRequest) -> bytes:
    """Return invalid stream data payload."""
    assert isinstance(request.param, bytes)
    return request.param


async def test_invalid_response(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    patch_bms_timeout,
    invalid_stream: bytes,
) -> None:
    """Test data update with invalid stream data."""
    patch_bms_timeout("lithionics_bms")
    monkeypatch.setattr(MockLithionicsBleakClient, "_RESP", invalid_stream)
    patch_bleak_client(MockLithionicsBleakClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = {}
    with pytest.raises(TimeoutError):
        result = await bms.async_update()

    assert not result
    await bms.disconnect()


def test_uuid_tx_not_implemented() -> None:
    """Test that TX UUID is intentionally not implemented for stream-only protocol."""
    with pytest.raises(NotImplementedError):
        BMS.uuid_tx()


@pytest.mark.parametrize(
    ("status_line", "expected"),
    [
        ("&,", {}),
        ("&,1,2", {"cycle_charge": 2.0}),
    ],
    ids=["status_min_fields", "status_remaining_ah_only"],
)
async def test_status_field_variants(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    status_line: str,
    expected: BMSSample,
) -> None:
    """Test status parsing variants with optional fields."""
    stream = (
        b"1399,350,350,350,349,55,48,-3,99,000000\r\n" + status_line.encode() + b"\r\n"
    )
    monkeypatch.setattr(MockLithionicsBleakClient, "_RESP", stream)
    patch_bleak_client(MockLithionicsBleakClient)

    bms = BMS(generate_ble_device(name="Lithionics"))
    result = await bms.async_update()

    for key, value in expected.items():
        assert result.get(key) == value

    if "cycle_charge" not in expected:
        assert "cycle_charge" not in result
    if "total_charge" not in expected:
        assert "total_charge" not in result

    await bms.disconnect()
