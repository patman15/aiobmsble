"""Test the Pylontech RT series BMS implementation."""

from collections.abc import Buffer
from typing import Final
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.scanner import AdvertisementData
from bleak.uuids import normalize_uuid_str
import pytest

from aiobmsble import BMSInfo, BMSSample
from aiobmsble.bms.pylontech_bms import BMS
from aiobmsble.test_data import adv_dict_to_advdata
from aiobmsble.utils import _advertisement_matches
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import BMSBasicTests

# ---------------------------------------------------------------------------
# Reference values
#
# Captured from a Pylontech RT12100G31 during discharge at ~4.8 A:
#
#   Main block response (0x1016–0x1022, 13 registers):
#   01 03 1a                            addr, FC, byte-count
#   05 2c                               0x1016  voltage:   1324  -> 13.24 V
#   ff d0                               0x1017  current:    -48  -> -4.8 A
#   0c f0                               0x1018  cell max:  3312  ->  3.312 V
#   0c ef                               0x1019  cell min:  3311  ->  3.311 V
#   00 96                               0x101A  temp max:   150  -> 15.0 °C
#   00 96                               0x101B  temp min:   150  -> 15.0 °C
#   00 5b                               0x101C  SoC:         91  -> 91 %
#   00 63                               0x101D  SoH:         99  -> 99 %
#   00 3f                               0x101E  power:       63  -> 63 W
#   00 00                               0x101F  unknown:      0
#   0b 90                               0x1020  lifetime:  2960  -> 296.0 kWh
#   03 e8                               0x1021  allowed:   1000  -> 100.0 A
#   03 e8                               0x1022  dcap:      1000  -> 100 Ah
#   45 d8                               CRC
#
#   SN block response (0x2000–0x2007, 8 registers = "A231015000000001"):
#   01 03 10 41 32 33 31 30 31 35 30 30 30 30 30 30 30 30 31 85 04
# ---------------------------------------------------------------------------

# Modbus request bytes (used as keys in mock response dict)
_REQ_MAIN: Final[bytes] = b"\x01\x03\x10\x16\x00\x0d\x61\x0b"
_REQ_SN: Final[bytes] = b"\x01\x03\x20\x00\x00\x08\x4f\xcc"

# Recorded Modbus responses
_RESP_MAIN: Final[bytearray] = bytearray(
    b"\x01\x03\x1a\x05\x2c\xff\xd0\x0c\xf0\x0c\xef\x00\x96\x00\x96"
    b"\x00\x5b\x00\x63\x00\x3f\x00\x00\x0b\x90\x03\xe8\x03\xe8\x45\xd8"
)
_RESP_SN: Final[bytearray] = bytearray(
    b"\x01\x03\x10\x41\x32\x33\x31\x30\x31\x35\x30\x30\x30\x30\x30\x30\x30\x30\x31\x85\x04"
)

# Pre-computed modified responses for specific test cases
_RESP_MAIN_COLD: Final[bytearray] = bytearray(
    b"\x01\x03\x1a\x05\x2c\xff\xd0\x0c\xf0\x0c\xef\xff\xec\xff\xec"
    b"\x00\x5b\x00\x63\x00\x3f\x00\x00\x0b\x90\x03\xe8\x03\xe8\xbd\x16"
)
_RESP_SN_ZERO: Final[bytearray] = bytearray(
    b"\x01\x03\x10" + b"\x00" * 16 + b"\xe4\x59"
)

TX_UUID: Final[str] = BMS.uuid_tx()


def ref_value() -> BMSSample:
    """Return the expected BMSSample for the reference recording above."""
    return {
        "voltage": 13.24,
        "current": -4.8,
        "power": 63.0,
        "battery_level": 91,
        "battery_health": 99,
        "design_capacity": 100,
        "cycle_charge": 91.0,
        "cycle_capacity": round(13.24 * 91.0, 3),
        "temp_values": [15.0, 15.0],
        "temperature": 15.0,
        "cell_voltages": [3.312, 3.311],
        "delta_voltage": 0.001,
        "cell_count": 2,
        "battery_charging": False,
        "problem": False,
        "runtime": int(91.0 / 4.8 * 3600),
    }


class TestBasicBMS(BMSBasicTests):
    """Run the standard BMS interface tests for Pylontech RT series."""

    bms_class = BMS


class MockPylontechBleakClient(MockBleakClient):
    """Emulate a Pylontech RT series BleakClient."""

    RESP: dict[bytes, bytearray] = {
        _REQ_MAIN: bytearray(_RESP_MAIN),
        _REQ_SN: bytearray(_RESP_SN),
    }

    def _response(self, char_specifier: str | int, cmd: bytes) -> bytearray:
        if isinstance(char_specifier, str) and char_specifier != TX_UUID:
            return bytearray()
        return self.RESP.get(cmd, bytearray())

    async def write_gatt_char(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        data: Buffer,
        response: bool | None = None,
    ) -> None:
        """Issue write command to GATT and trigger notification with response."""
        await super().write_gatt_char(char_specifier, data, response)
        assert self._notify_callback is not None
        resp = self._response(
            char_specifier if isinstance(char_specifier, str) else str(char_specifier),
            bytes(data),
        )
        if resp:
            self._notify_callback("MockPylontechBleakClient", resp)


async def test_update(patch_bleak_client, keep_alive_fixture: bool) -> None:
    """Test BMS data update returns correct values."""
    patch_bleak_client(MockPylontechBleakClient)
    bms = BMS(generate_ble_device(), keep_alive_fixture)

    assert await bms.async_update() == ref_value()

    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture
    await bms.disconnect()


