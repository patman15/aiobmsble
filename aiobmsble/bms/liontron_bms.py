"""Module to support Liontron smart BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic

from aiobmsble import BMSInfo, MatcherPattern
from aiobmsble.bms.jbd_bms import BMS as JbdBMS


class BMS(JbdBMS):
    """Liontron smart BMS class implementation."""

    INFO: BMSInfo = {"manufacturer": "Liontron", "model": "smart BMS"}
    _UNLOCK_CMDS: Final[tuple[bytes, ...]] = (
        bytes.fromhex("FF AA 23 00 23"),
        bytes.fromhex("FF AA 03 00 03"),
    )

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            MatcherPattern(oui=oui, service_uuid=BMS.uuid_services()[0], connectable=True)
            for oui in ("A4:C1:38",)  # FIXME! align with JBD
        ]

    async def _init_connection(
        self, char_notify: BleakGATTCharacteristic | int | str | None = None
    ) -> None:
        """Unlock the BMS, falling back to the alternative command if no query reply."""
        await super(JbdBMS, self)._init_connection(char_notify)
        for cmd in self._UNLOCK_CMDS:
            await self._await_msg(cmd, wait_for_notify=False)
            self._frame.clear()  # discard unlock acknowledgement
            try:
                await self._await_cmd_resp(0x03)
            except TimeoutError:
                self._log.debug("no query reply after unlock command %s", cmd.hex(" "))
                continue
            return
        raise TimeoutError("Liontron BMS did not respond to unlock commands.")
