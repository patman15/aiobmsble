"""Module to support ECO-WORTHY (RB Controls) BMS.

Protocol reverse-engineered via Android HCI btsnoop log capture.
Manufacturer: RB Controls Co., Ltd. (company ID 0x0515)
Device advertises as: ECOE<last4ofMAC>, e.g. ECOE934

BLE characteristics (service 00000001):
  Write:  00000002-0000-1000-8000-00805f9b34fb  (handle 0x000c)
  Notify: 00000003-0000-1000-8000-00805f9b34fb  (handle 0x000e)

Command format: AA <cmd> 00 <cmd> 00
Response format: AA <cmd> <len> <data...>  (little-endian values)

Verified against: ECO-WORTHY 12V 150AH Bluetooth LiFePO4 (BMC1_E934)

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS, BMSValue


class BMS(BaseBMS):
    """ECO-WORTHY BMS implementation (RB Controls protocol)."""

    INFO: BMSInfo = {
        "default_manufacturer": "RB Controls Co., Ltd.",
        "default_model": "ECO-WORTHY LiFePO4",
    }

    # Protocol commands: AA <cmd> 00 <cmd> 00
    _CMD_INIT: Final[bytes] = bytes([0xAA, 0x00, 0x00, 0x00, 0x00])
    _CMD_BASIC: Final[bytes] = bytes([0xAA, 0x20, 0x00, 0x20, 0x00])  # current
    _CMD_PACK: Final[bytes] = bytes([0xAA, 0x21, 0x00, 0x21, 0x00])   # voltage/SOC/cap
    _CMD_CELLS: Final[bytes] = bytes([0xAA, 0x22, 0x00, 0x22, 0x00])  # cell voltages

    _SOF: Final[int] = 0xAA
    _MIN_LEN_BASIC: Final[int] = 10
    _MIN_LEN_PACK: Final[int] = 20
    _MIN_LEN_CELLS: Final[int] = 11

    def __init__(
        self,
        ble_device: BLEDevice,
        keep_alive: bool = True,
        secret: str = "",
        logger_name: str = "",
    ) -> None:
        """Initialize private BMS members."""
        super().__init__(ble_device, keep_alive, secret, logger_name)
        self._raw_pack: bytes = b""
        self._raw_basic: bytes = b""
        self._raw_cells: bytes = b""

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition.

        ECO-WORTHY batteries advertise as 'ECOE' followed by last 4 hex chars
        of the MAC address, e.g. ECOE934. Service UUID 0x0001 is always present.
        """
        return [
            {
                "local_name": "ECOE*",
                "service_uuid": normalize_uuid_str("0001"),
                "connectable": True,
            }
        ]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return (normalize_uuid_str("0001"),)

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification property."""
        return "0003"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        return "0002"

    @staticmethod
    def _raw_values() -> frozenset[BMSValue]:
        """Never calculate runtime — not enough data available."""
        return frozenset({"runtime"})

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle RX notify events — store responses keyed by command byte."""
        if len(data) < 3 or data[0] != BMS._SOF:
            self._log.debug("invalid SOF or too short: %s", data.hex())
            return

        cmd = data[1]
        self._log.debug("RX cmd=0x%02X len=%d: %s", cmd, len(data), data.hex())

        if cmd == 0x20 and len(data) >= BMS._MIN_LEN_BASIC:
            self._raw_basic = bytes(data)
        elif cmd == 0x21 and len(data) >= BMS._MIN_LEN_PACK:
            self._raw_pack = bytes(data)
        elif cmd == 0x22 and len(data) >= BMS._MIN_LEN_CELLS:
            self._raw_cells = bytes(data)

        if cmd in (0x20, 0x21, 0x22):
            self._msg = bytes(data)
            self._msg_event.set()

    @staticmethod
    def _parse_basic(data: bytes) -> BMSSample:
        """Parse 0x20 response — current in mA at d[3:5] LE signed."""
        raw_current = int.from_bytes(data[3:5], byteorder="little", signed=True)
        return {"current": raw_current / 1000.0}

    @staticmethod
    def _parse_pack(data: bytes) -> BMSSample:
        """Parse 0x21 response — voltage, SOC, capacity.

        Verified frame (20 bytes, MTU-limited to 20):
          AA 21 1A 00 37 00 .. 63 64 A8 46 02 00 F0 49 02
          d[3:5]   LE = voltage mV        (0x3700 = 14080 -> 14.080 V)
          d[11]    = SOC %                (99)
          d[13:17] 4-byte LE = remain Ah  (149160 mAh -> 149 Ah)
          d[17:20] 3-byte LE = full Ah    (150000 mAh -> 150 Ah, d[20]=0x00 cut by MTU)
        """
        voltage = int.from_bytes(data[3:5], byteorder="little") / 1000.0
        soc = int(data[11])
        remain_mah = int.from_bytes(data[13:17], byteorder="little")
        full_mah = int.from_bytes(data[17:20], byteorder="little")
        return {
            "voltage": voltage,
            "battery_level": soc,
            "battery_charging": False,
            "cycle_charge": round(remain_mah / 1000),
            "design_capacity": round(full_mah / 1000),
        }

    @staticmethod
    def _parse_cells(data: bytes) -> BMSSample:
        """Parse 0x22 response — little-endian 2-byte cell voltages at d[3+].

        Zero-terminated: first zero mv value marks end of cell list.
        """
        payload = data[3:]
        cells: list[float] = []
        for i in range(16):
            offset = i * 2
            if offset + 1 >= len(payload):
                break
            mv = int.from_bytes(payload[offset : offset + 2], byteorder="little")
            if mv == 0:
                break
            if 2000 <= mv <= 5000:
                cells.append(round(mv / 1000.0, 3))

        result: BMSSample = {}
        if cells:
            result["cell_voltages"] = cells
            result["delta_voltage"] = round(max(cells) - min(cells), 3)
        return result

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        self._raw_basic = b""
        self._raw_pack = b""
        self._raw_cells = b""

        await self._await_msg(BMS._CMD_INIT)
        await self._await_msg(BMS._CMD_BASIC)
        await self._await_msg(BMS._CMD_PACK)
        await self._await_msg(BMS._CMD_CELLS)

        data: BMSSample = {}

        if self._raw_basic:
            data.update(self._parse_basic(self._raw_basic))

        if self._raw_pack:
            data.update(self._parse_pack(self._raw_pack))
            if "current" in data:
                data["battery_charging"] = float(data["current"]) > 0

        if self._raw_cells:
            data.update(self._parse_cells(self._raw_cells))

        self._add_missing_values(data)
        return data