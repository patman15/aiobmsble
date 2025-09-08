"""Example of using the aiobmsble library to find a BLE device by name and print its sensor data.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

import asyncio
import logging
from typing import Final

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError

from aiobmsble import BMSsample
from aiobmsble.bms.dummy_bms import BMS  # TODO: use the right BMS class for your device

NAME: Final[str] = "BT Device Name"  # TODO: replace with the name of your BLE device

# Configure logging
logging.basicConfig(level=logging.INFO)
logger: logging.Logger = logging.getLogger(__name__)


async def main(dev_name) -> None:
    """Find a BLE device by name and update its sensor data."""

    device: BLEDevice | None = await BleakScanner.find_device_by_name(dev_name)
    if device is None:
        logger.error("Device '%s' not found.", dev_name)
        return

    logger.info("Found device: %s (%s)", device.name, device.address)
    try:
        async with BMS(ble_device=device) as bms:
            logger.info("Updating BMS data...")
            data: BMSsample = await bms.async_update()
            logger.info("BMS data: %s", repr(data).replace(", ", ",\n\t"))
    except BleakError as ex:
        logger.error("Failed to update BMS: %s", type(ex).__name__)


if __name__ == "__main__":
    asyncio.run(main(NAME))  # pragma: no cover
