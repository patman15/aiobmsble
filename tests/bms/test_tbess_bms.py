"""Test the V-TAC TBESS BMS implementation."""

import asyncio
from collections.abc import Awaitable, Callable
import contextlib
from typing import Final
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic

from aiobmsble import BMSConfig, BMSSample, Limit, PackSample, TempSensor as TS, Threshold
from aiobmsble.bms.tbess_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import BMSBasicTests

BT_FRAME_SIZE: Final[int] = 127

_PROTO_DEFS: Final[dict[str, bytes]] = {
    "sum": ( # 2 × V-TAC VT-14033, 28.66 kWh / 560 Ah, 51.2 V
        b"\xef\x01\x73\x46\x38\x35\x42\x31\x42\x36\x32\x33\x33\x42\x43\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x55\x00\x02\x02\x02\x14\xaa\xff\x5a\x15\xe0\x16\x57\x0f\xbe\x1b\x86\x27\x10\x08\x48"
        b"\x16\xd0\x0b\x54\x11\xd0\x0c\xed\x0c\xe8\x01\x0b\x02\x0d\x0b\x94\x0b\x8d\x01\x02\x02\x04"
        b"\x0b\xa2\x0b\x9d\x01\x01\x02\x01\x0b\xa9\x0b\xa8\x02\x01\x01\x01\x00\x1b\x00\x1a\xc0\x00"
        b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x30\xfb\x00\x00\x30\x00\xec"
        b"\x84\x16"
    ),
    "pack1": (
        b"\xef\x01\xdb\x35\x31\x34\x31\x31\x30\x39\x32\x32\x36\x30\x35\x30\x31\x30\x30\x35\x38\x34"
        b"\x00\x61\x00\x14\xac\xfd\x7d\x02\xbb\x4e\x46\x10\x0c\xec\x0c\xeb\x0c\xec\x0c\xec\x0c\xeb"
        b"\x0c\xed\x0c\xea\x0c\xec\x0c\xeb\x0c\xec\x0c\xee\x0c\xec\x0c\xea\x0c\xec\x0c\xec\x0c\xeb"
        b"\x04\x00\xe7\x00\xe9\x00\xe7\x00\xe7\x00\xfd\x00\xf7\x00\x1b\x18\x6f\x18\xd6\x07\x4d\x00"
        b"\x00\x00\x00\x03\xe8\x6f\xf2\x6d\x60\x0c\xee\x0b\x0c\xea\x07\x00\x04\x00\xe9\x02\x00\xe7"
        b"\x01\x00\x02\x00\x00\x18\xd6\x00\x00\x18\x6f\xd8\x04\x16"
    ),
    "pack2": (
        b"\xef\x02\xdb\x35\x31\x34\x31\x31\x30\x39\x32\x32\x36\x30\x35\x30\x31\x30\x31\x32\x33\x32"
        b"\x00\x61\x00\x14\xac\xfc\xf4\x02\xc4\x4e\xfd\x10\x0c\xec\x0c\xea\x0c\xed\x0c\xed\x0c\xea"
        b"\x0c\xec\x0c\xea\x0c\xed\x0c\xea\x0c\xeb\x0c\xee\x0c\xec\x0c\xea\x0c\xec\x0c\xed\x0c\xea"
        b"\x04\x00\xe5\x00\xe6\x00\xe4\x00\xe2\x00\xfe\x00\xf2\x00\x1a\x17\x91\x18\x25\x06\x13\x00"
        b"\x00\x00\x00\x03\xe8\x6f\x7d\x6d\x60\x0c\xee\x0b\x0c\xea\x02\x00\x04\x00\xe6\x02\x00\xe2"
        b"\x04\x00\x04\x00\x00\x18\x25\x00\x00\x17\x91\xd8\xc2\x16"
    ),
    "config": (
        b"\xef\x01\xdc\x35\x31\x34\x31\x31\x30\x39\x32\x32\x36\x30\x35\x30\x31\x30\x30\x35\x38\x34"
        b"\x00\x2d\x00\x10\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x04\x00"
        b"\x00\x00\x00\x00\x00\x00\x06\x40\x00\x00\x00\x00\x02\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\xfa\xd4\x16"
    ),
    "info": (
        b"\xef\x01\xd0\x35\x31\x34\x31\x31\x30\x39\x32\x32\x36\x30\x35\x30\x31\x30\x30\x35\x38\x34"
        b"\x00\x88\x00\x6d\x60\x34\x35\x30\x33\x30\x30\x38\x39\x37\x00\x00\x00\x35\x31\x34\x31\x31"
        b"\x30\x39\x31\x20\x32\x36\x30\x35\x30\x37\x30\x30\x36\x37\x00\x35\x31\x34\x31\x31\x30\x39"
        b"\x32\x32\x36\x30\x35\x30\x31\x30\x30\x35\x38\x34\x00\x53\x54\x4d\x33\x32\x46\x31\x30\x33"
        b"\x56\x45\x54\x36\x00\x00\x43\x4e\x32\x30\x30\x47\x41\x30\x36\x2d\x34\x38\x32\x30\x30\x2d"
        b"\x31\x30\x41\x00\x2a\x30\x01\x00\x00\x01\x43\x4e\x31\x30\x34\x38\x32\x30\x30\x31\x36\x53"
        b"\x5a\x54\x42\x32\x35\x30\x33\x30\x33\x30\x30\x31\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x00\x00\x00\xe3\xac\x16"
    ),
}

