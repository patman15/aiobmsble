"""Module to support Lithionics BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

import asyncio
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSConfig, BMSInfo, BMSSample, MatcherPattern, TempSensor
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
    def _parse_primary_fixed(fields: list[str]) -> BMSSample:
        """Parse a fixed-length primary line."""
        charging: Final[bool] = int(fields[5]) == 1
        sign: Final[int] = 1 if charging else -1

        return {
            "voltage": int(fields[2]) / 10,
            "battery_level": int(fields[3]),
            "cycle_charge": int(fields[1]) / 10,
            "current": sign * int(fields[6]) / 10,
            "power": float(sign * int(fields[7])),
            "battery_charging": charging,
            "temp_values": [TempSensor(round((int(fields[8]) - 32) * 5 / 9, 3))],
            "temp_sensors": 1,
            "problem_code": int(fields[9], 16) & BMS._PROBLEM_MASK,
        }

    @staticmethod
    def _parse_status_fixed(fields: list[str]) -> BMSSample:
        """Parse a fixed-length trace line; it ends with lowest/highest/avg cell."""
        return {"delta_voltage": round((int(fields[13]) - int(fields[12])) / 100, 3)}

    @staticmethod
    def _parse_primary(fields: list[str]) -> BMSSample:
        # BMS reports temperatures in Fahrenheit.
        temp_values: Final[list[TempSensor]] = [
            TempSensor(round((int(fields[idx]) - 32) * 5 / 9, 3)) for idx in (5, 6)
        ]

        return {
            "voltage": int(fields[0]) / 100,
            "cell_voltages": [int(value) / 100 for value in fields[1:5]],
            "temp_values": temp_values,
            "temp_sensors": 2,
            "current": float(fields[7]),
            "battery_level": int(fields[8]),
            "problem_code": int(fields[9], 16),
        }

    @staticmethod
    def _parse_status(fields: list[str]) -> BMSSample:

        result: BMSSample = {"cycle_charge": float(fields[2])}
        if len(fields) > 3:
            result["total_charge"] = int(fields[3])

        return result

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        self._stream_data.clear()
        self._msg_event.clear()
        await asyncio.wait_for(self._wait_event(), timeout=BMS.TIMEOUT)

        primary: Final[list[str]] = self._stream_data["primary"]
        status: Final[list[str]] = self._stream_data["status"]

        try:
            if BMS._is_fixed_length(primary):
                # The trace line of this variant carries the cell voltage
                # extremes; shorter ones only repeat data already parsed.
                result: BMSSample = BMS._parse_primary_fixed(primary) | (
                    BMS._parse_status_fixed(status)
                    if len(status) >= BMS._FIXED_STATUS_FIELDS
                    else {}
                )
            else:
                result = BMS._parse_primary(primary) | BMS._parse_status(status)
        except (IndexError, ValueError) as exc:
            raise ValueError("BMS data incomplete.") from exc

        return result
