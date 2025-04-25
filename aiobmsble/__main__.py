"""Example function for package usage."""

import argparse
import asyncio
import logging

from bleak import BleakScanner
from bleak.backends.device import BLEDevice

from aiobmsble.bms import ogt_bms

logger: logging.Logger = logging.getLogger(__name__)


async def query(query_args: argparse.Namespace) -> None:
    """Queries a Bluetooth device based on the provided arguments."""
    logger.info("starting scan...")

    dev: BLEDevice | None = (
        await BleakScanner.find_device_by_address(query_args.address)
        if query_args.address
        else await BleakScanner.find_device_by_name(query_args.name)
    )
    if dev is None:
        logger.error("specified device not found!")
        raise IOError

    logger.info("querying to device...")

    bms = ogt_bms.BMS(dev, reconnect=True)
    logger.info("%s", await bms.async_update())

    logger.info("done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    dg: argparse._MutuallyExclusiveGroup = parser.add_mutually_exclusive_group(
        required=True
    )

    dg.add_argument(
        "--name",
        metavar="<name>",
        help="the name of the bluetooth device to connect to",
    )
    dg.add_argument(
        "--address",
        metavar="<address>",
        help="the address of the bluetooth device to connect to",
    )

    parsed_args: argparse.Namespace = parser.parse_args()

    asyncio.run(query(parsed_args))
