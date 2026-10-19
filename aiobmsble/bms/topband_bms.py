"""Module to support Topband BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

import asyncio
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSConfig, BMSDp, BMSInfo, BMSSample, MatcherPattern, TempSensor as TS
from aiobmsble.basebms import BaseBMS, crc_sum


class BMS(BaseBMS):
    """Topband BMS implementation."""

    INFO: BMSInfo = {"manufacturer": "Topband", "model": "smart BMS"}
    _HEX_UPPER: Final[frozenset[int]] = frozenset(b"0123456789ABCDEF")
    _HEAD_TABLE = bytes(0x00 if chr(i) in "0123456789ABCDEF" else 0xFF for i in range(256))
    _HEAD_RSP: Final[bytes] = bytes(c for c in range(256) if chr(c) not in "0123456789ABCDEF")
    _MAX_CELLS: Final[int] = 16
    _INFO_LEN: Final[int] = 113
    _CRC_LEN: Final[int] = 4
    FIELDS: tuple[BMSDp, ...] = (
        BMSDp("voltage", 0, 4, False, lambda x: x / 1000),
        BMSDp("current", 4, 4, True, lambda x: x / 1000),
        BMSDp("battery_level", 14, 2, False),
        BMSDp("cycle_charge", 8, 4, False, lambda x: x / 1000),
        BMSDp("cycles", 12, 2, False),
        BMSDp("temp_values", 16, 2, False, lambda x: [TS(round(x / 10 - 273.15, 3))]),
        BMSDp("problem_code", 18, 1, False),
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
            {
                "service_uuid": BMS.uuid_services()[0],
                "connectable": True,
                "manufacturer_id": m_id,
            }
            for m_id in (0, 0xFFFF)
        ]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return (normalize_uuid_str("ffe0"),)

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "ffe4"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        raise NotImplementedError

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""

        # check for beginning of frame
        if (start := bytes(data).translate(BMS._HEAD_TABLE).rfind(0xFF)) != -1 and (
            len(self._frame) + start <= BMS._INFO_LEN or not self._frame
        ):
            data = data[start:]
            self._frame.clear()

        self._frame.extend(data)
        self._log.debug("RX BLE data (%s): %s", "start" if data == self._frame else "cnt.", data)

        if len(self._frame) < BMS._INFO_LEN:
            return

        del self._frame[BMS._INFO_LEN :]
        self._frame = self._frame.rstrip(BMS._HEAD_RSP)

        # Handle potential two headers in final chunk
        if len(self._frame[1:]) % 2 or not BMS._HEX_UPPER.issuperset(self._frame[1:]):
            self._log.debug("incorrect frame coding: %s", self._frame)
            self._frame.clear()
            return

        _dec: Final[bytes] = bytes.fromhex(self._frame[1:].decode())

        if not self._check_integrity(
            _dec, lambda x: crc_sum(x, 2), slice(None, -2), slice(-2, None)
        ):
            self._frame.clear()
            return

        self._msg = _dec
        self._msg_event.set()
        self._frame.clear()

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""

        await asyncio.wait_for(self._wait_event(), timeout=BMS.TIMEOUT)
        return self._decode_data(BMS.FIELDS, self._msg, byteorder="little") | {
            "cell_voltages": BMS._cell_voltages(
                self._msg, cells=BMS._MAX_CELLS, start=22, byteorder="little"
            )
        }
