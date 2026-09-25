"""Module to support Allpowers portable power stations (PPS).

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

import asyncio
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSConfig, BMSDp, BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS


class BMS(BaseBMS):
    """Allpowers portable power station BMS class implementation."""

    INFO: BMSInfo = {"manufacturer": "Allpowers", "model": "portable power station"}

    _SOF: Final[int] = 0xA5
    _STATUS_MIN_LEN: Final[int] = 15  # minimum length for a status frame

    # Flag byte (index 7) bit masks
    _FLAG_DC: Final[int] = 0x01
    _FLAG_AC: Final[int] = 0x02

    # Sentinel value meaning "no discharge runtime available" (charging or idle)
    _RUNTIME_NONE: Final[int] = 0xFFFF

    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("chrg_mosfet", 7, 1, False, lambda x: bool(x & BMS._FLAG_AC)),
        BMSDp("dischrg_mosfet", 7, 1, False, lambda x: bool(x & BMS._FLAG_DC)),
        BMSDp("battery_level", 8, 1, False),
        BMSDp("power", 9, 4, False, lambda x: float((x >> 16) - (x & 0xFFFF))),
        BMSDp("runtime", 13, 2, False, lambda x: x * 60),
    )

    def __init__(
        self,
        ble_device: BLEDevice,
        config: BMSConfig | None = None,
        logger_name: str = "",
    ) -> None:
        """Initialize private BMS members."""
        super().__init__(ble_device, config, logger_name)
        self._msg: bytes = b""

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            MatcherPattern(
                local_name=pattern,
                service_uuid=BMS.uuid_services()[0],
                connectable=True,
            )
            for pattern in ("AP R*", "VOLIX-*")
        ]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return (normalize_uuid_str("fff0"),)

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "fff1"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        raise NotImplementedError

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        self._log.debug("RX BLE data: %s", data.hex())

        if len(data) < BMS._STATUS_MIN_LEN:
            self._log.debug("incorrect frame length")
            return

        if data[0] != BMS._SOF:
            self._log.debug("incorrect SOF")
            return

        self._msg = bytes(data)
        self._msg_event.set()

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""

        self._msg_event.clear()
        await asyncio.wait_for(self._wait_event(), timeout=BMS.TIMEOUT)

        result: BMSSample = BMS._decode_data(BMS._FIELDS, self._msg)

        # runtime only applies while discharging with a valid (non-sentinel) reading
        if (
            result.get("power", 0) >= 0
            or result.get("runtime") == BMS._RUNTIME_NONE * 60
        ):
            result.pop("runtime", None)

        return result
