"""Module to support JBD smart BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from functools import cache
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSDp, BMSInfo, BMSSample, BMSValue, MatcherPattern
from aiobmsble.basebms import BaseBMS


class BMS(BaseBMS):
    """JBD smart BMS class implementation."""

    INFO: BMSInfo = {"default_manufacturer": "Jiabaida", "default_model": "smart BMS"}
    HEAD_RSP: Final[bytes] = bytes([0xDD])  # header for responses
    HEAD_CMD: Final[bytes] = bytes([0xDD, 0xA5])  # read header for commands
    TAIL: Final[int] = 0x77  # tail for command
    INFO_LEN: Final[int] = 7  # minimum frame size
    BASIC_INFO: Final[int] = 23  # basic info data length
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("temp_sensors", 26, 1, False, lambda x: x),  # count is not limited
        BMSDp("voltage", 4, 2, False, lambda x: x / 100),
        BMSDp("current", 6, 2, True, lambda x: x / 100),
        BMSDp("battery_level", 23, 1, False, lambda x: x),
        BMSDp("cycle_charge", 8, 2, False, lambda x: x / 100),
        BMSDp("cycles", 12, 2, False, lambda x: x),
        BMSDp("problem_code", 20, 2, False, lambda x: x),
    )  # general protocol v4

    def __init__(self, ble_device: BLEDevice, keep_alive: bool = True) -> None:
        """Intialize private BMS members."""
        super().__init__(ble_device, keep_alive)
        self._valid_reply: int = 0x00
        self._data_final: bytearray = bytearray()

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            MatcherPattern(
                local_name=pattern,
                service_uuid=BMS.uuid_services()[0],
                connectable=True,
            )
            for pattern in (
                "JBD-*",
                "SX1*",  # Supervolt v3
                "SX60*", # Supervolt Ultra
                "SBL-*",  # SBL
                "OGR-*",  # OGRPHY
                "TZ-H*",  # CERRNSS battery
            )
        ] + [
            MatcherPattern(
                oui=oui, service_uuid=BMS.uuid_services()[0], connectable=True
            )
            for oui in ("A4:C1:37", "A4:C1:38", "A5:C2:37", "AA:C2:37", "70:3E:97")
        ]

    @staticmethod
    def uuid_services() -> list[str]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return [normalize_uuid_str("ff00")]

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "ff01"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        return "ff02"

    # async def _fetch_device_info(self) -> BMSInfo: unknown, use default

    @staticmethod
    def _calc_values() -> frozenset[BMSValue]:
        return frozenset(
            {
                "power",
                "battery_charging",
                "cycle_capacity",
                "runtime",
                "delta_voltage",
                "temperature",
            }
        )

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        # check if answer is a heading of basic info (0x3) or cell block info (0x4)
        if (
            data.startswith(self.HEAD_RSP)
            and len(self._data) > self.INFO_LEN
            and data[1] in (0x03, 0x04)
            and data[2] == 0x00
            and len(self._data) >= self.INFO_LEN + self._data[3]
        ):
            self._data = bytearray()

        self._data += data
        self._log.debug(
            "RX BLE data (%s): %s", "start" if data == self._data else "cnt.", data
        )

        # verify that data is long enough
        if (
            len(self._data) < BMS.INFO_LEN
            or len(self._data) < BMS.INFO_LEN + self._data[3]
        ):
            return

        # check correct frame ending
        frame_end: Final[int] = BMS.INFO_LEN + self._data[3] - 1
        if self._data[frame_end] != BMS.TAIL:
            self._log.debug("incorrect frame end (length: %i).", len(self._data))
            return

        if (crc := BMS._crc(self._data[2 : frame_end - 2])) != int.from_bytes(
            self._data[frame_end - 2 : frame_end], "big"
        ):
            self._log.debug(
                "invalid checksum 0x%X != 0x%X",
                int.from_bytes(self._data[frame_end - 2 : frame_end], "big"),
                crc,
            )
            return

        if len(self._data) != BMS.INFO_LEN + self._data[3]:
            self._log.debug("wrong data length (%i): %s", len(self._data), self._data)

        if self._data[1] != self._valid_reply:
            self._log.debug("unexpected response (type 0x%X)", self._data[1])
            return

        self._data_final = self._data
        self._data_event.set()

    @staticmethod
    def _crc(frame: bytearray) -> int:
        """Calculate JBD frame CRC."""
        return 0x10000 - sum(frame)

    @staticmethod
    @cache
    def _cmd(cmd: bytes) -> bytes:
        """Assemble a JBD BMS command."""
        frame = bytearray([*BMS.HEAD_CMD, cmd[0], 0x00])
        frame.extend([*BMS._crc(frame[2:4]).to_bytes(2, "big"), BMS.TAIL])
        return bytes(frame)

    async def _await_cmd_resp(self, cmd: int) -> None:
        msg: Final[bytes] = BMS._cmd(bytes([cmd]))
        self._valid_reply = msg[2]
        await self._await_reply(msg)
        self._valid_reply = 0x00

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        data: BMSSample = {}
        await self._await_cmd_resp(0x03)
        data = BMS._decode_data(BMS._FIELDS, self._data_final)
        data["temp_values"] = BMS._temp_values(
            self._data_final,
            values=data.get("temp_sensors", 0),
            start=27,
            signed=False,
            offset=2731,
            divider=10,
        )

        await self._await_cmd_resp(0x04)
        data["cell_voltages"] = BMS._cell_voltages(
            self._data_final, cells=self._data_final[3] // 2, start=4, byteorder="big"
        )

        return data
