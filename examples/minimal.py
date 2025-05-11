"""Example of using the aiobmsble library to find a BLE device by name and print its senosr data."""

import asyncio
import logging
from typing import Final

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError

from aiobmsble import BMSsample
from aiobmsble.bms.ogt_bms import BMS  # use the right BMS class for your device

NAME: Final[str] = "BT Device Name"  # Replace with the name of your BLE device

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main(dev_name) -> None:
    """Find a BLE device by name and update its sensor data."""

    device: BLEDevice | None = await BleakScanner.find_device_by_name(dev_name)
    if device is None:
        logger.error("Device '%s' not found.", dev_name)
        return

    logger.info("Found device: %s (%s)", device.name, device.address)
    bms = BMS(ble_device=device, reconnect=True)
    try:
        logger.info("Updating BMS data...")
        data: BMSsample = await bms.async_update()
        logger.info("BMS data: %s", repr(data).replace(", ", ",\n\t"))
    except BleakError as ex:
        logger.error("Failed to update BMS: %s", ex)


asyncio.run(main(NAME))
