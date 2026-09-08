"""Module to support PowerXtreme BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

import asyncio
from contextlib import suppress
from typing import Literal

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSConfig, BMSDp, BMSInfo, BMSSample, MatcherPattern
from aiobmsble.bms.topband_bms import BMS as TopbandBMS


class BMS(TopbandBMS):
    """PowerXtreme BMS implementation."""

    INFO: BMSInfo = {
        "default_manufacturer": "PowerXtreme",
        "default_model": "smart BMS",
    }
    FIELDS: tuple[BMSDp, ...] = tuple(
        f._replace(fct=lambda x: x / 10) if f.key == "current" else f
        for f in TopbandBMS.FIELDS
    )

    ALIVE_INTERVAL = 3.0  # seconds
    _ctrl_proto: bytes = b""  # parse control protocol

    def __init__(
        self,
        ble_device: BLEDevice,
        config: BMSConfig | None = None,
        logger_name: str = "",
    ) -> None:
        """Initialize private BMS members."""
        super().__init__(ble_device, config, logger_name)
        self._alive_task: asyncio.Task[None] | None = None

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            {
                "service_uuid": BMS.uuid_services()[0],
                "connectable": True,
                "manufacturer_id": 76,
            }
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
        info_cmd: tuple[tuple[bytes, Literal["serial_number", "model"]], ...] = (
            (b"<M:SR>", "serial_number"),
            (b"<N:NA>", "model"),
        )
        bms_info: BMSInfo = await super()._fetch_device_info()

        for cmd, info in info_cmd:
            try:
                self._ctrl_proto = cmd[1:2]
                await self._await_msg(cmd)
                bms_info[info] = self._msg[2:].decode("ascii", errors="strict")
            except TimeoutError:
                self._log.debug("failed to fetch %s", info)
            except UnicodeError:
                self._log.debug("failed to decode %s", info)
            finally:
                self._ctrl_proto = b""
                self._msg_event.clear()

        return bms_info

    async def _alive(self) -> None:
        """Continuously poll the module so it keeps streaming."""
        with suppress(TimeoutError):
            self._ctrl_proto = b"I"
            await self._await_msg(b"<I:WA>")
            self._ctrl_proto = b""
            self._msg_event.clear()

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        if self._ctrl_proto:
            if (
                len(data) >= 3
                and data[0] == 0x3C
                and data[-1] == 0x3E
                and data[1] == self._ctrl_proto[0]
            ):
                self._log.debug("RX BLE data (ctrl): %s", data)
                self._msg = bytes(data[1:-1])
                self._msg_event.set()
                return
            self._log.debug("ignoring non-control data: %s", data)
            return
        super()._notification_handler(_sender, data)

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""

        await self._await_msg(b"<B:ST>", wait_for_notify=False)
        await self._await_msg(b"<H:ST>", wait_for_notify=False)

        await asyncio.wait_for(self._wait_event(), timeout=BMS.TIMEOUT)

        return self._decode_data(BMS.FIELDS, self._msg, byteorder="little") | {
            "cell_voltages": BMS._cell_voltages(
                self._msg, cells=BMS._MAX_CELLS, start=22, byteorder="little"
            )
        }
