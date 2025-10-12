"""Module to support LiPower BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSDp, BMSInfo, BMSSample, BMSValue, MatcherPattern
from aiobmsble.basebms import BaseBMS, crc_modbus


class BMS(BaseBMS):
    """LiPower BMS implementation."""

    INFO: BMSInfo = {"default_manufacturer": "LiPower", "default_model": "battery"}
    _HEAD: Final[bytes] = b"\x22\x03"  # beginning of frame
    _MIN_LEN: Final[int] = 5  # minimal frame length, including SOF and checksum
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("voltage", 15, 2, False, lambda x: x / 10),
        BMSDp(
            "current", 12, 3, False, lambda x: (x & 0xFFFF) * -(1 ** (x >> 16)) / 100
        ),
        BMSDp("battery_level", 5, 2, False),
        BMSDp(
            "runtime",
            7,
            6,
            False,
            lambda x: (((x >> 32) * 3600 + ((x >> 16) & 0xFFFF) * 60) * (x & 0xFF)),
        ),
        BMSDp("cycle_charge", 3, 2, False),
        # BMSDp("power", 17, 2, False),
    )

    def __init__(self, ble_device: BLEDevice, keep_alive: bool = True) -> None:
        """Initialize BMS."""
        super().__init__(ble_device, keep_alive)

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [{"service_uuid": normalize_uuid_str("af30"), "connectable": True}]

    @staticmethod
    def uuid_services() -> list[str]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return [normalize_uuid_str("ffe0")]

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "ffe1"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        return "ffe1"

    @staticmethod
    def _calc_values() -> frozenset[BMSValue]:
        return frozenset(
            {"battery_charging", "cycle_capacity", "power"}
        )  # calculate further values from BMS provided set ones

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        self._log.debug("RX BLE data: %s", data)

        if not data.startswith(BMS._HEAD) or len(data) < BMS._MIN_LEN:
            self._log.debug("incorrect SOF")
            return

        if len(data) != data[2] + BMS._MIN_LEN:
            self._log.debug("incorrect frame length")
            return

        if (crc := crc_modbus(data[:-2])) != int.from_bytes(
            data[-2:], byteorder="little"
        ):
            self._log.debug(
                "invalid checksum 0x%X != 0x%X",
                int.from_bytes(data[-2:], byteorder="little"),
                crc,
            )
            return

        self._data = data.copy()
        self._data_event.set()

    @staticmethod
    def _cmd(addr: int, words: int) -> bytes:
        """Assemble a LiPower BMS command (MODBUS)."""
        frame: bytearray = (
            bytearray(BMS._HEAD)
            + b"\x04"
            + int.to_bytes(addr, 2, byteorder="big")
            + int.to_bytes(words, 1, byteorder="big")
        )

        frame.extend(int.to_bytes(crc_modbus(frame), 2, byteorder="little"))
        return bytes(frame)

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        self._log.debug("replace with command to UUID %s", BMS.uuid_tx())
        await self._await_reply(BMS._cmd(0, 8))  # b"\x22\x03\x04\x00\x00\x08\x42\x6f"

        return BMS._decode_data(BMS._FIELDS, self._data)
