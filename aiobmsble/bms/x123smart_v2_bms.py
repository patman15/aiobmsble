r"""Module to support 123\\SmartBMS (123electric) generation 2.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSInfo, MatcherPattern
from aiobmsble.bms.x123smart_bms import BMS as x123SmartBMS


class BMS(x123SmartBMS):
    r"""123\\SmartBMS gen2 implementation."""

    INFO: BMSInfo = {"manufacturer": "123electric", "model": "123\\SmartBMS", "model_id": "gen 2"}
    _NOTIFY_CHAR: Final[str] = "fdd6b4d3-046d-4330-bdec-1fd0c90cb43b"

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            MatcherPattern(
                oui="EC:FE:7E",
                service_uuid=BMS.uuid_services()[0],
                connectable=True,
            )
        ]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return (normalize_uuid_str("da2b84f1-6279-48de-bdc0-afbea0226079"),)

    @staticmethod
    def uuid_rx() -> str:
        """Return UUID of characteristic that provides notifications (TX of the module)."""
        return "18cda784-4bd3-4370-85bb-bfed91ec86af"

    @staticmethod
    def uuid_tx() -> str:
        """Return UUID of characteristic that accepts writes (RX of the module)."""
        return "bf03260c-7205-4c25-af43-93b1c299d159"

    async def _init_connection(
        self, char_notify: BleakGATTCharacteristic | int | str | None = None
    ) -> None:
        await super()._init_connection(char_notify)
        # subscribe to second notify characteristic
        await self._client.start_notify(
            BMS._NOTIFY_CHAR, getattr(self, "_notification_handler")
        )

    def _notification_handler(self, sender: BleakGATTCharacteristic, data: bytearray) -> None:
        self._log.debug("sender: %s", sender)
        super()._notification_handler(sender, data)
