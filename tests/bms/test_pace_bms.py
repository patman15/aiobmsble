"""Test the Pace BMS implementation."""

from collections.abc import Buffer
from typing import Final
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
import pytest

from aiobmsble import BMSConfig, BMSSample, TempSensor as TS
from aiobmsble.bms.pace_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import BMSBasicTests

BT_FRAME_SIZE = 200

_RESULT_DEFS: BMSSample = {
    "voltage": 53.02,
    "current": -3.84,
    "battery_level": 74,
    "battery_health": 100,
    "cycle_charge": 74.23,
    "design_capacity": 100,
    "cycle_capacity": 3935.675,
    "delta_voltage": 0.004,
    "cycles": 239,
    "cell_count": 16,
    "cell_voltages": [
        3.31,
        3.308,
        3.31,
        3.311,
        3.311,
        3.31,
        3.311,
        3.311,
        3.311,
        3.312,
        3.311,
        3.31,
        3.31,
        3.311,
        3.31,
        3.308,
    ],
    "temp_values": [TS(t, TS.T.CELL) for t in (22.2, 22.4, 22.7, 22.4)],
    "temperature": 22.425,
    "battery_charging": False,
    "runtime": 69590,
    "power": -203.597,
    "problem": False,
}


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


class MockPaceBleakClient(MockBleakClient):
    """Emulate a Pace BMS BleakClient."""

    _RESP: Final[dict[bytes, bytearray]] = {
        b"\x9a\x00\x00\x00\x01\x00\x00\x00\xe4\xc8\x9d": bytearray(  # REQ not in traces!
            b"\x9a\x00\x00\x00\x01\x00\x00\x43\x00\x15\x50\x31\x36\x53\x31\x30"
            b"\x30\x41\x2d\x33\x31\x39\x31\x36\x2d\x31\x2e\x30\x36\x00\x00\x20"
            b"\x50\x31\x36\x53\x31\x30\x30\x41\x2d\x33\x31\x39\x31\x36\x2d\x31"
            b"\x2e\x30\x36\x2d\x30\x30\x31\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x0a\x32\x31\x39\x33\x39\x56\x31\x34\x30\x00\x6c\xa7\x9d"
        ),
        b"\x9a\x00\x00\x00\x04\x00\x00\x00\x28\xc8\x9d": bytearray(
            b"\x9a\x00\x00\x00\x04\x00\x00\x17\x01\x15\x34\x33\x32\x31\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xa1"
            b"\x9b\x9d"
        ),
        b"\x9a\x00\x00\x0a\x00\x00\x00\x00\x19\x51\x9d": bytearray(
            b"\x9a\x00\x00\x0a\x00\x00\x00\x33\x01\xff\xff\xfe\x59\x00\x00\x14"
            b"\xb5\x00\x00\x1c\xe8\x00\x00\x27\x10\x00\x00\x27\x10\x4a\x64\x00"
            b"\x00\x00\xef\x00\x00\x00\x00\x00\x00\x00\x00\x01\x08\x0c\xef\x01"
            b"\x10\x0c\xec\x01\x03\x0b\x8e\x01\x01\x0b\x89\x99\x16\x9d"
        ),  # system values: voltage 53.01, current -4.23, battery level 74, cycle: 239
        b"\x9a\x00\x00\x0a\x03\x00\x00\x02\x01\x01\xf9\x9d\x9d": bytearray(
            b"\x9a\x00\x00\x0a\x03\x00\x00\x0d\x02\x00\x00\x0e\x06\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x18\xae\x9d"
        ),
        b"\x9a\x00\x00\x00\x07\x00\x00\x00\x6c\xc8\x9d": bytearray(
            b"\x9a\x00\x00\x00\x07\x00\x00\x06\x19\x0a\x12\x11\x0c\x14\x3b\x2c\x9d"
        ),  # date/time: 25-10-18 17:12:20
        b"\x9a\x00\x00\x00\x05\x00\x00\x00\xd4\xc9\x9d": bytearray(
            b"\x9a\x00\x00\x00\x05\x00\x00\x16\x15\x34\x33\x32\x31\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x64\xe8\x9d"
        ),
        b"\x9a\x00\x00\x00\x0c\x00\x00\x00\x48\xca\x9d": bytearray(
            b"\x9a\x00\x00\x00\x0c\x00\x00\x3e\x12\x00\x01\x00\x02\x00\x03\x00"
            b"\x04\x00\x05\x00\x06\x00\x07\x00\x08\x00\x09\x00\x0a\x00\x0b\x00"
            b"\x0c\x00\x0e\x00\x0f\x00\x24\x00\x13\x00\x3d\x00\x3e\x0c\x00\x01"
            b"\x00\x02\x00\x03\x00\x04\x00\x0c\x00\x0d\x00\x28\x00\x0f\x00\x13"
            b"\x00\x2b\x00\x3d\x00\x3e\xf4\x08\x9d"
        ),
        b"\x9a\x00\x00\x00\x0d\x00\x00\x00\xb4\xcb\x9d": bytearray(
            b"\x9a\x00\x00\x00\x0d\x00\x00\x04\x00\x0b\x00\x3e\xd0\x7f\x9d"
        ),
        b"\x9a\x00\x00\x00\x00\x00\x00\x04\x00\x00\x00\x4b\x6c\x0e\x9d": bytearray(
            b"\x9a\x00\x00\x00\x00\x00\x00\x9a\x00\x00\x00\x4b\x00\x01\x1c\xff"
            b"\x27\x10\x27\x10\x00\x4a\xde\xa8\x07\xd0\x00\x0a\x00\x10\x0d\x16"
            b"\x00\x1e\x00\xef\x0b\xea\x00\x0a\x00\x0c\x00\x64\x00\x01\x00\x0a"
            b"\x16\x80\x16\xd0\x15\x18\x00\x01\x00\x0a\x12\xc0\x10\xe0\x12\x20"
            b"\x00\x01\x00\x0a\x0e\x10\x0e\x42\x0d\x34\x00\x01\x00\x0a\x0b\xb8"
            b"\x0a\x8c\x0b\x54\x00\x01\x00\x0a\x00\x69\x00\x6e\x00\x00\x00\x01"
            b"\x00\x0a\x00\x69\x00\x6e\x00\x00\x00\x96\x00\x05\x00\x96\x00\x05"
            b"\x00\x01\x0c\x9e\x0c\xd0\x0c\x9e\x0c\xd0\x0d\x02\x0c\xd0\x00\x01"
            b"\x0a\xc8\x0a\x96\x0a\xc8\x0a\x14\x09\xe2\x0a\x14\x00\x01\x0e\x2e"
            b"\x0e\xc4\x0d\xfc\x00\x01\x09\xe2\x09\xb0\x09\xe2\x0d\x34\x0d\x66"
            b"\x0d\x34\xfe\x74\x9d"
        ),
        b"\x9a\x00\x00\x00\x00\x00\x00\x04\xf1\x01\x00\x07\xa5\x6c\x9d": bytearray(
            b"\x9a\x00\x00\x00\x00\x00\x00\x12\xf1\x01\x00\x07\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x83\xac\x9d"
        ),
        b"\x9a\x00\x00\x00\x02\x00\x00\x00\xa0\xc8\x9d": bytearray(
            b"\x9a\x00\x00\x00\x02\x00\x00\x0e\x0d\x31\x32\x33\x34\x35\x36\x37"
            b"\x38\x39\x30\x31\x32\x5a\x7d\x7d\x9d"
        ),  # serial number 123456789012Z
        b"\x9a\x00\x00\x0a\x01\x00\x00\x02\x01\x01\x1b\x9c\x9d": bytearray(
            b"\x9a\x00\x00\x0a\x01\x00\x00\x2b\x02\xfe\x80\x14\xb6\x1c\xff\x27"
            b"\x10\x27\x10\x4a\x64\x00\xef\x00\x00\x00\x00\x00\x00\x00\x00\x14"
            b"\xd7\x00\x00\x03\x0b\x8e\x01\x0b\x89\x0b\x93\x0b\x9c\x0a\x0c\xf0"
            b"\x10\x0c\xec\xa4\xb4\x9d"
        ),  # pack -3.84A, 53.02V
        b"\x9a\x00\x00\x0a\x02\x00\x00\x02\x01\x01\x28\x9c\x9d": bytearray(
            b"\x9a\x00\x00\x0a\x02\x00\x00\x44\x02\x14\xb6\x10\x0c\xee\x0b\x89"
            b"\x0c\xec\x0b\x8b\x0c\xee\x0b\x8e\x0c\xef\x0b\x8b\x0c\xef\x00\x00"
            b"\x0c\xee\x00\x00\x0c\xef\x00\x00\x0c\xef\x00\x00\x0c\xef\x00\x00"
            b"\x0c\xf0\x00\x00\x0c\xef\x00\x00\x0c\xee\x00\x00\x0c\xee\x00\x00"
            b"\x0c\xef\x00\x00\x0c\xee\x00\x00\x0c\xec\x00\x00\x32\xa1\x9d"
        ),  # pack 53.02V
    }

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
    ) -> bytearray:
        frame: Final[bytes] = bytes(data)
        assert char_specifier == "fff2"

        return self._RESP.get(frame, bytearray())

    async def write_gatt_char(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        data: Buffer,
        response: bool | None = None,
    ) -> None:
        """Issue write command to GATT."""

        assert (
            self._notify_callback
        ), "write to characteristics but notification not enabled"

        resp: Final[bytearray] = self._response(char_specifier, data)
        for notify_data in [
            resp[i : i + BT_FRAME_SIZE] for i in range(0, len(resp), BT_FRAME_SIZE)
        ]:
            self._notify_callback("MockPaceBleakClient", notify_data)


