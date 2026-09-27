"""Module to support Stark VARG battery telemetry."""

import asyncio
from hashlib import sha256
from string import hexdigits
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSConfig, BMSDp, BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS


class BMS(BaseBMS):
    """Stark VARG read-only battery telemetry implementation."""

    INFO: BMSInfo = {"manufacturer": "Stark Future", "model": "VARG"}
    accept_secret: bool = True

    _UUID_SUFFIX: Final[str] = "-5374-6172-4b20-467574757265"
    _VIN_WMI: Final[str] = "UDU"  # Vehicle Id Number / World Manufacturer Identifier
    _AUTH_CHAR: Final[str] = f"00001001{_UUID_SUFFIX}"
    _DATA_CHARS: Final[frozenset[int]] = frozenset(
        {0x5001, 0x6003, 0x6004, 0x6005, 0x6007, 0x6008}
    )
    _MIN_LENGTHS: Final[dict[int, int]] = {
        0x5001: 19,
        0x6003: 4,
        0x6004: 2,
        0x6005: 27,
        0x6007: 200,
        0x6008: 13,
    }
    _CELLS: Final[int] = 100
    _FIELDS: tuple[BMSDp, ...] = (
        BMSDp("current", 2, 2, False, lambda x: x / 10, 0x5001),
        BMSDp("cell_count", 0, 1, False, idx=0x6003),
        BMSDp("battery_level", 0, 2, False, idx=0x6004),
        BMSDp("battery_health", 2, 2, False, idx=0x6004),
        BMSDp("voltage", 4, 2, False, lambda x: x / 10, 0x6004),
        BMSDp("temp_sensors", 26, 1, False, idx=0x6005),
        BMSDp("balancer", 0, 13, False, bool, 0x6008),
    )

    def __init__(
        self,
        ble_device: BLEDevice,
        config: BMSConfig | None = None,
        logger_name: str = "",
    ) -> None:
        """Initialize authentication and notification state."""
        super().__init__(ble_device, config, logger_name)
        self._msg: dict[int, bytes] = {}
        self._auth_event: asyncio.Event = asyncio.Event()
        self._auth_result: bool = False
        self._auth_phase: str = "idle"

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Match connectable Stark Future motorcycles advertising their VIN."""
        return [
            {
                "local_name": BMS._VIN_WMI + "[A-HJ-NPR-Z0-9]" * 14,
                "connectable": True,
            }
        ]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return the Bike, Charger, and Battery GATT service UUIDs."""
        return tuple(
            normalize_uuid_str(f"0000{service}{BMS._UUID_SUFFIX}")
            for service in ("1000", "5000", "6000")
        )

    @staticmethod
    def uuid_rx() -> str:
        """Return the app-level authentication notification characteristic UUID."""
        return normalize_uuid_str(BMS._AUTH_CHAR)

    @staticmethod
    def uuid_tx() -> str:
        """Return the app-level authentication read/write characteristic UUID."""
        return normalize_uuid_str(BMS._AUTH_CHAR)

    @staticmethod
    def _auth_key(secret: str) -> bytes:
        """Decode a configured 16-byte derived key represented as 32 hex digits."""
        if len(secret) != 32 or any(ch not in hexdigits for ch in secret):
            raise ValueError("Authentication requires a 32-character hex key.")
        return bytes.fromhex(secret)

    @staticmethod
    def _auth_response(key: bytes, nonce: bytes) -> bytes:
        """Build the documented V2 challenge response without exposing secret bytes."""
        if len(key) != 16:
            raise ValueError("Authentication key must contain 16 bytes.")
        if len(nonce) != 32:
            raise ValueError("Authentication nonce must contain 32 bytes.")
        header: Final[bytes] = b"\x02\x01"
        return header + sha256(key + header + nonce).digest()

    async def _init_connection(
        self, char_notify: BleakGATTCharacteristic | int | str | None = None
    ) -> None:
        """Authenticate before subscribing to protected battery telemetry."""
        if not self._cfg.secret:
            raise ConnectionRefusedError(
                "Stark VARG telemetry requires a configured 32-character hex key."
            )
        key: Final[bytes] = self._auth_key(self._cfg.secret)

        await super()._init_connection(char_notify)
        self._auth_phase = "reading_nonce"
        nonce: Final[bytes] = bytes(await self._client.read_gatt_char(BMS._AUTH_CHAR))
        if len(nonce) != 32:
            raise ConnectionRefusedError("invalid authentication nonce.")

        self._auth_result = False
        self._auth_event.clear()
        self._auth_phase = "awaiting_result"
        await self._client.write_gatt_char(
            BMS._AUTH_CHAR, BMS._auth_response(key, nonce), response=True
        )
        try:
            await asyncio.wait_for(self._auth_event.wait(), timeout=BMS.TIMEOUT)
        except TimeoutError as exc:
            raise ConnectionRefusedError("authentication timed out") from exc
        if not self._auth_result:
            raise ConnectionRefusedError("rejected app-level authentication")

        self._auth_phase = "authenticated"
        await self._client.stop_notify(BMS._AUTH_CHAR)
        for char_id in BMS._DATA_CHARS:
            await self._client.start_notify(
                f"{char_id:08x}{BMS._UUID_SUFFIX}", self._notification_handler
            )

    async def _disconnect(self, reset: bool) -> None:
        """Clear telemetry and security state before reconnecting."""
        self._msg.clear()
        self._msg_event.clear()
        self._auth_event.clear()
        self._auth_phase = "idle"
        self._auth_result = False

    def _notification_handler(
        self, sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Validate notification lengths and cache telemetry by characteristic."""
        char_uuid: str = str(getattr(sender, "uuid", sender)).lower()
        self._log.debug("RX BLE data (%s): %s", char_uuid[:8], data)
        if char_uuid == BMS.uuid_rx():
            if self._auth_phase == "awaiting_result" and data:
                self._auth_result = data[0] == 0x01
                self._auth_event.set()
            return

        try:
            char_id: int = int(char_uuid.split("-", maxsplit=1)[0], 16)
        except ValueError:
            self._log.debug("ignoring notification with an unknown characteristic UUID")
            return
        if char_id not in BMS._DATA_CHARS:
            self._log.debug("ignoring unsupported characteristic %#06x", char_id)
            return
        if len(data) < BMS._MIN_LENGTHS[char_id]:
            self._log.debug(
                "ignoring short payload %#06x (%d bytes)", char_id, len(data)
            )
            return

        self._msg[char_id] = bytes(data)
        if BMS._DATA_CHARS.issubset(self._msg):
            self._msg_event.set()

    async def _async_update(self) -> BMSSample:
        """Wait for battery telemetry and map documented values to BMSSample."""
        await asyncio.wait_for(self._msg_event.wait(), timeout=BMS.TIMEOUT)

        result: BMSSample = BMS._decode_data(BMS._FIELDS, self._msg, byteorder="little")

        cells: bytes = self._msg[0x6007]
        result["cell_voltages"] = BMS._cell_voltages(
            cells, cells=BMS._CELLS, start=0, byteorder="little", divider=10_000
        )

        temperatures: bytes = self._msg[0x6005]
        valid_sensors: int = int.from_bytes(temperatures[24:26], "little")
        result["temp_values"] = [
            temperature
            for index, temperature in enumerate(
                BMS._temp_values(
                    temperatures,
                    start=0,
                    values=12,
                    byteorder="little",
                    signed=False,
                    divider=10,
                )
            )
            if valid_sensors & (1 << index)
        ]

        self._msg.clear()
        self._msg_event.clear()

        return result
