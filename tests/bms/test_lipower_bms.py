"""Test the Ective BMS implementation."""

from collections.abc import Awaitable, Buffer, Callable
from typing import Final
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
import pytest

from aiobmsble import BMSSample
from aiobmsble.bms.lipower_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient

BT_FRAME_SIZE = 32

_RESULT_DEFS: Final[BMSSample] = {
    "voltage": 13.7,
    "current": -0.08,
    "battery_level": 99,
    "cycle_charge": 118,
    "cycle_capacity": 1616.6,
    "power": -1.096,
    "runtime": 5354520,
    "battery_charging": False,
    "problem": False,
}


class MockLiPwrBleakClient(MockBleakClient):
    """Emulate a Ective BMS BleakClient."""

    _RESP: Final[bytearray] = bytearray(
        b"\x22\x03\x10\x00\x76\x00\x63\x05\xcf\x00\x16\x00\x01\x00\x08\x00\x89\x00\x01\x9e\xcf"
    )  # 13.7V, 99%, 5354520s, -0.08A, -1W

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
    ) -> bytearray:
        if not isinstance(char_specifier, str) or char_specifier != "ffe1":
            return bytearray()
        addr: int = int.from_bytes(bytes(data)[3:5])
        if addr == 0x0:
            return MockLiPwrBleakClient._RESP
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

        for notify_data in [
            self._response(char_specifier, data)[i : i + BT_FRAME_SIZE]
            for i in range(0, len(self._response(char_specifier, data)), BT_FRAME_SIZE)
        ]:
            self._notify_callback("MockLiPwrBleakClient", notify_data)


async def test_update(patch_bleak_client, keep_alive_fixture) -> None:
    """Test Ective BMS data update."""

    patch_bleak_client(MockLiPwrBleakClient)

    bms = BMS(generate_ble_device(), keep_alive_fixture)

    assert await bms.async_update() == _RESULT_DEFS

    # query again to check already connected state
    await bms.async_update()
    assert bms._client and bms._client.is_connected is keep_alive_fixture

    await bms.disconnect()


# async def test_tx_notimplemented(patch_bleak_client) -> None:
#     """Test Ective BMS uuid_tx not implemented for coverage."""

#     patch_bleak_client(MockEctiveBleakClient)

#     bms = BMS(generate_ble_device(), False)

#     with pytest.raises(NotImplementedError):
#         _ret = bms.uuid_tx()


# @pytest.fixture(
#     name="wrong_response",
#     params=[
#         (
#             b"\x5e\x38\x34\x33\x35\x30\x30\x30\x30\x33\x38\x43\x44\x46\x46\x46\x46"
#             b"\x32\x43\x46\x39\x30\x32\x30\x30\x39\x37\x30\x31\x36\x32\x30\x30"
#             b"\x45\x31\x30\x42\x30\x30\x30\x30\x30\x30\x30\x30"
#             b"\x35\x45\x30\x44\x37\x31\x30\x44\x36\x35\x30\x44\x35\x45\x30\x44"
#             b"\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30"
#             b"\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30"
#             b"\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30"
#             b"\x30\x38\x38\x45\x00\x00\x00\x00\x00\x00\x00\x00",
#             "wrong_CRC",
#         ),
#         (
#             b"\x5a\x38\x34\x33\x35\x30\x30\x30\x30\x33\x38\x43\x44\x46\x46\x46\x46"
#             b"\x32\x43\x46\x39\x30\x32\x30\x30\x39\x37\x30\x31\x36\x32\x30\x30"
#             b"\x45\x31\x30\x42\x30\x30\x30\x30\x30\x30\x30\x30"
#             b"\x35\x45\x30\x44\x37\x31\x30\x44\x36\x35\x30\x44\x35\x45\x30\x44"
#             b"\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30"
#             b"\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30"
#             b"\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30"
#             b"\x30\x38\x38\x46\x00\x00\x00\x00\x00\x00\x00\x00",
#             "wrong_SOF",
#         ),
#         (
#             b"\x5e\x34\x33\x35\x30\x30\x30\x30\x33\x38\x43\x44\x46\x46\x46\x46"
#             b"\x32\x43\x46\x39\x30\x32\x30\x30\x39\x37\x30\x31\x36\x32\x30\x30"
#             b"\x45\x31\x30\x42\x30\x30\x30\x30\x30\x30\x30\x30"
#             b"\x35\x45\x30\x44\x37\x31\x30\x44\x36\x35\x30\x44\x35\x45\x30\x44"
#             b"\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30"
#             b"\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30"
#             b"\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30"
#             b"\x30\x38\x38\x46",
#             "wrong_length",  # 1st byte missing
#         ),
#         (
#             b"\x5e\x5e\x34\x33\x35\x30\x30\x30\x30\x33\x38\x43\x44\x46\x46\x46\x46"
#             b"\x32\x43\x46\x39\x30\x32\x30\x30\x39\x37\x30\x31\x36\x32\x30\x30"
#             b"\x45\x31\x30\x42\x30\x30\x30\x30\x30\x30\x30\x30"
#             b"\x35\x45\x30\x44\x37\x31\x30\x44\x36\x35\x30\x44\x35\x45\x30\x44"
#             b"\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30"
#             b"\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30"
#             b"\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30"
#             b"\x30\x38\x38\x46",
#             "wrong_character",
#         ),
#     ],
#     ids=lambda param: param[1],
# )
# def response(request) -> bytearray:
#     """Return faulty response frame."""
#     return request.param[0]


