"""Module to support Lithionics BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

import asyncio
from typing import Any, Final, Literal, cast

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSConfig, BMSDp, BMSInfo, BMSSample, MatcherPattern, TempSensor
from aiobmsble.basebms import BaseBMS


class BMS(BaseBMS):
    """Lithionics BMS implementation (ASCII stream protocol)."""

    INFO: BMSInfo = {
        "default_manufacturer": "Lithionics",
        "default_model": "NeverDie smart BMS",
    }
    _HEAD_STATUS: Final[str] = "&,"
    _MIN_FIELDS_PRIMARY: Final[int] = 10
    _MIN_FIELDS_STATUS: Final[int] = 3
    _FIXED_WIDTHS: Final[tuple[int, ...]] = (1, 5, 4, 3, 3, 1, 5, 6, 3, 6)
    _FIXED_STATUS_FIELDS: Final[int] = 15
    _PROBLEM_MASK: Final[int] = 0x68CEFD

    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("voltage", 0, 1, False, lambda x: int(str(x)) / 100, 0),
        BMSDp(
            "cell_voltages",
            1,
            4,
            False,
            lambda values: [
                int(value) / 100 for value in cast(list[str], values)
            ],
            0,
        ),
        BMSDp(
            "temp_values",
            5,
            2,
            False,
            lambda values: [
                TempSensor(round((int(value) - 32) * 5 / 9, 3))
                for value in cast(list[str], values)
            ],
            0,
        ),
        BMSDp("current", 7, 1, False, lambda x: float(str(x)), 0),
        BMSDp("battery_level", 8, 1, False, lambda x: int(str(x)), 0),
        BMSDp(
            "problem_code",
            9,
            1,
            False,
            lambda x: int(str(x), 16) & BMS._PROBLEM_MASK,
            0,
        ),
        BMSDp("cycle_charge", 2, 1, False, lambda x: float(str(x)), 1),
        BMSDp("total_charge", 3, 1, False, lambda x: int(str(x)), 1),
    )
    _FIELDS_FIXED: Final[tuple[BMSDp, ...]] = (
        BMSDp("voltage", 2, 1, False, lambda x: int(str(x)) / 10, 0),
        BMSDp("battery_level", 3, 1, False, int, 0),
        BMSDp("cycle_charge", 1, 1, False, lambda x: int(str(x)) / 10, 0),
        BMSDp("current", 6, 1, False, lambda x: float(str(x)) / 10, 0),
        BMSDp("power", 7, 1, False, lambda x: float(str(x)), 0),
        BMSDp("battery_charging", 5, 1, False, lambda x: int(str(x)) == 1, 0),
        BMSDp(
            "temp_values",
            8,
            1,
            False,
            lambda x: [TempSensor(round((int(str(x)) - 32) * 5 / 9, 3))],
            0,
        ),
        BMSDp("temp_sensors", 8, 1, False, lambda x: 1, 0),
        BMSDp("problem_code", 9, 1, False, lambda x: int(str(x), 16) & BMS._PROBLEM_MASK, 0),
        BMSDp("delta_voltage", 13, 1, False, lambda x: 0.0, 1),
    )

    def __init__(
        self,
        ble_device: BLEDevice,
        config: BMSConfig | None = None,
        logger_name: str = "",
    ) -> None:
        """Initialize private BMS members."""
        super().__init__(ble_device, config, logger_name)
        self._stream_data: dict[str, list[str]] = {}

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
            line: str = self._frame[:idx].decode("ascii", errors="ignore").strip()
            del self._frame[: idx + 2]

            if not line:
                continue

            if line == "ERROR":
                self._log.debug("ignoring command response: %s", line)
                continue

            fields: list[str] = line.split(",")
            if (
                line.startswith(BMS._HEAD_STATUS)
                and len(fields) >= BMS._MIN_FIELDS_STATUS
            ):
                self._stream_data["status"] = fields
            elif line[0].isdigit() and len(fields) >= BMS._MIN_FIELDS_PRIMARY:
                self._stream_data["primary"] = fields

            if self._stream_data.keys() >= {"primary", "status"}:
                self._msg_event.set()

        if len(self._frame) > BMS.BLE_MAX_ATTR_SIZE:
            self._log.debug("invalid frame")
            self._frame.clear()

    @staticmethod
    def _is_fixed_length(fields: list[str]) -> bool:
        """Detect the zero-padded fixed-length stream variant."""
        return len(fields) == len(BMS._FIXED_WIDTHS) and all(
            len(field) == width
            for field, width in zip(fields, BMS._FIXED_WIDTHS, strict=True)
        )

    @staticmethod
    def _decode_data(
        fields: tuple[BMSDp, ...],
        data: bytes | dict[int, bytes],
        *,
        byteorder: Literal["little", "big"] = "big",
        start: int = 0,
    ) -> BMSSample:
        """Decode a CSV stream payload using the shared field definition format."""
        del byteorder
        result: BMSSample = {}
        for field in fields:
            msg: bytes | list[str]
            if isinstance(data, dict):
                if field.idx not in data:
                    continue
                msg = cast(bytes | list[str], data[field.idx])
            else:
                msg = data

            idx: int = start + field.pos
            if idx >= len(msg):
                continue

            value: Any
            if field.size == 1:
                value = msg[idx]
            else:
                end: int = idx + field.size
                if end > len(msg):
                    continue
                value = msg[idx:end]

            result[field.key] = field.fct(value)
        return result

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        self._stream_data.clear()
        self._msg_event.clear()
        await asyncio.wait_for(self._wait_event(), timeout=BMS.TIMEOUT)

        primary: Final[list[str]] = self._stream_data["primary"]
        status: Final[list[str]] = self._stream_data["status"]

        try:
            _msg: dict[int, bytes] = cast(dict[int, bytes], {0: primary, 1: status})
            if BMS._is_fixed_length(primary):
                # The trace line of this variant carries the cell voltage
                # extremes; shorter ones only repeat data already parsed.

                result = BMS._decode_data(BMS._FIELDS_FIXED, _msg)
                if len(status) >= BMS._FIXED_STATUS_FIELDS:
                    result["delta_voltage"] = round(
                        (int(status[13]) - int(status[12])) / 100,
                        3,
                    )
            else:
                result = BMS._decode_data(BMS._FIELDS, _msg)
        except (IndexError, ValueError) as exc:
            raise ValueError("BMS data incomplete.") from exc

        return result
