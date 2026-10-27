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
    _HEAD_LEN: Final[int] = 3  # device id, function code, byte count
    _CRC_POS: Final[int] = -2
    _BLOCK_REGS: Final[int] = 0x10  # registers per read request
    _MAX_CELLS: Final[int] = 16  # cell block is padded with zeros up to 16 cells
    _MAX_TEMPS: Final[int] = 5  # temperature block, unused sensors read as zero
    # start register of each block read, also used as message index in _FIELDS
    _BLOCKS: Final[tuple[int, ...]] = (0x0000, 0x0020, 0x0030)
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("voltage", 0x08 * 2, 2, False, lambda x: x / 10, 0x0020),  # 0x0028
        BMSDp("current", 0x09 * 2, 2, False, lambda x: (30000 - x) / 10, 0x0020),
        BMSDp("battery_level", 0x0A * 2, 2, False, lambda x: x / 10, 0x0020),
        BMSDp("cycle_charge", 0x00 * 2, 2, False, lambda x: x / 10, 0x0030),  # Ah
        BMSDp("cycles", 0x03 * 2, 2, False, idx=0x0030),  # 0x0033
    )

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

        msgs: dict[int, bytes] = {}
        for addr in BMS._BLOCKS:
            await self._await_msg(
                self._cmd_modbus(dev_id=BMS._DEV_ID, addr=addr, count=BMS._BLOCK_REGS)
            )
            msgs[addr] = self._msg

        result: BMSSample = BMS._decode_data(BMS._FIELDS, msgs, start=BMS._HEAD_LEN)
        # unused cells read as zero and are skipped by _cell_voltages
        result["cell_voltages"] = BMS._cell_voltages(
            msgs[0x0000], cells=BMS._MAX_CELLS, start=BMS._HEAD_LEN
        )
        # raw temperature value is degrees C + 40, zero means unused sensor
        result["temp_values"] = BMS._temp_values(
            msgs[0x0020], values=BMS._MAX_TEMPS, start=BMS._HEAD_LEN, offset=40
        )

        return result
