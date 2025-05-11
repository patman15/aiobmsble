"""Example function for package usage."""

import asyncio
import logging
from types import ModuleType

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from bleak.exc import BleakError

from aiobmsble import BMSsample
from aiobmsble.bms import ogt_bms
from aiobmsble.utils import bms_supported

bms_plugins: list[ModuleType] = [ogt_bms]

logging.basicConfig(
    format="%(levelname)s: %(message)s",
    level=logging.INFO,
)
logger: logging.Logger = logging.getLogger(__name__)

logger.info(
    "loaded BMS types: %s", [key.__name__.rsplit(".", 1)[-1] for key in bms_plugins]
)


async def detect_bms() -> None:
    """Query a Bluetooth device based on the provided arguments."""

    logger.info("starting scan...")
    scan_result: dict[str, tuple[BLEDevice, AdvertisementData]] = (
        await BleakScanner.discover(return_adv=True)
    )
    logger.info("%i BT devices in range.", len(scan_result))

    for ble_dev, advertisement in scan_result.values():
        logger.info(
            "%s\nBT device '%s' (%s)\n\t%s",
            "-" * 72,
            ble_dev.name,
            ble_dev.address,
            repr(advertisement).replace(", ", ",\n\t"),
        )
        for bms_module in bms_plugins:
            if bms_supported(bms_module.BMS, advertisement):
                logger.info(
                    "Found matching BMS type: %s",
                    bms_module.__name__.rsplit(".", maxsplit=1)[-1],
                )
                bms = bms_module.BMS(ble_device=ble_dev, reconnect=True)
                try:
                    logger.info("Updating BMS data...")
                    data: BMSsample = await bms.async_update()
                    logger.info("BMS data: %s", repr(data).replace(", ", ",\n\t"))
                except BleakError as ex:
                    logger.error("Failed to update BMS: %s", ex)

    logger.info("done.")


def main() -> None:
    """Entry point for the script to run the BMS detection."""
    asyncio.run(detect_bms())


if __name__ == "__main__":
    main()
