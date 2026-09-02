"""Module to support Daren smart BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

import contextlib
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic

from aiobmsble import BMSDp, BMSInfo, MatcherPattern, TempSensor as TS
from aiobmsble.basebms import b2str, swap32
from aiobmsble.bms.jbd_bms import BMS as JBDBMS


class BMS(JBDBMS):
    """Daren smart BMS class implementation."""

    INFO: BMSInfo = {"default_manufacturer": "Daren", "default_model": "smart BMS"}
    _VALID_CMD: frozenset[int] = frozenset({0x03, 0x04, 0x05, 0x08, 0xFF})
    _MAX_TEMP_COUNT: Final[int] = 4
    _TEMP_TYPES: tuple[TS.T, ...] = (TS.T.CELL,) * 4 + (TS.T.MOSFET, TS.T.AMBIENT)
    _FIELDS: tuple[BMSDp, ...] = (
        BMSDp("voltage", 4, 2, False, lambda x: x / 100),
        BMSDp("current", 6, 2, True, lambda x: x / 100),
        BMSDp("cycle_charge", 8, 2, False, lambda x: x / 100),
        BMSDp("design_capacity", 10, 2, False, lambda x: x // 100),
        BMSDp("cycles", 12, 2, False),
        BMSDp("balancer", 16, 4, False, swap32),
        BMSDp("problem_code", 20, 2, False),
        BMSDp("battery_level", 23, 1, False),
        BMSDp("chrg_mosfet", 24, 1, False, lambda x: bool(x & 0x1)),
        BMSDp("dischrg_mosfet", 24, 1, False, lambda x: bool(x & 0x2)),
        BMSDp("cell_count", 25, 1, False, lambda x: min(x, BMS._MAX_CELL_COUNT)),
        BMSDp("temp_sensors", 26, 1, False, lambda x: min(x, BMS._MAX_TEMP_COUNT) + 2),
        # extended frame fields, overwrite previous fields
        BMSDp("battery_health", 39, 1, False),
        BMSDp("cycle_charge", 43, 2, False, lambda x: x / 10),
        BMSDp("design_capacity", 45, 2, False, lambda x: x / 10),
        BMSDp("current", 49, 2, True, lambda x: x / 10),
    )

    accept_secret: bool = True

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            MatcherPattern(
                local_name=pattern,
                service_uuid=BMS.uuid_services()[0],
                connectable=True,
            )
            for pattern in ("DWF*",)  # Daren BMS, Docan battery
        ]

    async def _fetch_device_info(self) -> BMSInfo:
        """Fetch the device information via BLE."""
        await self._await_cmd_resp(0x03)
        result: BMSInfo = {"sw_version": f"{self._msg[22] >> 4}.{self._msg[22] & 0xF}"}
        try:
            await self._await_cmd_resp(0x05)
            result["hw_version"] = b2str(self._msg[4 : self._msg[3] + 4])
        except TimeoutError:
            pass
        return result

    async def _init_connection(
        self, char_notify: BleakGATTCharacteristic | int | str | None = None
    ) -> None:
        if self._cfg.secret:
            await self._client.start_notify(BMS.uuid_rx(), self._notify_init_handler)
            data: Final[bytes] = self._cfg.secret.encode(encoding="ASCII")
            try:
                await self._await_msg(
                    BMS._HEAD_INIT
                    + b"\x15"
                    + len(self._cfg.secret).to_bytes(1)
                    + data
                    + ((0x15 + len(self._cfg.secret) + sum(data)) & 0xFF).to_bytes(1)
                )
            except TimeoutError:
                self._log.warning("Failed to initialize connection with secret")
                raise
            if self._msg[4] != 0x00:
                self._log.warning("incorrect secret")
                raise PermissionError("Incorrect secret.")

            await self._client.stop_notify(BMS.uuid_rx())

        self._frame.clear()
        self._msg_event.clear()

        self._log.debug(
            "start notify on RX characteristic %s", str(char_notify or self.uuid_rx())
        )
        await self._client.start_notify(
            char_notify or self.uuid_rx(), getattr(self, "_notification_handler")
        )
        with contextlib.suppress(TimeoutError):
            await self._await_cmd_resp(0xFF, b"\xff\xff\xff\xff\xff\xff")
            await self._await_cmd_resp(0x08)
