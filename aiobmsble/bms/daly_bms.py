"""Module to support Daly smart BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from typing import Final, NamedTuple

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSConfig, BMSDp, BMSInfo, BMSSample, MatcherPattern, TempSensor
from aiobmsble.basebms import BaseBMS, b2str, crc_modbus


class BMS(BaseBMS):
    """Daly smart BMS class implementation."""

    INFO: BMSInfo = {"default_manufacturer": "Daly", "default_model": "smart BMS"}
    _FCT_RD: Final[int] = 0x03
    _HEAD_LEN: Final[int] = 3
    _CRC_LEN: Final[int] = 2
    _MAX_CELLS: Final[dict[int, int]] = {0xD2: 32, 0x81: 48}
    _MAX_TEMP: Final[int] = 8
    _MOSTEMP_POS: Final[int] = _HEAD_LEN + 8

    class _dcmd(NamedTuple):
        fct: int
        adr: int
        length: int

    _CMDS: Final[dict[int, dict[str, _dcmd]]] = {
        0xD2: {
            "resp": _dcmd(0xD2, 0, 0),
            "rt1": _dcmd(_FCT_RD, 0x0, 62),
            "mos": _dcmd(_FCT_RD, 0x3E, 0x9),
            "info": _dcmd(_FCT_RD, 0xA9, 32),
        },
        0x81: {
            "resp": _dcmd(0x51, 0, 0),
            "rt1": _dcmd(_FCT_RD, 0x0, 64),
            "rt2": _dcmd(_FCT_RD, 0x41, 62),
            "info": _dcmd(_FCT_RD, 0x178, 74),
        },
    }
    _FIELDS: Final[dict[int, tuple[BMSDp, ...]]] = {
        0xD2: (
            BMSDp("voltage", 80, 2, False, lambda x: x / 10, 62),
            BMSDp("current", 82, 2, False, lambda x: (x - 30000) / 10, 62),
            BMSDp("battery_level", 84, 2, False, lambda x: x / 10, 62),
            BMSDp("cycle_charge", 96, 2, False, lambda x: x / 10, 62),
            BMSDp(
                "cell_count", 98, 2, False, lambda x: min(x, BMS._MAX_CELLS[0xD2]), 62
            ),
            BMSDp("temp_sensors", 100, 2, False, lambda x: min(x, BMS._MAX_TEMP), 62),
            BMSDp("cycles", 102, 2, False, idx=62),
            BMSDp("delta_voltage", 112, 2, False, lambda x: x / 1000, 62),
            BMSDp("problem_code", 116, 8, False, lambda x: x % 2**64, 62),
            BMSDp("balancer", 104, 2, False, idx=62),
            BMSDp("chrg_mosfet", 106, 2, False, bool, 62),
            BMSDp("dischrg_mosfet", 108, 2, False, bool, 62),
        ),
        0x81: (
            BMSDp("voltage", 112, 2, False, lambda x: x / 10, 64),
            BMSDp("current", 114, 2, False, lambda x: (x - 30000) / 10, 64),
            BMSDp("battery_level", 116, 2, False, lambda x: x / 10, 64),
            BMSDp("cycle_charge", 150, 2, False, lambda x: x / 10, 64),
            BMSDp(
                "cell_count", 120, 2, False, lambda x: min(x, BMS._MAX_CELLS[0x81]), 64
            ),
            BMSDp("temp_sensors", 122, 2, False, lambda x: min(x, BMS._MAX_TEMP), 64),
            #     BMSDp("cycles", 102, 2, False), # TODO
            #     BMSDp("delta_voltage", 112, 2, False, lambda x: x / 1000),
            #     BMSDp("problem_code", 116, 8, False, lambda x: x % 2**64),
            #     BMSDp("balancer", 104, 2, False),
            #     BMSDp("chrg_mosfet", 106, 2, False, bool),
            #     BMSDp("dischrg_mosfet", 108, 2, False, bool),
        ),
    }

    def __init__(
        self,
        ble_device: BLEDevice,
        config: BMSConfig | None = None,
        logger_name: str = "",
    ) -> None:
        """Initialize private BMS members."""
        super().__init__(ble_device, config, logger_name)
        self._proto: int = 0xD2
        self._rt_cmds: tuple[BMS._dcmd, ...] = ()
        self._msg: bytes = b""
        self._mos_avail: bool | None = None

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            MatcherPattern(
                local_name="DL-*",
                service_uuid=BMS.uuid_services()[0],
                connectable=True,
            )
        ] + [
            MatcherPattern(
                manufacturer_id=m_id,
                connectable=True,
            )
            for m_id in (0x102, 0x104, 0x0302, 0x0303, 0x0402)
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

    async def _fetch_device_info(self) -> BMSInfo:
        """Fetch the device information via BLE."""
        await self._await_msg(
            BMS._cmd_modbus(self._proto, *BMS._CMDS[self._proto]["info"])
        )
        if self._msg[0] == BMS._CMDS[0x81]["resp"][0]:
            return {
                "sw_version": b2str(self._msg[3:31]),
                "hw_version": b2str(self._msg[31:45]),
                "serial_number": b2str(self._msg[45:59]),
            }
        return {
            "sw_version": b2str(self._msg[3:19]),
            "hw_version": b2str(self._msg[19:35]),
            # "manuf.date": barr2str(self._msg[35:51]),
        }

    async def _init_connection(
        self, char_notify: BleakGATTCharacteristic | int | str | None = None
    ) -> None:
        await super()._init_connection(char_notify)
        for self._proto in BMS._CMDS:
            try:
                await self._await_msg(
                    BMS._cmd_modbus(self._proto, *BMS._CMDS[self._proto]["rt1"])
                )
                self._log.debug("detected protocol: 0x%X", self._proto)
                if "mos" not in BMS._CMDS[self._proto]:
                    self._mos_avail = False
                self._rt_cmds = tuple(
                    cmd
                    for name, cmd in BMS._CMDS[self._proto].items()
                    if name.startswith("rt")
                )
                break
            except TimeoutError:
                ...  # try next protocol
        else:
            self._proto = next(iter(BMS._CMDS))  # fallback to first protocol
            raise TimeoutError

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        self._log.debug("RX BLE data: %s", data)

        if (
            len(data) < BMS._HEAD_LEN
            or data[0] != BMS._CMDS[self._proto]["resp"][0]
            or data[1] != BMS._FCT_RD
            or data[2] != len(data) - BMS._HEAD_LEN - BMS._CRC_LEN
        ):
            self._log.debug("response data is invalid")
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
        result: BMSSample = {}
        if self._mos_avail in (True, None):
            try:
                # request MOS temperature (possible: response, stuck response, no response)
                await self._await_msg(
                    BMS._cmd_modbus(self._proto, *BMS._CMDS[self._proto]["mos"])
                )

                if self._mos_avail is None and self._msg[
                    BMS._MOSTEMP_POS : BMS._MOSTEMP_POS + 2
                ] in (b"\x00\x00", b"\xff\xff"):
                    self._log.debug("MOS temperature invalid, deactivating")
                    self._mos_avail = False
                else:
                    result["temp_values"] = [
                        TempSensor(
                            int.from_bytes(
                                self._msg[BMS._MOSTEMP_POS : BMS._MOSTEMP_POS + 2],
                                byteorder="big",
                            )
                            - 40,
                            TempSensor.T.MOSFET,
                        )
                    ]
                    self._mos_avail = True
            except TimeoutError:
                self._log.debug("MOS temperature read failed, deactivating")
                self._mos_avail = False

        rt_msgs: dict[int, bytes] = {}
        for cmd in self._rt_cmds:
            await self._await_msg(BMS._cmd_modbus(self._proto, *cmd))
            if self._msg[2] // 2 != cmd.length:
                self._log.debug("incorrect response %i", self._msg[2])
                break
            rt_msgs[cmd.length] = self._msg

        if len(rt_msgs) != len(self._rt_cmds):
            raise ValueError("BMS data incomplete.")

        result |= BMS._decode_data(
            BMS._FIELDS[self._proto], rt_msgs, start=BMS._HEAD_LEN
        )

        rt1_msg: Final[bytes] = next(iter(rt_msgs.values()))
        # add temperature sensors
        result.setdefault("temp_values", []).extend(
            BMS._temp_values(
                rt1_msg,
                values=result.get("temp_sensors", 0),
                start=BMS._MAX_CELLS[self._proto] * 2 + BMS._HEAD_LEN,
                offset=40,
            )
        )

        # get cell voltages
        result["cell_voltages"] = BMS._cell_voltages(
            rt1_msg, cells=result.get("cell_count", 0), start=BMS._HEAD_LEN
        )

        return result
