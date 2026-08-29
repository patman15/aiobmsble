"""Test the C4S100-family BMS implementation (derived from VatrerBMS)."""

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
_REQ: bytes = b"\x02\x03\x00\x00\x00\x46\xc4\x0b"
_RESP: bytes = (
    b"\x02\x03\x8c\x05\x35\xff\xff\xfe\xaa\x00\x62\x24\x01\x27\x10\x00\x6b\x00\x62\x00"
    b"\x01\x00\x00\x00\x00\x0d\x0b\x0d\x01\x00\x0a\x00\x04\x00\x03\x00\x1c\x00\x1b\x00"
    b"\x01\x00\x00\x00\x00\x00\x04\x0d\x09\x0d\x02\x0d\x01\x0d\x0b\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\x1b\x00\x1c\x00\x00\x00\x00\x00\x1b\x00"
    b"\x1c\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x32\x00\x00\x00"
    b"\x00\x00\x00\xf4\x2f"
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


async def test_incomplete_data(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    patch_bms_timeout,
) -> None:
    """Test data update when the BMS returns a validly-framed but wrong-size reply."""

    patch_bms_timeout()

    monkeypatch.setattr(
        MockC4SBleakClient,
        "RESP",
        {_REQ: b"\x02\x03\x21" + bytes(33) + b"\xba\x66"},
    )

    patch_bleak_client(MockC4SBleakClient)

    bms = BMS(generate_ble_device())
    with pytest.raises(ValueError, match="BMS data incomplete."):
        await bms.async_update()

    await bms.disconnect()
