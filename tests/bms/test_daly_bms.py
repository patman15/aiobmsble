"""Test the Daly BMS implementation."""

from collections.abc import Buffer
from typing import Final
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.exc import BleakError
from bleak.uuids import normalize_uuid_str
import pytest

from aiobmsble import BMSConfig, BMSInfo, BMSSample, TempSensor as TS
from aiobmsble.basebms import crc_modbus
from aiobmsble.bms.daly_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import BMSBasicTests

MOS_INFO: Final[bytes] = b"\xd2\x03\x00\x3e\x00\x09\xf7\xa3"

_PROTO_DEFS: Final[dict[int, dict[bytes, bytes]]] = {
    0xD2: {
        b"\xd2\x03\x00\x00\x00\x3e\xd7\xb9": (
            b"\xd2\x03\x7c\x10\x1f\x10\x29\x10\x33\x10\x3d\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x3c\x00\x3d\x00\x3e\x00\x3f\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x8c\x75\x4e\x03\x84\x10\x3d\x10\x1f\x00\x00\x00\x00\x00\x00\x0d"
            b"\x80\x00\x04\x00\x04\x00\x39\x00\x01\x00\x00\x00\x01\x10\x2e\x01\x41\x00\x2a\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\xa0\xdf"
        ),  # 'voltage': 14.0, 'current': 3.0, 'battery_level': 90.0, 'cycles': 57,
        # 'cycle_charge': 345.6, 'numTemp': 4, 'temperature': 21.5, 'cycle_capacity': 4838.400000000001,
        # 'power': 42.0, 'battery_charging': True, 'runtime': none!, 'delta_voltage': 0.321
        MOS_INFO: (
            b"\xd2\x03\x12\x00\x00\x00\x00\x75\x30\x00\x00\x00\x4e\xff\xff\xff\xff\xff\xff\xff"
            b"\xff\x0b\x4e"
        ),
        # MOS_INFO: (
        #     b"\xd2\x03\x12\x00\x00\x00\x00\x75\x30\x00\x00\x00\x4e\xff\xff\xff\xff\xff\xff\xff"
        #     b"\xff\x0b\x4e"
        # ),
        b"\xd2\x03\x00\xa9\x00\x20\x87\x91": (
            b"\xd2\x03\x40\x54\x30\x30\x4b\x5f\x33\x32\x31\x30\x34\x32\x5f\x31\x31\x00\x00\x48"
            b"\x32\x2e\x30\x5f\x31\x30\x33\x52\x5f\x33\x30\x39\x46\x39\x46\x32\x30\x32\x34\x30"
            b"\x32\x32\x39\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x55\x41"
        ),
    },
    0x81: {
        b"\x81\x03\x00\x00\x00\x40\x5b\xfa": (
            b"\x51\x03\x80\x0c\xd1\x0c\x90\x0c\xa3\x0c\xd4\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\x00\xff\x00\xff"
            b"\x00\xff\x00\xff\x00\xff\x00\xff\x00\xff\x00\x82\x75\x28\x00\x70\x00\x48\x00\x04\x00"
            b"\x02\x0c\xd4\x00\x04\x72\x01"
        ),
        b"\x81\x03\x00\x41\x00\x3e\x8b\xce": (
            b"\x51\x03\x7c\x00\x02\x00\x44\x00\xff\x00\x00\x00\xff\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\xc9\x00\x00\x00\x00\x75\x30\x00\x00\x00\x00\x00\x00\x00\x01\x00\x01\x00"
            b"\x00\x00\x00\x00\x00\x0c\xba\x00\x09\x00\x00\x00\x45\x00\xff\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x75\x30\x1a\x06\x05\x09\x22\x10\x4a\xec\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x75\x30\x00\x30\x00\x70\x00\x00\x00\x00\x00\x00\x00\x02\x00\x00\x80\x00\x00\x00"
            b"\x75\x30\x0b\x7d\xff\xfe\xff\xfe\x00\x00\x7f\xf6\xff\xff\xff\xff\xff\xff\xff\xff\x00"
            b"\x02\x30\x7a"
        ),
        b"\x81\x03\x01\x78\x00\x4a\x5a\x18": (
            b"\x51\x03\x94\x31\x32\x5f\x32\x36\x30\x31\x32\x30\x5f\x4b\x30\x30\x54\x48\x32\x2e\x31"
            b"\x5f\x31\x30\x33\x45\x5f\x33\x30\x58\x46\x44\x4c\x5f\x48\x4b\x4d\x53\x5f\x33\x2e\x32"
            b"\x2e\x45\x00\x32\x32\x31\x4c\x44\x30\x31\x31\x31\x31\x31\x31\x31\x31\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x32\x30\x32\x36\x30\x35\x33\x30\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\xb1\xcb"
        ),
    },
}

