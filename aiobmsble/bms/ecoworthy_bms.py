"""Module to support ECO-WORTHY BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

import asyncio
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSDp, BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS, crc_modbus


class BMS(BaseBMS):
    """ECO-WORTHY BMS implementation."""

    INFO: BMSInfo = {"default_manufacturer": "ECO-WORTHY", "default_model": "BW 02/0B"}
    _HEAD: Final[tuple[bytes, ...]] = (b"\xa1", b"\xa2")
    _CELL_POS: Final[int] = 14
    _TEMP_POS: Final[int] = 80
    _FIELDS_V1: Final[tuple[BMSDp, ...]] = (
        BMSDp("battery_level", 16, 2, False, idx=0xA1),
        BMSDp("battery_health", 18, 2, False, idx=0xA1),
        BMSDp("voltage", 20, 2, False, lambda x: x / 100, 0xA1),
        BMSDp("current", 22, 2, True, lambda x: x / 100, 0xA1),
        BMSDp("problem_code", 51, 2, False, idx=0xA1),
        BMSDp("design_capacity", 26, 2, False, lambda x: x // 100, 0xA1),
        BMSDp("cell_count", _CELL_POS, 2, False, idx=0xA2),
        BMSDp("temp_sensors", _TEMP_POS, 2, False, idx=0xA2),
        # ("cycles", 0xA1, 8, 2, False,
    )
    _FIELDS_V2: Final[tuple[BMSDp, ...]] = tuple(
        BMSDp(
            *field[:-2],
            (lambda x: x / 10) if field.key == "current" else field.fct,
            field.idx,
        )
        for field in _FIELDS_V1
    )
    _INIT_CMDS: Final[tuple[bytes, ...]] = (
        b"\xff\x08\x02\x00\x0b\x01\x00\x64\x01\xff\xff\xff\xff\xff\xff\xff\x00\x2d",
        b"\xff\x08\x02\x00\x0b\x01\x00\x14\x01\xff\xff\xff\xff\xff\xff\xff\x65\xef",
    )
    _CMDS: Final = frozenset(field.idx for field in _FIELDS_V1)

    def __init__(
        self,
        ble_device: BLEDevice,
        keep_alive: bool = True,
        secret: str = "",
        logger_name: str = "",
    ) -> None:
        """Initialize private BMS members."""
        super().__init__(ble_device, keep_alive, secret, logger_name)
        self._mac_head: Final[tuple[bytes, ...]] = tuple(
            int(self._ble_device.address.replace(":", ""), 16).to_bytes(6) + head
            for head in BMS._HEAD
        )
        self._msg: dict[int, bytes] = {}

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [MatcherPattern(local_name="ECO-WORTHY 02_*", connectable=True)] + [
            MatcherPattern(
                local_name=pattern,
                service_uuid=BMS.uuid_services()[0],
                connectable=True,
            )
            for pattern in ("DCHOUSE*", "ECO-WORTHY*")
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
        return "fff2"

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        self._log.debug("RX BLE data: %s", data)

        if not data.startswith(BMS._HEAD + self._mac_head):
            self._log.debug("invalid frame type: '%s'", data[0:1].hex())
            return

        if not self._check_integrity(
            data,
            crc_modbus,
            slice(None, -2),
            slice(-2, None),
            "little",
        ):
            return

        # copy final data without message type and adapt to protocol type
        shift: Final[bool] = data.startswith(self._mac_head)
        self._msg[data[6 if shift else 0]] = bytes(2 if shift else 0) + bytes(data)
        if BMS._CMDS.issubset(self._msg.keys()):
            self._msg_event.set()

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""

        if not self._msg_event.is_set():
            self._log.debug("requesting data update")
            self._msg.update(
                {0xA1: b"", 0xA2: b""}
            )  # empty dictionary, i.e. wait for any BMS message
            for cmd in BMS._INIT_CMDS:
                await self._await_msg(cmd)
            self._msg.clear()
            self._msg_event.clear()

        await asyncio.wait_for(self._wait_event(), timeout=BMS.TIMEOUT)

        result: BMSSample = BMS._decode_data(
            (
                BMS._FIELDS_V1
                if self._msg[0xA1].startswith(BMS._HEAD)
                else BMS._FIELDS_V2
            ),
            self._msg,
        )

        result["cell_voltages"] = BMS._cell_voltages(
            self._msg[0xA2],
            cells=result.get("cell_count", 0),
            start=BMS._CELL_POS + 2,
        )
        result["temp_values"] = BMS._temp_values(
            self._msg[0xA2],
            values=result.get("temp_sensors", 0),
            start=BMS._TEMP_POS + 2,
            divider=10,
        )

        self._msg.clear()
        self._msg_event.clear()  # clear event to ensure new data is acquired

        return result
