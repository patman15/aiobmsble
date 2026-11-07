"""Module to support Seplos v2 BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from functools import lru_cache
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import (
    BMSConfig,
    BMSDp,
    BMSInfo,
    BMSLimits,
    BMSSample,
    Limit,
    LimitDp,
    MatcherPattern,
    TempSensor,
)
from aiobmsble.basebms import BaseBMS, b2str, crc_xmodem


class BMS(BaseBMS):
    """Seplos v2 BMS implementation."""

    INFO: BMSInfo = {"manufacturer": "Seplos", "model": "smart BMS V2"}
    _HEAD: Final[bytes] = b"\x7e"
    _TAIL: Final[bytes] = b"\x0d"
    _CMD_VER: Final[int] = 0x10  # TX protocol version
    _RSP_VER: Final[int] = 0x14  # RX protocol version
    _MIN_LEN: Final[int] = 10
    _MAX_SUBS: Final[int] = 0xF
    _CELL_POS: Final[int] = 9
    _PACK_POS: Final[int] = 42
    _SWV_POS: Final[int] = 38
    _PRB_MAX: Final[int] = 8  # max number of alarm event bytes
    _PRB_MASK: Final[int] = ~(0x80FFC0)  # mask alarm event 6-8 (internal bits)
    _PFIELDS: Final[tuple[BMSDp, ...]] = (  # Seplos V2: single machine data
        BMSDp("voltage", 2, 2, False, lambda x: x / 100),
        BMSDp("current", 0, 2, True, lambda x: x / 100),  # /10 for 0x62
        BMSDp("cycle_charge", 4, 2, False, lambda x: x / 100),  # /10 for 0x62
        BMSDp("cycles", 13, 2, False),
        BMSDp("design_capacity", 11, 2, False, lambda x: x // 100),
        BMSDp("battery_level", 9, 2, False, lambda x: x / 10),
        BMSDp("battery_health", 15, 2, False, lambda x: x / 10),
    )
    # 0x47 parameter table: parameter n (2-byte) at byte 2n-9, 1-byte parameters follow
        # discharge current is reported negative, scale inverts it
    _LIMIT_FIELDS: Final[tuple[LimitDp, ...]] = (
        LimitDp(Limit.CELL_OVP, "trip", 17, scale=0.001),  # #13
        LimitDp(Limit.CELL_OVP, "release", 19, scale=0.001),  # #14
        LimitDp(Limit.CELL_UVP, "trip", 21, scale=0.001),  # #15
        LimitDp(Limit.CELL_UVP, "release", 23, scale=0.001),  # #16
        LimitDp(Limit.PACK_OVP, "trip", 37, scale=0.01),  # #23
        LimitDp(Limit.PACK_OVP, "release", 39, scale=0.01),  # #24
        LimitDp(Limit.PACK_UVP, "trip", 41, scale=0.01),  # #25
        LimitDp(Limit.PACK_UVP, "release", 43, scale=0.01),  # #26
        LimitDp(Limit.CHARGE_OTP, "trip", 57, scale=0.1, offset=273.1),  # #33
        LimitDp(Limit.CHARGE_OTP, "release", 59, scale=0.1, offset=273.1),  # #34
        LimitDp(Limit.CHARGE_UTP, "trip", 61, scale=0.1, offset=273.1),  # #35
        LimitDp(Limit.CHARGE_UTP, "release", 63, scale=0.1, offset=273.1),  # #36
        LimitDp(Limit.DISCHARGE_OTP, "trip", 73, scale=0.1, offset=273.1),  # #41
        LimitDp(Limit.DISCHARGE_OTP, "release", 75, scale=0.1, offset=273.1),  # #42
        LimitDp(Limit.DISCHARGE_UTP, "trip", 77, scale=0.1, offset=273.1),  # #43
        LimitDp(Limit.DISCHARGE_UTP, "release", 79, scale=0.1, offset=273.1),  # #44
        LimitDp(Limit.MOS_OTP, "trip", 105, scale=0.1, offset=273.1),  # #57
        LimitDp(Limit.MOS_OTP, "release", 107, scale=0.1, offset=273.1),  # #58
        LimitDp(Limit.CHARGE_OCP, "trip", 117, scale=0.01),  # #63
        LimitDp(Limit.DISCHARGE_OCP, "trip", 119, scale=-0.01, signed=True),  # #64
        LimitDp(Limit.CHARGE_OCP, "delay", 136, size=1),  # #76
        LimitDp(Limit.DISCHARGE_OCP, "delay", 137, size=1),  # #77
    )
    _GSMD_LEN: Final[int] = _CELL_POS + max((dp.pos + dp.size) for dp in _PFIELDS) + 3
    _CMDS: Final[frozenset[tuple[int, bytes]]] = frozenset({(0x51, b""), (0x61, b"\x00")})

    def __init__(
        self,
        ble_device: BLEDevice,
        config: BMSConfig | None = None,
        logger_name: str = "",
    ) -> None:
        """Initialize private BMS members."""
        super().__init__(ble_device, config, logger_name)
        self._msg: dict[int, bytes] = {}
        self._exp_len: int = BMS._MIN_LEN
        self._exp_reply: set[int] = set()

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            {
                "local_name": pattern,
                "service_uuid": BMS.uuid_services()[0],
                "connectable": True,
            }
            for pattern in ("BP0?", "BP1?", "BP2?")
        ]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return (normalize_uuid_str("ff00"),)

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "ff01"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        return "ff02"

    async def _fetch_device_info(self) -> BMSInfo:
        """Fetch the device information via BLE."""
        self._exp_reply = {0x51}
        await self._await_msg(BMS._cmd(0x51))
        _dat: Final[bytes] = self._msg[0x51]
        if len(_dat) <= BMS._SWV_POS:
            raise ValueError("BMS data incomplete")
        return {
            "model": b2str(_dat[26:36]),
            "sw_version": f"{int(_dat[BMS._SWV_POS-1])}.{int(_dat[BMS._SWV_POS])}",
        }

    def _notification_handler(self, _sender: BleakGATTCharacteristic, data: bytearray) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        if (
            len(data) > BMS._MIN_LEN
            and data.startswith(BMS._HEAD)
            and (len(self._frame) >= self._exp_len or not self._frame)
        ):
            self._exp_len = min(BMS._MIN_LEN + int.from_bytes(data[5:7]), BMS._MAX_MSG_LEN)
            self._frame.clear()

        self._frame.extend(data)
        self._log.debug("RX BLE data (%s): %s", "start" if data == self._frame else "cnt.", data)

        # verify that data is long enough
        if len(self._frame) < self._exp_len:
            return

        if not self._frame.endswith(BMS._TAIL):
            self._log.debug("incorrect frame end: 0x%X", self._frame[-1])
            return

        if self._frame[1] != BMS._RSP_VER:
            self._log.debug("unknown frame version: V%.1f", self._frame[1] / 10)
            return

        if self._frame[4]:
            self._log.debug("BMS reported error code: 0x%X", self._frame[4])
            return

        if not self._check_integrity(
            self._frame, lambda x: crc_xmodem(x[1:-3]), slice(None, None), slice(-3, -1)
        ):
            return

        self._log.debug(
            "address: 0x%X, function: 0x%X, return: 0x%X",
            self._frame[2],
            self._frame[3],
            self._frame[4],
        )

        self._msg[self._frame[3]] = bytes(self._frame)
        try:
            self._exp_reply.remove(self._frame[3])
            self._msg_event.set()
        except KeyError:
            self._log.debug("unexpected reply: 0x%X", self._frame[3])

    async def _fetch_limits(self) -> BMSLimits:
        """Fetch the protection thresholds (0x47 parameter frame, group 0)."""
        self._exp_reply = {0x47}
        await self._await_msg(BMS._cmd(0x47, data=b"\x00"))
        return BMS._decode_limits(self._msg.pop(0x47), BMS._LIMIT_FIELDS)

    async def _init_connection(
        self, char_notify: BleakGATTCharacteristic | int | str | None = None
    ) -> None:
        """Initialize protocol state."""
        await super()._init_connection()
        self._exp_len = BMS._MIN_LEN

    @staticmethod
    @lru_cache(maxsize=32)
    def _cmd(cmd: int, address: int = 0, data: bytes = b"") -> bytes:
        """Assemble a Seplos V2 BMS command."""
        assert cmd in (0x47, 0x51, 0x61, 0x62, 0x04)  # allow only read commands
        frame = bytearray([*BMS._HEAD, BMS._CMD_VER, address, 0x46, cmd])
        frame.extend(len(data).to_bytes(2, "big", signed=False) + data)
        frame.extend(int.to_bytes(crc_xmodem(frame[1:]), 2, byteorder="big") + BMS._TAIL)
        return bytes(frame)

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""

        for cmd, data in BMS._CMDS:
            self._exp_reply.add(cmd)
            await self._await_msg(BMS._cmd(cmd, data=data))

        result: BMSSample = {}
        result["cell_count"] = self._msg[0x61][BMS._CELL_POS]
        temp_pos: Final[int] = BMS._CELL_POS + result["cell_count"] * 2 + 1
        if len(self._msg[0x51]) <= BMS._PACK_POS or len(self._msg[0x61]) <= temp_pos:
            raise ValueError("BMS data incomplete")

        # get extension pack count from manufacturer information (only main unit != 0)
        result["pack_count"] = self._msg[0x51][BMS._PACK_POS]
        result["temp_count"] = self._msg[0x61][temp_pos]
        ct_blk_len: Final[int] = (result["cell_count"] + result["temp_count"]) * 2 + 2

        if (BMS._GSMD_LEN + ct_blk_len) > len(self._msg[0x61]):
            raise ValueError("BMS data incomplete")

        result |= BMS._decode_data(BMS._PFIELDS, self._msg[0x61], start=BMS._CELL_POS + ct_blk_len)

        states_pos: Final[int] = (
            (BMS._CELL_POS + ct_blk_len)
            + (result["cell_count"] + result["temp_count"])
            + (3 + 19)
        )
        cst_alarm_pos: Final[int] = states_pos + 1
        if len(self._msg[0x61]) <= cst_alarm_pos:
            raise ValueError("BMS data incomplete")

        # get switches from parallel data (main pack)
        states: Final[int] = self._msg[0x61][states_pos]
        result |= {
            "dischrg_mosfet": bool(states & 0x1),
            "chrg_mosfet": bool(states & 0x2),
            "heater": bool(states & 0x8),
        }

        balance_pos: Final[int] = cst_alarm_pos + 1 + self._msg[0x61][cst_alarm_pos]
        balance_len: Final[int] = min((result["cell_count"] + 7) // 8, 8)  # round up
        result["balancer"] = int.from_bytes(
            self._msg[0x61][balance_pos : balance_pos + balance_len]
        )

        # get alarms from parallel data (main pack)
        alarm_evt: Final[int] = min(self._msg[0x61][cst_alarm_pos], BMS._PRB_MAX)
        result["problem_code"] = (
            int.from_bytes(
                self._msg[0x61][cst_alarm_pos + 1 : cst_alarm_pos + 1 + alarm_evt],
                byteorder="big",
            )
            & BMS._PRB_MASK
        )

        result["cell_voltages"] = BMS._cell_voltages(
            self._msg[0x61],
            cells=self._msg[0x61][BMS._CELL_POS],
            start=10,
        )
        result["temperature"] = BMS._temperature(
            self._msg[0x61],
            values=result.get("temp_count", 0),
            start=BMS._CELL_POS + result.get("cell_count", 0) * 2 + 2,
            signed=False,
            offset=2731,
            divider=10,
            types=(TempSensor.T.CELL,) * (result.get("temp_count", 2) - 2)
            + (TempSensor.T.AMBIENT, TempSensor.T.MOSFET),
        )

        self._msg.clear()

        return result