_RESULT_DEFS: Final[dict[int, BMSSample]] = {
    0xD2: {
        "voltage": 14.0,
        "current": 3.0,
        "battery_level": 90.0,
        "cycles": 57,
        "cycle_charge": 345.6,
        "cell_voltages": [4.127, 4.137, 4.147, 4.157],
        "cell_count": 4,
        "delta_voltage": 0.321,
        "temp_sensors": 4,
        "cycle_capacity": 4838.4,
        "power": 42.0,
        "battery_charging": True,
        "problem": False,
        "problem_code": 0,
        "chrg_mosfet": False,
        "dischrg_mosfet": True,
        "balancer": True,
    }
}

_DEV_DEFS: Final[dict[int, BMSInfo]] = {
    0xD2: {
        "hw_version": "H2.0_103R_309F9F",
        "sw_version": "T00K_321042_11",
    },
    0x81: {
        "hw_version": "DL_HKMS_3.2.E",
        "serial_number": "221LD011111111",
        "sw_version": "12_260120_K00TH2.1_103E_30XF",
    },
}


@pytest.fixture(name="protocol_type", params=_PROTO_DEFS.keys())
def proto(request: pytest.FixtureRequest) -> int:
    """Protocol fixture."""
    assert isinstance(request.param, int)
    return request.param


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


class MockDalyBleakClient(MockBleakClient):
    """Emulate a Daly BMS BleakClient."""

    _FCT_READ: Final[int] = 0x03
    MOS_AVAIL: bool = True
    RESP: Final[dict[bytes, bytes]] = _PROTO_DEFS[0xD2]

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
    ) -> bytearray:
        if (
            isinstance(char_specifier, str)
            and normalize_uuid_str(char_specifier) == normalize_uuid_str("fff2")
            and bytes(data)[0] == next(iter(MockDalyBleakClient.RESP))[0]  # 1st resp
            and bytes(data)[1] == MockDalyBleakClient._FCT_READ
        ):
            if bytes(data) == MOS_INFO and not self.MOS_AVAIL:
                raise TimeoutError
            return bytearray(MockDalyBleakClient.RESP.get(bytes(data), b""))

        return bytearray()

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
            "MockDalyBleakClient", self._response(char_specifier, data)
        )


class MockInvalidBleakClient(MockDalyBleakClient):
    """Emulate a Daly BMS BleakClient."""

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
    ) -> bytearray:
        if isinstance(char_specifier, str) and normalize_uuid_str(
            char_specifier
        ) == normalize_uuid_str("fff2"):
            return bytearray(
                b"\xd2\x03\x11\x10\x1f\x10\x29\x10\x33\x10\x3d\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                b"\x5d\x0f"
            )

        return bytearray()

    async def disconnect(self) -> None:
        """Mock disconnect to raise BleakError."""
        raise BleakError


@pytest.mark.parametrize("mos_sensor_avail", [True, False])
async def test_update(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    mos_sensor_avail: bool,
    keep_alive_fixture: bool,
) -> None:
    """Test Daly BMS data update."""

    monkeypatch.setattr(  # patch recoginiation of MOS request to fail
        MockDalyBleakClient, "MOS_AVAIL", mos_sensor_avail
    )

    patch_bleak_client(MockDalyBleakClient)

    bms = BMS(generate_ble_device(), BMSConfig(keep_alive_fixture))

    assert await bms.async_update() == _RESULT_DEFS[0xD2] | (
        {
            "temperature": 24.8,
            "temp_values": [
                TS(38.0, TS.T.MOSFET),
                TS(20.0, TS.T.GENERIC),
                TS(21.0, TS.T.GENERIC),
                TS(22.0, TS.T.GENERIC),
                TS(23.0, TS.T.GENERIC),
            ],
        }
        if mos_sensor_avail
        else {
            "temperature": 21.5,
            "temp_values": [20.0, 21.0, 22.0, 23.0],
        }
    )

    # query again to check already connected state
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()


async def test_device_info(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    patch_bms_timeout,
    protocol_type: int,
) -> None:
    """Test that the BMS returns initialized dynamic device information."""
    monkeypatch.setattr(MockDalyBleakClient, "RESP", _PROTO_DEFS[protocol_type])
    patch_bms_timeout()
    patch_bleak_client(MockDalyBleakClient)
    bms = BMS(generate_ble_device())
    assert await bms.device_info() == _DEV_DEFS[protocol_type]