_RESULT_DEFS: Final[BMSSample] = BMSSample(
    pack_count=2,
    voltage=52.9,
    current=-16.6,
    design_capacity=560,
    cycle_charge=403.0,
    battery_level=70.46,
    battery_health=100.0,
    cycles=27,
    total_charge=12288,
    packs=[
        PackSample(
            voltage=52.92,
            current=-6.43,
            battery_level=69.9,
            cycle_charge=2003.8,
            cell_count=16,
            cell_voltages=[
                3.308,
                3.307,
                3.308,
                3.308,
                3.307,
                3.309,
                3.306,
                3.308,
                3.307,
                3.308,
                3.31,
                3.308,
                3.306,
                3.308,
                3.308,
                3.307,
            ],
            temp_sensors=4,
            temp_values=[
                TS(23.1, TS.T.CELL),
                TS(23.3, TS.T.CELL),
                TS(23.1, TS.T.CELL),
                TS(23.1, TS.T.CELL),
                TS(25.3, TS.T.MOSFET),
                TS(24.7, TS.T.AMBIENT),
            ],
            cycles=27,
            battery_health=100.0,
            design_capacity=2800,
            delta_voltage=0.004,
        ),
        PackSample(
            voltage=52.92,
            current=-7.8,
            battery_level=70.8,
            cycle_charge=2022.1,
            cell_count=16,
            cell_voltages=[
                3.308,
                3.306,
                3.309,
                3.309,
                3.306,
                3.308,
                3.306,
                3.309,
                3.306,
                3.307,
                3.31,
                3.308,
                3.306,
                3.308,
                3.309,
                3.306,
            ],
            temp_sensors=4,
            temp_values=[
                TS(22.9, TS.T.CELL),
                TS(23.0, TS.T.CELL),
                TS(22.8, TS.T.CELL),
                TS(22.6, TS.T.CELL),
                TS(25.4, TS.T.MOSFET),
                TS(24.2, TS.T.AMBIENT),
            ],
            cycles=26,
            battery_health=100.0,
            design_capacity=2800,
            delta_voltage=0.004,
        ),
    ],
    cell_voltages=[
        3.308,
        3.307,
        3.308,
        3.308,
        3.307,
        3.309,
        3.306,
        3.308,
        3.307,
        3.308,
        3.31,
        3.308,
        3.306,
        3.308,
        3.308,
        3.307,
        3.308,
        3.306,
        3.309,
        3.309,
        3.306,
        3.308,
        3.306,
        3.309,
        3.306,
        3.307,
        3.31,
        3.308,
        3.306,
        3.308,
        3.309,
        3.306,
    ],
    cell_count=16,
    delta_voltage=0.004,
    battery_charging=False,
    cycle_capacity=21318.7,
    power=-878.14,
    runtime=87397,
    problem=False,
)


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


class MockTBESSBleakClient(MockBleakClient):
    """Emulate the TBESS notification stream with captured frames."""

    _task: asyncio.Task[None] | None = None

    async def _notify(self) -> None:
        """Start notifications and deliver the recorded data stream."""
        assert self._notify_callback is not None
        while True:
            for frame in _PROTO_DEFS.values():
                for notify_data in [
                    frame[i : i + BT_FRAME_SIZE] for i in range(0, len(frame), BT_FRAME_SIZE)
                ]:
                    self._notify_callback("MockTBESSBleakClient", bytearray(notify_data))
                    await asyncio.sleep(0)

    async def start_notify(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        callback: Callable[[BleakGATTCharacteristic, bytearray], None | Awaitable[None]],
        **kwargs,
    ) -> None:
        """Issue write command to GATT."""
        await super().start_notify(char_specifier, callback, **kwargs)

        if char_specifier == "fff1":
            self._task = asyncio.create_task(self._notify(), name="send_loop")
        await asyncio.sleep(0)  # yield control to allow task to start

    async def disconnect(self) -> None:
        """Mock disconnect and wait for send task."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        await super().disconnect()


async def test_update(
    patch_bleak_client,
    keep_alive_fixture: bool,
) -> None:
    """Decode two captured pack frames and update an existing connection."""
    patch_bleak_client(MockTBESSBleakClient)
    bms = BMS(generate_ble_device(), BMSConfig(keep_alive_fixture))

    result: BMSSample = await bms.async_update()
    assert result == _RESULT_DEFS

    assert await bms.async_update() == result
    assert bms.is_connected is keep_alive_fixture
    await bms.disconnect()


async def test_limits(
    patch_bleak_client,
) -> None:
    """Return protection thresholds decoded from the system status frame."""
    patch_bleak_client(MockTBESSBleakClient)
    bms = BMS(generate_ble_device(), BMSConfig())

    limits = await bms.limits()
    assert limits == {
        Limit.PACK_OVP: Threshold(trip=58.4),
        Limit.PACK_UVP: Threshold(trip=45.6),
        Limit.CHARGE_OCP: Threshold(trip=212.0),
        Limit.DISCHARGE_OCP: Threshold(trip=290.0),
    }
    await bms.disconnect()
