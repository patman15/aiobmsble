"""Module to support Sentorise BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice

from aiobmsble import BMSConfig, BMSDp, BMSInfo, BMSSample, MatcherPattern, TempSensor
from aiobmsble.basebms import BaseBMS, b2str, crc_modbus


class BMS(BaseBMS):
    """Sentorise BMS implementation."""

    INFO: BMSInfo = {"manufacturer": "Sentorise", "model": "smart battery"}
    _DEV_ID: Final[int] = 0x01
    _HEAD: Final[bytes] = b"\x01\x03"  # dev, read (0x03)
    _MIN_LEN: Final[int] = 5  # length of frame, including SOF and checksum
    _MAX_TEMP: Final[int] = 9  # maximum number of cell temperatures
    _MAX_CELLS: Final[int] = 32
    _CELL_NA: Final[int] = 0xEE49  # placeholder for unused cell slots
    _REG_INFO: Final[tuple[int, int]] = (0xC002, 0x30)  # serial, vendor, firmware
    _REG_CELLS: Final[tuple[int, int]] = (0xD000, 0x25)  # cell voltages
    _REG_STATUS: Final[tuple[int, int]] = (0xD025, 0x1A)  # voltage, temp, current, SoC, ...
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("voltage", 3, 2, False, lambda x: x / 100),
        BMSDp("current", 29, 2, True, lambda x: x / 10),
        BMSDp("battery_level", 33, 2, False),
        BMSDp("battery_health", 35, 2, False),
        BMSDp("cycle_charge", 37, 2, False, lambda x: x / 100),
        BMSDp("design_capacity", 41, 2, False, lambda x: x // 100),
        BMSDp("cycles", 43, 2, False),
    )

    def __init__(
        self,
        ble_device: BLEDevice,
        config: BMSConfig | None = None,
        logger_name: str = "",
    ) -> None:
        """Initialize private BMS members."""
        super().__init__(ble_device, config, logger_name)
        self._exp_len: int = 0
        self._msg: bytes = b""

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            {"local_name": "BT-*", "oui": "EC:F6:4C", "connectable": True},
        ]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return ("6e400001-b5a3-f393-e0a9-e50e24dcca9e",)

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        return "6e400002-b5a3-f393-e0a9-e50e24dcca9e"

    async def _fetch_device_info(self) -> BMSInfo:
        """Fetch the device information via BLE."""
        info: BMSInfo = await super()._fetch_device_info()
        await self._read_registers(*BMS._REG_INFO)
        return info | {
            "serial_number": b2str(self._msg[3:35]),
            "model": b2str(self._msg[35:67]),
            "sw_version": b2str(self._msg[67:99]),
        }

    def _notification_handler(self, _sender: BleakGATTCharacteristic, data: bytearray) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""

        if (
            len(data) > BMS._MIN_LEN
            and data.startswith(BMS._HEAD)
            and len(self._frame) >= self._exp_len
        ):
            self._exp_len = BMS._MIN_LEN + data[2]
            self._frame.clear()

        self._frame.extend(data)
        self._log.debug("RX BLE data (%s): %s", "start" if data == self._frame else "cnt.", data)

        if len(self._frame) < 3 or len(self._frame) < self._frame[2] + BMS._MIN_LEN:
            return

        if not self._check_integrity(
            self._frame,
            crc_modbus,
            slice(None, -2),
            slice(-2, None),
            "little",
        ):
            return

        self._msg = bytes(self._frame)
        self._msg_event.set()

    async def _read_registers(self, addr: int, count: int) -> None:
        """Request registers and verify the reply has the requested size."""
        await self._await_msg(BMS._cmd_modbus(dev_id=BMS._DEV_ID, addr=addr, count=count))
        if self._msg[2] != 2 * count:
            raise ValueError(f"unexpected reply length {self._msg[2]} for 0x{addr:04X}")

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        await self._read_registers(*BMS._REG_STATUS)
        result: BMSSample = BMS._decode_data(BMS._FIELDS, self._msg)
        result["temp_values"] = BMS._temp_values(
            self._msg,
            start=5,
            values=BMS._MAX_TEMP,
            offset=400,
            divider=10,
            types=(TempSensor.T.CELL,) * BMS._MAX_TEMP,
        ) + BMS._temp_values(self._msg, start=23, offset=400, divider=10)

        await self._read_registers(*BMS._REG_CELLS)
        result["cell_voltages"] = [
            voltage
            for voltage in BMS._cell_voltages(self._msg, cells=BMS._MAX_CELLS, start=3)
            if voltage != BMS._CELL_NA / 1000
        ]

        return result
