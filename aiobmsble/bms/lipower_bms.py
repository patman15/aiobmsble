"""Module to support LiPower BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSDp, BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS, crc_modbus


class BMS(BaseBMS):
    """LiPower BMS implementation."""

    INFO: BMSInfo = {"default_manufacturer": "Ective", "default_model": "LiPower BMS"}
    _DEV_IDS: Final[tuple[bytes, ...]] = (b"\x22", b"\x0B", b"\x08")  # alternative device IDs
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
            4,
            False,
            lambda x: (x >> 16) * BMS._HRS_TO_SECS + (x & 0xFFFF) * 60,
        ),
        BMSDp("cycle_charge", 3, 2, False),
        # BMSDp("power", 17, 2, False),  # disabled, due to precision
    )

    def __init__(
        self,
        ble_device: BLEDevice,
        keep_alive: bool = True,
        secret: str = "",
        logger_name: str = "",
    ) -> None:
        """Initialize private BMS members."""
        super().__init__(ble_device, keep_alive, secret, logger_name)
        self._heads: tuple[bytes, ...] = BMS._DEV_IDS
        self._msg: bytes = b""

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [{"service_uuid": normalize_uuid_str("af30"), "connectable": True}]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return (normalize_uuid_str("ffe0"),)

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "ffe1"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        return "ffe1"

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        self._log.debug("RX BLE data: %s", data)

        if (not data.startswith(self._heads)) or len(data) < BMS._MIN_LEN:
            self._log.debug("incorrect SOF")
            return

        if len(data) != data[2] + BMS._MIN_LEN:
            self._log.debug("incorrect frame length")
            return

        if not self._check_integrity(
            data,
            crc_modbus,
            slice(None, -2),
            slice(-2, None),
            "little",
        ):
            return

        self._msg = bytes(data)
        self._msg_event.set()

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        for head in self._heads:
            try:
                await self._await_msg(
                    BMS._cmd_modbus(dev_id=int.from_bytes(head), addr=0x400, count=0x8)
                )
                if len(self._heads) > 1:
                    self._log.debug("detected frame head: %s", head.hex())
                    self._heads = (head,)  # set to single head for further commands
                break
            except TimeoutError:
                ...  # try next frame head
        else:
            raise TimeoutError

        return BMS._decode_data(BMS._FIELDS, self._msg)
