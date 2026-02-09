"""Module to support Humsienk BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from functools import cache
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSDp, BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS, b2str, crc_sum


class BMS(BaseBMS):
    """Humsienk BMS implementation.

    Protocol details (confirmed via live device testing):

    Read commands (used by this driver):
        0x00: Handshake/init
        0x11: Device model (ASCII string)
        0x20: Operating status (FETs, alarms, runtime, balance, disconnect)
        0x21: Battery info (voltage, current, SOC, SOH, capacity, cycles, temps)
        0x22: Cell voltages (up to 24 cells, 2 bytes each, millivolts LE)
        0x58: Configuration (protection thresholds, capacity, cell count)
        0xF5: Firmware/hardware version (ASCII string)

    Read commands (not used, documented for reference):
        0x23: Redundant current reading (4-byte signed LE, mA) — same value
              already present in 0x21 at offset 4. Not worth the BLE round-trip.
        0x40: Battery chemistry type. Response contains a single byte at data
              offset 13 indicating the pack composition (e.g. 0=NMC/ternary,
              1=LiFePO4). Could be fetched in _fetch_device_info() and stored
              in BMSInfo once a "chemistry" field exists in the schema
              (see https://github.com/patman15/aiobmsble/issues/136).

    Write commands (not implemented, documented for reference):
        0x50: Charge FET control (data: [0x00]=off, [0x01]=on)
        0x51: Discharge FET control (data: [0x00]=off, [0x01]=on)
        0x52: Balance control (data: [0x00]=off, [0x01]=on)
        0x53: Clear error/protection status

    Frame format:
        [0xAA, CMD, LEN, DATA..., CHK_LO, CHK_HI]
        Checksum: 16-bit LE sum of bytes from CMD through end of DATA

    0x21 Battery Info data layout (26 bytes):
        [0:4]   voltage      - Pack voltage in mV (unsigned 32-bit LE)
        [4:8]   current      - Current in mA (signed 32-bit LE, positive=charging)
        [8]     SOC          - State of Charge %
        [9]     SOH          - State of Health %
        [10:14] capacity     - Remaining capacity in mAh (unsigned 32-bit LE)
        [14:18] allCapacity  - Total/design capacity in mAh (unsigned 32-bit LE)
        [18:20] cycles       - Charge cycle count (unsigned 16-bit LE)
        [20]    temp1        - Cell temperature 1 in °C (signed byte)
        [21]    temp2        - Cell temperature 2 in °C (signed byte)
        [22]    temp3        - Cell temperature 3 in °C (signed byte)
        [23]    temp4        - Cell temperature 4 in °C (signed byte)
        [24]    MOS temp     - MOSFET temperature in °C (signed byte)
        [25]    env temp     - Environment temperature in °C (signed byte)

    0x20 Status data layout (14-15 bytes):
        [0:2]   runtime days    - Device uptime days (unsigned 16-bit LE)
        [2]     runtime hours   - Device uptime hours (unsigned byte)
        [3]     runtime minutes - Device uptime minutes (unsigned byte)
        Note: Uptime fields (bytes 0-3) are not parsed. The framework's
        "runtime" field means "time remaining until empty" (derived from
        cycle_charge/current), which is a different concept from device uptime.
        [4:8]   operation_status - 32-bit alarm/protection/FET flags (LE):
                Bit 0:  Charge overcurrent protection
                Bit 1:  Charge over-temperature protection
                Bit 2:  Charge under-temperature protection
                Bit 4:  Pack overvoltage protection
                Bit 7:  Charge FET status (1=on)
                Bit 8:  Charge overcurrent warning
                Bit 9:  Charge over-temperature warning
                Bit 10: Charge under-temperature warning
                Bit 12: Pack overvoltage warning
                Bit 15: Balance active (1=yes)
                Bit 16: Discharge overcurrent protection
                Bit 17: Discharge over-temperature protection
                Bit 18: Discharge under-temperature protection
                Bit 20: Short circuit protection
                Bit 21: Pack undervoltage protection
                Bit 23: Discharge FET status (1=on)
                Bit 24: Discharge overcurrent warning
                Bit 25: Discharge over-temperature warning
                Bit 26: Discharge under-temperature warning
                Bit 28: Pack undervoltage warning
                Bit 29: MOS over-temperature warning
                Bit 30: MOS over-temperature protection
        [8:11]  cell_balance     - 24-bit bitmap of cells being balanced
                Each bit corresponds to a cell (bit 0 = cell 1, bit 1 = cell 2,
                etc.). A set bit means that cell is actively being balanced.
                Combined with cell_voltages from 0x22, this enables per-cell
                diagnostics — e.g. identifying which cells are drifting and
                how effectively the BMS is compensating. Currently exposed as
                a scalar "balancer" bool; a per-cell list would be more useful
                (see https://github.com/patman15/aiobmsble/issues/134).
        [11:14] cell_disconnect  - 24-bit bitmap of disconnected cells
                Same bit-per-cell layout as cell_balance. A set bit indicates
                a physically disconnected cell (broken wire, faulty connection).
                Any non-zero value triggers problem=True in this driver.

    0x58 Configuration data layout (44 bytes, all 2-byte unsigned LE unless noted):
        [0:2]   cell_count               - Number of cells in series
        [2:4]   rated_capacity           - Rated capacity in 0.01 Ah
        [4:6]   cell_ovp                 - Cell overvoltage protection threshold (mV)
        [6:8]   cell_ovp_recovery        - Cell OVP recovery voltage (mV)
        [8:10]  ovp_delay                - OVP trigger delay (seconds)
        [10:12] cell_uvp                 - Cell undervoltage protection threshold (mV)
        [12:14] cell_uvp_recovery        - Cell UVP recovery voltage (mV)
        [14:16] uvp_delay                - UVP trigger delay (seconds)
        [16:18] charge_ocp               - Charge overcurrent protection (0.1 A)
        [18:20] charge_ocp_delay         - Charge OCP delay (seconds)
        [20:22] discharge_ocp1           - Discharge overcurrent level 1 (0.1 A)
        [22:24] discharge_ocp1_delay     - Discharge OCP1 delay (seconds)
        [24:26] discharge_ocp2           - Discharge overcurrent level 2 (0.1 A)
        [26:28] discharge_ocp2_delay     - Discharge OCP2 delay (seconds)
        [28:30] charge_high_temp         - Charge high temp threshold (deciKelvin)
        [30:32] charge_high_temp_recovery
        [32:34] charge_low_temp          - Charge low temp threshold (deciKelvin)
        [34:36] charge_low_temp_recovery
        [36:38] discharge_high_temp      - Discharge high temp threshold (deciKelvin)
        [38:40] discharge_high_temp_recovery
        [40:42] discharge_low_temp       - Discharge low temp threshold (deciKelvin)
        [42:44] discharge_low_temp_recovery
        Temperature conversion: °C = (raw - 2731) / 10
    """

    INFO: BMSInfo = {
        "default_manufacturer": "Humsienk",
        "default_model": "BMC",
    }
    _HEAD: Final[bytes] = b"\xaa"  # beginning of frame
    _MIN_LEN: Final[int] = 5  # minimal frame len
    # Mask to extract alarm/protection bits from operation_status (exclude FET + balance)
    _ALARM_MASK: Final[int] = ~((1 << 7) | (1 << 15) | (1 << 23)) & 0xFFFFFFFF
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        # 0x21: Battery info
        # Voltage is 4 bytes (32-bit); 2 bytes would silently work for ≤65V packs
        # but overflow for higher-voltage configurations.
        BMSDp("voltage", 3, 4, False, lambda x: x / 1000, 0x21),
        BMSDp("current", 7, 4, True, lambda x: x / 1000, 0x21),
        BMSDp("battery_level", 11, 1, False, idx=0x21),
        BMSDp("battery_health", 12, 1, False, idx=0x21),
        BMSDp("cycle_charge", 13, 4, False, lambda x: x / 1000, 0x21),
        BMSDp("design_capacity", 17, 4, False, lambda x: round(x / 1000), 0x21),
        BMSDp("cycles", 21, 2, False, idx=0x21),
        # 0x20: Operating status
        BMSDp("chrg_mosfet", 7, 1, False, lambda x: bool(x & 0x80), 0x20),
        BMSDp("dischrg_mosfet", 9, 1, False, lambda x: bool(x & 0x80), 0x20),
        BMSDp("balancer", 8, 1, False, lambda x: bool(x & 0x80), 0x20),
        BMSDp("problem_code", 7, 4, False, lambda x: x & 0xFF7F7F7F, 0x20),
    )
    # 0x23 excluded: returns redundant current reading already in 0x21 (see docstring)
    _CMDS: Final = frozenset({b"\x20", b"\x21", b"\x22"})

    def __init__(self, ble_device: BLEDevice, keep_alive: bool = True) -> None:
        """Initialize BMS."""
        super().__init__(ble_device, keep_alive)
        self._msg: dict[int, bytes] = {}
        self._valid_reply: int = 0x00

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            {
                "local_name": "HS*",
                "service_uuid": BMS.uuid_services()[0],
                "connectable": True,
            }
        ]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return (normalize_uuid_str("0001"),)

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "0003"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        return "0002"

    async def _fetch_device_info(self) -> BMSInfo:
        """Fetch the device information via BLE."""
        for cmd in (b"\x11", b"\xf5"):
            await self._await_msg(BMS._cmd(cmd))
        return {
            "model": b2str(self._msg[0x11][3:-2]),
            "hw_version": b2str(self._msg[0xF5][3:-2]),
        }

    async def _init_connection(
        self, char_notify: BleakGATTCharacteristic | int | str | None = None
    ) -> None:
        """Initialize RX/TX characteristics and protocol state."""
        await super()._init_connection(char_notify)
        await self._await_msg(BMS._cmd(b"\x00"))  # init

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        self._log.debug("RX BLE data: %s", data)

        if not data.startswith(BMS._HEAD) or ((length := len(data)) < BMS._MIN_LEN):
            self._log.debug("incorrect SOF")
            return

        if length != data[2] + BMS._MIN_LEN:
            self._log.debug("invalid frame length %d != %d", length, data[2])
            return

        if data[1] != self._valid_reply:
            self._log.debug("unexpected response (type 0x%X)", data[1])
            return

        if (crc := crc_sum(data[1:-2], 2)) != int.from_bytes(
            data[-2:], byteorder="little"
        ):
            self._log.debug(
                "invalid checksum 0x%X != 0x%X",
                int.from_bytes(data[-2:], byteorder="little"),
                crc,
            )
            return

        self._msg[data[1]] = bytes(data)
        self._msg_event.set()

    @staticmethod
    @cache
    def _cmd(cmd: bytes) -> bytes:
        """Assemble a Humsienk BMS command."""
        assert len(cmd) == 1
        frame: Final[bytes] = cmd[:1] + b"\x00"
        # head, cmd, length, 16-bit sum
        return (
            BMS._HEAD
            + frame
            + crc_sum(frame).to_bytes(2, byteorder="little")
        )

    async def _await_msg(
        self,
        data: bytes,
        char: int | str | None = None,
        wait_for_notify: bool = True,
        max_size: int = 0,
    ) -> None:
        """Send data to the BMS and wait for valid reply notification."""

        self._valid_reply = data[1]  # expected reply type
        await super()._await_msg(data, char, wait_for_notify, max_size)

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        for cmd in BMS._CMDS:
            await self._await_msg(BMS._cmd(cmd))

        result: BMSSample = BMS._decode_data(
            BMS._FIELDS, data=self._msg, byteorder="little"
        )
        result["cell_voltages"] = BMS._cell_voltages(
            self._msg[0x22], cells=24, start=3, byteorder="little"
        )
        result["temp_values"] = BMS._temp_values(
            self._msg[0x21], values=6, start=23, size=1, byteorder="little"
        )

        # Cell disconnect bitmap: 0x20 data bytes 11-13 (frame bytes 14-16).
        # A non-zero value indicates physically disconnected cells (broken
        # wires, faulty connections) — a critical safety condition that should
        # flag the battery as having a problem regardless of other alarm bits.
        msg20 = self._msg[0x20]
        if len(msg20) >= 17:
            disconnect = int.from_bytes(msg20[14:17], byteorder="little", signed=False)
            if disconnect:
                result["problem"] = True

        return result
