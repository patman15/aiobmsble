"""Module to support SOK SK BMS over Modbus BLE."""

from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSConfig, BMSDp, BMSInfo, BMSSample, MatcherPattern, TempSensor
from aiobmsble.basebms import BaseBMS, b2str, crc_modbus


class BMS(BaseBMS):
    """SOK SK BMS implementation."""

    INFO: BMSInfo = {"manufacturer": "SOK", "model": "Modbus BMS"}
    _HEAD: Final[bytes] = b"\x01\x03\xf4"
    _FRAME_LEN: Final[int] = 249
    _MODEL_START: Final[int] = 187
    _MODEL_END: Final[int] = 207
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("voltage", 2, 2, False, lambda x: x / 100),
        BMSDp("battery_level", 4, 2, False),
        BMSDp("cycle_charge", 8, 2, False, lambda x: x / 100),
        BMSDp("design_capacity", 10, 2, False, lambda x: round(x / 100)),
        BMSDp("battery_health", 6, 2, False),
        BMSDp("cycles", 14, 2, False),
        BMSDp("chrg_mosfet", 24, 2, False, lambda x: bool(x & 0x02)),
        BMSDp("dischrg_mosfet", 24, 2, False, lambda x: bool(x & 0x04)),
        BMSDp("current", 0, 2, True, lambda x: x / 100),
        BMSDp("cell_count", 34, 2, False),
        BMSDp("temp_sensors", 40, 2, False),
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
            {"local_name": f"SK{voltage}V*", "connectable": True}
            for voltage in ("12", "24", "36")
        ]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return (normalize_uuid_str("fff0"),)

    @staticmethod
    def uuid_rx() -> str:
        """Return UUID of the characteristic that provides notifications."""
        return "fff1"

    @staticmethod
    def uuid_tx() -> str:
        """Return UUID of the characteristic used to send commands."""
        return "fff2"

    async def _fetch_device_info(self) -> BMSInfo:
        """Fetch model and serial number from the status registers."""
        info: BMSInfo = await super()._fetch_device_info()
        self._frame.clear()
        self._msg = b""
        await self._await_msg(BMS._cmd_modbus(dev_id=1, addr=0x80, count=0x7A))

        info.update(
            {
                "model": b2str(self._msg[BMS._MODEL_START:BMS._MODEL_END]),
                "serial_number": b2str(self._msg[BMS._MODEL_END:-2]),
            }
        )
        return info

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Assemble and validate a fragmented Modbus response."""
        self._log.debug("RX BLE data: %s", data)

        if not self._frame and not data.startswith(BMS._HEAD):
            self._log.debug("incorrect response header")
            return

        self._frame.extend(data)
        if len(self._frame) < BMS._FRAME_LEN:
            return

        if len(self._frame) != BMS._FRAME_LEN:
            self._log.debug("incorrect response length")
            self._frame.clear()
            return

        if not self._check_integrity(
            self._frame, crc_modbus, slice(None, -2), slice(-2, None), "little"
        ):
            self._frame.clear()
            return

        self._msg = bytes(self._frame)
        self._msg_event.set()

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        self._frame.clear()
        self._msg = b""
        await self._await_msg(BMS._cmd_modbus(dev_id=1, addr=0x80, count=0x7A))

        result: BMSSample = BMS._decode_data(BMS._FIELDS, self._msg, start=3)
        result["cell_voltages"] = BMS._cell_voltages(
            self._msg,
            cells=result.get("cell_count", 0),
            start=3 + 27 * 2,
        )
        result["temp_values"] = BMS._temp_values(
            self._msg,
            start=3 + 59 * 2,
            values=2,
            divider=10,
            types=(TempSensor.T.CELL, TempSensor.T.CELL),
        ) + BMS._temp_values(
            self._msg,
            start=3 + 23 * 2,
            values=2,
            divider=10,
            types=(TempSensor.T.MOSFET, TempSensor.T.AMBIENT),
        )
        return result
