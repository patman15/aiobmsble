"""Test the C4S100-family BMS implementation."""

from collections.abc import Buffer
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
import pytest

from aiobmsble import BMSConfig, BMSSample, TempSensor as TS
from aiobmsble.bms.c4s_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import BMSBasicTests

# real request/response pair, recorded from the device while discharging at ~-3.4A
_REQ: bytes = bytes.fromhex("02 03 00 00 00 46 c4 0b")
_RESP: bytes = bytes.fromhex(
    "02 03 8c 05 35 ff ff fe aa 00 62 24 01 27 10 00 6b 00 62 00"
    "01 00 00 00 00 0d 0b 0d 01 00 0a 00 04 00 03 00 1c 00 1b 00"
    "01 00 00 00 00 00 04 0d 09 0d 02 0d 01 0d 0b 00 00 00 00 00"
    "00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00"
    "00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00"
    "00 00 00 00 00 00 00 00 02 00 1b 00 1c 00 00 00 00 00 1b 00"
    "1c 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 32 00 00 00"
    "00 00 00 f4 2f"
)


def ref_value() -> BMSSample:
    """Return reference value for mock C4S100 BMS (real captured discharge frame)."""
    return {
        "voltage": 13.33,
        "current": -3.42,
        "battery_level": 98,
        "cycle_charge": 92.17,
        "design_capacity": 100,
        "cycles": 107,
        "battery_health": 98,
        "delta_voltage": 0.01,
        "cell_count": 4,
        "cell_voltages": [3.337, 3.33, 3.329, 3.339],
        "temp_sensors": 2,
        "temp_values": [TS(28.0, TS.T.MOSFET), TS(27.0, TS.T.AMBIENT)],
        "battery_charging": False,
        "temperature": 27.5,
        "cycle_capacity": 1228.626,
        "power": -45.589,
        "runtime": 97021,
        "problem": False,
    }


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


class MockC4SBleakClient(MockBleakClient):
    """Emulate a C4S100 BMS BleakClient."""

    RESP: dict[bytes, bytes] = {_REQ: _RESP}

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
            "MockC4SBleakClient", bytearray(self.RESP.get(bytes(data), b""))
        )


async def test_update(patch_bleak_client, keep_alive_fixture: bool) -> None:
    """Test C4S100 BMS data update."""

    patch_bleak_client(MockC4SBleakClient)

    bms = BMS(generate_ble_device(), BMSConfig(keep_alive_fixture))

    assert await bms.async_update() == ref_value()

    # query again to check already connected state
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()


@pytest.fixture(
    name="wrong_response",
    params=[
        (b"\x01\x03\x8c" + bytes(140) + b"\x00\x00", "wrong_SOF"),
        (b"\x02\x03\x8c" + bytes(140) + b"\x00\x00\x00", "wrong_length"),
        (b"\x02\x03\x8c" + bytes(140) + b"\x00\x00", "wrong_CRC"),
        (b"\x02\x03\x21" + bytes(33) + b"\xba\x66", "wrong_type"),
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
    """Test data update with BMS returning invalid data."""

    patch_bms_timeout()

    monkeypatch.setattr(
        MockC4SBleakClient,
        "RESP",
        MockC4SBleakClient.RESP | {_REQ: wrong_response},
    )

    patch_bleak_client(MockC4SBleakClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = {}
    with pytest.raises(TimeoutError):
        result = await bms.async_update()

    assert not result
    await bms.disconnect()
