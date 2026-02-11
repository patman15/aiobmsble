"""Test the Lithionics BMS implementation."""

from collections.abc import Awaitable, Callable
from typing import Final
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.uuids import normalize_uuid_str
import pytest

from aiobmsble import BMSSample
from aiobmsble.bms.lithionics_bms import BMS
from aiobmsble.test_data import adv_dict_to_advdata
from aiobmsble.utils import bms_supported
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import verify_device_info

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
        "temp_values": [55, 48],
        "temperature": 51.5,
        "delta_voltage": 0.01,
        "power": -41.97,
        "battery_charging": False,
        "problem": False,
    }


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


async def test_update(monkeypatch, patch_bleak_client, keep_alive_fixture: bool) -> None:
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


def test_matcher() -> None:
    """Test Bluetooth matcher for Lithionics patterns."""
    adv = adv_dict_to_advdata(
        {
            "local_name": "Lithionics 12V",
            "service_uuids": [normalize_uuid_str("ffe0")],
        }
    )

    assert bms_supported(BMS, adv, "00:11:22:33:44:55")


def test_matcher_li3() -> None:
    """Test Bluetooth matcher for Li3 naming observed on Lithionics packs."""
    adv = adv_dict_to_advdata(
        {
            "local_name": "Li3-061322094",
            "manufacturer_data": {"19784": "6c79b8b44fc0"},
            "service_uuids": [normalize_uuid_str("ffe0")],
        }
    )

    assert bms_supported(BMS, adv, "6C:79:B8:B4:4F:C0")


async def test_invalid_response(
    monkeypatch: pytest.MonkeyPatch, patch_bleak_client, patch_bms_timeout
) -> None:
    """Test data update with invalid stream data."""
    patch_bms_timeout("lithionics_bms")
    monkeypatch.setattr(MockLithionicsBleakClient, "_RESP", b"ERROR\r\n")
    patch_bleak_client(MockLithionicsBleakClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = {}
    with pytest.raises(TimeoutError):
        result = await bms.async_update()

    assert not result
    await bms.disconnect()
