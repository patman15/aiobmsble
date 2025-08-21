"""Example function for package usage."""

import argparse
import asyncio
import importlib
import logging
import pkgutil
from types import ModuleType
from typing import Any, Final

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from bleak.exc import BleakError

from aiobmsble import BMSsample
from aiobmsble.utils import bms_supported

logging.basicConfig(
    format="%(levelname)s: %(message)s",
    level=logging.INFO,
)
logger: logging.Logger = logging.getLogger(__name__)


def load_bms_plugins() -> set[ModuleType]:
    """Load all available BMS plugin modules."""
    bms_plugins: set[ModuleType] = {
        importlib.import_module(f"aiobmsble.bms.{module_name}")
        for _, module_name, _ in pkgutil.iter_modules(["aiobmsble/bms"])
    }
    logger.debug(
        "loaded BMS types: %s", [key.__name__.rsplit(".", 1)[-1] for key in bms_plugins]
    )
    return bms_plugins


async def scan_devices() -> dict[str, tuple[BLEDevice, AdvertisementData]]:
    """Scan for BLE devices and return results."""
    logger.info("starting scan...")
    scan_result: dict[str, tuple[BLEDevice, AdvertisementData]] = (
        await BleakScanner.discover(return_adv=True)
    )
    logger.info("%i BT devices in range.", len(scan_result))
    return scan_result


async def detect_bms(loglevel: int) -> None:
    """Query a Bluetooth device based on the provided arguments."""

    bms_plugins: set[ModuleType] = load_bms_plugins()
    scan_result: dict[str, tuple[BLEDevice, AdvertisementData]] = await scan_devices()
    for ble_dev, advertisement in scan_result.values():
        logger.info(
            "%s\nBT device '%s' (%s)\n\t%s",
            "-" * 72,
            ble_dev.name,
            ble_dev.address,
            repr(advertisement).replace(", ", ",\n\t"),
        )
        for bms_module in bms_plugins:
            if not bms_supported(bms_module.BMS, advertisement):
                continue

            logger.info(
                "Found matching BMS type: %s",
                bms_module.__name__.rsplit(".", maxsplit=1)[-1],
            )
            bms: Any = bms_module.BMS(ble_device=ble_dev, reconnect=True)
            logging.getLogger(
                f"{bms_module.__name__.replace('.bms', '')}::{ble_dev.name}:"
                f"{ble_dev.address[-5:].replace(':','')}"
            ).setLevel(loglevel)
            try:
                logger.info("Updating BMS data...")
                data: BMSsample = await bms.async_update()
                logger.info("BMS data: %s", repr(data).replace(", ", ",\n\t"))
            except (BleakError, TimeoutError) as ex:
                logger.error("Failed to update BMS: %s", ex)

    logger.info("done.")


def setup_logging(args: argparse.Namespace) -> int:
    """Configure logging based on command line arguments."""
    loglevel: Final[int] = logging.DEBUG if args.verbose else logging.INFO

    if args.logfile:
        file_handler = logging.FileHandler(args.logfile)
        file_handler.setLevel(loglevel)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(levelname)s: %(message)s")
        )
        logger.addHandler(file_handler)

    logger.setLevel(loglevel)
    return loglevel


def main() -> None:
    """Entry point for the script to run the BMS detection."""
    parser = argparse.ArgumentParser(
        description="Reference script for 'aiobmsble' to show all recognized BMS in range."
    )
    parser.add_argument("-l", "--logfile", type=str, help="Path to the log file")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable debug logging"
    )

    loglevel: Final[int] = setup_logging(parser.parse_args())

    asyncio.run(detect_bms(loglevel))


if __name__ == "__main__":
    main()
