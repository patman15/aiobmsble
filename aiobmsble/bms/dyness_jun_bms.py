"""Module to support Dyness Junior Box BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

import asyncio
import hashlib
import hmac
import json
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.base import CipherContext

from aiobmsble import BMSConfig, BMSDp, BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS, crc_xmodem


class BMS(BaseBMS):
    """Dyness Junior Box BMS class implementation (BluFi transport)."""

    INFO: BMSInfo = {"manufacturer": "Dyness", "model": "Junior Box"}

    accept_secret: bool = True  # device password is used as BluFi 'bleauth' sign

    _AES_KEY_PRE: Final[bytes] = b"214028"  # serial-number key prefix
    _DEFAULT_KEY: Final[bytes] = b"1111111111111111"  # fallback if no serial
    _HMAC_KEY: Final[bytes] = bytes.fromhex("75cb83eb7066a944085c0b157831d1b9")

    # BluFi frame type (lower 2 bits of the type byte) and subtypes (upper 6 bits)
    _T_CTRL: Final[int] = 0x00
    _T_DATA: Final[int] = 0x01
    _CTRL_SET_SEC: Final[int] = 0x01  # control: set security mode
    _DATA_CUSTOM: Final[int] = 0x13  # data: custom (application) payload
    # BluFi frame control flags
    _FC_ENC: Final[int] = 0x01  # data field is encrypted
    _FC_CKSUM: Final[int] = 0x02  # frame carries a trailing CRC16
    _FC_FRAG: Final[int] = 0x10  # more fragments follow
    _SEC_MODE: Final[int] = 0x03  # enable checksum + encryption for data frames
    _MTU: Final[int] = 200  # maximum BluFi payload per frame (fits 1-byte length)
    # provisional Modbus read command (function 0x03) and register map
    _MODBUS_READ: Final[bytes] = bytes.fromhex("010300000003")

    def __init__(
        self,
        ble_device: BLEDevice,
        config: BMSConfig | None = None,
        logger_name: str = "",
    ) -> None:
        """Initialize private BMS members."""
        super().__init__(ble_device, config, logger_name)
        self._key: bytes = BMS._derive_key(self.name)
        self._tx_seq: int = 0  # BluFi transmit sequence counter
        self._msg: bytes = b""  # decrypted application payload

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [MatcherPattern(local_name="R07*", connectable=True)]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return (normalize_uuid_str("fe00"),)

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "fe02"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        return "fe01"

    @classmethod
    def _derive_key(cls, serial: str) -> bytes:
        """Derive the 16-byte AES key/IV from the device serial number.

        The key is the first 16 bytes of the ASCII string ``"214028" + SN[:15]``;
        an empty serial falls back to a fixed default key.
        """
        if not serial or serial == "undefined":
            return cls._DEFAULT_KEY
        return (cls._AES_KEY_PRE + serial[:15].encode("ascii"))[:16].ljust(16, b"\x00")

    def _encrypt(self, data: bytes) -> bytes:
        """Encrypt data with AES-128-CBC (key == IV) and PKCS7 padding."""
        padder: padding.PaddingContext = padding.PKCS7(128).padder()
        enc: CipherContext = Cipher(algorithms.AES(self._key), modes.CBC(self._key)).encryptor()
        return enc.update(padder.update(data) + padder.finalize()) + enc.finalize()

    def _decrypt(self, data: bytes) -> bytes:
        """Decrypt AES-128-CBC data (key == IV) and remove PKCS7 padding."""
        dec: CipherContext = Cipher(algorithms.AES(self._key), modes.CBC(self._key)).decryptor()
        unpadder: padding.PaddingContext = padding.PKCS7(128).unpadder()
        plain: Final[bytes] = dec.update(data) + dec.finalize()
        return unpadder.update(plain) + unpadder.finalize()

    def _sign(self) -> str:
        """Return the configured device password or the HMAC-derived fallback."""
        if self._cfg.secret:
            return self._cfg.secret
        return hmac.new(
            BMS._HMAC_KEY, self.name.encode("ascii"), hashlib.sha256
        ).hexdigest()

    def _build_frame(
        self, subtype: int, ftype: int, payload: bytes, encrypt: bool
    ) -> bytes:
        """Assemble a single (non-fragmented) BluFi frame."""
        assert len(payload) <= BMS._MTU, "payload exceeds single BluFi frame"
        data: Final[bytes] = self._encrypt(payload) if encrypt and payload else payload
        fctrl: Final[int] = BMS._FC_CKSUM | (BMS._FC_ENC if encrypt and payload else 0)
        seq: Final[int] = self._tx_seq & 0xFF
        self._tx_seq += 1
        head: Final[bytes] = bytes([(subtype << 2) | ftype, fctrl, seq, len(data)])
        crc: Final[int] = crc_xmodem(bytes([seq, len(data)]) + data)
        return head + data + crc.to_bytes(2, "little")

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new BluFi frame arrives)."""
        self._log.debug("RX BLE data: %s", data.hex(" "))
        frame: Final[bytes] = bytes(data)
        if len(frame) < 4:
            self._log.debug("BluFi frame too short")
            return

        fctrl, dlen = frame[1], frame[3]
        body: Final[bytes] = frame[4:]
        if fctrl & BMS._FC_CKSUM:
            if len(body) < dlen + 2:
                self._log.debug("BluFi frame incomplete")
                return
            if not self._check_integrity(
                frame, crc_xmodem, slice(2, 4 + dlen), slice(4 + dlen, 6 + dlen), "little"
            ):
                return
        elif len(body) < dlen:
            self._log.debug("BluFi frame incomplete")
            return

        content: bytes = body[:dlen]
        fragmented: Final[bool] = bool(fctrl & BMS._FC_FRAG)
        if fragmented:  # skip the 2-byte total-content-length prefix
            content = content[2:]
        if fctrl & BMS._FC_ENC:
            try:
                content = self._decrypt(content)
            except ValueError:
                self._log.debug("BluFi decryption failed")
                return

        self._frame.extend(content)
        if fragmented:
            return  # wait for the remaining fragments

        self._msg = bytes(self._frame)
        self._frame.clear()
        self._msg_event.set()

    async def _init_connection(
        self, char_notify: BleakGATTCharacteristic | int | str | None = None
    ) -> None:
        """Set up notifications and perform the BluFi authentication handshake."""
        self._tx_seq = 0
        await super()._init_connection(char_notify)

        # enable checksum + encryption for BluFi data frames
        await self._await_msg(
            self._build_frame(
                BMS._CTRL_SET_SEC, BMS._T_CTRL, bytes([BMS._SEC_MODE]), False
            ),
            wait_for_notify=False,
        )
        await asyncio.sleep(0)

        # authenticate the session with the device password (BluFi custom data)
        auth: Final[bytes] = json.dumps(
            {"req": "bleauth", "sign": self._sign()}, separators=(",", ":")
        ).encode("ascii")
        await self._await_msg(self._build_frame(BMS._DATA_CUSTOM, BMS._T_DATA, auth, True))
        if not self._msg:
            self._log.warning("BluFi authentication was rejected")
            raise PermissionError("BluFi authentication failed.")

    async def _fdbg(self, command: bytes) -> bytes:
        """Send a Modbus command via the BluFi 'fdbg' request and return the reply."""
        request: Final[bytes] = json.dumps(
            {"req": "fdbg", "data": command.hex()}, separators=(",", ":")
        ).encode("ascii")
        await self._await_msg(
            self._build_frame(BMS._DATA_CUSTOM, BMS._T_DATA, request, True)
        )
        reply: str = self._msg.decode("utf-8", errors="ignore").strip()
        if reply.startswith("{"):  # response may wrap the payload in JSON
            reply = str(json.loads(reply).get("data", ""))
        return bytes.fromhex(reply) if reply else b""

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        # provisional: read-holding-registers request and register map are unconfirmed
        frame: Final[bytes] = await self._fdbg(BMS._MODBUS_READ)
        if len(frame) < 3 or frame[1] != 0x03 or len(frame) < 5 + frame[2]:
            raise ValueError("invalid Modbus response")
        return BMS._decode_data(BMS._FIELDS, frame)

    _FIELDS: tuple[BMSDp, ...] = (
        BMSDp("voltage", 3, 2, False, lambda x: x / 100),
        BMSDp("current", 5, 2, True, lambda x: x / 100),
        BMSDp("battery_level", 7, 2, False),
    )