@pytest.mark.parametrize(
    "test_seq",
    [
        # test ignore invalid MOS after valid read
        ((b"\x00\x30", (8.0,)), (b"\x00\x00", (-40.0,))),
        ((b"\x00\x30", (8.0,)), (b"\xff\xff", (65495.0,))),
        # test disabling of MOS read after initial invalid value
        ((b"\xff\xff", ()), (b"\x00\x30", ())),
        ((b"\x00\x00", ()), (b"\x00\x30", ())),
    ],
)
async def test_mos_excl(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    test_seq: tuple[tuple[bytearray, tuple[float, ...]], ...],
) -> None:
    """Test Daly BMS data update."""

    patch_bleak_client(MockDalyBleakClient)
    bms = BMS(generate_ble_device("cc:cc:cc:cc:cc:cc", "MockBLEdevice"))

    for response, expected in test_seq:
        mos_info: bytearray = bytearray(MockDalyBleakClient.RESP[MOS_INFO])
        mos_info[BMS._MOSTEMP_POS : BMS._MOSTEMP_POS + 2] = response
        mos_info[-2:] = crc_modbus(mos_info[:-2]).to_bytes(2, byteorder="little")
        monkeypatch.setattr(
            MockDalyBleakClient,
            "RESP",
            _PROTO_DEFS[0xD2] | {MOS_INFO: mos_info},
        )
        assert await bms.async_update() == _RESULT_DEFS[0xD2] | {
            "temperature": (sum(expected) + 86) / (len(expected) + 4),
            "temp_values": [TS(v, TS.T.MOSFET) for v in expected]
            + [TS(v) for v in (20.0, 21.0, 22.0, 23.0)],
        }

    await bms.disconnect()


async def test_too_short_frame(patch_bleak_client) -> None:
    """Test data update with BMS returning valid but too short data."""

    patch_bleak_client(MockInvalidBleakClient)

    bms: BMS = BMS(generate_ble_device())

    assert not await bms.async_update()

    await bms.disconnect()


@pytest.fixture(
    name="wrong_response",
    params=[
        (b"invalid_value", "invalid value"),
        (
            (
                b"\xd2\x03\x7c\x10\x1f\x10\x29\x10\x33\x10\x3d\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                b"\x00\x00\x00\x00\x00\x00\x00\x00\x3c\x00\x3d\x00\x3e\x00\x3f\x00\x00\x00\x00\x00"
                b"\x00\x00\x00\x00\x8c\x75\x4e\x03\x84\x10\x3d\x10\x1f\x00\x00\x00\x00\x00\x00\x0d"
                b"\x80\x00\x04\x00\x04\x00\x39\x00\x01\x00\x00\x00\x01\x10\x2e\x01\x41\x00\x2a\x00"
                b"\x00\x00\x00\x00\x00\x00\x00\xde\xad"
            ),
            "wrong CRC",
        ),
        (b"\xd2\x03", "too short"),
    ],
    ids=lambda param: param[1],
)
def fix_response(request: pytest.FixtureRequest) -> bytes:
    """Return faulty response frame."""
    assert isinstance(request.param[0], bytes)
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
        MockDalyBleakClient, "_response", lambda _s, _c, _d: bytearray(wrong_response)
    )

    patch_bleak_client(MockDalyBleakClient)

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
            (
                b"\xd2\x03\x7c\x10\x1f\x10\x29\x10\x33\x10\x3d\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                b"\x00\x00\x00\x00\x00\x00\x00\x00\x3c\x00\x3d\x00\x3e\x00\x3f\x00\x00\x00\x00\x00"
                b"\x00\x00\x00\x00\x8c\x75\x4e\x03\x84\x10\x3d\x10\x1f\x00\x00\x00\x00\x00\x00\x0d"
                b"\x80\x00\x04\x00\x04\x00\x39\x00\x01\x00\x00\x00\x01\x10\x2e\x01\x41\x00\x2a\x00"
                b"\x00\x00\x00\x00\x00\x00\x01\x61\x1f"
            ),
            "first_bit",
        ),
        (
            (
                b"\xd2\x03\x7c\x10\x1f\x10\x29\x10\x33\x10\x3d\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                b"\x00\x00\x00\x00\x00\x00\x00\x00\x3c\x00\x3d\x00\x3e\x00\x3f\x00\x00\x00\x00\x00"
                b"\x00\x00\x00\x00\x8c\x75\x4e\x03\x84\x10\x3d\x10\x1f\x00\x00\x00\x00\x00\x00\x0d"
                b"\x80\x00\x04\x00\x04\x00\x39\x00\x01\x00\x00\x00\x01\x10\x2e\x01\x41\x00\x2a\x80"
                b"\x00\x00\x00\x00\x00\x00\x00\xa8\xbf"
            ),
            "last_bit",
        ),
    ],
    ids=lambda param: param[1],
)
def prb_response(request: pytest.FixtureRequest) -> tuple[bytes, str]:
    """Return faulty response frame."""
    assert (
        isinstance(request.param, tuple)
        and isinstance(request.param[0], bytes)
        and isinstance(request.param[1], str)
    )
    return request.param


async def test_problem_response(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    problem_response: tuple[bytearray, str],
) -> None:
    """Test data update with BMS returning error flags."""

    monkeypatch.setattr(
        MockDalyBleakClient,
        "_response",
        lambda _s, _c, _d: bytearray(problem_response[0]),
    )

    patch_bleak_client(MockDalyBleakClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = await bms.async_update()
    assert result.get("problem", False)  # we expect a problem
    assert result.get("problem_code", 0) == (
        1 << (0 if problem_response[1] == "first_bit" else 63)
    )

    await bms.disconnect()
