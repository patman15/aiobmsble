"""Module to support PowerBoozt Batteries."""

from string import hexdigits
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSDp, BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import crc_sum

from .ej_bms import BMS as EJBMS


class BMS(EJBMS):
    """PowerBoozt battery implementation."""

    INFO: BMSInfo = {
        "default_manufacturer": "Powerboozt",
        "default_model": "battery",
    }
    _FIELDS: tuple[BMSDp, ...] = (
        # BMSDp(
        #     "current", 44, 4, False, lambda x: ((x >> 16) - (x & 0xFFFF)) / 100, Cmd.RT
        # ),
        BMSDp("battery_level", 69, 1, False),
        BMSDp("current", 54, 4, True, lambda x: x / 1000),
        # BMSDp("cycle_charge", 7, 2, False, lambda x: x / 10, Cmd.CAP),
        # BMSDp(
        #     "temp_values", 48, 1, False, lambda x: [TempSensor(x - 40)], Cmd.RT
        # ),  # only 1st sensor relevant
        BMSDp("cycles", 67, 2, False),
        BMSDp("design_capacity", 70, 4, False, lambda x: x // 1000),
        BMSDp("voltage", 62, 2, False, lambda x: x / 1000),
        # BMSDp(
        #     "problem_code", 52, 2, False, lambda x: x & 0x0FFC, Cmd.RT
        # ),  # mask status bits
        # BMSDp("dischrg_mosfet", 52, 1, False, lambda x: bool(x & 0x10), Cmd.RT),
        # BMSDp("chrg_mosfet", 52, 1, False, lambda x: bool(x & 0x20), Cmd.RT),
        # BMSDp("balancer", 55, 2, False, int, idx=Cmd.RT),
        # BMSDp("heater", 54, 1, False, bool, Cmd.RT),
        # BMSDp("design_capacity", 66, 2, False, lambda x: x // 10, Cmd.RT),
    )

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            {
                "local_name": "BT-Battery*",
                "manufacturer_id": 32516,
                "service_uuid": BMS.uuid_services()[0],
                "connectable": True,
            },
        ]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return (normalize_uuid_str("fff0"),)

    @staticmethod
    def uuid_rx() -> str:
        """Return 128-bit UUID of characteristic that provides notification/read property."""
        return "fff1"

    @staticmethod
    def uuid_tx() -> str:
        """Return 128-bit UUID of characteristic that provides write property."""
        return "fff2"

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""

        if data.startswith(BMS._BT_MODULE_MSG):
            self._log.debug("filtering AT cmd")
            if not (data := data.removeprefix(BMS._BT_MODULE_MSG)):
                return

        if data.startswith(BMS._HEAD):  # check for beginning of frame
            self._frame.clear()

        self._frame.extend(data)

        self._log.debug(
            "RX BLE data (%s): %s", "start" if data == self._frame else "cnt.", data
        )

        exp_frame_len: Final[int] = (
            min(int(self._frame[7:11], 16), BMS._MAX_MSG_LEN)
            if len(self._frame) > 10
            and all(chr(c) in hexdigits for c in self._frame[7:11])
            else BMS._MAX_MSG_LEN
        )
        self._frame = self._frame.replace(b"\x00", b"")

        if not self._frame.startswith(BMS._HEAD) or (
            not self._frame.endswith(BMS._TAIL) and len(self._frame) < exp_frame_len
        ):
            return

        if not self._frame.endswith(BMS._TAIL):
            self._log.debug("incorrect EOF")
            self._frame.clear()
            return

        if (len(self._frame) % 2) or not all(
            chr(c) in hexdigits for c in self._frame[1:-1]
        ):
            self._log.debug("incorrect frame encoding")
            self._frame.clear()
            return

        if len(self._frame) != exp_frame_len:
            self._log.debug(
                "incorrect frame length %i != %i", len(self._frame), exp_frame_len
            )
            self._frame.clear()
            return

        self._log.debug(
            "address: 0x%X, command 0x%X, version: 0x%X, length: 0x%X",
            int(self._frame[1:3], 16),
            int(self._frame[3:5], 16) & 0x7F,
            int(self._frame[5:7], 16),
            len(self._frame),
        )

        self._msg = bytes.fromhex(self._frame[1:-1].decode())

        if not self._check_integrity(
            self._msg, lambda x: crc_sum(x) ^ 0xFF, slice(1, -1), self._msg[-1]
        ):
            self._frame.clear()
            return

        self._msg_event.set()

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""

        # query real-time information and capacity
        await self._await_msg(b":015150000EFE~")

        return self._decode_data(BMS._FIELDS, self._msg) | {
            "cell_voltages": BMS._cell_voltages(
                self._msg, cells=BMS._MAX_CELLS, start=BMS._CELL_POS
            ),
            "temp_values": BMS._temp_values(
                self._msg, start=48, values=4, size=1, signed=False, offset=40
            ),
        }
