"""Module to support Allpowers portable power stations (PPS).

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/

Protocol (R1500 V2.0, little-endian multi-byte values):

Status notification (length > 14 bytes, prefix 0xA5):
  Byte  0: 0xA5  (SOF)
  Byte  1: 0x65
  Byte  2: 0xB1
  Bytes 3-6: unknown
  Byte  7: flags
            bit0 = DC on
            bit1 = AC on
            bit2 = AC frequency (0 = 50 Hz, 1 = 60 Hz)
            bit4 = Torch/light on
  Byte  8: battery level [%]
  Bytes 9-10: input power [W] (big-endian)
  Bytes 11-12: output power [W] (big-endian)
  Bytes 13-14: minutes remaining (big-endian); 0xFFFF = charging/idle

Settings notification (length ~10 bytes, prefix 0xA5 0x65 0xB1 0x00 0x01 0x06 0x03):
  Byte  7: X = (work_mode_bits | eco_flag)
            bits 1-2: work mode (0x00=Mute, 0x02=Standard, 0x04=Fast)
            bit  0:   eco mode enabled
  Byte  8: Y = eco shutdown timer in hours (1/2/4/6)
"""

import asyncio
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS


class BMS(BaseBMS):
    """Allpowers portable power station BMS class implementation."""

    INFO: BMSInfo = {
        "default_manufacturer": "Allpowers",
        "default_model": "portable power station",
    }

    # Service / characteristic UUIDs
    _SVC_UUID: Final[str] = normalize_uuid_str("fff0")
    _NOTIFY_UUID: Final[str] = "fff1"  # CHARACTERISTIC_NOTIFY
    _WRITE_UUID: Final[str] = "fff2"  # CHARACTERISTIC_WRITE

    # Frame identification
    _SOF: Final[int] = 0xA5
    _STATUS_MIN_LEN: Final[int] = 15  # minimum length for a status frame
    _SETTINGS_PREFIX: Final[bytes] = bytes.fromhex("a565b100010603")

    # Flag byte (index 7) bit masks
    _FLAG_DC: Final[int] = 0x01
    _FLAG_AC: Final[int] = 0x02
    _FLAG_FREQ: Final[int] = 0x04  # set = 60 Hz, clear = 50 Hz
    _FLAG_TORCH: Final[int] = 0x10

    # Sentinel value meaning "no discharge runtime available" (charging or idle)
    _RUNTIME_NONE: Final[int] = 0xFFFF

    def __init__(
        self,
        ble_device: BLEDevice,
        keep_alive: bool = True,
        secret: str = "",
        logger_name: str = "",
    ) -> None:
        """Initialize private BMS members."""
        super().__init__(ble_device, keep_alive, secret, logger_name)
        self._msg: bytes = b""

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            MatcherPattern(local_name="AP S*", connectable=True),
            MatcherPattern(local_name="VOLIX*", connectable=True),
        ]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return (BMS._SVC_UUID,)

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return BMS._NOTIFY_UUID

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        return BMS._WRITE_UUID

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        self._log.debug("RX BLE data: %s", data.hex())

        if not data or data[0] != BMS._SOF:
            self._log.debug("incorrect SOF, ignoring frame")
            return

        if len(data) < BMS._STATUS_MIN_LEN:
            # Short frame — settings notification; not surfaced as BMSSample keys.
            self._log.debug("short settings frame, length=%i", len(data))
            return

        # Status frame: capture and signal waiter.
        self._msg = bytes(data)
        self._msg_event.set()

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        # The Allpowers PPS pushes status frames autonomously once a BLE
        # connection with notifications enabled is established.  We simply
        # wait for the next inbound notification without sending a TX command.
        self._msg_event.clear()
        try:
            await asyncio.wait_for(self._wait_event(), timeout=self.TIMEOUT)
        except TimeoutError:
            self._log.debug("timed out waiting for status frame")
            raise

        data = self._msg
        if len(data) < BMS._STATUS_MIN_LEN:
            self._log.debug("status frame too short: %i bytes", len(data))
            return {}

        flags: int = data[7]
        battery_level: int = data[8]
        input_power: int = (data[9] << 8) | data[10]
        output_power: int = (data[11] << 8) | data[12]
        minutes_remaining: int = (data[13] << 8) | data[14]

        # Derive net current direction from power flows:
        #   charging  → current positive  (net power positive)
        #   idle      → current zero
        #   discharge → current negative  (net power negative)
        # BMSSample.power convention: positive = charging
        net_power: float = float(input_power - output_power)

        result: BMSSample = {
            "battery_level": battery_level,
            "power": net_power,
            # Expose AC/DC output state via BMS switch semantics:
            #   chrg_mosfet  ↔ AC output enabled
            #   dischrg_mosfet ↔ DC output enabled
            "chrg_mosfet": bool(flags & BMS._FLAG_AC),
            "dischrg_mosfet": bool(flags & BMS._FLAG_DC),
        }

        # Runtime is only meaningful while discharging
        if minutes_remaining != BMS._RUNTIME_NONE and net_power < 0:
            result["runtime"] = minutes_remaining * 60  # seconds

        return result
