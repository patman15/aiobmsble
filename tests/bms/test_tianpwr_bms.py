"""Test the TianPwr BMS implementation."""

from collections.abc import Buffer
from typing import Final
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.uuids import normalize_uuid_str
import pytest

from aiobmsble import BMSConfig, BMSSample, TempSensor as TS
from aiobmsble.bms.tianpwr_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import BMSBasicTests

_RESULT_DEFS: Final[BMSSample] = {
    "temp_sensors": 4,
    "voltage": 54.74,
    "current": 0.0,
    "battery_level": 60,
    "battery_health": 100,
    "cycle_charge": 138.96,
    "cycles": 0,
    "temperature": 23.333,
    "cycle_capacity": 7606.67,
    "power": 0.0,
    "design_capacity": 230,
    "battery_charging": False,
    "cell_count": 16,
    "cell_voltages": [
        3.415,
        3.419,
        3.419,
        3.422,
        3.421,
        3.422,
        3.425,
        3.424,
        3.421,
        3.425,
        3.421,
        3.421,
        3.422,
        3.42,
        3.422,
        3.429,
    ],
    "temp_values": [TS(23.0)] * 4 + [TS(23.0, TS.T.AMBIENT), TS(25.0, TS.T.MOSFET)],
    "delta_voltage": 0.014,
    "balancer": False,
    "chrg_mosfet": True,
    "dischrg_mosfet": True,
    "problem": False,
    "problem_code": 0,
}


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


class MockTianPwrBleakClient(MockBleakClient):
    """Emulate a TianPwr BMS BleakClient."""

    RESP: Final[dict[int, bytes]] = {
        0x81: (  # Software version frame
            b"\x55\x14\x81\x30\x2e\x31\x2e\x31\x30\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xaa"
        ),
        0x82: (  # Hardware version frame
            b"\x55\x14\x82\x54\x50\x2d\x4c\x54\x35\x35\x00\x54\x42\x00\x00\x00\x00\x00\x00\xaa"
        ),
        0x83: (  # Status frame
            b"\x55\x14\x83\x00\x3c\x15\x62\x01\x18\x00\xe6\x00\xfa\x00\x00\x30\x30\x00\x64\xaa"
        ),  # 60%, 54.74V, 0A, 28° ambient temp, 23°, 25° MOS temp
        0x84: (  # General info frame
            b"\x55\x14\x84\x10\x04\x59\xd8\x36\x48\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xaa"
        ),
        0x85: (  # Mosfet status frame
            b"\x55\x14\x85\x08\x23\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xaa"
        ),
        0x87: (  # Temperatures frame
            b"\x55\x14\x87\x00\xe6\x00\xe6\x00\xe6\x00\xe6\x00\x00\x00\x00\x00\x00\x00\x00\xaa"
        ),
        0x88: (  # Cell voltages frame
            b"\x55\x14\x88\x0d\x57\x0d\x5b\x0d\x5b\x0d\x5e\x0d\x5d\x0d\x5e\x0d\x61\x0d\x60\xaa"
        ),
        0x89: (  # Cell voltages frame
            b"\x55\x14\x89\x0d\x5d\x0d\x61\x0d\x5d\x0d\x5d\x0d\x5e\x0d\x5c\x0d\x5e\x0d\x65\xaa"
        ),
        0x8A: (  # Cell voltages frame
            b"\x55\x14\x8a\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xaa"
        ),
        0x90: (b"\x55\x14\x90\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xaa"),
        0x91: (b"\x55\x14\x91\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xaa"),
        0x94: (b"\x55\x14\x91\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xaa"),
        0x95: (b"\x55\x14\x91\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xaa"),
    }

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
    ) -> bytearray:
        if isinstance(char_specifier, str) and normalize_uuid_str(
            char_specifier
        ) == normalize_uuid_str("ff02"):
            frame: Final[bytes] = bytes(data)
            if frame[0] == 0x55 and frame[-1] == 0xAA and frame[1] == 0x04:
                return bytearray(self.RESP[frame[2]])

        return bytearray()

    async def write_gatt_char(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        data: Buffer,
        response: bool | None = None,
    ) -> None:
        """Issue write command to GATT."""

        assert self._notify_callback, "write to characteristics but notification not enabled"

        self._notify_callback("MockTianPwrBleakClient", self._response(char_specifier, data))


