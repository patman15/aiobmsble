"""Module to support Pylontech RT-series BMS (RT12100, RT12200, RT24100, ...).

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSDp, BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS, b2str, crc_modbus


class BMS(BaseBMS):
    """Pylontech RT series BMS implementation."""

    INFO: BMSInfo = {"default_manufacturer": "Pylontech", "default_model": "RT series"}
    _DEV_ID: Final[int] = 1
    _REG_SN: Final[tuple[int, int]] = (0x2000, 8)
    # Contiguous block 0x1016-0x1022 = 13 registers
    _INFO_BLOCK: Final[tuple[int, int]] = (0x1016, 13)

    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("voltage", 0, 2, False, lambda x: x / 100),
        BMSDp("current", 2, 2, True, lambda x: x / 10),
        BMSDp("battery_level", 12, 2, False),
        BMSDp("battery_health", 14, 2, False),
        BMSDp("power", 16, 2, False, float),
        BMSDp("design_capacity", 24, 2, False, lambda x: x // 10),
    )

    def __init__(
        self,
        ble_device: BLEDevice,
        keep_alive: bool = True,
        secret: str = "",
        logger_name: str = "",
    ) -> None:
        """Initialize BMS members."""
        super().__init__(ble_device, keep_alive, secret, logger_name)
        self._msg: bytes = b""
        self._exp_len: int = 0

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Return Bluetooth advertisement matchers."""
        return [
            {
                "local_name": "RT[1-4][2,4,6,8]*",
                "service_uuid": normalize_uuid_str("180f"),
                "connectable": True,
            }
        ]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return required BLE service UUIDs."""
        return ("00010203-0405-0607-0809-0a0b0c0d1910",)

    @staticmethod
    def uuid_rx() -> str:
        """Return UUID of the notify characteristic (Module -> Phone)."""
        return "00010203-0405-0607-0809-0a0b0c0d2b10"

    @staticmethod
    def uuid_tx() -> str:
        """Return UUID of the write characteristic (Phone -> Module)."""
        return "00010203-0405-0607-0809-0a0b0c0d2b11"

    def _notification_handler(
        self,
        _sender: BleakGATTCharacteristic,
        data: bytearray,
    ) -> None:
        """Accumulate BLE fragments; signal when a complete and valid Modbus frame arrives."""
        self._frame.extend(data)
        self._log.debug(
            "RX BLE data (%s): %s", "start" if data == self._frame else "cnt.", data
        )

        if len(self._frame) >= 5 and self._frame.startswith(b"\x01\x03"):
            self._exp_len = 3 + self._frame[2] + 2
        else:
            self._log.debug("unexpected SOF")
            self._frame.clear()
            return

        if not self._exp_len or len(self._frame) < self._exp_len:
            return

        frame = bytes(self._frame[:self._exp_len])
        self._frame.clear()
        self._exp_len = 0

        if not self._check_integrity(
            frame, crc_modbus, slice(None, -2), slice(-2, None), "little"
        ):
            return

        self._msg = frame
        self._msg_event.set()

    async def _fetch_device_info(self) -> BMSInfo:
        """Read standard BT device info plus serial number from Modbus registers."""
        info: BMSInfo = await super()._fetch_device_info()

        try:
            await self._await_msg(
                BMS._cmd_modbus(
                    dev_id=BMS._DEV_ID, addr=BMS._REG_SN[0], count=BMS._REG_SN[1]
                )
            )
            if sn := b2str(self._msg[3 : 3 + BMS._REG_SN[1] * 2]):
                info["serial_number"] = sn
        except TimeoutError:
            pass

        return info

    async def _async_update(self) -> BMSSample:
        """Read current BMS state and return a BMSSample."""
        await self._await_msg(
            BMS._cmd_modbus(
                dev_id=BMS._DEV_ID, addr=BMS._INFO_BLOCK[0], count=BMS._INFO_BLOCK[1]
            )
        )

        result: BMSSample = BMS._decode_data(BMS._FIELDS, self._msg, start=3)
        # Modbus exposes only min/max cell aggregates (0x1018, 0x1019), not per-cell values.
        result["cell_voltages"] = BMS._cell_voltages(self._msg, cells=2, start=7)
        result["temp_values"] = BMS._temp_values(
            self._msg, values=2, start=11, divider=10
        )

        return result
