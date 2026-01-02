"""Test the Super-B v2 BMS implementation."""

from collections.abc import Awaitable, Buffer, Callable
from typing import Final
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.uuids import normalize_uuid_str
import pytest

from aiobmsble import BMSSample
from aiobmsble.bms.superb_v2_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import verify_device_info

BT_FRAME_SIZE = 32

RESP: dict[bytes, bytearray] = {
    b"\x21\x54\x00": bytearray(
        b"\x00\x23\x04\x13\xff\xff\x81\xe3\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x12\x64\x00\x01\x2f\x29"
    )
}


_RESULT_DEFS: Final[BMSSample] = {
    "battery_charging": False,
    "battery_health": 100,
    "battery_level": 35,
    "cycles": 18,
    "current": -2.465,
    "power": -32.555,
    "problem": False,
    "runtime": 77609,
    "voltage": 13.207,
}


class MockSuperBv2BleakClient(MockBleakClient):
    """Emulate a Super-B v2 BMS BleakClient."""

    _QUERY_RESP: dict[bytes, bytearray] = RESP
    _NOTIFY_RESP: bytearray = bytearray(
        b"\x02\x0d\x00\x00\x00\x00\xff\xff\xf6\x5f\x33\x97\x00\x00\x09\x64\x00\x00\x00\x00\x00\x00"
        b"\x00\x00"
    )

    def _send_info(self) -> None:
        assert self._notify_callback is not None
        for notify_data in [
            self._NOTIFY_RESP[i : i + BT_FRAME_SIZE]
            for i in range(0, len(self._NOTIFY_RESP), BT_FRAME_SIZE)
        ]:
            self._notify_callback("MockSuperBv2BleakClient", notify_data)

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str | UUID, cmd: bytes
    ) -> bytearray:
        if isinstance(char_specifier, str) and normalize_uuid_str(
            char_specifier
        ) != normalize_uuid_str("cf9ccdfa-eee9-43ce-87a5-82b54af5324e"):
            return bytearray()

        return self._QUERY_RESP.get(cmd, bytearray())

    @property
    def is_connected(self) -> bool:
        """Mock connected."""
        if self._connected:
            self._send_info()  # patch to provide data when not reconnecting
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
        self._send_info()

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
            self._notify_callback("MockSuperBv2BleakClient", notify_data)


async def test_update(
    monkeypatch: pytest.MonkeyPatch, patch_bleak_client, keep_alive_fixture: bool
) -> None:
    """Test Super-B v2 BMS data update."""

    patch_bleak_client(MockSuperBv2BleakClient)

    bms = BMS(generate_ble_device(), keep_alive_fixture)

    assert await bms.async_update() == _RESULT_DEFS

    # query again to check already connected state
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()


async def test_update_chrg(monkeypatch: pytest.MonkeyPatch, patch_bleak_client) -> None:
    """Test Super-B v2 BMS data update while charging."""

    monkeypatch.setattr(
        MockSuperBv2BleakClient,
        "_QUERY_RESP",
        {
            b"\x21\x54\x00": bytearray(
                b"\x00\x23\x04\x13\x00\x01\xdf\xd9\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x12\x64\xff\xff\xff\xff"
            )
        },
    )
    monkeypatch.setattr(
        MockSuperBv2BleakClient,
        "_NOTIFY_RESP",
        bytearray(
            b"\x02\x0e\x00\x00\x00\x00\x00\x00\x24\x12\x33\xd9\x00\x00\x09\x64\x00\x00\x00\x00\x00\x00\x00\x00"
        ),
    )
    patch_bleak_client(MockSuperBv2BleakClient)

    bms = BMS(generate_ble_device())

    assert await bms.async_update() == {
        "battery_charging": True,
        "battery_health": 100,
        "battery_level": 35,
        "cycles": 18,
        "current": 9.234,
        "power": 122.563,
        "problem": False,
        "voltage": 13.273,
    }

    await bms.disconnect()


async def test_device_info(patch_bleak_client) -> None:
    """Test that the BMS returns initialized dynamic device information."""
    await verify_device_info(patch_bleak_client, MockSuperBv2BleakClient, BMS)


@pytest.mark.parametrize(
    ("wrong_response"),
    [
        b"",
        MockSuperBv2BleakClient._NOTIFY_RESP[:-1],
        MockSuperBv2BleakClient._NOTIFY_RESP + b"\x00",
    ],
    ids=["empty", "too_short", "too_long"],
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
        MockSuperBv2BleakClient, "_NOTIFY_RESP", bytearray(wrong_response)
    )
    patch_bleak_client(MockSuperBv2BleakClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = {}
    with pytest.raises(TimeoutError):
        result = await bms.async_update()

    assert not result
    await bms.disconnect()


# @pytest.mark.parametrize(
#     ("problem_response"),
#     [
#         b"\x00\x74\x5e\x64\x00\x00\x01\xa4\xbe\xcc\xcc\xcd\x41\x62\x89\xc5\x00\x00\x00\x00",
#         b"\x00\x72\x5e\x64\x00\x00\x01\xa4\xbe\xcc\xcc\xcd\x41\x62\x89\xc5\x00\x00\x00\x00",
#     ],
#     ids=["chrg_warning", "dischrg_warning"],
# )
# async def test_problem_response(
#     monkeypatch, patch_bleak_client, problem_response
# ) -> None:
#     """Test data update with BMS returning error flags."""

#     monkeypatch.setattr(MockSuperBv2BleakClient, "_RESP", bytearray(problem_response))

#     patch_bleak_client(MockSuperBv2BleakClient)

#     bms = BMS(generate_ble_device())

#     result: BMSSample = await bms.async_update()
#     assert result == _RESULT_DEFS | {"problem": True, "problem_code": 1}

#     await bms.disconnect()
