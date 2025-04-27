"""Example function for package usage."""

import asyncio
import importlib
import logging
import pkgutil
import re
from fnmatch import translate
from types import ModuleType

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from bleak.exc import BleakError

import aiobmsble.bms
from aiobmsble.basebms import BMSsample

logging.basicConfig(
    format="%(levelname)s: %(message)s",
    level=logging.INFO,
)
logger: logging.Logger = logging.getLogger(__name__)


def adv_matches(
    matcher: dict,
    adv_data: AdvertisementData,
) -> bool:
    """Check if a Bleak advertisement data matches the matcher dictionary."""

    if (
        service_uuid := matcher.get("service_uuid")
    ) and service_uuid not in adv_data.service_uuids:
        return False

    if (
        service_data_uuid := matcher.get("service_data_uuid")
    ) and service_data_uuid not in adv_data.service_data:
        return False

    if (manufacturer_id := matcher.get("manufacturer_id")) is not None:
        if manufacturer_id not in adv_data.manufacturer_data:
            return False

        if manufacturer_data_start := matcher.get("manufacturer_data_start"):
            if not adv_data.manufacturer_data[manufacturer_id].startswith(
                bytes(manufacturer_data_start)
            ):
                return False

    if (local_name := matcher.get("local_name")) and not re.compile(
        translate(local_name)
    ).match(adv_data.local_name or ""):
        return False

    return True


async def query() -> None:
    """Queries a Bluetooth device based on the provided arguments."""

    bms_plugins: dict[str, ModuleType] = {
        name: importlib.import_module(name)
        for finder, name, ispkg in pkgutil.iter_modules(
            aiobmsble.bms.__path__, "aiobmsble.bms."
        )
        if not (ispkg or name.split(".")[-1].startswith("dummy_"))
    }
    logger.debug(
        "loaded BMS types: %s", [key.split(".")[-1] for key in bms_plugins.keys()]
    )

    logger.info("starting scan...")
    scan_result: dict[str, tuple[BLEDevice, AdvertisementData]] = (
        await BleakScanner.discover(return_adv=True)
    )

    for ble_dev, advertisement in scan_result.values():
        logger.debug(
            "%s\nBT device '%s' (%s)\n\t%s",
            "-" * 72,
            ble_dev.name,
            ble_dev.address,
            repr(advertisement).replace(",", ",\n\t"),
        )
        for bms_type, bms_module in bms_plugins.items():
            if any(
                adv_matches(matcher, advertisement)
                for matcher in bms_module.BMS.matcher_dict_list()
            ):
                logger.info("Found matching BMS type: %s", bms_type)
                bms = bms_module.BMS(ble_device=ble_dev, reconnect=True)
                try:
                    logger.info("Updating BMS data...")
                    data: BMSsample = await bms.async_update()
                    logger.info("BMS data: %s", data)
                except BleakError as ex:
                    logger.error("Failed to update BMS: %s", ex)
            else:
                logger.debug("Device does not match any BMS type.")

    logger.info("done.")


if __name__ == "__main__":
    asyncio.run(query())
