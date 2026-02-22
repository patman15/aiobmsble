"""Module to support Lithionics BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

import asyncio
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS


class BMS(BaseBMS):
    """Lithionics BMS implementation (ASCII stream protocol)."""

    INFO: BMSInfo = {
        "default_manufacturer": "Lithionics",
        "default_model": "NeverDie smart BMS",
    }
    _HEAD_STATUS: Final[str] = "&,"
    _MIN_FIELDS_PRIMARY: Final[int] = 10
    _MIN_FIELDS_STATUS: Final[int] = 2

    def __init__(self, ble_device: BLEDevice, keep_alive: bool = True) -> None:
        """Initialize BMS."""
        super().__init__(ble_device, keep_alive)
        self._stream_data: dict[str, str] = {}

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            # Seen on Lithionics Li3 packs: "Li3-061322094"
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

        self._frame += data
        while (idx := self._frame.find(b"\r\n")) >= 0:
            line: str = self._frame[:idx].decode("ascii", errors="ignore").strip()
            self._frame = self._frame[idx + 2 :]

            if not line:
                continue

            if line == "ERROR":
                self._log.debug("ignoring command response: %s", line)
                continue

            if line.startswith(BMS._HEAD_STATUS):
                self._stream_data["status"] = line
                self._msg_event.set()
                continue

            if "," in line and line[0] in "0123456789-":
                if len(line.split(",")) >= BMS._MIN_FIELDS_PRIMARY:
                    self._stream_data["primary"] = line
                    self._msg_event.set()

    @staticmethod
    def _parse_primary(line: str) -> BMSSample:
        fields: list[str] = line.split(",")

        # Lithionics protocol reports temperatures in Fahrenheit.
        temp_values: list[float] = [
            round((int(fields[idx]) - 32) * 5 / 9, 3) for idx in (5, 6)
        ]

        result: BMSSample = {
            "voltage": int(fields[0]) / 100,
            "cell_voltages": [int(value) / 100 for value in fields[1:5]],
            "temp_values": temp_values,
            "temp_sensors": 2,
            "current": float(fields[7]),
            "battery_level": int(fields[8]),
            "problem_code": int(fields[9], 16),
        }
        return result

    @staticmethod
    def _parse_status(line: str) -> BMSSample:
        fields: list[str] = line.split(",")
        result: BMSSample = {}

        # The status stream includes Remaining AH and Total Consumed AH.
        # Expose them as common aiobmsble keys so HA can surface them.
        if len(fields) > 2:
            result["cycle_charge"] = float(fields[2])  # Remaining AH
        if len(fields) > 3:
            result["total_charge"] = int(fields[3])  # Total Consumed AH

        return result

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        while {"primary", "status"} - self._stream_data.keys():
            await asyncio.wait_for(self._wait_event(), timeout=BMS.TIMEOUT)

        result: BMSSample = BMS._parse_primary(
            self._stream_data["primary"]
        ) | BMS._parse_status(
            self._stream_data["status"]
        )
        self._stream_data.clear()
        return result