# async def test_invalid_response(
#     monkeypatch, patch_bleak_client, patch_bms_timeout, wrong_response
# ) -> None:
#     """Test data up date with BMS returning invalid data."""

#     patch_bms_timeout("ective_bms")
#     monkeypatch.setattr(MockEctiveBleakClient, "_RESP", bytearray(wrong_response))
#     patch_bleak_client(MockEctiveBleakClient)

#     bms = BMS(generate_ble_device())

#     result: BMSsample = {}
#     with pytest.raises(TimeoutError):
#         result = await bms.async_update()

#     assert not result
#     await bms.disconnect()


# @pytest.fixture(
#     name="problem_response",
#     params=[
#         (
#             bytearray(
#                 b"\x5e\x38\x34\x33\x35\x30\x30\x30\x30\x33\x38\x43\x44\x46\x46\x46\x46"
#                 b"\x32\x43\x46\x39\x30\x32\x30\x30\x39\x37\x30\x31\x36\x32\x30\x30"
#                 b"\x45\x31\x30\x42\x30\x31\x30\x30\x30\x30\x30\x30"
#                 b"\x35\x45\x30\x44\x37\x31\x30\x44\x36\x35\x30\x44\x35\x45\x30\x44"
#                 b"\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30"
#                 b"\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30"
#                 b"\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30"
#                 b"\x30\x38\x39\x30"
#             ),
#             "first_bit",
#         ),
#         (
#             bytearray(
#                 b"\x5e\x38\x34\x33\x35\x30\x30\x30\x30\x33\x38\x43\x44\x46\x46\x46\x46"
#                 b"\x32\x43\x46\x39\x30\x32\x30\x30\x39\x37\x30\x31\x36\x32\x30\x30"
#                 b"\x45\x31\x30\x42\x38\x30\x30\x30\x30\x30\x30\x30"
#                 b"\x35\x45\x30\x44\x37\x31\x30\x44\x36\x35\x30\x44\x35\x45\x30\x44"
#                 b"\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30"
#                 b"\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30"
#                 b"\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30\x30"
#                 b"\x30\x39\x30\x46"
#             ),
#             "last_bit",
#         ),
#     ],
#     ids=lambda param: param[1],
# )
# def prb_response(request):
#     """Return faulty response frame."""
#     return request.param


# async def test_problem_response(
#     monkeypatch, patch_bleak_client, problem_response
# ) -> None:
#     """Test data update with BMS returning error flags."""

#     monkeypatch.setattr(MockEctiveBleakClient, "_RESP", bytearray(problem_response[0]))

#     patch_bleak_client(MockEctiveBleakClient)

#     bms = BMS(generate_ble_device())

#     result: BMSsample = await bms.async_update()
#     assert result == {
#         "voltage": 13.7,
#         "current": -13.0,
#         "battery_level": 98,
#         "cycles": 407,
#         "cycle_charge": 194.86,
#         "cell_voltages": [
#             3.422,
#             3.441,
#             3.429,
#             3.422,
#         ],
#         "delta_voltage": 0.019,
#         "temperature": 31.0,
#         "cycle_capacity": 2669.582,
#         "power": -178.1,
#         "runtime": 53961,
#         "battery_charging": False,
#         "problem": True,
#         "problem_code": (1 if problem_response[1] == "first_bit" else 128),
#     }

#     await bms.disconnect()
