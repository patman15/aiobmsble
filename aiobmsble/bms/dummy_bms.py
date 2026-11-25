"""Module to support Dummy BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

import logging

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSConfig, BMSInfo, BMSSample
from aiobmsble.basebms import BaseBMS
from aiobmsble.plugin import MatcherPattern


class BMS(BaseBMS):
    """Dummy BMS implementation."""

    INFO: BMSInfo = {  # TODO: fill correct manufacturer/model
        "manufacturer": "Dummy Manufacturer",
        "model": "dummy model",
    }
    # _HEAD: Final[bytes] = b"\x55"  # beginning of frame
    # _TAIL: Final[bytes] = b"\xAA"  # end of frame
    # _FRAME_LEN: Final[int] = 10  # length of frame, including SOF and checksum
    # _FIELDS: tuple[BMSDp[BMSValue], ...] = () # TODO: define BMS sensor decoder definitions
    # _LIMIT_FIELDS: Final[tuple[LimitDp, ...]] = () # TODO: define BMS limits
    # _PROBLEMS: tuple[BMSPrbDef, ...] = () # TODO: add problem code decoder definitions
    # _SKIP_INFO_CHARS: bool = False  # set True to skip information from BT default chars for BMSInfo()
    #
    # ACCEPT_SECRET: bool = True  # if the BMS accepts a secret for authentication
    # _ALIVE_INTERVAL: float | None = None  # keep-alive period in seconds; None disables

    def __init__(
        self,
        ble_device: BLEDevice,
        config: BMSConfig | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        """Initialize private BMS members."""
        super().__init__(ble_device, config, logger)

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Return the advertisement patterns used to identify the BMS."""
        return [{"local_name": "dummy", "connectable": True}]  # TODO: define matcher

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return UUIDs of services required by BMS."""
        return (normalize_uuid_str("0000"),)  # TODO: change service UUID here!

    @staticmethod
    def uuid_rx() -> str:
        """Return the UUID (16/32/128-bit) of the characteristic providing notifications."""
        return "0000"  # TODO: change RX characteristic UUID here!

    @staticmethod
    def uuid_tx() -> str:
        """Return the UUID (16/32/128-bit) of the characteristic used to send commands."""
        return "0000"  # TODO: change TX characteristic UUID here!

    async def _fetch_device_info(self) -> BMSInfo:
        """Fetch the device information via BLE."""
        return BMSInfo(
            manufacturer="Dummy Manufacturer", model="dummy model"
        )  # TODO: implement query code or remove function to query service 0x180A

    # @staticmethod
    # def _raw_values() -> frozenset[BMSValue]:
    #     return frozenset({"runtime"})  # never calculate, e.g. runtime

    # async def _fetch_limits(self) -> BMSLimits:
    #     """Fetch the BMS limits via BLE."""
    #     TODO: query from BMS and use _decode_limits
    #     return {Limit.CELL_OVP: Threshold(trip=3.65, release=3.5)}

    # async def _alive(self) -> None:
    #     """Override to run periodic actions while `_ALIVE_INTERVAL` is set."""
    #     raise NotImplementedError

    def _notification_handler(self, sender: BleakGATTCharacteristic, data: bytearray) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        # self._log.debug("RX BLE data: %s", data)

        # *******************************************************
        # TODO: Do things like checking correctness of frame here
        # and store it into a instance variable, e.g. self._frame
        # in case the frame is fragmented.
        # Below are some examples of how to do it
        # Have a look at the BMS base class for function to use,
        # take a look at other implementations for more  details
        # *******************************************************

        # if not data.startswith(BMS._HEAD):
        #     self._log.debug("incorrect SOF")
        #     return

        # if not self._check_integrity(self._frame, crc_sum, slice(None, -1), slice(-1, None)):
        #     return

        # Do an immutable copy of the assembled (data) frame and notify _await_msg()
        # self._msg = bytes(self._frame)
        # self._msg_event.set()

    async def _update(self) -> BMSSample:
        """Update battery status information."""
        self._log.debug("replace with command to UUID %s", BMS.uuid_tx())
        # await self._await_msg(b"<some_command>")

        # TODO: parse data from self._msg here

        return {
            "battery_level": 73,
            "current": 1.5,
            "voltage": 12.0,
        }  # TODO: fixed values, replace parsed data
