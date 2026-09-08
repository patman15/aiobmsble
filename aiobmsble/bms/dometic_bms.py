"""Module to support Dometic BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

import asyncio
from enum import StrEnum
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str
from bleak_retry_connector import BLEAK_TIMEOUT

from aiobmsble import (
    BMSConfig,
    BMSDp,
    BMSInfo,
    BMSSample,
    MatcherPattern,
    TempSensor as TS,
)
from aiobmsble.basebms import BaseBMS


class BMS(BaseBMS):
    """Dometic BMS implementation."""

    INFO: BMSInfo = {
        "default_manufacturer": "Dometic",
        "default_model": "Büttner BMS",
    }

    class _NotifyChars(StrEnum):
        ch_a_tx = "00000001-0000-1000-8000-008025000000"
        ch_a_rx = "00000002-0000-1000-8000-008025000000"
        ch_b_tx = "00000003-0000-1000-8000-008025000000"
        ch_b_rx = "00000004-0000-1000-8000-008025000000"
        ch_c_tx = "00000009-0000-1000-8000-008025000000"
        ch_c_rx = "0000000a-0000-1000-8000-008025000000"

    _HEAD: Final[bytes] = b"\x23\x85"
    _FRAME_LEN: Final[int] = 8
    ALIVE_INTERVAL: float | None = 24.0  # seconds
    _GATHER_TIMEOUT: Final[float] = BLEAK_TIMEOUT
    _UUID_SLC: Final[slice] = slice(4, 8)
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("voltage", 4, 2, False, lambda x: x / 100, 0x2),
        BMSDp(
            "current",
            6,
            2,
            False,
            lambda x: (x if x <= 32767 else 32767 - x) / 100,
            0x2,
        ),
        BMSDp("design_capacity", 4, 4, False, idx=0x7),
        BMSDp("battery_level", 4, 1, False, idx=0xB),
        BMSDp("temp_values", 4, 2, False, lambda x: [TS((x - 500) / 10)], 0x0C),
        BMSDp("cycle_capacity", 4, 2, False, idx=0x36),
        BMSDp("battery_health", 4, 1, False, idx=0xE),
    )
    _CMDS: Final[set[int]] = {field.idx for field in _FIELDS if field.idx != 0x7} | {
        0x56,
        0x57,
    }  # do not wait for design capacity (won't change anyway)

    accept_secret: bool = True

    def __init__(
        self,
        ble_device: BLEDevice,
        config: BMSConfig | None = None,
        logger_name: str = "",
    ) -> None:
        """Initialize BMS."""
        super().__init__(ble_device, config, logger_name)
        self._data_final: dict[int, dict[int, bytes]] = {}
        self._exp_reply: bytes = b""
        self._disconnect_event: asyncio.Event = asyncio.Event()
        self._ch_b_event: asyncio.Event = asyncio.Event()
        self._ch_c_event: asyncio.Event = asyncio.Event()
        self._ka_resp: int = 0xFF
        self._design_cap: dict[int, bytes] = {}

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
        return BMS._NotifyChars.ch_a_rx

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        return BMS._NotifyChars.ch_a_tx

    async def _alive(self) -> None:
        """Continuously poll the module so it keeps streaming."""
        await self._await_msg(b"APP+NET", wait_for_notify=False)
        await self._await_msg(
            self._ka_resp.to_bytes(1),
            BMS._NotifyChars.ch_b_tx,
            False,
        )
        self._ka_resp ^= 0x20

    async def _subscribe_and_wait(
        self, char_uuid: _NotifyChars, event: asyncio.Event
    ) -> None:
        self._log.debug("Subscribing to notify characteristic %s", char_uuid)

        await self._client.start_notify(char_uuid, self._keep_alive_handler)
        event.clear()
        await asyncio.wait_for(event.wait(), timeout=BMS.TIMEOUT)

    async def _init_connection(
        self, char_notify: BleakGATTCharacteristic | int | str | None = None
    ) -> None:
        self._ka_resp = 0xFF
        self._disconnect_event.clear()

        await self._subscribe_and_wait(BMS._NotifyChars.ch_c_rx, self._ch_c_event)
        await self._subscribe_and_wait(BMS._NotifyChars.ch_b_rx, self._ch_b_event)

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

    async def _keep_alive_handler(
        self, sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        self._log.debug("RX BLE data (UUID=%s): %s", sender.uuid[BMS._UUID_SLC], data)

        if not len(data):
            self._log.debug("empty notification")
            return

        match sender.uuid:
            case BMS._NotifyChars.ch_b_rx:
                await self._await_msg(
                    self._ka_resp.to_bytes(1), BMS._NotifyChars.ch_b_tx, False
                )
                self._ka_resp ^= 0x20
                self._ch_b_event.set()
            case BMS._NotifyChars.ch_c_rx:
                await self._await_msg(bytes(data), BMS._NotifyChars.ch_c_tx, False)
                self._ch_c_event.set()
            case _:
                self._log.debug("unknown notification sender")
        return

    async def _notification_handler(
        self, sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        self._log.debug("RX BLE data (UUID=%s): %s", sender.uuid[BMS._UUID_SLC], data)

        if data == b"+++":
            self._log.debug("received disconnect from BMS")
            self._disconnect_event.set()
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

        if self._disconnect_event.is_set():
            await super().disconnect()
            if not self._msg_event.is_set():
                self._data_final.clear()
                raise ValueError("BMS data incomplete")

        if not self._msg_event.is_set():
            self._log.debug("requesting data update")
            self._data_final.clear()
            self._exp_reply = b"MST+DCO="
            await self._await_msg(b"APP+RDN=1")
            self._msg_event.clear()

        await asyncio.wait_for(self._wait_event(), timeout=BMS._GATHER_TIMEOUT)

        # restore design capacity if not received
        for dev, data in self._data_final.items():
            if (cap_msg := data.get(0x7) or self._design_cap.get(dev)) is None:
                raise ValueError("BMS data incomplete.")
            self._design_cap[dev] = data[0x7] = cap_msg

        result: BMSSample = BMSSample(pack_count=len(self._data_final))
        for pack in sorted(self._data_final):
            pack_result: BMSSample = self._decode_data(
                BMS._FIELDS, self._data_final[pack]
            )
            pack_result["cell_voltages"] = BMS._cellV(self._data_final[pack], cells=4)
            result.setdefault("packs", []).append(pack_result)

        self._data_final.clear()
        self._msg_event.clear()
        return result
