"""Module to support Dometic BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

import asyncio
from enum import Enum
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSConfig, BMSDp, BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS


class BMS(BaseBMS):
    """Dometic BMS implementation."""

    INFO: BMSInfo = {
        "default_manufacturer": "Dometic",
        "default_model": "Büttner BMS",
    }

    class _NotifyChars(Enum):
        ch_b = "00000004-0000-1000-8000-008025000000"
        ch_c = "0000000a-0000-1000-8000-008025000000"

    _HEAD: Final[bytes] = b"\x23\x85"
    _FRAME_LEN: Final[int] = 8
    _ALIVE_INTERVAL: Final[float] = 24.0  # seconds
    _UUID_SLC: Final[slice] = slice(4, 8)
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("voltage", 4, 2, False, lambda x: x / 100, 0x02),
        BMSDp(
            "current",
            6,
            2,
            False,
            lambda x: (x if x <= 32767 else 32767 - x) / 100,
            0x02,
        ),
        BMSDp("design_capacity", 4, 4, False, idx=0x07),
        BMSDp("battery_level", 4, 1, False, idx=0x0B),
        BMSDp("temperature", 4, 2, False, lambda x: (x - 500) / 10, 0x0C),
        BMSDp("cycle_capacity", 4, 2, False, idx=0x36),
        BMSDp("battery_health", 4, 1, False, idx=0x0E),
    )
    _CMDS: Final[set[int]] = {field.idx for field in _FIELDS} | {0x56, 0x57}

    accept_secret: bool = True

    def __init__(
        self,
        ble_device: BLEDevice,
        config: BMSConfig | None = None,
        logger_name: str = "",
    ) -> None:
        """Initialize BMS."""
        super().__init__(ble_device, config, logger_name)
        self._alive_task: asyncio.Task[None] | None = None
        self._data_final: dict[int, dict[int, bytes]] = {}
        self._exp_reply: bytes = b""
        self._ch_b_event: asyncio.Event = asyncio.Event()
        self._ch_c_event: asyncio.Event = asyncio.Event()
        self._ka_resp: int = 0xFF

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            {
                "manufacturer_id": 2117,
                "manufacturer_data_start": [0x14, 0x85],
                "connectable": True,
            }
        ]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return (normalize_uuid_str("fefb"), normalize_uuid_str("2345"))

    @staticmethod
    def uuid_rx() -> str:
        """Return UUID of characteristic that provides notification/read property."""
        return BMS.normalize_db_uuid_str("0002")

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        return BMS.normalize_db_uuid_str("0001")

    # async def _fetch_device_info(self) -> BMSInfo:
    #     """Fetch the device information via BLE."""
    #     return BMSInfo(
    #         default_manufacturer="Dummy manufacturer", default_model="Dummy BMS"
    #     )  # TODO: implement query code or remove function to query service 0x180A

    # @staticmethod
    # def _raw_values() -> frozenset[BMSValue]:
    #     return frozenset({"runtime"})  # never calculate, e.g. runtime

    @staticmethod
    def normalize_db_uuid_str(uuid: str) -> str:
        """Normalize a Dometic Büttner characteristics UUID."""
        assert len(uuid) == 4
        return f"0000{uuid}-0000-1000-8000-008025000000"

    async def _alive_loop(self) -> None:
        """Continuously poll the module so it keeps streaming."""
        try:
            while True:
                await asyncio.sleep(BMS._ALIVE_INTERVAL)
                async with self._op_lock:
                    await self._await_msg(b"APP+NET", wait_for_notify=False)
                    await self._await_msg(
                        self._ka_resp.to_bytes(1),
                        BMS.normalize_db_uuid_str("0003"),
                        False,
                    )
                    self._ka_resp ^= 0x20
        except asyncio.CancelledError:
            return
        except Exception as exc:  # noqa: BLE001 - keep-alive must not crash the loop
            self._log.debug("alive loop stopped (%s)", type(exc).__name__)

    async def _subscribe_and_wait(self, char_uuid, event: asyncio.Event) -> None:
        self._log.debug("Subscribing to notify characteristic %s", char_uuid)
        try:
            await self._client.start_notify(char_uuid, self._keep_alive_handler)
        except BleakError as ex:
            self._log.debug(
                "Could not subscribe to notify characteristic %s: %s", char_uuid, ex
            )
        event.clear()
        await asyncio.wait_for(event.wait(), timeout=BMS.TIMEOUT)

    async def _init_connection(
        self, char_notify: BleakGATTCharacteristic | int | str | None = None
    ) -> None:
        self._ka_resp = 0xFF

        await self._subscribe_and_wait(BMS._NotifyChars.ch_c.value, self._ch_c_event)
        await self._subscribe_and_wait(BMS._NotifyChars.ch_b.value, self._ch_b_event)

        await super()._init_connection(char_notify)

        self._exp_reply = b"MST+AEN"
        await self._await_msg(
            b"APP+AEN"
            + (f"={self._cfg.secret}".encode("ASCII") if self._cfg.secret else b""),
            wait_for_notify=True,
        )

        self._exp_reply = b"MST+NET="
        await self._await_msg(b"APP+NET", wait_for_notify=True)
        self._msg_event.clear()

        if self._alive_task is None or self._alive_task.done():
            self._alive_task = asyncio.create_task(
                self._alive_loop(), name="BMS keep-alive"
            )

    async def _disconnect(self, reset: bool) -> None:
        if self._alive_task:
            self._alive_task.cancel()
        return await super()._disconnect(reset)

    async def _keep_alive_handler(
        self, sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        self._log.debug("RX BLE data (UUID=%s): %s", sender.uuid[BMS._UUID_SLC], data)

        if not len(data):
            self._log.debug("empty notification")
            return

        if sender.uuid == BMS._NotifyChars.ch_b.value:
            await self._await_msg(
                self._ka_resp.to_bytes(1), BMS.normalize_db_uuid_str("0003"), False
            )
            self._ka_resp ^= 0x20
            self._ch_b_event.set()
            return

        if sender.uuid == BMS._NotifyChars.ch_c.value:
            await self._await_msg(bytes(data), BMS.normalize_db_uuid_str("0009"), False)
            self._ch_c_event.set()
            return

        self._log.debug("unknown notification source")
        return

    async def _notification_handler(
        self, sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        self._log.debug("RX BLE data (UUID=%s): %s", sender.uuid[BMS._UUID_SLC], data)

        if data == b"+++":
            self._log.debug("received disconnect from BMS")
            await self.disconnect()
            return

        if self._exp_reply and bytes(data).startswith(self._exp_reply):
            self._exp_reply = b""
            self._msg_event.set()
            return

        if not data.startswith(BMS._HEAD):
            self._log.debug("unknown SOF (%s)", data[:2].hex(" "))
            return

        if len(data) != BMS._FRAME_LEN:
            self._log.debug(
                "incorrect frame length %d != %d", len(data), BMS._FRAME_LEN
            )
            return

        self._data_final.setdefault(data[2], {})[data[3]] = bytes(data)
        if self._data_final and all(
            BMS._CMDS.issubset(data.keys()) for data in self._data_final.values()
        ):
            self._msg_event.set()

    @staticmethod
    def _cellV(
        data: dict[int, bytes],
        *,
        cells: int,
    ) -> list[float]:
        """Return cell voltages from status message."""
        voltages: list[float] = []
        for i in range(int(cells // 2)):
            voltages.extend(BMS._cell_voltages(data[0x56 + i], cells=2, start=4))
        return voltages

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""

        if not self._msg_event.is_set():
            self._log.debug("requesting data update")
            self._data_final.clear()
            self._exp_reply = b"MST+DCO="
            await self._await_msg(b"APP+RDN=1")

        await asyncio.wait_for(self._wait_event(), timeout=BMS.TIMEOUT)
        result: BMSSample = self._decode_data(
            BMS._FIELDS, next(iter(self._data_final.values()))
        )
        result["cell_voltages"] = BMS._cellV(
            next(iter(self._data_final.values())), cells=4
        )

        self._data_final.clear()
        return result
