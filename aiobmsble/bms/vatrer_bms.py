"""Module to support Vatrer BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice

from aiobmsble import BMSsample, BMSvalue, MatcherPattern
from aiobmsble.basebms import BaseBMS, BMSdp, crc_modbus


class BMS(BaseBMS):
    """Vatrer BMS implementation."""

    _HEAD: Final[bytes] = b"\x02\x03"  # beginning of frame
    _FIELDS: Final[tuple[BMSdp, ...]] = (
        BMSdp("voltage", 3, 2, False, lambda x: x / 100),
        # BMSdp("current", 82, 2, False, lambda x: (x - 30000) / 10),
        # BMSdp("battery_level", 84, 2, False, lambda x: x / 10),
        # BMSdp("cycle_charge", 96, 2, False, lambda x: x / 10),
        # BMSdp("cell_count", 98, 2, False, lambda x: min(x, BMS.MAX_CELLS)),
        # BMSdp("temp_sensors", 100, 2, False, lambda x: min(x, BMS.MAX_TEMP)),
        # BMSdp("cycles", 102, 2, False, lambda x: x),
        # BMSdp("delta_voltage", 112, 2, False, lambda x: x / 1000),
        # BMSdp("problem_code", 116, 8, False, lambda x: x % 2**64),
    )

    def __init__(self, ble_device: BLEDevice, keep_alive: bool = True) -> None:
        """Initialize BMS."""
        super().__init__(ble_device, keep_alive)

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            {  # name is likely YYMMDDVVVAAAAxx (date, V, Ah)
                "local_name": "[2-9]???[0-3]?512??00??",
                "service_uuid": BMS.uuid_services()[0],
                "connectable": True,
            }
        ]

    @staticmethod
    def device_info() -> dict[str, str]:
        """Return device information for the battery management system."""
        return {"manufacturer": "Vatrer", "model": "Smart BMS"}

    @staticmethod
    def uuid_services() -> list[str]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return ["6e400001-b5a3-f393-e0a9-e50e24dcca9e"]

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        return "6e400002-b5a3-f393-e0a9-e50e24dcca9e"

    @staticmethod
    def _calc_values() -> frozenset[BMSvalue]:
        return frozenset(
            {"power", "battery_charging"}
        )  # calculate further values from BMS provided set ones

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        self._log.debug("RX BLE data: %s", data)

        if not data.startswith(BMS._HEAD):
            self._log.debug("incorrect SOF")
            return

        if (crc := crc_modbus(data[:-2])) != int.from_bytes(data[-2:],byteorder="little"):
            self._log.debug("invalid checksum 0x%X != 0x%X", data[-2:], crc)
            return

        self._data = data.copy()
        self._data_event.set()

    @staticmethod
    def _cmd(addr: int, words: int) -> bytes:
        """Assemble a Vatrer BMS command."""
        frame = (
            bytearray(BMS._HEAD)
            + addr.to_bytes(2, byteorder="big")
            + words.to_bytes(2, byteorder="big")
        )
        frame.extend(crc_modbus(frame).to_bytes(2, "little"))
        return bytes(frame)

    async def _async_update(self) -> BMSsample:
        """Update battery status information."""
        await self._await_reply(BMS._cmd(0x0, 0x14))
        result = BMS._decode_data(BMS._FIELDS, self._data)

        return result
