"""Module to support Lithionics (Li3) BLE BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from __future__ import annotations

from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS


class BMS(BaseBMS):
    """Lithionics Li3 BLE UART BMS class implementation.

    Protocol summary (based on captures):
    - BLE UART service FFE0 with characteristic FFE1 (notify + write)
    - Write b"\\r\\n" to request data
    - Notifications deliver CRLF-terminated ASCII CSV frames, sometimes split across multiple BLE packets.
    - Type A example:
        1362,340,341,341,340,37,41,0,99,000000
      Mappings (v1):
        - voltage: 13.62 V (centivolts)
        - cell_voltages: 3.40..3.41 V (centivolts), 4 cells observed
        - temps: two integer values (units assumed °C but not guaranteed)
        - current: integer (scaling TBD)
        - battery_level: SOC percent
        - flags_raw: last field (string)
    - Type B example starts with '&' and is stored as raw status line.
    """

    INFO: BMSInfo = {
        "default_manufacturer": "Lithionics",
        "default_model": "Li3 BLE BMS",
    }

    # BLE UART UUIDs (16-bit)
    _SVC: Final[str] = "ffe0"
    _CHAR: Final[str] = "ffe1"

    def __init__(self, ble_device: BLEDevice, keep_alive: bool = True) -> None:
        """Initialize private BMS members."""
        super().__init__(ble_device, keep_alive)
        self._rx: bytearray = bytearray()
        self._last_sample: BMSSample = {}
        self._last_status_line: str | None = None

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition.

        IMPORTANT: FFE0/FFE1 is generic BLE UART, so we key on Li3-* name
        to avoid mis-detecting unrelated UART devices.
        """
        return [
            MatcherPattern(
                local_name="Li3-*",
                service_uuid=BMS.uuid_services()[0],
                connectable=True,
            )
        ]

    @staticmethod
    def uuid_services() -> list[str]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return [normalize_uuid_str(BMS._SVC)]

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return BMS._CHAR

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        # Lithionics uses the same characteristic for notify + write.
        return BMS._CHAR

    async def _fetch_device_info(self) -> BMSInfo:
        """Fetch device information (best effort).

        Li3 protocol doesn't provide a known 'device info' frame yet; return defaults.
        """
        return dict(BMS.INFO)

    def _feed_notify(self, data: bytes) -> list[str]:
        """Return any complete CRLF-terminated ASCII lines (reassembles packet splits)."""
        self._rx += data
        lines: list[str] = []
        while True:
            idx = self._rx.find(b"\r\n")
            if idx < 0:
                break
            raw = bytes(self._rx[:idx])
            del self._rx[: idx + 2]
            if not raw:
                continue
            try:
                lines.append(raw.decode("ascii", errors="strict"))
            except UnicodeDecodeError:
                continue
        return lines

    def _parse_line(self, line: str) -> None:
        """Parse one complete Li3 CSV line and update _last_sample where applicable."""
        line = line.strip()
        if not line or line == "ERROR":
            return

        # Status / metadata frame
        if line.startswith("&"):
            self._last_status_line = line
            return

        parts = line.split(",")
        if len(parts) < 9:
            return

        # Example:
        # 1362,340,341,341,340,37,41,0,99,000000
        sample: BMSSample = {}

        try:
            pack_cv = int(parts[0])
            sample["voltage"] = pack_cv / 100.0

            cell_cvs = [int(x) for x in parts[1:5]]
            sample["cell_voltages"] = [cv / 100.0 for cv in cell_cvs]
            sample["cell_count"] = len(cell_cvs)

            # temps (units not formally confirmed; keep as raw integers)
            sample["temp_values"] = [int(parts[5]), int(parts[6])]

            # current scaling unknown; keep integer for now
            sample["current"] = int(parts[7])

            # SOC confirmed against app
            sample["battery_level"] = int(parts[8])

            if len(parts) > 9:
                sample["flags_raw"] = parts[9]

            if self._last_status_line:
                sample["status_raw"] = self._last_status_line

        except (ValueError, IndexError):
            return

        self._last_sample = sample

        # Unblock BaseBMS._await_reply(); content is irrelevant for this protocol.
        self._data = bytearray(b"\x01")
        self._data_event.set()

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle incoming BLE notifications."""
        self._log.debug("RX BLE data: %s", data)
        for line in self._feed_notify(bytes(data)):
            self._log.debug("RX Li3 line: %s", line)
            self._parse_line(line)

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        # Send poll and wait for one parsed sample via notifications.
        await self._await_reply(b"\r\n")
        return self._last_sample
