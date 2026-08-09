"""Module to support 123SmartBMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

import asyncio
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice

from aiobmsble import BMSConfig, BMSDp, BMSInfo, BMSSample, MatcherPattern, TempSensor
from aiobmsble.basebms import BaseBMS


class BMS(BaseBMS):
    """123SmartBMS implementation.

    The BMS is accessed via a BLE UART bridge (Nordic UART Service, e.g. the
    Raytac/Alice nRF52810 module). The BMS pushes one 58 byte status frame
    per second. Each frame contains the fixed status values plus rotating
    data: the information of one specific cell and one key/value pair.
    See docs/smartbms_bms.md for the frame layout and key/value pair
    definition.
    """

    INFO: BMSInfo = {
        "default_manufacturer": "123electric",
        "default_model": "123SmartBMS",
    }
    _MSG_LEN: Final[int] = 58  # frame length in bytes
    _CELL_OFFSET: Final[int] = 0x0114  # temperature offset, 0x0114 -> 0 degC
    _KV_POS: Final[int] = 47  # position of the key/value pair key
    _KV_OFFSET: Final[int] = 25  # key value offset, 25 -> key 0
    _MAX_KEY: Final[int] = 18  # highest key value
    _STATUS2_ALARM_MASK: Final[int] = 0x0E  # early warning, Tmin exceed bits
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("voltage", 0, 3, False, lambda x: x / 200),
        BMSDp("battery_level", 40, 1, False),
        BMSDp("cell_count", 25, 1, False),
        BMSDp("chrg_mosfet", 30, 1, False, lambda x: bool(x & 0x01)),
        BMSDp("dischrg_mosfet", 30, 1, False, lambda x: bool(x & 0x02)),
        BMSDp("problem_code", 30, 1, False, lambda x: (x >> 2) & 0x3F),
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
        self._cells: dict[int, tuple[float, float]] = {}
        self._kv: dict[int, int] = {}

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            {
                "local_name": pattern,
                "service_uuid": BMS.uuid_services()[0],
                "connectable": True,
            }
            for pattern in ("123\\SmartBMS", "123BMS-BLE*")
        ]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return ("6e400001-b5a3-f393-e0a9-e50e24dcca9e",)

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        return "6e400002-b5a3-f393-e0a9-e50e24dcca9e"

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        self._log.debug("RX BLE data: %s", data)
        self._frame.extend(data)
        frame: Final[bytearray] = self._frame
        offset: int = 0
        while len(frame) - offset >= BMS._MSG_LEN:
            if BMS._valid_frame(bytes(frame[offset : offset + BMS._MSG_LEN])):
                self._process_frame(bytes(frame[offset : offset + BMS._MSG_LEN]))
                offset += BMS._MSG_LEN
            else:
                offset += 1  # no header, resync on next possible frame start
        del frame[:offset]

    @staticmethod
    def _valid_frame(frame: bytes) -> bool:
        """Check the 8-bit checksum at the end of the frame."""
        return sum(frame[: BMS._MSG_LEN - 1]) & 0xFF == frame[BMS._MSG_LEN - 1]

    def _process_frame(self, frame: bytes) -> None:
        """Process a valid frame and accumulate rotating data."""
        self._msg = frame
        cell_nr: Final[int] = frame[24]
        cell_count: Final[int] = frame[25]
        if 0 < cell_nr <= cell_count:
            self._cells[cell_nr] = (
                int.from_bytes(frame[26:28], "big") / 200,
                BMS._decode_temperature(frame[28:30]),
            )
        key: Final[int] = frame[BMS._KV_POS] - BMS._KV_OFFSET
        if 0 <= key <= BMS._MAX_KEY:
            self._kv[key] = frame[BMS._KV_POS + 1]
        self._msg_event.set()

    @staticmethod
    def _decode_current(raw: int) -> float:
        """Decode the sum current from sign byte and value with 0.125 A resolution."""
        sign: Final[int] = (raw >> 16) & 0xFF
        value: Final[float] = (raw & 0xFFFF) * 0.125
        if sign == ord("X"):
            return 0.0
        return -value if sign == ord("-") else value

    @staticmethod
    def _decode_temperature(raw: bytes) -> float:
        """Decode a temperature value with 1 degC resolution."""
        return int.from_bytes(raw, "big") - BMS._CELL_OFFSET

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        await asyncio.wait_for(self._wait_event(), timeout=BMS.TIMEOUT)

        result: BMSSample = BMS._decode_data(BMS._FIELDS, self._msg, byteorder="big")
        result["current"] = BMS._decode_current(int.from_bytes(self._msg[9:12], "big"))

        vmin: Final[float] = int.from_bytes(self._msg[12:14], "big") / 200
        vmax: Final[float] = int.from_bytes(self._msg[15:17], "big") / 200
        result["delta_voltage"] = round(vmax - vmin, 3)

        temp_values: list[TempSensor] = [
            TempSensor(
                BMS._decode_temperature(self._msg[18:20]), TempSensor.T.CELL_MIN
            ),
            TempSensor(
                BMS._decode_temperature(self._msg[21:23]), TempSensor.T.CELL_MAX
            ),
        ]

        cell_count: Final[int] = result["cell_count"]
        cells: list[int] = [nr for nr in range(1, cell_count + 1) if nr in self._cells]
        if len(cells) == cell_count:
            # only report cells once the full set has been received (rotating data)
            result["cell_voltages"] = [self._cells[nr][0] for nr in cells]
            temp_values.extend(
                TempSensor(self._cells[nr][1], TempSensor.T.CELL) for nr in cells
            )
        result["temp_values"] = temp_values

        if 0 in self._kv and self._kv[0] <= 100:
            result["battery_health"] = self._kv[0]
        if 8 in self._kv and 9 in self._kv:
            result["cycles"] = (self._kv[8] << 8) + self._kv[9]
        if 16 in self._kv:
            result["problem_code"] = result.get("problem_code", 0) | (
                self._kv[16] & BMS._STATUS2_ALARM_MASK
            )
        if 4 in self._kv and 5 in self._kv and cell_count:
            nominal: Final[float] = (
                (self._kv[4] << 8) + self._kv[5]
            ) / 200  # nominal cell voltage
            capacity_kwh: Final[float] = int.from_bytes(self._msg[49:51], "big") / 10
            if nominal > 0:
                result["design_capacity"] = round(
                    capacity_kwh * 1000 / (nominal * cell_count)
                )

        result["cycle_capacity"] = int.from_bytes(self._msg[34:37], "big")

        return result