async def test_update(patch_bleak_client, keep_alive_fixture: bool) -> None:
    """Test TianPwr BMS data update."""

    patch_bleak_client(MockTianPwrBleakClient)

    bms = BMS(generate_ble_device(), BMSConfig(keep_alive_fixture))

    assert await bms.async_update() == _RESULT_DEFS

    # query again to check already connected state
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()


async def test_device_info(patch_bleak_client) -> None:
    """Test that the BMS returns initialized dynamic device information."""
    patch_bleak_client(MockTianPwrBleakClient)
    bms = BMS(generate_ble_device())
    assert await bms.device_info() == {
        "hw_version": "TP-LT55",
        "sw_version": "0.1.10",
    }


@pytest.fixture(
    name="wrong_response",
    params=[
        (b"\x51\x14\x83" + bytes(16) + b"\xaa", "wrong_SOF"),
        (b"\x55\x14\x83" + bytes(16) + b"\xa1", "wrong_EOF"),
        (b"\x55\x14\x83" + bytes(17) + b"\xaa", "wrong_length_max"),
        (b"\x55\x14\x83" + bytes(15) + b"\xaa", "wrong_length_min"),
        (b"", "empty_frame"),
    ],
    ids=lambda param: param[1],
)
def fix_response(request: pytest.FixtureRequest) -> bytes:
    """Return faulty response frame."""
    assert isinstance(request.param, tuple) and isinstance(request.param[0], bytes)
    return request.param[0]


async def test_invalid_response(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    patch_bms_timeout,
    wrong_response: bytes,
) -> None:
    """Test data up date with BMS returning invalid data."""

    patch_bms_timeout()

    monkeypatch.setattr(
        MockTianPwrBleakClient,
        "RESP",
        MockTianPwrBleakClient.RESP | {0x83: wrong_response},
    )

    patch_bleak_client(MockTianPwrBleakClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = {}
    with pytest.raises(TimeoutError):
        result = await bms.async_update()

    assert not result
    await bms.disconnect()


async def test_missing_message(
    monkeypatch: pytest.MonkeyPatch, patch_bleak_client, patch_bms_timeout
) -> None:
    """Test data up date with BMS returning no message type 83 but 90."""

    patch_bms_timeout()

    monkeypatch.setattr(
        MockTianPwrBleakClient,
        "RESP",
        MockTianPwrBleakClient.RESP
        | {
            0x83: (
                b"\x55\x14\x90\x00\x3c\x15\x62\x01\x18\x00\xe6\x00\xfa\x00\x00\x30\x30\x00\x64\xaa"
            )
        },
    )
    patch_bleak_client(MockTianPwrBleakClient)

    bms = BMS(generate_ble_device())

    with pytest.raises(ValueError, match="BMS data incomplete."):
        await bms.async_update()


@pytest.mark.parametrize(
    ("problem_response", "expected"),
    [
        (b"\x00\x00\x00\x00\x00\x00\x00\x01", 0x1),
        (b"\x80\x00\x00\x00\x00\x00\x00\x00", 0x0),
        (b"\x40\x00\x00\x00\x00\x00\x00\x00", 0x4000000000000000),
        (b"\x00\x00\x00\x03\x00\x00\x00\x00", 0x0),
    ],
    ids=["first_bit", "sleep_bit", "last_bit", "mosfet_bits"],
)
async def test_problem_response(
    monkeypatch: pytest.MonkeyPatch, patch_bleak_client, problem_response: bytes, expected: int
) -> None:
    """Test data update with BMS returning error flags."""

    monkeypatch.setattr(
        MockTianPwrBleakClient,
        "RESP",
        MockTianPwrBleakClient.RESP
        | {0x84: MockTianPwrBleakClient.RESP[0x84][:-9] + problem_response + b"\xaa"},
    )

    patch_bleak_client(MockTianPwrBleakClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = await bms.async_update()
    assert result == _RESULT_DEFS | {"problem": bool(expected), "problem_code": expected}

    await bms.disconnect()
