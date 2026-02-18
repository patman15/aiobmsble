"""Test the Renogy Pro BMS implementation."""

from collections.abc import Buffer
from typing import Final
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.service import BleakGATTService, BleakGATTServiceCollection
from bleak.uuids import normalize_uuid_str
import pytest

from aiobmsble import BMSSample
from aiobmsble.bms.renogy_pro_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import DefGATTChar, MockBleakClient
from tests.test_basebms import BMSBasicTests

BT_FRAME_SIZE = 512  # ATT max is 512 bytes


def ref_value() -> BMSSample:
    """Return reference value for mock Renogy Pro BMS."""
    return {
        "battery_charging": False,
        "battery_level": 99.0,
        "cell_voltages": [3.3, 3.3, 3.3, 3.3],
        "cell_count": 4,
        "current": -1.2,
        "cycle_capacity": 2779.195,
        "cycle_charge": 208.962,
        "cycles": 6,
        "delta_voltage": 0.0,
        "design_capacity": 211,
        "power": -15.96,
        "problem": False,
        "problem_code": 0,
        "runtime": 626886,
        "temp_values": [27.3, 26.8, 27.5],
        "temp_sensors": 3,
        "temperature": 27.2,
        "voltage": 13.3,
        "chrg_mosfet": True,
        "dischrg_mosfet": True,
        "heater": False,
    }


BASE_VALUE_CMD: Final[bytes] = b"\x30\x03\x13\xb2\x00\x07\xa4\x8a"


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS

class MockRenogyProBleakClient(MockBleakClient):
    """Emulate a Renogy Pro BMS BleakClient."""

    RESP: dict[bytes, bytearray] = {
        b"\x30\x03\x13\x88\x00\x22\x45\x5c": bytearray(
            b"\x30\x03\x44\x00\x04\x00\x21\x00\x21\x00\x21\x00\x21\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x03\x01\x11\x01"
            b"\x0c\x01\x13\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x65\x4a"
        ),
        BASE_VALUE_CMD: bytearray(
            b"\x30\x03\x0e\xff\xf4\x00\x85\x00\x03\x30\x42\x00\x03\x3b\xda\x00\x06\x3e\x33"
        ),  # -1.2A, 13.3V, 208.9Ah [mAh], 211.9Ah [mAh], 6 cycles
         b"\x30\x03\x13\xec\x00\x08\x85\x5c": bytearray(
            b"\x30\x03\x10\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x0e\x00\x00\xf7\x62"
        ),
    }

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str | UUID, cmd: bytes
    ) -> bytearray:
        if isinstance(char_specifier, str) and normalize_uuid_str(
            char_specifier
        ) != normalize_uuid_str("ffd1"):
            return bytearray()

        return self.RESP.get(cmd, bytearray())

    async def write_gatt_char(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        data: Buffer,
        response: bool | None = None,
    ) -> None:
        """Issue write command to GATT."""
        await super().write_gatt_char(char_specifier, data, response)

        assert self._notify_callback is not None

        resp: bytearray = self._response(char_specifier, bytes(data))
        for notify_data in [
            resp[i : i + BT_FRAME_SIZE] for i in range(0, len(resp), BT_FRAME_SIZE)
        ]:
            self._notify_callback("MockRenogyProBleakClient", notify_data)

    @property
    def services(self) -> BleakGATTServiceCollection:
        """Emulate Renogy BT service setup."""

        serv_col = BleakGATTServiceCollection()
        for service in (
            BleakGATTService(None, 1, uuid=normalize_uuid_str("ffd0")),
            BleakGATTService(None, 5, uuid=normalize_uuid_str("fff0")),
        ):
            service.add_characteristic(
                DefGATTChar(
                    service.handle + 1,
                    uuid=f"{service.uuid[4:7]!s}1",
                    properties=["notify"],
                    service=service,
                )
            )
            service.add_characteristic(
                DefGATTChar(
                    service.handle + 2,
                    uuid=f"{service.uuid[4:7]!s}1",
                    properties=["write", "write-without-response"],
                    service=service,
                )
            )
            service.add_characteristic(
                DefGATTChar(
                    service.handle + 3,
                    uuid="0000",
                    properties=["write", "write-without-response"],
                    service=service,
                )
            )

            serv_col.add_service(service)

        return serv_col


class MockWrongBleakClient(MockBleakClient):
    """Mock client with invalid service for Renogy BMS."""

    @property
    def services(self) -> BleakGATTServiceCollection:
        """Emulate Renogy BT service setup."""

        return BleakGATTServiceCollection()


async def test_update(patch_bleak_client, keep_alive_fixture: bool) -> None:
    """Test Renogy Pro BMS data update."""

    patch_bleak_client(MockRenogyProBleakClient)

    bms = BMS(generate_ble_device(), keep_alive_fixture)

    assert await bms.async_update() == ref_value()

    # query again to check already connected state
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()


async def test_invalid_device(patch_bleak_client) -> None:
    """Test data update with BMS returning invalid data."""

    patch_bleak_client(MockWrongBleakClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = {}

    with pytest.raises(
        ConnectionError, match=r"^Failed to detect characteristics from.*"
    ):
        result = await bms.async_update()

    assert not result

    await bms.disconnect()
