"""Module to support Lithionics BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

import asyncio
from enum import IntEnum, auto
from typing import Final, Literal

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSConfig, BMSDp, BMSInfo, BMSSample, MatcherPattern, TempSensor
from aiobmsble.basebms import BaseBMS


class BMS(BaseBMS):
    """Lithionics BMS implementation (ASCII stream protocol)."""

    class _Msg(IntEnum):
        prim = auto()
        stat = auto()

    INFO: BMSInfo = {
        "default_manufacturer": "Lithionics",
        "default_model": "NeverDie smart BMS",
    }
    _HEAD_STAT: Final[bytes] = b"&,"
    _MIN_FIELDS_PRIM: Final[int] = 10
    _MIN_FIELDS_STAT: Final[int] = 3
    _FIXED_LEN_PRIM: Final[int] = 46
    _FIELDS_STAT: Final[int] = 15
    _PROBLEM_MASK: Final[int] = 0x68CEFD

    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("voltage", 0, 1, False, lambda x: x / 100, _Msg.prim),
        BMSDp("cell_voltages", 1, 4, False, lambda x: x / 100, _Msg.prim),
        BMSDp(
            "temp_values",
            5,
            2,
            False,
            lambda x: round((x - 32) * 5 / 9, 3),
            _Msg.prim,
        ),
        BMSDp("current", 7, 1, False, float, _Msg.prim),
        BMSDp("battery_level", 8, 1, False, lambda x: x, _Msg.prim),
        BMSDp(
            "problem_code",
            9,
            1,
            False,
            lambda x: int(str(x), 16) & BMS._PROBLEM_MASK,
            _Msg.prim,
        ),
        BMSDp("cycle_charge", 2, 1, False, lambda x: x, _Msg.stat),
        BMSDp("total_charge", 3, 1, False, lambda x: x, _Msg.stat),
    )
    _FIELDS_FIXED: Final[tuple[BMSDp, ...]] = (
        BMSDp("voltage", 2, 1, False, lambda x: x / 10, _Msg.prim),
        BMSDp("battery_level", 3, 1, False, int, _Msg.prim),
        BMSDp("cycle_charge", 1, 1, False, lambda x: x / 10, _Msg.prim),
        BMSDp("current", 6, 1, False, lambda x: x / 10, _Msg.prim),
        BMSDp("power", 7, 1, False, lambda x: x, _Msg.prim),
        BMSDp("battery_charging", 5, 1, False, lambda x: x == 1, _Msg.prim),
        BMSDp(
            "temp_values", 8, 1, False, lambda x: round((x - 32) * 5 / 9, 3), _Msg.prim
        ),
        BMSDp(
            "problem_code",
            9,
            1,
            False,
            lambda x: int(str(x), 16) & BMS._PROBLEM_MASK,
            _Msg.prim,
        ),
    )

    def __init__(
        self,
        ble_device: BLEDevice,
        config: BMSConfig | None = None,
        logger_name: str = "",
    ) -> None:
        """Initialize private BMS members."""
        super().__init__(ble_device, config, logger_name)
        self._msg: dict[int, bytes] = {}

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            MatcherPattern(
                local_name="Li[0-9]-*",
                service_uuid=BMS.uuid_services()[0],
                manufacturer_id=19784,
                connectable=True,
            ),
        ]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return (normalize_uuid_str("ffe0"),)

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "ffe1"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        raise NotImplementedError

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        self._log.debug("RX BLE data: %s", data)

        self._frame.extend(data)

        while (idx := self._frame.find(b"\r\n")) >= 0:
            line = bytes(self._frame[:idx])
            del self._frame[: idx + 2]

            if not line:
                continue

            if line == b"ERROR":
                self._log.debug("ignoring command response: %s", line)
                continue

            fields: int = line.count(b",") + 1

            if line.startswith(BMS._HEAD_STAT) and fields >= BMS._MIN_FIELDS_STAT:
                self._msg[BMS._Msg.stat] = line
            elif line[:1].isdigit() and fields >= BMS._MIN_FIELDS_PRIM:
                self._msg[BMS._Msg.prim] = line

        if self._msg.keys() >= {m.value for m in BMS._Msg}:
            self._msg_event.set()

        if len(self._frame) > BMS.BLE_MAX_ATTR_SIZE:
            self._log.debug("invalid frame")
            self._frame.clear()

    @staticmethod
    def _is_fixed_length(msg: bytes) -> bool:
        """Detect the zero-padded fixed-length stream variant."""
        # check number of fields and battery ID < 10 as comma separated has voltage as first field
        return len(msg) == BMS._FIXED_LEN_PRIM and msg.find(b",") == 1

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        self._msg.clear()
        self._msg_event.clear()
        await asyncio.wait_for(self._wait_event(), timeout=BMS.TIMEOUT)

        try:
            if BMS._is_fixed_length(self._msg[BMS._Msg.prim]):
                result = BMS._decode_data(BMS._FIELDS_FIXED, self._msg)
                # TODO: status: list[bytes] = self._msg[BMS._Msg.stat].split(b",")
                # if len(status) >= BMS._FIELDS_STAT:
                #     result["delta_voltage"] = round(
                #         (int(status[13]) - int(status[12])) / 100,
                #         3,
                #     )
            else:
                result = BMS._decode_data(BMS._FIELDS, self._msg)
        except (IndexError, ValueError) as exc:
            raise ValueError("BMS data incomplete.") from exc

        return result

    @staticmethod
    def _decode_data(
        fields: tuple[BMSDp, ...],
        data: bytes | dict[int, bytes],
        *,
        byteorder: Literal["little", "big"] = "big",
        start: int = 0,
    ) -> BMSSample:
        """Decode a CSV stream payload using the shared field definition format."""
        assert isinstance(data, dict)

        msg_dict: dict[int, list[str]] = {}
        for line, raw in data.items():
            msg_dict[line] = raw.decode("ascii").strip().split(",")

        result: BMSSample = {}
        for field in fields:
            end: int = start + field.pos + field.size
            msg: list[str] = msg_dict[field.idx]
            if end > len(msg):
                continue

            if field.key == "cell_voltages":
                result[field.key] = [
                    field.fct(int(msg[i])) for i in range(start + field.pos, end)
                ]
            elif field.key == "temp_values":
                result[field.key] = [
                    TempSensor(field.fct(int(msg[i])))
                    for i in range(start + field.pos, end)
                ]
            else:  # assumes field.size == 1
                result[field.key] = field.fct(int(msg[start + field.pos]))

        return result
