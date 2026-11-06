r"""Test the 123\\SmartBMS gen 2 implementation."""

import asyncio

from aiobmsble import BMSConfig
from aiobmsble.bms.x123smart_v2_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.bms.test_x123smart_bms import _RESULT_DEFS, Mock123SmartBleakClient
from tests.test_basebms import BMSBasicTests


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS

async def test_update(patch_bleak_client, keep_alive_fixture: bool) -> None:
    r"""Test 123\\SmartBMS data update."""
    patch_bleak_client(Mock123SmartBleakClient)

    bms = BMS(
        generate_ble_device(),
        BMSConfig(keep_alive_fixture, secret=Mock123SmartBleakClient.SECRET),
    )

    assert await bms.async_update() == _RESULT_DEFS
    await asyncio.sleep(bms.ALIVE_INTERVAL or 0)  # wait for keep-alive ping to be sent
    await bms.async_update()  # second query to cover already-connected path
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()
