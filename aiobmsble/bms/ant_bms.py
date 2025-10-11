"""Module to support ANT BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from functools import cache
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSDp, BMSInfo, BMSSample, BMSValue, MatcherPattern
from aiobmsble.basebms import BaseBMS, barr2str, crc_modbus


class BMS(BaseBMS):
    """ANT BMS implementation."""

    INFO: BMSInfo = {"default_manufacturer": "ANT", "default_model": "smart BMS"}
    _HEAD: Final[bytes] = b"\x7e\xa1"
    _TAIL: Final[bytes] = b"\xaa\x55"
    _MIN_LEN: Final[int] = 10  # frame length without data
    _CMD_STAT: Final[int] = 0x01
    _CMD_DEV: Final[int] = 0x02
    _TEMP_POS: Final[int] = 8
    _MAX_TEMPS: Final[int] = 6
    _CELL_COUNT: Final[int] = 9
    _CELL_POS: Final[int] = 34
    _MAX_CELLS: Final[int] = 32
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("voltage", 38, 2, False, lambda x: x / 100),
        BMSDp("current", 40, 2, True, lambda x: x / 10),
        BMSDp("design_capacity", 50, 4, False, lambda x: x // 1e6),
        BMSDp("battery_level", 42, 2, False, lambda x: x),
        BMSDp(
            "problem_code",
            46,
            2,
            False,
            lambda x: ((x & 0xF00) if (x >> 8) not in (0x1, 0x4, 0xB, 0xF) else 0)
            | ((x & 0xF) if (x & 0xF) not in (0x1, 0x4, 0xB, 0xC, 0xF) else 0),
        ),
        BMSDp("cycle_charge", 54, 4, False, lambda x: x / 1e6),
        BMSDp("total_charge", 58, 4, False, lambda x: x // 1000),
        BMSDp("delta_voltage", 82, 2, False, lambda x: x / 1000),
        BMSDp("power", 62, 4, True, lambda x: x / 1),
    )

    def __init__(self, ble_device: BLEDevice, keep_alive: bool = True) -> None:
        """Initialize BMS."""
        super().__init__(ble_device, keep_alive)
        self._data_final: bytearray = bytearray()
        self._valid_reply: int = BMS._CMD_STAT | 0x10  # valid reply mask
        self._exp_len: int = 0

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            {
                "local_name": "ANT-BLE*",
                "service_uuid": BMS.uuid_services()[0],
                "manufacturer_id": 0x2313,
                "connectable": True,
            }
        ]

    @staticmethod
    def uuid_services() -> list[str]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return [normalize_uuid_str("ffe0")]  # change service UUID here!

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "ffe1"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        return "ffe1"

    async def _fetch_device_info(self) -> BMSInfo:
        """Fetch the device information via BLE."""

        await self._await_reply(BMS._cmd(BMS._CMD_DEV, 0x026C, 0x20))
        return BMSInfo(
            hw_version=barr2str(self._data_final[6:22]),
            sw_version=barr2str(self._data_final[22:38]),
        )

    @staticmethod
    def _calc_values() -> frozenset[BMSValue]:
        return frozenset(
            {"cycle_capacity", "cycles", "temperature"}
        )  # calculate further values from BMS provided set ones

    async def _init_connection(
        self, char_notify: BleakGATTCharacteristic | int | str | None = None
    ) -> None:
        """Initialize RX/TX characteristics and protocol state."""
        await super()._init_connection(char_notify)
        self._exp_len = 0

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""

        if (
            data.startswith(BMS._HEAD)
            and len(self._data) >= self._exp_len
            and len(data) >= BMS._MIN_LEN
        ):
            self._data = bytearray()
            self._exp_len = data[5] + BMS._MIN_LEN

        self._data += data
        self._log.debug(
            "RX BLE data (%s): %s", "start" if data == self._data else "cnt.", data
        )

        if len(self._data) < self._exp_len or len(self._data) < BMS._MIN_LEN:
            return

        if self._data[2] != self._valid_reply:
            self._log.debug("unexpected response (type 0x%X)", self._data[2])
            return

        if len(self._data) != self._exp_len and self._data[2] != BMS._CMD_DEV | 0x10:
            # length of CMD_DEV is incorrect, so we ignore the length check here
            self._log.debug(
                "invalid frame length %d != %d", len(self._data), self._exp_len
            )
            return

        if not self._data.endswith(BMS._TAIL):
            self._log.debug("invalid frame end")
            return

        if (crc := crc_modbus(self._data[1 : self._exp_len - 4])) != int.from_bytes(
            self._data[self._exp_len - 4 : self._exp_len - 2], "little"
        ):
            self._log.debug(
                "invalid checksum 0x%X != 0x%X",
                int.from_bytes(
                    self._data[self._exp_len - 4 : self._exp_len - 2], "little"
                ),
                crc,
            )
            return

        self._data_final = self._data.copy()
        self._data_event.set()

    @staticmethod
    @cache
    def _cmd(cmd: int, adr: int, value: int) -> bytes:
        """Assemble a ANT BMS command."""
        frame: bytearray = (
            bytearray([*BMS._HEAD, cmd & 0xFF])
            + adr.to_bytes(2, "little")
            + int.to_bytes(value & 0xFF, 1)
        )
        frame.extend(int.to_bytes(crc_modbus(frame[1:]), 2, "little"))
        return bytes(frame) + BMS._TAIL

    @staticmethod
    def _temp_sensors(data: bytearray, sensors: int, offs: int) -> list[float]:
        return [
            float(int.from_bytes(data[idx : idx + 2], byteorder="little", signed=True))
            for idx in range(offs, offs + sensors * 2, 2)
        ]

    async def _await_reply(
        self,
        data: bytes,
        char: int | str | None = None,
        wait_for_notify: bool = True,
        max_size: int = 0,
    ) -> None:
        """Send data to the BMS and wait for valid reply notification."""

        self._valid_reply = data[2] | 0x10  # expected reply type
        await super()._await_reply(data, char, wait_for_notify, max_size)

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        await self._await_reply(BMS._cmd(BMS._CMD_STAT, 0, 0xBE))

        result: BMSSample = {}
        result["battery_charging"] = self._data_final[7] == 0x2
        result["cell_count"] = min(self._data_final[BMS._CELL_COUNT], BMS._MAX_CELLS)
        result["cell_voltages"] = BMS._cell_voltages(
            self._data_final,
            cells=result["cell_count"],
            start=BMS._CELL_POS,
            byteorder="little",
        )
        result["temp_sensors"] = min(self._data_final[BMS._TEMP_POS], BMS._MAX_TEMPS)
        result["temp_values"] = BMS._temp_sensors(
            self._data_final,
            result["temp_sensors"] + 2,  # + MOSFET, balancer temperature
            BMS._CELL_POS + result["cell_count"] * 2,
        )
        result.update(
            BMS._decode_data(
                BMS._FIELDS,
                self._data_final,
                byteorder="little",
                offset=(result["temp_sensors"] + result["cell_count"]) * 2,
            )
        )

        return result
