"""Plugin to support ATORCH CW20 DC Meter (Smart Shunt)."""

import logging
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble.basebms import BaseBMS, BMSdp, BMSsample, BMSvalue, MatcherPattern

_LOGGER = logging.getLogger(__name__)


class BMS(BaseBMS):
    """ATORCH CW20 Smart Shunt implementation."""

    INFO_LEN: Final[int] = 36  # typical CW20 frame size

    # Data fields mapping: byte positions → decoded values
    _FIELDS: Final[tuple[BMSdp, ...]] = (
        BMSdp("voltage", 4, 3, False, lambda x: x / 10.0),       # 0.1 V
        BMSdp("current", 7, 3, True, lambda x: x / 1000.0),      # 0.001 A
        BMSdp("capacity", 10, 3, False, lambda x: x / 1000.0),   # 0.001 Ah
        BMSdp("energy", 13, 4, False, lambda x: x / 100.0),      # 0.01 kWh
        BMSdp("temperature", 24, 2, False, lambda x: x),         # °C
    )

    def __init__(self, ble_device: BLEDevice, keep_alive: bool = True) -> None:
        """Initialize CW20 members."""
        # Important: do not create BleakClient if details=None
        self._data_final: bytearray = bytearray()
        super().__init__(ble_device, keep_alive)

    # --------------------
    # Device identification
    # --------------------
    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition for CW20.

        Some firmwares advertise as `CW20_BLE`, others as `ATORCH-CW20`.
        Some devices expose service UUID `FFE0`, others `FFF0`.
        """
        return [
            # Variant 1: CW20_BLE with FFE0
            MatcherPattern(
                local_name="CW20_BLE",
                service_uuid=normalize_uuid_str("ffe0"),
                connectable=True,
            ),
            # Variant 2: ATORCH-CW20 with FFE0
            MatcherPattern(
                local_name="ATORCH-CW20",
                service_uuid=normalize_uuid_str("ffe0"),
                connectable=True,
            ),
            # Variant 3: CW20_BLE with FFF0
            MatcherPattern(
                local_name="CW20_BLE",
                service_uuid=normalize_uuid_str("fff0"),
                connectable=True,
            ),
            # Variant 4: ATORCH-CW20 with FFF0
            MatcherPattern(
                local_name="ATORCH-CW20",
                service_uuid=normalize_uuid_str("fff0"),
                connectable=True,
            ),
        ]

    @staticmethod
    def device_info() -> dict[str, str]:
        """Return device information for the shunt."""
        return {"manufacturer": "ATORCH", "model": "CW20 DC Meter"}

    @staticmethod
    def uuid_services() -> list[str]:
        """Return list of 128-bit UUIDs of services required by CW20."""
        return [normalize_uuid_str("ffe0"), normalize_uuid_str("fff0")]

    @staticmethod
    def uuid_rx() -> str:
        """UUID of characteristic that provides notifications."""
        return normalize_uuid_str("ffe1")

    @staticmethod
    def uuid_tx() -> str:
        """UUID of characteristic that allows writes (not needed here)."""
        return ""

    @staticmethod
    def _calc_values() -> frozenset[BMSvalue]:
        """Extra calculated values for CW20."""
        return frozenset({"power"})

    # --------------------
    # Data handling
    # --------------------
    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle incoming BLE notifications from CW20."""
        if not data.startswith(b"\xFF\x55"):
            return

        if len(data) >= BMS.INFO_LEN:
            self._data_final = data
            _LOGGER.debug("CW20 RX frame: %s", data.hex())
        else:
            _LOGGER.debug("CW20 RX frame too short: %s", data.hex())

    async def _async_update(self) -> BMSsample:
        """Update shunt status information."""
        data: BMSsample = {}

        if not self._data_final:
            return data

        # Decode basic fields
        data = BMS._decode_data(BMS._FIELDS, self._data_final)

        # Add calculated power (V * A)
        if "voltage" in data and "current" in data:
            data["power"] = round(data["voltage"] * data["current"], 2)

        return data
