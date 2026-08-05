"""Module to support PowerXtreme BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSInfo, BMSSample, MatcherPattern
from aiobmsble.bms.topband_bms import BMS as TopbandBMS


class BMS(TopbandBMS):
    """PowerXtreme BMS implementation."""

    INFO: BMSInfo = {
        "default_manufacturer": "PowerXtreme",
        "default_model": "smart BMS",
    }
    _ctrl_proto: bool = False  # parse control protocol

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
        await self._await_msg(b"<N:NA>")
        bms_info["serial_number"] = str(self._msg[2:])

        return bms_info

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        if self._ctrl_proto and len(data) >= 3 and data[0] == 0x3C and data[-1] == 0x3E:
            self._msg = bytes(data[1:-1])
            self._ctrl_proto = False
            self._msg_event.set()
            return
        super()._notification_handler(_sender, data)

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""

        await self._await_msg(b"<B:ST>")

        return await super()._async_update()
