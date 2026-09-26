"""Test Stark VARG authentication and notification validation."""

from collections.abc import Callable
from hashlib import sha256
from types import SimpleNamespace
from typing import cast

from bleak.backends.characteristic import BleakGATTCharacteristic
import pytest

from aiobmsble.bms.stark_varg_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.test_basebms import BMSBasicTests


class TestBasicBMS(BMSBasicTests):
    """Test common Stark VARG metadata checks."""

    bms_class = BMS

    async def test_result_value_types(
        self,
        patch_bleak_client: Callable[..., None],
        patch_bms_timeout: Callable[..., None],
        request: pytest.FixtureRequest,
    ) -> None:
        """Require real captured battery payloads for sample type validation."""
        pytest.skip("No anonymized real-device telemetry capture is available.")


def test_auth_key() -> None:
    """Decode the configured V2 key without altering its bytes."""
    secret: str = "00112233445566778899aabbccddeeff"
    assert BMS._auth_key(secret) == bytes.fromhex(secret)


@pytest.mark.parametrize("secret", ["", "not-hex", "00" * 15, "00" * 17])
def test_auth_key_rejects_invalid_values(secret: str) -> None:
    """Reject missing, malformed, and incorrectly sized authentication keys."""
    with pytest.raises(ValueError, match="32-character hex key"):
        BMS._auth_key(secret)


def test_auth_response() -> None:
    """Match the documented response envelope using a synthetic nonce."""
    key: bytes = bytes(range(16))
    nonce: bytes = bytes(range(32))
    header: bytes = b"\x02\x01"
    assert BMS._auth_response(key, nonce) == header + sha256(key + header + nonce).digest()


@pytest.mark.parametrize(
    ("key", "nonce", "message"),
    [
        (b"short", bytes(32), "key must contain 16 bytes"),
        (bytes(16), b"short", "nonce must contain 32 bytes"),
    ],
)
def test_auth_response_rejects_invalid_lengths(key: bytes, nonce: bytes, message: str) -> None:
    """Reject invalid challenge-response inputs before hashing."""
    with pytest.raises(ValueError, match=message):
        BMS._auth_response(key, nonce)


def test_notification_handler_rejects_unusable_notifications() -> None:
    """Ignore malformed UUIDs, unsupported characteristics, and short data."""
    bms: BMS = BMS(generate_ble_device())
    bms._notification_handler(
        cast(BleakGATTCharacteristic, SimpleNamespace(uuid="not-a-uuid")), bytearray()
    )
    bms._notification_handler(
        cast(
            BleakGATTCharacteristic,
            SimpleNamespace(uuid=f"00006006{BMS._UUID_SUFFIX}"),
        ),
        bytearray(6),
    )
    bms._notification_handler(
        cast(
            BleakGATTCharacteristic,
            SimpleNamespace(uuid=f"00005001{BMS._UUID_SUFFIX}"),
        ),
        bytearray(18),
    )
    assert bms._msg == {}
    assert not bms._msg_event.is_set()


def test_auth_notification_requires_response_phase() -> None:
    """Accept only a success byte received after submitting the response."""
    bms: BMS = BMS(generate_ble_device())
    sender: BleakGATTCharacteristic = cast(
        BleakGATTCharacteristic, SimpleNamespace(uuid=BMS.uuid_rx())
    )
    bms._auth_phase = "reading_nonce"
    bms._notification_handler(sender, bytearray(b"\x01"))
    assert not bms._auth_event.is_set()

    bms._auth_phase = "awaiting_result"
    bms._notification_handler(sender, bytearray())
    assert not bms._auth_event.is_set()
    bms._notification_handler(sender, bytearray(b"\x01"))
    assert bms._auth_result
    assert bms._auth_event.is_set()
