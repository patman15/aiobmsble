"""Module to support PowerXtreme BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

import asyncio
from typing import Final

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

    _ALIVE_INTERVAL: Final[float] = 8.0  # seconds
    _ctrl_proto: bool = False  # parse control protocol

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
        self._ctrl_proto = True
        bms_info: BMSInfo = await super()._fetch_device_info()
        try:
            await self._await_msg(b"<N:NA>")
        finally:
            self._ctrl_proto = False
        bms_info["serial_number"] = str(self._msg[2:])

        return bms_info

    async def _alive_loop(self) -> None:
        """Continuously poll the module so it keeps streaming."""
        try:
            while True:
                await asyncio.sleep(BMS._ALIVE_INTERVAL)
                async with self._op_lock:
                    await self._await_msg(b"<I:WA>", wait_for_notify=False)
        except asyncio.CancelledError:
            return
        except Exception as exc:  # noqa: BLE001 - keep-alive must not crash the loop
            self._log.debug("alive loop stopped (%s)", type(exc).__name__)

    async def _init_connection(
        self, char_notify: BleakGATTCharacteristic | int | str | None = None
    ) -> None:
        """Set up notifications, keep-alive alive, PIN auth and data streaming."""
        await super()._init_connection(char_notify)

        if self._alive_task is None or self._alive_task.done():
            self._alive_task = asyncio.create_task(self._alive_loop())

    async def _disconnect(self, reset: bool) -> None:
        """Stop the keep-alive alive task, then disconnect."""
        if self._alive_task is not None:
            self._alive_task.cancel()
            self._alive_task = None

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        if self._ctrl_proto:
            if len(data) >= 3 and data[0] == 0x3C and data[-1] == 0x3E:
                self._log.debug("RX BLE data (ctrl): %s", data)
                self._msg = bytes(data[1:-1])
                self._msg_event.set()
                return
            self._log.debug("ignoring non-control data: %s", data)
            return
        super()._notification_handler(_sender, data)

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""

        await self._await_msg(b"<B:ST>")

        return await super()._async_update()
