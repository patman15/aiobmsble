"""Test the Saihang BMS implementation."""

from collections.abc import Buffer
from typing import Final
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
import pytest

from aiobmsble import BMSSample
from aiobmsble.bms.saihang_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import BMSBasicTests


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


class MockSaihangBleakClient(MockBleakClient):
    """Emulate a Saihang BMS BleakClient."""

    _RESP: Final[bytes] = (
        b"\xa5\xa5\x00\x03\x90\x00\x00\x00\x00\x00\x00\x0a\xa8\x00\x60\x00\x64\x00\x00\x25\xa6\x00"
        b"\x00\x27\x10\x00\x00\x27\x10\x00\x02\xff\xff\x00\x01\x00\x00\x06\x00\x00\x00\x00\x00\x00"
        b"\x08\x0d\xa9\x0d\x6a\x0d\x28\x0d\x3d\x0d\x2c\x0d\x6b\x0d\x4d\x0d\x38\xff\xff\xff\xff\xff"
        b"\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\x00\x02\x0b"
        b"\x43\x0b\x46\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\x0b\x56\x0b"
        b"\xa4\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\x00\x00\x6d\x60\x00\x00\x72"
        b"\x10\x00\x00\x68\x10\x00\x0a\x0d\xac\x0e\x42\x0d\x02\x00\x0a\x00\x00\x9a\x5a"
    )

    async def write_gatt_char(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        data: Buffer,
        response: bool | None = None,
    ) -> None:
        """Issue write command to GATT."""

        await super().write_gatt_char(char_specifier, data, response)

        assert (
            self._notify_callback
        ), "write to characteristics but notification not enabled"

        if bytes(data) != b"\xa5\xa5\x00\x03\x00\x00\x00\x48\x44\x2d":
            return

        self._notify_callback("MockRoyPowBleakClient", self._RESP)


async def test_update(patch_bleak_client, keep_alive_fixture: bool) -> None:
    """Test Saihang BMS data update."""

    patch_bleak_client(MockSaihangBleakClient)

    bms = BMS(generate_ble_device(), keep_alive_fixture)

    assert await bms.async_update() == {
        "voltage": 27.28,
        "temperature": 15.35,
        "battery_charging": False,
        "battery_health": 100,
        "battery_level": 96,
        "cell_count": 8,
        "current": 0.0,
        "cycles": 2,
        "temp_sensors": 2,
        "temp_values": [15.2, 15.5],
        "cell_voltages": [
            3.497,
            3.434,
            3.368,
            3.389,
            3.372,
            3.435,
            3.405,
            3.384,
        ],
        "cycle_capacity": 2629.246,
        "cycle_charge": 96.38,
        "delta_voltage": 0.129,
        "design_capacity": 100,
        "problem": False,
        "problem_code": 0,
        "power": 0.0,
    }

    # query again to check already connected state
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()


def test_uuid_tx_not_used() -> None:
    """Test that TX UUID is intentionally not used."""
    assert BMS.uuid_tx() == "fffb"


@pytest.mark.parametrize(
    ("wrong_response"),
    [
        b"",
        b"\xa5\xa5\x00\x03\x90\x71\x5c",
        b"\xa5\xa6" + MockSaihangBleakClient._RESP[2:],
        MockSaihangBleakClient._RESP[:-2] + b"\x00\x00",
        b"\xa5\xa5\x00\x03\x89" + MockSaihangBleakClient._RESP[5:-2] + b"\xfc\x79",
    ],
    ids=[
        "empty",
        "minimal",
        "wrong_SOF",
        "wrong_CRC",
        "wrong_length",
    ],
)
async def test_invalid_response(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    patch_bms_timeout,
    wrong_response: bytes,
) -> None:
    """Test data up date with BMS returning invalid data."""

    patch_bms_timeout()
    monkeypatch.setattr(MockSaihangBleakClient, "_RESP", bytearray(wrong_response))
    patch_bleak_client(MockSaihangBleakClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = {}
    with pytest.raises(TimeoutError):
        result = await bms.async_update()

    assert not result
    await bms.disconnect()
