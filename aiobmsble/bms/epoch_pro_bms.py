"""Module to support Epoch Pro BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSConfig, BMSDp, BMSInfo, BMSPDp, BMSSample, MatcherPattern, PackSample
from aiobmsble.basebms import BaseBMS, crc_modbus


class BMS(BaseBMS):
    """Epoch Pro BMS implementation."""

    INFO: BMSInfo = {"manufacturer": "Epoch", "model": "Pro"}
    _HEAD: Final[bytes] = b"\xfa"
    _CMDS: Final[set[int]] = {0xF3}
    _VER: Final[bytes] = b"\x16"  # version 1.6?
    _CELLNUM_POS: Final[int] = 55  # number of cells in pack
    _CELL_POS: Final[int] = 77  # position of first cell voltage in pack
    _TEMPNUM_POS: Final[int] = 56  # number of temperature sensors in pack
    _TEMP_POS: Final[int] = 109  # position of first temperature sensor in pack
    _HEAD_LEN: Final[int] = 5
    _MIN_LEN: Final[int] = 7  # HEAD, CMD, VER, DEV, LEN, CRC (2 bytes)

    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("battery_level", 8, 2, False),
        BMSDp("battery_health", 10, 2, False),
        BMSDp("voltage", 14, 2, False, lambda x: x / 100),
        BMSDp("current", 16, 2, True),
        BMSDp("temperature", 18, 2, True, lambda x: x / 10),
        BMSDp("pack_count", 42, 2, False),
        # BMSdp("cycle_charge", 8, 4, False),
        # BMSdp("cycles", 46, 2, False),
        # BMSdp("design_capacity", 4, 4, False),
        # BMSDp("problem_code", 100, 8, False), # not verified
    )

    _PFIELDS: Final[tuple[BMSPDp, ...]] = (
        BMSPDp("cycles", 16, 2, False, lambda x: x),
        BMSPDp("voltage", 46, 2, False, lambda x: x / 100),
        BMSPDp("current", 48, 2, True, lambda x: x / 100),
        BMSPDp("battery_level", 66, 2, False, lambda x: x / 10),
    )

    def __init__(
        self, ble_device: BLEDevice, config: BMSConfig | None = None, logger_name: str = ""
    ) -> None:
        """Initialize private BMS members."""
        super().__init__(ble_device, config, logger_name)
        self._pkglen: int = 0
        self._msg: dict[int, bytes] = {}

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            {
                "service_uuid": BMS.uuid_services()[0],
                "service_data_uuid": normalize_uuid_str("3333"),
                "connectable": True,
            }
        ]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return (normalize_uuid_str("ffe0"),)

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "ffe4"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        return "ffe1"

    def _notification_handler(self, _sender: BleakGATTCharacteristic, data: bytearray) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""

        # Check for a valid new packet header
        if (
            len(data) >= BMS._MIN_LEN
            and data[0:1] == BMS._HEAD
            and data[1] in BMS._CMDS
            and data[2:3] == BMS._VER
        ):
            self._frame.clear()
            self._pkglen = data[4] + BMS._MIN_LEN

        self._frame.extend(data)
        self._log.debug("RX BLE data (%s): %s", "start" if data == self._frame else "cnt.", data)

        # verify that data is long enough
        if self._pkglen and len(self._frame) < self._pkglen:
            return

        if (crc := crc_modbus(self._frame[: self._pkglen - 2])) != int.from_bytes(
            self._frame[self._pkglen - 2 : self._pkglen], "little"
        ):
            self._log.debug(
                "invalid checksum 0x%X != 0x%X",
                int.from_bytes(self._frame[self._pkglen - 2 : self._pkglen], "little"),
                crc,
            )
            self._frame.clear()
            return

        if len(self._frame) != self._pkglen:
            self._log.debug(
                "wrong data length (%i!=%s): %s",
                len(self._frame),
                self._pkglen,
                self._frame,
            )

        self._msg[int(self._frame[3]) << 8 | int(self._frame[4])] = bytes(self._frame)
        self._msg_event.set()

    @staticmethod
    def _cmd(device: int, cmd: int, start: int, count: int) -> bytes:
        """Assemble a Seplos BMS command."""
        assert start >= 0 and count > 0 and start + count <= 0xFFFF
        frame: bytearray = (
            bytearray(BMS._HEAD)
            + int.to_bytes(cmd, 1, byteorder="big")
            + BMS._VER
            + int.to_bytes(start, 2, byteorder="big")
            + int.to_bytes(device, 1)
            + int.to_bytes(count, 2, byteorder="big")
        )
        frame += int.to_bytes(crc_modbus(frame), 2, byteorder="little")
        return bytes(frame)

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        # await self._await_reply(BMS._cmd(0, 0xf3, 0xea64, 0x1))
        await self._await_msg(BMS._cmd(1, 0xF3, 0x7654, 0x37))

        result: BMSSample = BMS._decode_data(BMS._FIELDS, self._msg[0x016E], start=BMS._HEAD_LEN)

        for pack in range(1, 1 + result.get("pack_count", 0)):
            await self._await_msg(BMS._cmd(pack, 0xF3, 0x75F8, 0x52))
            pack_response: bytes = self._msg[pack << 8 | 0xA4]

            pack_sample: PackSample = BMS._decode_pack(BMS._PFIELDS, pack_response, start=BMS._HEAD_LEN)
            # get cell voltages
            pack_sample["cell_voltages"] = BMS._cell_voltages(
                pack_response, cells=pack_response[BMS._CELLNUM_POS], start=BMS._CELL_POS
            )

            # add temperature sensors (4x cell temperature + 4 reserved)
            pack_sample["temp_values"] = BMS._temp_values(
                pack_response, values=pack_response[BMS._TEMPNUM_POS], start=BMS._TEMP_POS
            )
            result.setdefault("packs",[]).append(pack_sample)

        self._msg.clear()

        return result
