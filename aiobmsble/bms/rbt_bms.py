"""Module to support Changfa / RBT BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from functools import lru_cache
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSConfig, BMSDp, BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS, crc_sum


class BMS(BaseBMS):
    """Changfa / RBT BMS implementation."""

    INFO: BMSInfo = {"manufacturer": "Huizhou Changfa Electronic Technology", "model": "RBT BMS"}
    _HEAD_RSP: Final[bytes] = b"\x3b\x9d"  # start of response frame
    _HEAD_CMD: Final[bytes] = b"\x3a\x9d"  # start of request frame
    _CMD_READ: Final[int] = 0x21  # read command
    _REG_TELEMETRY: Final[int] = 0x41  # register block with telemetry data
    _HDR_LEN: Final[int] = 6  # head (2), command (1), flag (1), register (1), length (1)
    _CSUM_OFFSET: Final[int] = 0x20  # offset added to the checksum sum
    _MAX_FRAME_LEN: Final[int] = (
        0x100  # bound for the frame buffer, larger than any telemetry frame
    )
    _TEMP_OFFSET: Final[int] = 2731  # temperatures are in 0.1 K
    _FIELDS: tuple[BMSDp, ...] = (
        BMSDp("battery_level", 1, 1, False),
        BMSDp("cycles", 4, 2, False),
        BMSDp("design_capacity", 6, 2, False, lambda x: x // 100),
        BMSDp("voltage", 12, 2, False, lambda x: x / 100),
        BMSDp(
            "current", 14, 2, False, lambda x: -x / 100
        ),  # assumed discharge sign, charging not verified
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
            MatcherPattern(
                local_name="CF_BMS_*",
                service_uuid=BMS.uuid_services()[0],
                connectable=True,
            )
        ]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return (normalize_uuid_str("00002734-08c2-11e1-9073-0e8ac72e1001"),)

    @staticmethod
    def uuid_rx() -> str:
        """Return 128-bit UUID of characteristic that provides notification/read property."""
        return "00002734-08c2-11e1-9073-0e8ac72e0002"

    @staticmethod
    def uuid_tx() -> str:
        """Return 128-bit UUID of characteristic that provides write property."""
        return "00002734-08c2-11e1-9073-0e8ac72e0001"

    @staticmethod
    @lru_cache(maxsize=4)
    def _cmd(register: int, length: int) -> bytes:
        """Assemble a read request frame for a register block."""
        frame: bytes = BMS._HEAD_CMD + bytes((BMS._CMD_READ, 0x01, register, length))
        return frame + bytes(((crc_sum(frame) + 0x20) & 0xFF,))

    def _notification_handler(self, _sender: BleakGATTCharacteristic, data: bytearray) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        self._log.debug("RX BLE data: %s", data)

        if data.startswith(BMS._HEAD_RSP):
            self._frame.clear()
        elif not self._frame.startswith(BMS._HEAD_RSP):
            return  # no frame in progress, discard fragment

        if len(self._frame) + len(data) > BMS._MAX_FRAME_LEN:
            self._log.debug("frame too long, discarding buffer")
            self._frame.clear()
            return

        self._frame.extend(data)

        if len(self._frame) < BMS._HDR_LEN:
            return

        frame_len: Final[int] = BMS._HDR_LEN + self._frame[5] + 1  # includes checksum
        if len(self._frame) < frame_len:
            return

        if len(self._frame) > frame_len or self._frame[4] != BMS._REG_TELEMETRY:
            self._log.debug("unexpected frame (length: %i)", len(self._frame))
            self._frame.clear()
            return

        if not self._check_integrity(
            self._frame,
            lambda d: (crc_sum(d) + BMS._CSUM_OFFSET) & 0xFF,
            slice(None, -1),
            slice(-1, None),
        ):
            self._frame.clear()
            return

        self._msg = bytes(self._frame)
        self._msg_event.set()

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        await self._await_msg(BMS._cmd(BMS._REG_TELEMETRY, 0x00))

        result: BMSSample = self._decode_data(
            BMS._FIELDS, self._msg, byteorder="little", start=BMS._HDR_LEN
        )
        result["temperature"] = BMS._temperature(
            self._msg,
            start=32 + BMS._HDR_LEN,
            values=4,
            byteorder="little",
            signed=False,
            offset=BMS._TEMP_OFFSET,
            divider=10,
        )
        result["cell_voltages"] = BMS._cell_voltages(
            self._msg, cells=4, start=48 + BMS._HDR_LEN, byteorder="little"
        )
        return result
