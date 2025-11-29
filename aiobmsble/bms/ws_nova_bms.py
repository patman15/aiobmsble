"""Module to support Dummy BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

import asyncio
from string import hexdigits
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSDp, BMSInfo, BMSSample, BMSValue, MatcherPattern
from aiobmsble.basebms import BaseBMS, barr2str, crc_sum


class BMS(BaseBMS):
    """Dummy BMS implementation."""

    INFO: BMSInfo = {
        "default_manufacturer": "Wattstunde",
        "default_model": "Nova Core",
    }
    _HEAD: Final[bytes] = b"\x3a"  # beginning of frame
    _TAIL: Final[bytes] = b"\x7e"  # end of frame
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp(
            "current",
            2,
            4,
            False,
            lambda x: (x & 0x7FFF) / 1000 * (-1 if x >> 15 else 1),
        ),
        BMSDp("voltage", 10, 2, False, lambda x: x / 1000),
        BMSDp("cycles", 15, 2, False),
        BMSDp("battery_level", 17, 1, False),
        BMSDp("design_capacity", 18, 4, False, lambda x: x // 1000),
        BMSDp("cycle_charge", 22, 4, False, lambda x: x / 1000),
        BMSDp("sw_heater", 107, 4, False, lambda x: bool(x)),
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
                "manufacturer_id": 28256,
                "manufacturer_data_start": [0x41],
                "connectable": True,
            }
        ]

    @staticmethod
    def uuid_services() -> list[str]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return [normalize_uuid_str("FFF0")]

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "FFF6"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        raise NotImplementedError

    async def _fetch_device_info(self) -> BMSInfo:
        """Fetch the device information via BLE."""
        await asyncio.wait_for(self._wait_event(), timeout=BMS.TIMEOUT)
        return BMSInfo(serial_number=barr2str(self._data_final[91:107]))

    @staticmethod
    def _calc_values() -> frozenset[BMSValue]:
        return frozenset(
            {"power", "delta_voltage", "temperature", "runtime", "battery_charging"}
        )

    async def _init_connection(
        self, char_notify: BleakGATTCharacteristic | int | str | None = None
    ) -> None:
        for uuid_str in ("fff1", "fff3", "fff4"):
            self._log.debug("start notify on RX characteristic %s", uuid_str)
            await self._client.start_notify(uuid_str, getattr(self, "_backup_handler"))
        await super()._init_connection(char_notify)

    def _backup_handler(self, sender: BleakGATTCharacteristic, data: bytearray) -> None:
        self._log.debug("notification from %s: %s", sender, data)

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        self._log.debug("RX BLE data: %s", data)

        if not data.startswith(BMS._HEAD):
            self._log.debug("incorrect SOF")
            return

        if not data.endswith(BMS._TAIL):
            self._log.debug("incorrect EOF")
            return

        if len(data) % 2:
            self._log.debug("incorrect frame length (%i)", len(data))
            return

        if not all(chr(c) in hexdigits for c in self._data[1:-1]):
            self._log.debug("incorrect frame encoding.")
            self._data.clear()
            return

        data = bytearray(b ^ 0x20 for b in bytes.fromhex(data[1:-1].decode("ascii")))

        # if (crc := crc_sum(data[:-1])) != data[-1]:
        #     self._log.debug("invalid checksum 0x%X != 0x%X", data[-1], crc)
        #     return

        self._data_final = data.copy()
        self._data_event.set()

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        await asyncio.wait_for(self._wait_event(), timeout=BMS.TIMEOUT)

        result: BMSSample = BMS._decode_data(BMS._FIELDS, self._data_final, offset=52)
        result["cell_voltages"] = BMS._cell_voltages(
            self._data_final, cells=16, start=12
        )
        result["temp_values"] = BMS._temp_values(
            self._data_final, values=4, start=48, size=1, signed=False, offset=40
        )
        return result