async def test_device_info_sn_from_registers(patch_bleak_client) -> None:
    """Test that serial number is read from Modbus registers."""
    patch_bleak_client(MockPylontechBleakClient)
    bms = BMS(generate_ble_device())
    info: BMSInfo = await bms.device_info()
    assert info.get("serial_number") == "A231015000000001"
    await bms.disconnect()


async def test_device_info_empty_sn_no_exception(
    monkeypatch, patch_bleak_client
) -> None:
    """Test that all-zero SN registers do not raise an exception."""
    monkeypatch.setattr(
        MockPylontechBleakClient,
        "RESP",
        {**MockPylontechBleakClient.RESP, _REQ_SN: bytearray(_RESP_SN_ZERO)},
    )
    patch_bleak_client(MockPylontechBleakClient)
    bms = BMS(generate_ble_device())
    info: BMSInfo = await bms.device_info()
    assert info is not None
    await bms.disconnect()


async def test_negative_temperature(monkeypatch, patch_bleak_client) -> None:
    """Test that negative temperatures (int16) decode correctly."""
    monkeypatch.setattr(
        MockPylontechBleakClient,
        "RESP",
        {**MockPylontechBleakClient.RESP, _REQ_MAIN: bytearray(_RESP_MAIN_COLD)},
    )
    patch_bleak_client(MockPylontechBleakClient)
    bms = BMS(generate_ble_device())
    result: BMSSample = await bms.async_update()
    assert result.get("temp_values") == [-2.0, -2.0]
    await bms.disconnect()


@pytest.fixture(
    name="wrong_response",
    params=[
        (bytearray(_RESP_MAIN[:-2]) + bytes(2), "wrong_CRC"),
        (bytearray(b"\x02\x03\x02\x00\x5b\x00\x00"), "bad_ID"),
        (bytearray(b"\x01\x83\x02\xc0\xf1"), "modbus_exception"),
        (bytearray(b"\x01\x03\x02"), "too_short"),
        (bytearray(b"\x01\x03\x1a\x05\x2c"), "incomplete_msg"),
        (bytearray(b"\x01\x03\x19") + _RESP_MAIN[3:], "wrong_byte_count"),
        (bytearray(b"\x01\x04\x1a") + bytes(28), "wrong_fct_code"),
        (bytearray(), "empty"),
    ],
    ids=lambda p: p[1],
)
def fix_wrong_response(request: pytest.FixtureRequest) -> bytearray:
    """Return a faulty response frame."""
    return request.param[0]


async def test_invalid_response(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    patch_bms_timeout,
    wrong_response: bytearray,
) -> None:
    """Test that invalid BMS responses raise TimeoutError."""
    patch_bms_timeout()
    monkeypatch.setattr(
        MockPylontechBleakClient,
        "RESP",
        MockPylontechBleakClient.RESP | {_REQ_MAIN: wrong_response},
    )
    patch_bleak_client(MockPylontechBleakClient)
    bms = BMS(generate_ble_device())
    with pytest.raises(TimeoutError):
        await bms.async_update()
    await bms.disconnect()


async def test_device_info_sn_register_timeout(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    patch_bms_timeout,
) -> None:
    """Test that a timeout reading the SN register does not crash device_info."""
    monkeypatch.setattr(
        MockPylontechBleakClient,
        "RESP",
        {k: v for k, v in MockPylontechBleakClient.RESP.items() if k != _REQ_SN},
    )
    patch_bms_timeout()
    patch_bleak_client(MockPylontechBleakClient)
    bms = BMS(generate_ble_device())
    assert await bms.device_info() is not None
    await bms.disconnect()


@pytest.mark.parametrize(
    ("local_name", "has_service_uuid", "should_match"),
    [
        ("RT12100-710003", True, True),  # standard RT12100 with Battery Service UUID
        ("RT12200-000001", True, True),  # RT12200 variant
        ("RT24100-000001", True, True),  # 24V variant
        ("RT48100-000001", True, True),  # 48V variant
        ("RT36050-000001", True, True),  # 36V variant
        # ("GModule", True, True),  # Telink default full name
        # ("GMod", True, True),  # Telink name truncated in BLE advertisement
        ("RT12100-710003", False, False),  # correct name but missing service UUID
        ("RT-fake", True, False),  # RT without digits
        ("SomeOther", True, False),  # unrelated device
        ("", True, False),  # no name
    ],
    ids=[
        "RT12100",
        "RT12200",
        "RT24100",
        "RT48100",
        "RT36050",
        # "GModule",
        # "GMod",
        "RT12100-no-svc",
        "RT-no-digits",
        "unrelated",
        "empty",
    ],
)
def test_matcher_covers_rt_variants(
    local_name: str, has_service_uuid: bool, should_match: bool
) -> None:
    """Test that matcher_dict_list covers all RT voltage/capacity variants."""
    # All variants advertise 0x180F in BLE advertisement packets.
    adv_dict: dict = {}
    if local_name:
        adv_dict["local_name"] = local_name
    if has_service_uuid:
        adv_dict["service_uuids"] = [normalize_uuid_str("180f")]
    adv: AdvertisementData = adv_dict_to_advdata(adv_dict)
    matched: bool = any(
        _advertisement_matches(m, adv, "") for m in BMS.matcher_dict_list()
    )
    assert matched is should_match
