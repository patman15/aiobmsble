"""Module to support Rolls VB-series LFP BMS (RD-RJ8S150A).

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSConfig, BMSDp, BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS, crc_modbus


class BMS(BaseBMS):
    """Rolls VB-series LFP battery class implementation."""

    INFO: BMSInfo = {"manufacturer": "Rolls", "model": "VB-series LFP (RD-RJ8S150A)"}
    _DEV_ID: Final[int] = 0xD2
    _MAX_CELLS: Final[int] = 16  # cell block is padded with zeros up to 16 cells
    _MAX_TEMPS: Final[int] = 5  # temperature block, unused sensors read as zero
    _CRC_POS: Final[int] = -2
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("voltage", 3, 2, False, lambda x: x / 10),
        BMSDp("current", 5, 2, False, lambda x: (30000 - x) / 10),
    )
    # register 0x0031: cell count, temperature sensor count, cycle count
    _FIELDS_COUNTS: Final[tuple[BMSDp, ...]] = (BMSDp("cycles", 7, 2, False),)

    def __init__(
        self,
        ble_device: BLEDevice,
        config: BMSConfig | None = None,
        logger_name: str = "",
    ) -> None:
        """Initialize private BMS members."""
        super().__init__(ble_device, config, logger_name)
        self._msg: bytes = b""

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            {
                "local_name": "RD????????????",  # "RD" + MAC without colons
                "service_data_uuid": normalize_uuid_str("ffe1"),
                "connectable": True,
            }
        ]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return (normalize_uuid_str("fff0"),)

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "fff1"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        return "fff2"

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        self._log.debug("RX BLE data: %s", data)

        if not data.startswith(bytes([BMS._DEV_ID, 0x03])) or len(data) < 3:
            self._log.debug("incorrect SOF")
            return

        if data[2] + 5 != len(data):
            self._log.debug("incorrect frame length: %i != %i", len(data), data[2] + 5)
            return

        if not self._check_integrity(
            data,
            crc_modbus,
            slice(None, BMS._CRC_POS),
            slice(BMS._CRC_POS, None),
            "little",
        ):
            return

        self._msg = bytes(data)
        self._msg_event.set()

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""

        # cell voltages, register 0x0000, block of 16 registers (mV), unused cells
        # read as zero and are skipped by _cell_voltages
        await self._await_msg(
            self._cmd_modbus(dev_id=BMS._DEV_ID, addr=0x0000, count=BMS._MAX_CELLS)
        )
        result: BMSSample = {
            "cell_voltages": BMS._cell_voltages(
                self._msg, cells=BMS._MAX_CELLS, start=3
            )
        }

        # temperatures, register 0x0020, raw value is degrees C + 40, zero means unused
        await self._await_msg(
            self._cmd_modbus(dev_id=BMS._DEV_ID, addr=0x0020, count=BMS._MAX_TEMPS)
        )
        result["temp_values"] = BMS._temp_values(
            self._msg, values=BMS._MAX_TEMPS, start=3, offset=40
        )

        # cell count, temperature sensor count and cycles, register 0x0031
        await self._await_msg(self._cmd_modbus(dev_id=BMS._DEV_ID, addr=0x0031, count=3))
        result |= BMS._decode_data(BMS._FIELDS_COUNTS, self._msg)

        # pack voltage + current, register 0x0028, 2 registers
        await self._await_msg(self._cmd_modbus(dev_id=BMS._DEV_ID, addr=0x0028, count=2))
        result |= BMS._decode_data(BMS._FIELDS, self._msg)

        # state of charge, register 0x002a, 1 register (0.1 %)
        await self._await_msg(self._cmd_modbus(dev_id=BMS._DEV_ID, addr=0x002A, count=1))
        result["battery_level"] = (
            int.from_bytes(self._msg[3:5], byteorder="big") / 10
        )

        return result
