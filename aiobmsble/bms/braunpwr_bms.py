"""Module to support Braun Power BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSDp, BMSInfo, BMSSample, BMSValue, MatcherPattern
from aiobmsble.basebms import BaseBMS, barr2str


class BMS(BaseBMS):
    """Braun Power BMS class implementation."""

    INFO: BMSInfo = {
        "default_manufacturer": "Braun Power",
        "default_model": "smart BMS",
    }
    _HEAD: Final[bytes] = b"\x7b"  # header for responses
    _TAIL: Final[int] = 0x7D  # tail for command
    _MIN_LEN: Final[int] = 4  # minimum frame size
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("cell_count", 3, 1, False, lambda x: x, 0x2),
        BMSDp("temp_sensors", 3, 1, False, lambda x: x, 0x3),
        BMSDp("voltage", 5, 2, False, lambda x: x / 100, 0x1),
        BMSDp("current", 13, 2, True, lambda x: x / 100, 0x1),
        BMSDp("battery_level", 4, 1, False, lambda x: x, 0x1),
        BMSDp("cycle_charge", 15, 2, False, lambda x: x / 100, 0x1),
        BMSDp("design_capacity", 17, 2, False, lambda x: x // 100, 0x1),
        BMSDp("cycles", 23, 2, False, lambda x: x, 0x1),
        BMSDp("problem_code", 31, 2, False, lambda x: x, 0x1),
    )
    _CMDS: Final[set[int]] = {field.idx for field in _FIELDS}
    _INIT_CMDS: Final[set[int]] = {
        0x74,  # SW version
        0xF4,  # BMS program version
        0xF5,  # BMS boot version
    }

    def __init__(self, ble_device: BLEDevice, keep_alive: bool = True) -> None:
        """Intialize private BMS members."""
        super().__init__(ble_device, keep_alive)
        self._data_final: dict[int, bytearray] = {}
        self._exp_reply: tuple[int] = (0x01,)

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            MatcherPattern(
                local_name=pattern,
                service_uuid=BMS.uuid_services()[0],
                manufacturer_id=0x7B,
                connectable=True,
            )
            for pattern in ("HSKS-*", "BL-*")
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

    async def _fetch_device_info(self) -> BMSInfo:
        """Fetch the device information via BLE."""
        for cmd in BMS._INIT_CMDS:
            self._exp_reply = (cmd,)
            await self._await_reply(BMS._cmd(cmd))
        return {
            "sw_version": '.'.join(str(x) for x in self._data_final[0xF4][3:6]),
            "hw_version": barr2str(self._data_final[0x74][3:-1]),
        }

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
        # check if answer is a heading of valid response type
        if (
            data.startswith(BMS._HEAD)
            and len(self._data) >= BMS._MIN_LEN
            and data[1] in {*BMS._CMDS, *BMS._INIT_CMDS}
            and len(self._data) >= BMS._MIN_LEN + self._data[2]
        ):
            self._data = bytearray()

        self._data += data
        self._log.debug(
            "RX BLE data (%s): %s", "start" if data == self._data else "cnt.", data
        )

        # verify that data is long enough
        if (
            len(self._data) < BMS._MIN_LEN
            or len(self._data) < BMS._MIN_LEN + self._data[2]
        ):
            return

        # check correct frame ending
        if self._data[-1] != BMS._TAIL:
            self._log.debug("incorrect frame end (length: %i).", len(self._data))
            self._data.clear()
            return

        if self._data[1] not in self._exp_reply:
            self._log.debug("unexpected command 0x%02X", self._data[1])
            self._data.clear()
            return

        # check if response length matches expected length
        if len(self._data) != BMS._MIN_LEN + self._data[2]:
            self._log.debug("wrong data length (%i): %s", len(self._data), self._data)
            self._data.clear()
            return

        self._data_final[self._data[1]] = self._data
        self._data_event.set()

    @staticmethod
    def _cmd(cmd: int, data: bytes = b"") -> bytes:
        """Assemble a Braun Power BMS command."""
        assert len(data) <= 255, "data length must be a single byte."
        return bytes([*BMS._HEAD, cmd, len(data), *data, BMS._TAIL])

    async def _init_connection(
        self, char_notify: BleakGATTCharacteristic | int | str | None = None
    ) -> None:
        """Connect to the BMS and setup notification if not connected."""
        await super()._init_connection()
        await self._fetch_device_info()

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        self._data_final.clear()
        for cmd in BMS._CMDS:
            self._exp_reply = (cmd,)
            await self._await_reply(BMS._cmd(cmd))

        data: BMSSample = BMS._decode_data(BMS._FIELDS, self._data_final)
        data["cell_voltages"] = BMS._cell_voltages(
            self._data_final[0x2], cells=data.get("cell_count", 0), start=4
        )
        data["temp_values"] = BMS._temp_values(
            self._data_final[0x3],
            values=data.get("temp_sensors", 0),
            start=4,
            offset=2731,
            divider=10,
        )

        return data
