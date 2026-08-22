"""Module to support "C4S100"-family generic Modbus-over-BLE Smart BMS.

Reverse-engineered from a 4S/100A LiFePO4 BMS sold under the local BLE name
"C4S100IEnnnnn" (app: "E-BMS"), HW module RC6621A (Onmicro HS6621CM,
transparent BLE-UART bridge). The application-level protocol is plain
MODBUS RTU (slave id 0x02, function 0x03 - Read Holding Registers) carried
transparently inside the Nordic UART Service. A single request for the 70
holding registers starting at address 0x0000 returns the complete telemetry
set (voltage, signed current, SOC, cell voltages, capacity, cycles, temps).

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice

from aiobmsble import BMSConfig, BMSDp, BMSInfo, BMSSample, MatcherPattern, TempSensor
from aiobmsble.basebms import BaseBMS, crc_modbus


class BMS(BaseBMS):
    """C4S100-family generic Modbus-over-BLE Smart BMS implementation."""

    INFO: BMSInfo = {
        "default_manufacturer": "Generic",
        "default_model": "C4S100 Smart BMS (RC6621A)",
    }
    _HEAD: Final[bytes] = b"\x02\x03"  # slave id 0x02, function 0x03 (read holding regs)
    _FRAME_LEN: Final[int] = 5  # head(2) + byte-count(1) + CRC(2)
    _CELLS: Final[int] = 4  # fixed 4S pack
    _TEMPS: Final[int] = 2  # 2 physical temp sensors (MOS_T, ENV_T); app mirrors
    #  them a second time as TCell1/TCell2 with identical values, not reported here
    _REG_COUNT: Final[int] = 0x46  # 70 holding registers polled in one request
    _RESP_LEN: Final[int] = _REG_COUNT * 2  # expected byte-count field (0x8C)

    # BMSDp(key, pos, size, signed, fct, idx)
    # pos = byte offset within the full received frame (0=addr,1=func,2=byte-count,
    # 3.. = register data, big-endian, 2 bytes/register)
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("voltage", 3, 2, False, lambda x: x / 100, _RESP_LEN),  # reg0
        # reg1 (hi word) + reg2 (lo word): signed 32-bit current, 0.01A,
        # positive = charging, negative = discharging (matches app & library convention)
        BMSDp("current", 5, 4, True, lambda x: x / 100, _RESP_LEN),  # reg1+reg2
        BMSDp("battery_level", 9, 2, False, idx=_RESP_LEN),  # reg3, SOC %
        BMSDp("cycle_charge", 11, 2, False, lambda x: x / 100, _RESP_LEN),  # reg4, Ah
        BMSDp(
            "design_capacity", 13, 2, False, lambda x: round(x / 100), _RESP_LEN
        ),  # reg5, Ah
        BMSDp("cycles", 15, 2, False, idx=_RESP_LEN),  # reg6
        BMSDp("battery_health", 17, 2, False, idx=_RESP_LEN),  # reg7, SOH %
        BMSDp("delta_voltage", 29, 2, False, lambda x: x / 1000, _RESP_LEN),  # reg13
        BMSDp("cell_count", 45, 2, False, idx=_RESP_LEN),  # reg21
    )
    _RESPS: Final = frozenset(field.idx for field in _FIELDS)
    _CMDS: Final[frozenset[tuple[int, int]]] = frozenset({(0x0, _REG_COUNT)})

    def __init__(
        self,
        ble_device: BLEDevice,
        config: BMSConfig | None = None,
        logger_name: str = "",
    ) -> None:
        """Initialize private BMS members."""
        super().__init__(ble_device, config, logger_name)
        self._msg: dict[int, bytes] = {}

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            {  # observed name: "C4S100IE06007" (model prefix + serial, Unix glob)
                "local_name": "C4S100IE?????",
                "service_uuid": BMS.uuid_services()[0],
                "connectable": True,
            }
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

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        self._log.debug("RX BLE data: %s", data)

        if not data.startswith(BMS._HEAD):
            self._log.debug("incorrect SOF")
            return

        if len(data) < BMS._FRAME_LEN or len(data) != data[2] + BMS._FRAME_LEN:
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

        self._msg[data[2]] = bytes(data)
        self._msg_event.set()

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        self._msg.clear()
        for addr, length in BMS._CMDS:
            await self._await_msg(BMS._cmd_modbus(dev_id=0x2, addr=addr, count=length))
        if not BMS._RESPS.issubset(set(self._msg.keys())):
            self._log.debug("incomplete data set %s", self._msg.keys())
            raise TimeoutError("BMS data incomplete.")

        result: BMSSample = BMS._decode_data(BMS._FIELDS, self._msg)
        result["cell_voltages"] = BMS._cell_voltages(
            self._msg[BMS._RESP_LEN],
            cells=result.get("cell_count", BMS._CELLS),
            start=47,  # reg22
        )
        result["temp_sensors"] = BMS._TEMPS
        result["temp_values"] = BMS._temp_values(
            self._msg[BMS._RESP_LEN],
            start=35,  # reg16 (MOS_T), reg17 (ENV_T)
            values=BMS._TEMPS,
            types=(TempSensor.T.MOSFET, TempSensor.T.AMBIENT),
        )

        return result
