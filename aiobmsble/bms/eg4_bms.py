"""Module to support EG4 BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

import asyncio
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSDp, BMSInfo, BMSSample, BMSValue, MatcherPattern
from aiobmsble.basebms import BaseBMS, crc_modbus


class BMS(BaseBMS):
    """EG4 BMS implementation."""

    INFO: BMSInfo = {"default_manufacturer": "EG4 electronics", "default_model": "LL"}
    _HEAD: Final[bytes] = b"\x01\x03"  # header for responses
    _MIN_LEN: Final[int] = 5
    _MAX_CELLS: Final[int] = 16
    _INFO_LEN: Final[int] = 113
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("voltage", 3, 2, False, lambda x: x / 100),
        BMSDp("current", 5, 2, True, lambda x: x / 100),
        BMSDp("battery_level", 51, 2, False),
        BMSDp("cycle_charge", 45, 2, False, lambda x: x / 10),
        BMSDp("cycles", 61, 4, False, lambda x: x),
        BMSDp("cell_count", 75, 2, False),
        # BMSDp("design_capacity", 77, 2, False, lambda x: x / 10),
        BMSDp("temperature", 39, 2, True),
        BMSDp("problem_code", 55, 6, False, lambda x: x),
        # BMSDP("balance", 76, 2, False, lambda x: bool(x)),
    )

    def __init__(self, ble_device: BLEDevice, keep_alive: bool = True) -> None:
        """Initialize BMS."""
        super().__init__(ble_device, keep_alive)
        self._data_final: bytearray = bytearray()

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            {
                "service_uuid": BMS.uuid_services()[0],
                "connectable": True,
            }
        ]

    @staticmethod
    def uuid_services() -> list[str]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return [normalize_uuid_str("1000")]

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "1002"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        raise NotImplementedError

    @staticmethod
    def _calc_values() -> frozenset[BMSValue]:
        return frozenset(
            {"battery_charging", "cycle_capacity", "delta_voltage", "power", "runtime"}
        )

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""

        self._log.debug("RX BLE data: %s", data)

        if not data.startswith(BMS._HEAD) or len(data) < BMS._MIN_LEN:
            self._log.debug("invalid SOF")
            return

        if len(data) != data[2] + BMS._MIN_LEN:
            return

        if (crc := crc_modbus(data[:-2])) != int.from_bytes(
            data[-2:], byteorder="little"
        ):
            self._log.debug(
                "invalid checksum 0x%X != 0x%X",
                int.from_bytes(data[-2:], byteorder="little"),
                crc,
            )
            self._data.clear()
            return

        self._data = data.copy()
        self._data_event.set()

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""

        await asyncio.wait_for(self._wait_event(), timeout=BMS.TIMEOUT)
        result: BMSSample = BMS._decode_data(BMS._FIELDS, self._data)
        # result["temp_values"] = BMS._temp_values(self._data, values=2, start=69, size=1)
        result["cell_voltages"] = BMS._cell_voltages(
            self._data, cells=min(result.get("cell_count", 0), BMS._MAX_CELLS), start=7
        )
        return result
