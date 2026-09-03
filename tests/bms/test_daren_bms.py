"""Test the Daren BMS implementation."""

import asyncio
from collections.abc import Buffer, Callable, Iterable
from typing import Any, Final
from uuid import UUID

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str
import pytest

from aiobmsble import BMSConfig, BMSSample, TempSensor as TS
from aiobmsble.bms.daren_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import BMSBasicTests

BT_FRAME_SIZE = 20

CMD_INFO = b"\xa5\x03"
CMD_CELL = b"\xa5\x04"
HW_INFO = b"\xa5\x05"
DR_INFO = b"\xa5\x08"
XX_INFO = b"\xa5\xff"  # unknown info constant

_PROTO_DEFS: Final[dict[int, dict[bytes, bytes]]] = {
    0x1: {
        CMD_INFO: (
            b"\xdd\x03\x00'\x14\x85\x00\x00A\x01~\xb9\x00\xd6\x00\x00\x00\x00\x00\x00\x00\x00\x003\x03\x10\x04\x0b\xc9\x0b\xcd\x0b\xcb\x0b\xce\x0b\xaf\x0b\xcac\x00\x00\x00\xf7Zw"
        ),
        CMD_CELL: (
            b"\xdd\x04\x00 \x0c\xcb\x0c\xca\x0c\xca\x0c\xcb\x0c\xca\x0c\xca\x0c\xca\x0c\xcb\x0c\xcc\x0c\xcc\x0c\xcb\x0c\xca\x0c\xcb\x0c\xcb\x0c\xcc\x0c\xca\xf2tw"
        ),
        HW_INFO: (b"\xdd\x05\x80\x00\xff\x80w"),  # n/a
        DR_INFO: (
            b"\xdd\x08\x00\xc1DJM2502261341\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00DJM2502261341\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00DJM2502261341\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x19\x03\x04DR\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00V2.21\x00\x00\x00\x00\x00DR_STD05_16S200JC26_V1.5.4_T2\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00DR-WIFI02_V1.2.7\x00\x00\x00\x00\xe9}w"
        ),
        XX_INFO: b"\xdd\xff\x00\x07\x00\xba\x03$-Y\x80\xfe\x12w",
    },
    0x2: {
        CMD_INFO: (
            b"\xdd\x03\x00/\x14z\xff\xff\xff\xff\xff\xff\x01-\x00\x00\x00\x00\x00\x00\x00\x00\x00/\x0b\x10\x04\x0b\xb6\x0b\xb7\x0b\xb9\x0b\xbb\x0b\xab\x0b\xc2c\x00\x00\x00\x05\x90\x0b\xb8\xff\xff\xff|\xef\tw"
        ),  # 52.42V, -13.2A, cycles: 301
        CMD_CELL: (
            b"\xdd\x04\x00 \x0c\xcc\x0c\xcc\x0c\xcd\x0c\xcd\x0c\xcd\x0c\xcd\x0c\xcd\x0c\xca\x0c\xcc\x0c\xcc\x0c\xcb\x0c\xcd\x0c\xcc\x0c\xcd\x0c\xcc\x0c\xcc\xf2\\w"
        ),
        HW_INFO: (b"\xdd\x05\x80\x00\xff\x80w"),  # n/a
        DR_INFO: (
            b"\xdd\x08\x00\xc1DJM2412250299\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00DJM2412250299\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00DJM2412250299\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x18\x0c\x1fDR\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00V2.21\x00\x00\x00\x00\x00DR_YP01_16S200JC26_V1.0.2_T1\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00DR-WIFI02_V1.4.11\x00\x00\x00\xe9]w"
        ),
        XX_INFO: b"\xdd\xff\x00\x07\x00\xba\x03$-Y\x80\xfe\x12w",
    },
    # "oversized": {
    #     CMD_INFO: (
    #         b"\xdd\x03\x00\x1d\x06\x18\xfe\xe1\x01\xf2\x01\xf4\x00\x2a\x2c\x7c\x00\x00\x00"
    #         b"\x00\x00\x00\x80\x64\x03\x04\x03\x0b\x8b\x0b\x8a\x0b\x84\xf8\x84\x77"
    #         b"\00\00\00\00\00\00"  # oversized response
    #     ),  # {'voltage': 15.6, 'current': -2.87, 'battery_level': 100, 'cycle_charge': 4.98, 'cycles': 42, 'temperature': 22.133333333333347}
    #     CMD_CELL: (
    #         b"\xdd\x04\x00\x08\x0d\x66\x0d\x61\x0d\x68\x0d\x59\xfe\x3c\x77"
    #         b"\00\00\00\00\00\00\00\00\00\00\00\00"  # oversized response
    #     ),  # {'cell#0': 3.43, 'cell#1': 3.425, 'cell#2': 3.432, 'cell#3': 3.417}
    #     HW_INFO: (b"\xdd\x05\x80\x00\xff\x80w"),  # n/a
    # },
}
_RESULT_DEFS: Final[dict[int, BMSSample]] = {
    0x1: {
        "voltage": 52.53,
        "current": 0.0,
        "cycle_charge": 166.41,
        "design_capacity": 324,
        "cycles": 214,
        "balancer": 0,
        "problem_code": 0,
        "battery_level": 51,
        "chrg_mosfet": True,
        "dischrg_mosfet": True,
        "cell_count": 16,
        "temp_sensors": 6,
        "battery_health": 99,
        "temp_values": [
            TS(28.6, TS.T.CELL),
            TS(29.0, TS.T.CELL),
            TS(28.8, TS.T.CELL),
            TS(29.1, TS.T.CELL),
            TS(26.0, TS.T.MOSFET),
            TS(28.7, TS.T.AMBIENT),
        ],
        "cell_voltages": [
            3.275,
            3.274,
            3.274,
            3.275,
            3.274,
            3.274,
            3.274,
            3.275,
            3.276,
            3.276,
            3.275,
            3.274,
            3.275,
            3.275,
            3.276,
            3.274,
        ],
        "battery_charging": False,
        "delta_voltage": 0.002,
        "temperature": 28.367,
        "cycle_capacity": 8741.517,
        "power": 0.0,
        "problem": False,
    },
    0x2: {
        "voltage": 52.42,
        "current": -13.2,
        "cycle_charge": 142.4,
        "design_capacity": 300,
        "cycles": 301,
        "balancer": 0,
        "problem_code": 0,
        "battery_level": 47,
        "chrg_mosfet": True,
        "dischrg_mosfet": True,
        "cell_count": 16,
        "temp_sensors": 6,
        "battery_health": 99,
        "temp_values": [
            TS(26.7, TS.T.CELL),
            TS(26.8, TS.T.CELL),
            TS(27.0, TS.T.CELL),
            TS(27.2, TS.T.CELL),
            TS(25.6, TS.T.MOSFET),
            TS(27.9, TS.T.AMBIENT),
        ],
        "cell_voltages": [
            3.276,
            3.276,
            3.277,
            3.277,
            3.277,
            3.277,
            3.277,
            3.274,
            3.276,
            3.276,
            3.275,
            3.277,
            3.276,
            3.277,
            3.276,
            3.276,
        ],
        "battery_charging": False,
        "delta_voltage": 0.003,
        "temperature": 26.867,
        "cycle_capacity": 7464.608,
        "power": -691.944,
        "runtime": 38836,
        "problem": False,
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


class MockDarenBleakClient(MockBleakClient):
    """Emulate a Daren BMS BleakClient."""

    HEAD_CMD = 0xDD
    ACK_MSG = b"\xff\xaa\x15\x01\x00\x16"
    REQUIRE_PASS = False
    UNLOCKED = False
    DEFAULT_SECRET = b"000000"
    _RESP: dict[bytes, bytes] = _PROTO_DEFS[0x1].copy()

    _tasks: set[asyncio.Task[None]] = set()

    def __init__(
        self,
        address_or_ble_device: BLEDevice,
        disconnected_callback: Callable[[BleakClient], None] | None,
        services: Iterable[str] | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize MockBleakClient."""
        super().__init__(
            address_or_ble_device, disconnected_callback, services, **kwargs
        )
        self._services = ["ff01", "ff02"]

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
    ) -> bytes:

        _msg: Final[bytes] = bytes(data)
        if (
            isinstance(char_specifier, str)
            and normalize_uuid_str(char_specifier) == normalize_uuid_str("ff02")
            and _msg.startswith(b"\xff\xaa\x15")
            and not self.UNLOCKED
        ):
            self.UNLOCKED = True
            return (
                MockDarenBleakClient.ACK_MSG
                if sum(_msg[2:-1]) & 0xFF == _msg[-1]
                and _msg[4:-1] == self.DEFAULT_SECRET
                else b"\xff\xaa\x15\x01\x01\x17"
            )

        if (
            isinstance(char_specifier, str)
            and normalize_uuid_str(char_specifier) == normalize_uuid_str("ff02")
            and _msg[0] == self.HEAD_CMD
            and self.REQUIRE_PASS == self.UNLOCKED
        ):
            return self._RESP.get(_msg[1:3], b"")
        return b""

    async def _send_data(self, char_specifier, data) -> None:
        assert (
            self._notify_callback
        ), "write to characteristics but notification not enabled"

        # always send two responses, to test timeout behaviour
        for resp in (
            self._response(char_specifier, b"\xdd\xa5\x03\x00\xff\xfd\x77"),
            self._response(char_specifier, data),
        ):
            for notify_data in [
                resp[i : i + BT_FRAME_SIZE] for i in range(0, len(resp), BT_FRAME_SIZE)
            ]:
                self._notify_callback("MockDarenBleakClient", bytearray(notify_data))
            await asyncio.sleep(0)

    async def write_gatt_char(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        data: Buffer,
        response: bool | None = None,
    ) -> None:
        """Issue write command to GATT."""

        _task: asyncio.Task[None] = asyncio.create_task(
            self._send_data(char_specifier, data), name="send_loop"
        )
        self._tasks.add(_task)
        _task.add_done_callback(self._tasks.discard)

    async def disconnect(self) -> None:
        """Mock disconnect."""
        await asyncio.gather(*self._tasks)
        await super().disconnect()


# class MockOversizedBleakClient(MockDarenBleakClient):
#     """Emulate a Daren BMS BleakClient returning wrong data length."""

#     _RESP: dict[bytes, bytes] = _PROTO_DEFS["oversized"].copy()

#     async def disconnect(self) -> None:
#         """Mock disconnect to raise BleakError."""
#         if self._tasks:
#             await asyncio.wait(self._tasks)
#         raise BleakError


async def test_update(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    protocol_type: int,
) -> None:
    """Test Daren BMS data update."""

    monkeypatch.setattr(
        MockDarenBleakClient, "_RESP", _PROTO_DEFS[protocol_type].copy()
    )
    patch_bleak_client(MockDarenBleakClient)

    bms = BMS(generate_ble_device(), BMSConfig())

    assert await bms.async_update() == _RESULT_DEFS[protocol_type]

    await bms.disconnect()


# @pytest.mark.parametrize(
#     "secret", ["000000", "wrong"], ids=["correct_secret", "wrong_secret"]
# )
# async def test_update_secret(
#     monkeypatch: pytest.MonkeyPatch, patch_bleak_client, secret: str
# ) -> None:
#     """Test Daren BMS data update."""

#     monkeypatch.setattr(MockDarenBleakClient, "REQUIRE_PASS", True)
#     patch_bleak_client(MockDarenBleakClient)

#     bms = BMS(generate_ble_device(), BMSConfig(secret=secret))
#     if secret == "wrong":
#         with pytest.raises(PermissionError):
#             await bms.async_update()
#     else:
#         assert await bms.async_update() == _RESULT_DEFS

#     await bms.disconnect()


@pytest.mark.parametrize(
    "wrong_init",
    [
        b"",
        b"\xf0\xaa\x15\x01\x00\x16",
        b"\xff\xaa\x15\x01\x16",
        b"\xff\xaa\x15\x01\x00\x15",
        b"\xff\xaa\x16\x01\x00\x17",
    ],
    ids=["empty_resp", "wrong_SOF", "wrong_len", "wrong_CRC", "wrong_cmd"],
)
async def test_invalid_init(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    patch_bms_timeout,
    wrong_init: bytes,
) -> None:
    """Test connection init with BMS returning invalid data (wrong CRC)."""

    patch_bms_timeout()
    monkeypatch.setattr(MockDarenBleakClient, "REQUIRE_PASS", True)
    monkeypatch.setattr(MockDarenBleakClient, "ACK_MSG", bytearray(wrong_init))
    patch_bleak_client(MockDarenBleakClient)

    bms = BMS(generate_ble_device(), BMSConfig(secret="000000"))

    with pytest.raises(TimeoutError):
        _result: BMSSample = await bms.async_update()

    await bms.disconnect()


async def test_device_info(patch_bleak_client, patch_bms_timeout) -> None:
    """Test that the BMS returns initialized dynamic device information."""
    patch_bms_timeout()
    patch_bleak_client(MockDarenBleakClient)
    bms = BMS(generate_ble_device())
    assert await bms.device_info() == {
        "fw_version": "DR-WIFI02_V1.2.7",
        "hw_version": "V2.21",
        "sw_version": "DR_STD05_16S200JC26_V1.5.4_T2",
        "model": "DJM2502261341",
    }


# @pytest.fixture(
#     name="wrong_response",
#     params=[
#         (
#             b"\xdd\x03\x00\x1d\x06\x18\xfe\xe1\x01\xf2\x01\xf4\x00\x2a\x2c\x7c\x00\x00\x00"
#             b"\x00\x00\x00\x80\x64\x03\x04\x03\x0b\x8b\x0b\x8a\x0b\x84\xf8\x84\xdd",
#             "wrong end",
#         ),
#         (b"\xdd\x04\x00\x1d" + b"\x00" * 31 + b"\x77", "wrong CRC"),
#         (b"\xdd\x03\x80\x00\xff\x80\x77", "error"),
#     ],
#     ids=lambda param: param[1],
# )
# def fix_response(request: pytest.FixtureRequest) -> bytes:
#     """Return faulty response frame."""
#     assert isinstance(request.param[0], bytes)
#     return request.param[0]


# async def test_invalid_response(
#     monkeypatch: pytest.MonkeyPatch,
#     patch_bleak_client,
#     patch_bms_timeout,
#     wrong_response: bytes,
# ) -> None:
#     """Test data update with BMS returning invalid data (wrong CRC)."""

#     patch_bms_timeout()

#     monkeypatch.setattr(
#         MockDarenBleakClient, "_response", lambda _s, _c, _d: wrong_response
#     )

#     patch_bleak_client(MockDarenBleakClient)

#     bms = BMS(generate_ble_device())

#     with pytest.raises(TimeoutError):
#         _result: BMSSample = await bms.async_update()

#     await bms.disconnect()


# async def test_oversized_response(patch_bleak_client) -> None:
#     """Test data update with BMS returning oversized data, result shall still be ok."""
#     patch_bleak_client(MockOversizedBleakClient)
#     bms = BMS(generate_ble_device())
#     assert await bms.async_update() == _RESULT_DEFS
#     await bms.disconnect()


# @pytest.fixture(
#     name="problem_response",
#     params=[
#         (
#             bytearray(
#                 b"\xdd\x03\x00\x1d\x06\x18\xfe\xe1\x01\xf2\x01\xf4\x00\x2a\x2c\x7c\x00\x00\x00"
#                 b"\x00\x00\x01\x80\x64\x03\x04\x03\x0b\x8b\x0b\x8a\x0b\x84\xf8\x83\x77"
#             ),
#             "first_bit",
#         ),
#         (
#             bytearray(
#                 b"\xdd\x03\x00\x1d\x06\x18\xfe\xe1\x01\xf2\x01\xf4\x00\x2a\x2c\x7c\x00\x00\x00"
#                 b"\x00\x80\x00\x80\x64\x03\x04\x03\x0b\x8b\x0b\x8a\x0b\x84\xf8\x04\x77"
#             ),
#             "last_bit",
#         ),
#     ],
#     ids=lambda param: param[1],
# )
# def prb_response(request: pytest.FixtureRequest) -> tuple[bytearray, str]:
#     """Return faulty response frame."""
#     assert isinstance(request.param, tuple)
#     return request.param


# async def test_problem_response(
#     monkeypatch: pytest.MonkeyPatch,
#     patch_bleak_client,
#     problem_response: tuple[bytearray, str],
# ) -> None:
#     """Test data update with BMS returning invalid data (wrong CRC)."""

#     def _response(
#         self,
#         char_specifier: BleakGATTCharacteristic | int | str | UUID,
#         data: Buffer,
#         resp: bytearray = problem_response[0],
#     ) -> bytearray:
#         if (
#             isinstance(char_specifier, str)
#             and normalize_uuid_str(char_specifier) == normalize_uuid_str("ff02")
#             and bytearray(data)[0] == self.HEAD_CMD
#         ):
#             if bytearray(data)[1:3] == self.CMD_INFO:
#                 return resp
#             if bytearray(data)[1:3] == self.CMD_CELL:
#                 return bytearray(
#                     b"\xdd\x04\x00\x08\x0d\x66\x0d\x61\x0d\x68\x0d\x59\xfe\x3c\x77"
#                 )  # {'cell#0': 3.43, 'cell#1': 3.425, 'cell#2': 3.432, 'cell#3': 3.417}

#         return bytearray()

#     monkeypatch.setattr(MockDarenBleakClient, "_response", _response)
#     patch_bleak_client(MockDarenBleakClient)
#     bms = BMS(generate_ble_device())

#     assert await bms.async_update() == _RESULT_DEFS | {
#         "problem": True,
#         "problem_code": 1 << (0 if problem_response[1] == "first_bit" else 15),
#     }

#     await bms.disconnect()