async def test_device_info(patch_bleak_client) -> None:
    """Test that the BMS returns initialized dynamic device information."""
    patch_bleak_client(MockPaceBleakClient)
    bms = BMS(generate_ble_device())
    assert await bms.device_info() == {
        "serial_number": "123456789012Z",
        "sw_version": "P16S100A-31916-1.06",
        "hw_version": "21939V140",
    }


async def test_update(patch_bleak_client, keep_alive_fixture) -> None:
    """Test Pace BMS main data update."""

    patch_bleak_client(MockPaceBleakClient)

    bms = BMS(generate_ble_device(), BMSConfig(keep_alive_fixture))

    assert await bms.async_update() == _RESULT_DEFS | {"pack_count": 1}

    # query again to check already connected state
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()


@pytest.mark.parametrize(
    ("wrong_response"),
    [
        b"\x90\x00\x00\x0a\x00\x00\x00\x33\x01\xff\xff\xfe\x59\x00\x00\x14\xb5\x00\x00\x1c\xe8\x00"
        b"\x00\x27\x10\x00\x00\x27\x10\x4a\x64\x00\x00\x00\xef\x00\x00\x00\x00\x00\x00\x00\x00\x01"
        b"\x08\x0c\xef\x01\x10\x0c\xec\x01\x03\x0b\x8e\x01\x01\x0b\x89\x91\x36\x9d",
        b"\x9a\x00\x00\x0a\x00\x00\x00\x33\x01\xff\xff\xfe\x59\x00\x00\x14\xb5\x00\x00\x1c\xe8\x00"
        b"\x00\x27\x10\x00\x00\x27\x10\x4a\x64\x00\x00\x00\xef\x00\x00\x00\x00\x00\x00\x00\x00\x01"
        b"\x08\x0c\xef\x01\x10\x0c\xec\x01\x03\x0b\x8e\x01\x01\x0b\x89\x99\x99\x9d",
        b"\x9a\x00\x00\x0a\x00\x00\x00\x33\x01\xff\xff\xfe\x59\x00\x00\x14\xb5\x00\x00\x1c\xe8\x00"
        b"\x00\x27\x10\x00\x00\x27\x10\x4a\x64\x00\x00\x00\xef\x00\x00\x00\x00\x00\x00\x00\x00\x01"
        b"\x08\x0c\xef\x01\x10\x0c\xec\x01\x03\x0b\x8e\x01\x01\x0b\x89\x00\x16\x11\x9d",
        b"\x9a\x00\x00\x00\x00\x00\x00\x33\x01\xff\xff\xfe\x59\x00\x00\x14\xb5\x00\x00\x1c\xe8\x00"
        b"\x00\x27\x10\x00\x00\x27\x10\x4a\x64\x00\x00\x00\xef\x00\x00\x00\x00\x00\x00\x00\x00\x01"
        b"\x08\x0c\xef\x01\x10\x0c\xec\x01\x03\x0b\x8e\x01\x01\x0b\x89\x59\x3d\x9d",
        b"",
    ],
    ids=["wrong_SOF", "wrong_CRC", "wrong_len", "wrong_response", "empty"],
)
async def test_invalid_response(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    patch_bms_timeout,
    wrong_response: bytes,
) -> None:
    """Test data up date with BMS returning invalid data."""

    patch_bms_timeout()
    monkeypatch.setattr(
        MockPaceBleakClient,
        "_RESP",
        MockPaceBleakClient._RESP
        | {b"\x9a\x00\x00\x0a\x00\x00\x00\x00\x19\x51\x9d": bytearray(wrong_response)},
    )
    patch_bleak_client(MockPaceBleakClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = {}
    with pytest.raises(TimeoutError):
        result = await bms.async_update()

    assert not result
    await bms.disconnect()


async def test_device_info_incomplete(
    monkeypatch: pytest.MonkeyPatch, patch_bleak_client
) -> None:
    """Test that a truncated (but CRC-valid) sw/hw version response raises ValueError."""
    monkeypatch.setattr(
        MockPaceBleakClient,
        "_RESP",
        MockPaceBleakClient._RESP
        | {
            b"\x9a\x00\x00\x00\x01\x00\x00\x00\xe4\xc8\x9d": bytearray(
                b"\x9a\x00\x00\x00\x01\x00\x00\x05\x00\x00\x00\x00\x00\x75\xd7\x9d"
            )
        },
    )
    patch_bleak_client(MockPaceBleakClient)

    bms = BMS(generate_ble_device())

    with pytest.raises(ValueError, match="BMS data incomplete"):
        await bms.device_info()

    await bms.disconnect()


async def test_cell_block_incomplete(
    monkeypatch: pytest.MonkeyPatch, patch_bleak_client
) -> None:
    """Test that a truncated (but CRC-valid) cell block response raises ValueError."""
    monkeypatch.setattr(
        MockPaceBleakClient,
        "_RESP",
        MockPaceBleakClient._RESP
        | {
            b"\x9a\x00\x00\x0a\x02\x00\x00\x02\x01\x01\x28\x9c\x9d": bytearray(
                b"\x9a\x00\x00\x0a\x02\x00\x00\x00\xa1\x50\x9d"
            )
        },
    )
    patch_bleak_client(MockPaceBleakClient)

    bms = BMS(generate_ble_device())

    with pytest.raises(ValueError, match="BMS data incomplete"):
        await bms.async_update()

    await bms.disconnect()


async def test_pack_update(monkeypatch: pytest.MonkeyPatch, patch_bleak_client) -> None:
    """Test Pace BMS pack data update."""

    monkeypatch.setattr(
        MockPaceBleakClient,
        "_RESP",
        MockPaceBleakClient._RESP
        | {
            b"\x9a\x00\x00\x0a\x00\x00\x00\x00\x19\x51\x9d": bytearray(
                b"\x9a\x00\x00\x0a\x00\x00\x00\x33" + bytes(51) + b"\x48\xde\x9d"
            )
        },
    )
    patch_bleak_client(MockPaceBleakClient)

    bms = BMS(generate_ble_device(), BMSConfig())

    assert await bms.async_update() == _RESULT_DEFS

    await bms.disconnect()
