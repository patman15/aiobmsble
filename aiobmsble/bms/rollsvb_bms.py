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

    INFO: BMSInfo = {"manufacturer": "Rolls", "model": "VB-series", "model_id": "RD-RJ8S150A"}
    _DEV_ID: Final[int] = 0xD2
    _HEAD_LEN: Final[int] = 3  # device id, function code, byte count
    _CRC_POS: Final[int] = -2
    _REG_COUNT: Final[int] = 0x10  # request size
    _MAX_CELLS: Final[int] = 16
    _MAX_TEMPS: Final[int] = 6
    _BLOCKS: Final[tuple[int, ...]] = (0x0000, 0x0020, 0x0030)  # used as message index in _FIELDS
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("voltage", 0x08 * 2, 2, False, lambda x: x / 10, 0x20),
        BMSDp("current", 0x09 * 2, 2, False, lambda x: (30000 - x) / 10, 0x20),
        BMSDp("battery_level", 0x0A * 2, 2, False, lambda x: x / 10, 0x20),
        BMSDp("cycle_charge", 0x00 * 2, 2, False, lambda x: x / 10, 0x30),
        BMSDp("cycles", 0x03 * 2, 2, False, idx=0x30),
    )

    def __init__(
        self, ble_device: BLEDevice, config: BMSConfig | None = None, logger_name: str = ""
    ) -> None:
        """Initialize private BMS members."""
        super().__init__(ble_device, config, logger_name)
        self._msg: bytes = b""

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            {
                "local_name": "RD????????????",
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

    def _notification_handler(self, _sender: BleakGATTCharacteristic, data: bytearray) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        self._log.debug("RX BLE data: %s", data)

        if not data.startswith(bytes([BMS._DEV_ID, 0x03])) or len(data) < 3:
            self._log.debug("incorrect SOF")
            return

        if data[2] + 5 != len(data):
            self._log.debug("incorrect frame length: %i != %i", len(data), data[2] + 5)
            return

        if not self._check_integrity(
            data, crc_modbus, slice(None, BMS._CRC_POS), slice(BMS._CRC_POS, None), "little"
        ):
            return

        self._msg = bytes(data)
        self._msg_event.set()

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""

        msgs: dict[int, bytes] = {}
        for addr in BMS._BLOCKS:
            await self._await_msg(
                self._cmd_modbus(dev_id=BMS._DEV_ID, addr=addr, count=BMS._REG_COUNT)
            )
            msgs[addr] = self._msg

        result: BMSSample = BMS._decode_data(BMS._FIELDS, msgs, start=BMS._HEAD_LEN)
        result["cell_voltages"] = BMS._cell_voltages(
            msgs[0x00], cells=BMS._MAX_CELLS, start=BMS._HEAD_LEN
        )
        result["temp_values"] = BMS._temp_values(
            msgs[0x20], values=BMS._MAX_TEMPS, start=BMS._HEAD_LEN, offset=40
        )

        return result
