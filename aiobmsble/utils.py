"""Utilitiy/Support functions for aiobmsble."""

from fnmatch import translate
from functools import lru_cache
import importlib
import pkgutil
import re
from types import ModuleType

from bleak.backends.scanner import AdvertisementData

from aiobmsble import AdvertisementPattern
from aiobmsble.basebms import BaseBMS


def advertisement_matches(
    matcher: AdvertisementPattern,
    adv_data: AdvertisementData,
) -> bool:
    """Determine whether the given advertisement data matches the specified pattern.

    Args:
        matcher (AdvertisementPattern): A dictionary containing the matching criteria.
            Possible keys include:
            - "service_uuid" (str): A specific service 128-bit UUID to match.
            - "service_data_uuid" (str): A specific service data UUID to match.
            - "manufacturer_id" (int): A manufacturer ID to match.
            - "manufacturer_data_start" (bytes): A byte sequence that the data should start with.
            - "local_name" (str): A pattern supporting Unix shell-style wildcards to match

        adv_data (AdvertisementData): An object containing the advertisement data to be checked.

    Returns:
        bool: True if the advertisement data matches the specified pattern, False otherwise.

    """
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

    return not (
        (local_name := matcher.get("local_name"))
        and not re.compile(translate(local_name)).match(adv_data.local_name or "")
    )


@lru_cache
def load_bms_plugins() -> set[ModuleType]:
    """
    Discover and load all available Battery Management System (BMS) plugin modules.

    This function scans the 'aiobmsble/bms' directory for all Python modules,
    dynamically imports each discovered module, and returns a set containing
    the imported module objects.

    Returns:
        set[ModuleType]: A set of imported BMS plugin modules.

    Raises:
        ImportError: If a module cannot be imported.
        OSError: If the plugin directory cannot be accessed.

    """
    return {
        importlib.import_module(f"aiobmsble.bms.{module_name}")
        for _, module_name, _ in pkgutil.iter_modules(["aiobmsble/bms"])
    }


def bms_supported(bms: BaseBMS, adv_data: AdvertisementData) -> bool:
    """Determine if the given BMS is supported based on advertisement data.

    Args:
        bms (BaseBMS): The BMS class to check.
        adv_data (AdvertisementData): The advertisement data to match against.

    Returns:
        bool: True if the BMS is supported, False otherwise.

    """
    for matcher in bms.matcher_dict_list():
        if advertisement_matches(matcher, adv_data):
            return True
    return False


def get_bms_cls(adv_data: AdvertisementData) -> type[BaseBMS] | None:
    """Identify and return the BMS class that matches the given advertisement data.

    Args:
        adv_data (AdvertisementData): The advertisement data to match against available BMS plugins.

    Returns:
        type[BaseBMS] | None: The matching BMS class if found, otherwise None.

    """
    for bms_module in load_bms_plugins():
        if bms_supported(bms_module.BMS, adv_data):
            return bms_module.BMS
    return None
