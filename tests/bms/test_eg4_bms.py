"""Test the EG4 BMS implementation."""

from collections.abc import Buffer
from typing import Final
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.uuids import normalize_uuid_str
import pytest

from aiobmsble.basebms import BMSSample
from aiobmsble.bms.eg4_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import BMSBasicTests, verify_device_info

BT_FRAME_SIZE: Final[int] = 80
CMD_STATUS: Final[bytes] = b"\x01\x03\x00\x00\x00\x27\x05\xd0"
CMD_INFO: Final[bytes] = b"\x01\x03\x00\x69\x00\x2e\x15\xca"

_RESULT_DEFS: Final[BMSSample] = {
    "balancer": 0,
    "voltage": 13.24,
    "current": -6.2,
    "battery_health": 100,
    "battery_level": 48,
    "cell_count": 4,
    "cell_voltages": [3.31, 3.313, 3.309, 3.313],
    "delta_voltage": 0.004,
    "temperature": 17,
    "power": -82.088,
    # "runtime": 54770,
    "battery_charging": False,
    "problem_code": 0,
    "problem": False,
    "temp_values": [17.0, -56.0, 0.0, 0.0, 0.0, 0.0],
}


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


class MockEG4BleakClient(MockBleakClient):
    """Emulate a EG4 BMS BleakClient."""

    _TX_CHAR_UUID: Final[str] = "1001"
    _RESP: dict[bytes, bytearray] = {
        CMD_STATUS: bytearray(
            b"\x01\x03\x4e\x05\x2c\xff\xc2\x0c\xee\x0c\xf1\x0c\xed\x0c\xf1\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x11\x00"
            b"\x11\x00\x11\x00\x00\x02\xee\x00\x64\x00\x30\x00\x02\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x11\xc8\x00\x00\x00\x00\x00\x04\x00\x00\x00\x00\xc4\x34"
        ),  # 13.24V, -6.2A, 17°C, 48%, dischrg, ver 1.5(7), 3.309V, 3.314V, 3.309V, 3.312V
        CMD_INFO: bytearray(
            b"\x01\x03\x2e\x32\x34\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x30"
            b"\x36\x00\x00\x00\x00\x30"
            b"\x31\x36\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x97\x8c"
        ),
    }

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
    ) -> bytearray:
        """Generate response based on command."""
        if not isinstance(char_specifier, str) or normalize_uuid_str(
            char_specifier
        ) != normalize_uuid_str(self._TX_CHAR_UUID):
            return bytearray()

        return self._RESP.get(bytes(data), bytearray())

    async def write_gatt_char(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        data: Buffer,
        response: bool | None = None,
    ) -> None:
        """Issue write command to GATT."""
        await super().write_gatt_char(char_specifier, data, response)
        assert self._notify_callback is not None
        for notify_data in [
            self._response(char_specifier, data)[i : i + BT_FRAME_SIZE]
            for i in range(0, len(self._response(char_specifier, data)), BT_FRAME_SIZE)
        ]:
            self._notify_callback("MockEG4BleakClient", notify_data)


async def test_update(patch_bleak_client, keep_alive_fixture: bool) -> None:
    """Test EG4 BMS data update."""

    patch_bleak_client(MockEG4BleakClient)

    bms = BMS(generate_ble_device(), keep_alive_fixture)

    assert await bms.async_update() == _RESULT_DEFS

    # query again to check already connected state
    await bms.async_update()
    assert bms._client and bms._client.is_connected is keep_alive_fixture

    await bms.disconnect()


async def test_device_info(patch_bleak_client) -> None:
    """Test that the BMS returns initialized dynamic device information."""
    await verify_device_info(
        patch_bleak_client,
        MockEG4BleakClient,
        BMS,
        {"fw_version": "6", "model": "24", "serial_number": "16"},
    )


@pytest.mark.parametrize(
    "wrong_response",
    [
        b"\x02" + MockEG4BleakClient._RESP[CMD_STATUS][1:],  # wrong_SOF
        MockEG4BleakClient._RESP[CMD_STATUS][:-2] + b"\xe1\x65",  # wrong_CRC
        b"\x01",
        b"",
    ],
    ids=["wrong_SOF", "wrong_CRC", "too_short", "empty"],
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
        MockEG4BleakClient,
        "_RESP",
        MockEG4BleakClient._RESP | {CMD_STATUS: bytearray(wrong_response)},
    )
    patch_bleak_client(MockEG4BleakClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = {}
    with pytest.raises(TimeoutError):
        result = await bms.async_update()

    assert not result
    await bms.disconnect()


@pytest.mark.parametrize(
    "problem_response",
    [
        b"\x01\x03\x4e\x05\x2c\xff\xc2\x0c\xee\x0c\xf1\x0c\xed\x0c\xf1\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x11\x00\x11\x00"
        b"\x11\x00\x00\x02\xee\x00\x64\x00\x30\x00\x02\x80\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x11\xc8\x00\x00\x00\x00\x00\x04\x00\x00\x00\x00\x6e\x48",
        b"\x01\x03\x4e\x05\x2c\xff\xc2\x0c\xee\x0c\xf1\x0c\xed\x0c\xf1\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x11\x00\x11\x00"
        b"\x11\x00\x00\x02\xee\x00\x64\x00\x30\x00\x02\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x11\xc8\x00\x00\x00\x00\x00\x04\x00\x00\x00\x00\xd4\xe5",
    ],
    ids=["last_bit", "first_bit"],
)
async def test_problem_response(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    problem_response: bytes,
    request,
) -> None:
    """Test data update with BMS returning error flags."""
    monkeypatch.setattr(
        MockEG4BleakClient,
        "_RESP",
        MockEG4BleakClient._RESP
        | {b"\x01\x03\x00\x00\x00\x27\x05\xd0": bytearray(problem_response)},
    )
    patch_bleak_client(MockEG4BleakClient)
    bms = BMS(generate_ble_device())

    assert await bms.async_update() == _RESULT_DEFS | {
        "problem": True,
        "problem_code": (1 if request.node.callspec.id == "first_bit" else 2**47),
    }

    await bms.disconnect()
