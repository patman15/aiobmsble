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
    """Rolls VB-series LFP battery class implementation.

    The battery's internal BMS (marked RD-RJ8S150A on the PCB) exposes a
    generic serial-over-BLE bridge (service 0xFFF0) that carries plain
    MODBUS RTU frames, slave address 0xD2. The current field uses the same
    zero-offset encoding found in the Daly BMS protocol family
    (``value - 30000``, in 0.1 A steps), but with the opposite sign: a raw
    value below 30000 means the battery is charging here, whereas the Daly
    family uses the same offset for discharging. This was confirmed against
    the vendor's own "Rolls LFP Connect" app, which showed a positive
    (charging) current for a raw reading below 30000.
    """

    INFO: BMSInfo = {"manufacturer": "Rolls", "model": "VB-series LFP (RD-RJ8S150A)"}
    _DEV_ID: Final[int] = 0xD2
    _CELL_COUNT: Final[int] = 8  # VB24-150LFP is an 8S pack
    _CELL_REG_COUNT: Final[int] = 16  # register block is padded to 16 cells
    _CRC_POS: Final[int] = -2
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("voltage", 3, 2, False, lambda x: x / 10),
        BMSDp("current", 5, 2, False, lambda x: (30000 - x) / 10),
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
                "local_name": "RD?*",
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

        # cell voltages, register 0x0000, padded block of 16 registers (mV)
        await self._await_msg(
            self._cmd_modbus(
                dev_id=BMS._DEV_ID, addr=0x0000, count=BMS._CELL_REG_COUNT
            )
        )
        result: BMSSample = {
            "cell_voltages": BMS._cell_voltages(
                self._msg,
                cells=BMS._CELL_COUNT,
                start=3,
                byteorder="big",
                divider=1000,
            )
        }

        # pack voltage + current, register 0x0028, 2 registers
        await self._await_msg(self._cmd_modbus(dev_id=BMS._DEV_ID, addr=0x0028, count=2))
        result |= BMS._decode_data(BMS._FIELDS, self._msg)

        # state of charge, register 0x002a, 1 register (0.1 %)
        await self._await_msg(self._cmd_modbus(dev_id=BMS._DEV_ID, addr=0x002A, count=1))
        result["battery_level"] = (
            int.from_bytes(self._msg[3:5], byteorder="big") / 10
        )

        return result
