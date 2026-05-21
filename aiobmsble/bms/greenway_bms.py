"""Module to support Greenway BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

import asyncio
from enum import IntEnum
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSDp, BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS, crc_sum


class MsgT(IntEnum):
    """Message types in MyVolta BMS data stream."""

    VOLTAGE = 0x9
    CURRENT = 0xA
    SOC = 0xD
    SOH = 0xE
    DCAP = 0xF
    CYCLES = 0x17
    CELL_VOLTAGES1 = 0x24
    CELL_VOLTAGES2 = 0x25


class BMS(BaseBMS):
    """Greenway BMS implementation."""

    INFO: BMSInfo = {
        "default_manufacturer": "Unknown",
        "default_model": "Greenway",
    }
    _HEAD: Final[bytes] = b"\x47\x16\x01"
    _LEN_POS: Final[int] = 4
    _MIN_LEN: Final[int] = 6
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("voltage", 0, 4, False, lambda x: x / 1000, MsgT.VOLTAGE),
        BMSDp("current", 0, 4, True, lambda x: x / 1000, MsgT.CURRENT),
        BMSDp("battery_level", 0, 4, False, idx=MsgT.SOC),
        BMSDp("battery_health", 0, 4, False, idx=MsgT.SOH),
        BMSDp("cycles", 0, 4, False, idx=MsgT.CYCLES),
        BMSDp("cycle_charge", 0, 4, False, lambda x: x / 1000, idx=MsgT.DCAP),
        # BMSDp("heater", 2, 2, False, lambda x: bool(x & 0x8000), MsgT.INFO),
        # BMSDp("problem_code", 1, 4, False, lambda x: x & BMS._PRB_MASK, MsgT.INFO),
    )

    _MSG_SET: Final[frozenset[int]] = frozenset(MsgT)

    def __init__(
        self,
        ble_device: BLEDevice,
        keep_alive: bool = True,
        secret: str = "",
        logger_name: str = "",
    ) -> None:
        """Initialize private BMS members."""
        super().__init__(ble_device, keep_alive, secret, logger_name)
        self._msg: dict[int, bytes] = {}

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            {
                "oui": "C4:A9:B8",
                "service_uuid": BMS.uuid_services()[0],
                "connectable": True,
            }
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
        self._log.debug("RX BLE data: %s", data)

        if data.startswith(BMS._HEAD):  # check for beginning of frame
            self._frame.clear()

        self._frame.extend(data)

        if (
            len(self._frame) < BMS._MIN_LEN
            or len(self._frame) < self._frame[BMS._LEN_POS] + BMS._MIN_LEN
        ):
            return

        if not self._frame.startswith(BMS._HEAD):
            self._log.debug("incorrect frame header")
            self._frame.clear()
            return

        if not self._check_integrity(
            self._frame, crc_sum, slice(None, -1), slice(-1, None)
        ):
            return

        self._msg[self._frame[3]] = bytes(self._frame)
        self._log.debug("received message type 0x%X", self._frame[3])
        if BMS._MSG_SET.issubset(self._msg.keys()):
            self._msg_event.set()

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        await asyncio.wait_for(self._wait_event(), timeout=BMS.TIMEOUT)

        result: BMSSample = self._decode_data(
            BMS._FIELDS, self._msg, byteorder="little", start=BMS._LEN_POS + 1
        )
        for msg_type in (
            MsgT.CELL_VOLTAGES1,
            MsgT.CELL_VOLTAGES2,
        ):
            result.setdefault("cell_voltages", []).extend(
                self._cell_voltages(
                    self._msg[msg_type],
                    cells=16,
                    start=BMS._LEN_POS + 1,
                    divider=1000,
                    byteorder="little",
                )
            )

        # for msg_type in (
        #     # MsgT.CELL_TEMPS1, MsgT.CELL_TEMPS2,
        #     MsgT.TEMPS3,
        #     MsgT.TEMPS4,
        #     MsgT.TEMPS5,
        #     # MsgT.TEMPS6, MsgT.TEMPS7, MsgT.TEMPS8,
        # ):
        #     result.setdefault("temp_values", []).extend(
        #         self._temp_values(
        #             self._msg[msg_type],
        #             values=4,
        #             start=7,
        #             divider=10,
        #             byteorder="little",
        #         )
        #     )

        self._msg.clear()
        self._msg_event.clear()
        return result
