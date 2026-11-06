"""Test the Liontron BMS implementation."""

from collections.abc import Buffer
from typing import Final
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.uuids import normalize_uuid_str
import pytest

from aiobmsble import BMSConfig, BMSSample
from aiobmsble.bms.liontron_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.bms.test_jbd_bms import _RESULT_DEFS, MockJBDBleakClient
from tests.test_basebms import BMSBasicTests

UNLOCK_CMD_1: Final[bytes] = bytes.fromhex("FF AA 23 00 23")
UNLOCK_CMD_2: Final[bytes] = bytes.fromhex("FF AA 03 00 03")


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


class MockLiontronBleakClient(MockJBDBleakClient):
    """Emulate a Liontron BMS, answering queries only after a valid unlock command."""

    REQUIRE_PASS = True
    VALID_UNLOCK: frozenset[bytes] = frozenset()
    UNLOCKED = False

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
    ) -> bytes:
        _msg: Final[bytes] = bytes(data)
        if (
            isinstance(char_specifier, str)
            and normalize_uuid_str(char_specifier) == normalize_uuid_str("ff02")
            and _msg in (UNLOCK_CMD_1, UNLOCK_CMD_2)
        ):
            if _msg in self.VALID_UNLOCK:
                self.UNLOCKED = True
            return b""

        if not self.UNLOCKED:
            return b""
        return super()._response(char_specifier, data)


@pytest.mark.parametrize(
    "valid_unlock",
    [{UNLOCK_CMD_1}, {UNLOCK_CMD_2}, set()],
    ids=["unlock_cmd_1", "unlock_cmd_2", "no_unlock"],
)
async def test_update_unlock(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    patch_bms_timeout,
    valid_unlock: set[bytes],
) -> None:
    """Test that no query reply is returned before a valid unlock command."""

    patch_bms_timeout()
    monkeypatch.setattr(MockLiontronBleakClient, "VALID_UNLOCK", frozenset(valid_unlock))
    patch_bleak_client(MockLiontronBleakClient)

    bms = BMS(generate_ble_device(), BMSConfig())
    if valid_unlock:
        result: BMSSample = await bms.async_update()
        assert result == _RESULT_DEFS
    else:
        with pytest.raises(TimeoutError):
            await bms.async_update()

    await bms.disconnect()
