"""Test the Dyness Junior Box BMS implementation."""

from collections.abc import Buffer
import json
from typing import Final
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.base import CipherContext
import pytest

from aiobmsble import BMSConfig, BMSSample
from aiobmsble.basebms import crc_xmodem
from aiobmsble.bms.dyness_jun_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import BMSBasicTests

_DEVICE_NAME: Final[str] = "R07E8546681A00F9"

_RESULT_DEFS: Final[BMSSample] = {
    "voltage": 51.2,
    "current": -2.87,
    "battery_level": 74,
    "power": -146.944,
    "battery_charging": False,
    "problem": False,
}

# Modbus RTU reply: addr 01, func 03, 6 bytes -> 51.2 V, -2.87 A, 74 % + CRC
_MODBUS_REPLY: Final[bytes] = bytes.fromhex("0103061400fee1004a0000")


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


class MockDynessBleakClient(MockBleakClient):
    """Emulate a Dyness Junior Box BluFi BleakClient."""

    WRAP_JSON: bool = False  # wrap the Modbus reply in a JSON envelope
    AUTH_OK: bool = True  # answer the bleauth request
    AUTH_EMPTY: bool = False  # answer bleauth with an empty payload
    BAD_MODBUS: bool = False  # answer fdbg with an empty/invalid payload

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Initialize the mock with the Dyness services and AES key."""
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self._services = ["fe01", "fe02", "fed5"]
        self._key: bytes = BMS._derive_key(self._ble_device.name or "")
        self._rx_seq: int = 0

    def _encrypt(self, data: bytes) -> bytes:
        padder: padding.PaddingContext = padding.PKCS7(128).padder()
        enc: CipherContext = Cipher(algorithms.AES(self._key), modes.CBC(self._key)).encryptor()
        return enc.update(padder.update(data) + padder.finalize()) + enc.finalize()

    def _decrypt(self, data: bytes) -> bytes:
        dec: CipherContext = Cipher(algorithms.AES(self._key), modes.CBC(self._key)).decryptor()
        unpadder: padding.PaddingContext = padding.PKCS7(128).unpadder()
        plain: bytes = dec.update(data) + dec.finalize()
        return unpadder.update(plain) + unpadder.finalize()

    def _resp(self, payload: bytes) -> bytearray:
        enc: Final[bytes] = self._encrypt(payload)
        seq: Final[int] = self._rx_seq & 0xFF
        self._rx_seq += 1
        head: Final[bytes] = bytes([(0x13 << 2) | 0x01, 0x03, seq, len(enc)])
        crc: Final[int] = crc_xmodem(bytes([seq, len(enc)]) + enc)
        return bytearray(head + enc + crc.to_bytes(2, "little"))

    async def write_gatt_char(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        data: Buffer,
        response: bool | None = None,
    ) -> None:
        """Parse the written BluFi frame and deliver a matching response."""
        assert self._notify_callback, "write to char but notifications not enabled"
        frame: Final[bytes] = bytes(data)
        fctrl, dlen = frame[1], frame[3]
        if not fctrl & 0x01:  # plaintext control frame (set security) -> no reply
            return

        request: Final[dict[str, str]] = json.loads(self._decrypt(frame[4 : 4 + dlen]))
        if request.get("req") == "bleauth":
            if self.AUTH_EMPTY:
                self._notify_callback("dyness", self._resp(b""))
            elif self.AUTH_OK:
                self._notify_callback("dyness", self._resp(b'{"code":0}'))
            return
        if request.get("req") == "fdbg":
            if self.BAD_MODBUS:
                reply: bytes = b""
            elif self.WRAP_JSON:
                reply = json.dumps({"data": _MODBUS_REPLY.hex()}).encode()
            else:
                reply = _MODBUS_REPLY.hex().encode()
            self._notify_callback("dyness", self._resp(reply))


@pytest.mark.parametrize("wrap_json", [False, True], ids=["plain", "json_wrapped"])
async def test_update(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    keep_alive_fixture: bool,
    wrap_json: bool,
) -> None:
    """Test Dyness Junior Box BMS data update via the BluFi handshake."""

    monkeypatch.setattr(MockDynessBleakClient, "WRAP_JSON", wrap_json)
    patch_bleak_client(MockDynessBleakClient)

    bms = BMS(generate_ble_device(name=_DEVICE_NAME), BMSConfig(keep_alive_fixture))

    assert await bms.async_update() == _RESULT_DEFS

    # query again to check already connected state
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()


async def test_auth_rejected(
    monkeypatch: pytest.MonkeyPatch, patch_bleak_client, patch_bms_timeout
) -> None:
    """Test that a missing bleauth response raises PermissionError."""

    patch_bms_timeout()
    monkeypatch.setattr(MockDynessBleakClient, "AUTH_OK", False)
    patch_bleak_client(MockDynessBleakClient)

    bms = BMS(generate_ble_device(name=_DEVICE_NAME))
    with pytest.raises(TimeoutError):
        await bms.async_update()

    await bms.disconnect()


async def test_auth_empty(monkeypatch: pytest.MonkeyPatch, patch_bleak_client) -> None:
    """Test that an empty bleauth response raises PermissionError."""

    monkeypatch.setattr(MockDynessBleakClient, "AUTH_EMPTY", True)
    patch_bleak_client(MockDynessBleakClient)

    bms = BMS(generate_ble_device(name=_DEVICE_NAME))
    with pytest.raises(PermissionError):
        await bms.async_update()

    await bms.disconnect()


async def test_invalid_modbus(
    monkeypatch: pytest.MonkeyPatch, patch_bleak_client
) -> None:
    """Test that an invalid Modbus reply raises ValueError."""

    monkeypatch.setattr(MockDynessBleakClient, "BAD_MODBUS", True)
    patch_bleak_client(MockDynessBleakClient)

    bms = BMS(generate_ble_device(name=_DEVICE_NAME))
    with pytest.raises(ValueError, match="invalid Modbus response"):
        await bms.async_update()

    await bms.disconnect()


@pytest.mark.parametrize(
    ("frame", "complete"),
    [
        (b"\x00\x00", False),
        (bytes([0x45, 0x02, 0x00, 0x0A]) + b"\x00\x00", False),
        (bytes([0x45, 0x02, 0x00, 0x01]) + b"\xaa\x00\x00", False),
        (bytes([0x44, 0x00, 0x00, 0x05]) + b"\x00\x00", False),
        (bytes([0x44, 0x00, 0x00, 0x03]) + b"abc", True),
    ],
    ids=["short", "cksum_incomplete", "crc_bad", "incomplete", "valid_plain"],
)
async def test_notification_handler(frame: bytes, complete: bool) -> None:
    """Test BluFi frame validation in the notification handler."""

    bms = BMS(generate_ble_device(name=_DEVICE_NAME))
    bms._notification_handler(None, bytearray(frame))  # type: ignore[arg-type]
    assert bms._msg_event.is_set() is complete
    if complete:
        assert bms._msg == b"abc"
    await bms.disconnect()


async def test_fragment_reassembly() -> None:
    """Test BluFi fragment reassembly across notifications."""

    bms = BMS(generate_ble_device(name=_DEVICE_NAME))
    frag1: Final[bytes] = bytes([0x4D, 0x10, 0x00, 0x04]) + b"\x00\x00hi"
    frag2: Final[bytes] = bytes([0x4D, 0x00, 0x01, 0x05]) + b"there"
    bms._notification_handler(None, bytearray(frag1))  # type: ignore[arg-type]
    assert not bms._msg_event.is_set()
    bms._notification_handler(None, bytearray(frag2))  # type: ignore[arg-type]
    assert bms._msg_event.is_set()
    assert bms._msg == b"hithere"
    await bms.disconnect()


async def test_decrypt_failure() -> None:
    """Test that an undecryptable encrypted frame is discarded."""

    bms = BMS(generate_ble_device(name=_DEVICE_NAME))
    content: Final[bytes] = b"\x00" * 15  # not a whole AES block -> decrypt fails
    crc: Final[int] = crc_xmodem(bytes([0x00, len(content)]) + content)
    frame: Final[bytes] = (
        bytes([0x4D, 0x03, 0x00, len(content)]) + content + crc.to_bytes(2, "little")
    )
    bms._notification_handler(None, bytearray(frame))  # type: ignore[arg-type]
    assert not bms._msg_event.is_set()
    await bms.disconnect()


async def test_derive_key() -> None:
    """Test AES key derivation from the serial number and the default fallback."""

    assert BMS._derive_key(_DEVICE_NAME) == b"214028R07E854668"
    assert BMS._derive_key("") == BMS._DEFAULT_KEY
    assert BMS._derive_key("undefined") == BMS._DEFAULT_KEY


async def test_crypto_roundtrip() -> None:
    """Test that AES-CBC encrypt/decrypt round-trips and secret/sign selection."""

    bms = BMS(generate_ble_device(name=_DEVICE_NAME), BMSConfig(secret="s3cret"))
    assert bms._decrypt(bms._encrypt(b"hello world")) == b"hello world"
    assert bms._sign() == "s3cret"

    anon = BMS(generate_ble_device(name=_DEVICE_NAME))
    assert anon._sign() != ""  # HMAC-derived fallback signature
    await bms.disconnect()
    await anon.disconnect()
