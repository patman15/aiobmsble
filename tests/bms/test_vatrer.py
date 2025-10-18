"""Test the Vatrer BMS implementation."""

from collections.abc import Buffer
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
import pytest

from aiobmsble.basebms import BMSSample
from aiobmsble.bms.vatrer_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient


def ref_value() -> BMSSample:
    """Return reference value for mock Vatrer BMS."""
    return {
        "voltage": 52.67,
        "current": -4.96,
        "battery_level": 40,
        "cycle_charge": 39.7,
        "cycle_capacity": 2090.999,
        "cycles": 27,
        "delta_voltage": 0.003,
        "cell_count": 16,
        "runtime": 28814,
        "temp_sensors": 4,
        "temp_values": [18.0, 20.0, 19.0, 20.0, 20.0, 20.0],
        "temperature": 19.5,
        "battery_charging": False,
        "power": -261.243,
        "problem": False,
        "cell_voltages": [
            3.295,
            3.295,
            3.296,
            3.296,
            3.296,
            3.296,
            3.296,
            3.296,
            3.296,
            3.296,
            3.296,
            3.296,
            3.296,
            3.296,
            3.296,
            3.293,
        ],
    }


class MockVatrerBleakClient(MockBleakClient):
    """Emulate a Vatrer BMS BleakClient."""

    RESP: dict[bytes, bytearray] = {
        b"\x02\x03\x00\x34\x00\x12\x84\x3a": bytearray(
            b"\x02\x03\x24\x00\x04\x00\x12\x00\x14\x00\x13\x00\x14\x00\x14\x00\x14\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x34\x02\x40\x00\x00\x00\x00\x46\x43"
        ),  # temp info
        b"\x02\x03\x00\x00\x00\x14\x45\xf6": bytearray(
            b"\x02\x03\x28\x14\x93\xff\xff\xfe\x10\x00\x28\x0f\x82\x27\x10\x00\x1b\x00\x64\x00\x01"
            b"\x00\x00\x00\x01\x0c\xe0\x0c\xdd\x00\x03\x00\x0f\x00\x10\x00\x14\x00\x12\x00\x02\x00"
            b"\x04\xe4\xe5"
        ),  # status info
        b"\x02\x03\x00\x15\x00\x1f\x15\xf5": bytearray(
            b"\x02\x03\x3e\x00\x10\x0c\xdf\x0c\xdf\x0c\xe0\x0c\xe0\x0c\xe0\x0c\xe0\x0c\xe0\x0c\xe0"
            b"\x0c\xe0\x0c\xe0\x0c\xe0\x0c\xe0\x0c\xe0\x0c\xe0\x0c\xe0\x0c\xdd\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\xcb\x54"
        ),  # cell info
    }

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
            "MockVatrerBleakClient", self.RESP.get(bytes(data), bytearray())
        )


async def test_update(patch_bleak_client, keep_alive_fixture) -> None:
    """Test Vatrer BMS data update."""

    patch_bleak_client(MockVatrerBleakClient)

    bms = BMS(generate_ble_device(), keep_alive_fixture)

    assert await bms.async_update() == ref_value()

    # query again to check already connected state
    await bms.async_update()
    assert bms._client and bms._client.is_connected is keep_alive_fixture

    await bms.disconnect()


async def test_device_info(patch_bleak_client) -> None:
    """Test that the BMS returns initialized dynamic device information."""
    patch_bleak_client(MockVatrerBleakClient)
    bms = BMS(generate_ble_device())
    assert await bms.device_info() == {
        "fw_version": "mock_FW_version",
        "hw_version": "mock_HW_version",
        "sw_version": "mock_SW_version",
        "manufacturer": "mock_manufacturer",
        "model": "mock_model",
        "serial_number": "mock_serial_number",
    }


@pytest.fixture(
    name="wrong_response",
    params=[
        (bytearray(b"\x01\x03\x24" + bytes(36) + b"\x7b\xa1"), "wrong_SOF"),
        (bytearray(b"\x02\x03\x24" + bytes(36) + b"\x60\x15\x00"), "wrong_length"),
        (bytearray(b"\x02\x03\x24" + bytes(36) + b"\x60\x16"), "wrong_CRC"),
        (bytearray(b"\x02\x03\x21" + bytes(33) + b"\xba\x66"), "wrong_type"),
        (bytearray(), "empty_frame"),
    ],
    ids=lambda param: param[1],
)
def fix_response(request) -> bytearray:
    """Return faulty response frame."""
    return request.param[0]


async def test_invalid_response(
    monkeypatch, patch_bleak_client, patch_bms_timeout, wrong_response: bytearray
) -> None:
    """Test data up date with BMS returning invalid data."""

    patch_bms_timeout()

    monkeypatch.setattr(
        MockVatrerBleakClient,
        "RESP",
        MockVatrerBleakClient.RESP
        | {b"\x02\x03\x00\x34\x00\x12\x84\x3a": wrong_response},
    )

    patch_bleak_client(MockVatrerBleakClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = {}
    with pytest.raises(TimeoutError):
        result = await bms.async_update()

    assert not result
    await bms.disconnect()


@pytest.fixture(
    name="problem_response",
    params=[
        (
            bytearray(
                b"\x02\x03\x24\x00\x04\x00\x12\x00\x14\x00\x13\x00\x14\x00\x14\x00\x14\x80\x00\x00\x00"
                b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x34\x02\x40\x00\x00\x00\x00\xCE\x2B"
            ),
            "first_bit",
        ),
        (
            bytearray(
                b"\x02\x03\x24\x00\x04\x00\x12\x00\x14\x00\x13\x00\x14\x00\x14\x00\x14\x00\x00\x00\x00"
                b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x34\x02\x40\x00\x00\x00\x00\x87\x8F"
            ),
            "last_bit",
        ),
    ],
    ids=lambda param: param[1],
)
def prb_response(request):
    """Return faulty response frame."""
    return request.param


async def test_problem_response(
    monkeypatch, patch_bleak_client, problem_response: tuple[bytearray, str]
) -> None:
    """Test data update with BMS returning error flags."""

    monkeypatch.setattr(
        MockVatrerBleakClient,
        "RESP",
        MockVatrerBleakClient.RESP
        | {b"\x02\x03\x00\x34\x00\x12\x84\x3a": problem_response[0]},
    )

    patch_bleak_client(MockVatrerBleakClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = await bms.async_update()
    assert result == ref_value() | {"problem": True}

    await bms.disconnect()
