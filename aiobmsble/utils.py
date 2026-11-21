"""Utility/Support functions for aiobmsble.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

import asyncio
from functools import cache
import importlib
import pkgutil
from string import hexdigits
from types import ModuleType
from typing import Any, Final

from bleak.backends.scanner import AdvertisementData

from aiobmsble.basebms import BaseBMS
import aiobmsble.bms
from aiobmsble.exceptions import BMSConfigError

_MODULE_POSTFIX: Final[str] = "_bms"


def adv_dict_to_advdata(adv_dict: dict[str, Any]) -> AdvertisementData:
    """Generate an AdvertisementData instance from a JSON dictionary.

    Args:
        adv_dict: advertisement fields, e.g. `local_name`, `manufacturer_data`
            (hex strings or bytes), `service_data`, `service_uuids`.

    Returns:
        AdvertisementData: advertisement usable with `identify()`.

    Raises:
        aiobmsble.exceptions.BMSConfigError: if the dictionary is malformed.

    """
    advertisement_data_defaults: Final[dict[str, Any]] = {
        "local_name": None,
        "manufacturer_data": {},
        "service_data": {},
        "service_uuids": [],
        "rssi": -127,
        "platform_data": ((),),
        "tx_power": None,
    }

    try:
        val_dict: dict[str, Any] = adv_dict.copy()
        if "manufacturer_data" in adv_dict:
            val_dict["manufacturer_data"] = {
                int(k): bytes.fromhex(v) if isinstance(v, str) else v
                for k, v in adv_dict["manufacturer_data"].items()
            }
        if "service_data" in adv_dict:
            val_dict["service_data"] = {
                k: bytes.fromhex(v) if isinstance(v, str) else v
                for k, v in adv_dict["service_data"].items()
            }
        if "platform_data" in adv_dict:
            pdata = adv_dict.get("platform_data", [])
            assert isinstance(
                pdata[0], str
            ), "first entry of platform_data needs to be string."
            parts = pdata[0].split(":")
            assert len(parts) == 6 and all(
                len(part) == 2 and all(c in hexdigits for c in part) for part in parts
            ), "first entry of platform_data only accepts MAC addresses"
            val_dict["platform_data"] = tuple(pdata)

        return AdvertisementData(**(advertisement_data_defaults | val_dict))
    except (AssertionError, IndexError, KeyError, TypeError, ValueError) as exc:
        raise BMSConfigError("Invalid advertisement data.") from exc


@cache
def load_bms_plugins() -> set[ModuleType]:
    """Discover and load all available Battery Management System (BMS) plugin modules.

    This function scans the 'aiobmsble/bms' directory for all Python modules,
    dynamically imports each discovered module, and returns a set containing
    the imported module objects required to end with "_bms" and be subclass of BaseBMS.

    Returns:
        set[ModuleType]: A set of imported BMS plugin modules.

    Raises:
        ImportError: If a module cannot be imported.
        OSError: If the plugin directory cannot be accessed.
        AttributeError: If a discovered module does not define a 'BMS' class.
        TypeError: If a discovered module does not define a valid BMS class.

    """

    modules: set[ModuleType] = set()
    for _, module_name, _ in pkgutil.iter_modules(aiobmsble.bms.__path__):
        if not module_name.endswith(_MODULE_POSTFIX):
            continue

        module: ModuleType = importlib.import_module(f"aiobmsble.bms.{module_name}")
        if not issubclass(module.BMS, BaseBMS):
            continue

        modules.add(module)

    return modules


async def get_bms(name: str) -> type[BaseBMS] | None:
    """Return the BMS class identified by a plugin name.

    Args:
        name (str): The name of the BMS type (filename of the module)

    Returns:
        type[BaseBMS] | None: If the BMS class defined by name is found, None otherwise.

    """
    if not name.endswith(_MODULE_POSTFIX):
        return None
    loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
    try:
        bms_module: ModuleType = await loop.run_in_executor(
            None, importlib.import_module, f"aiobmsble.bms.{name}"
        )
    except ModuleNotFoundError:
        return None

    bms_class: type[BaseBMS] | None = bms_module.BMS
    if not (isinstance(bms_class, type) and issubclass(bms_class, BaseBMS)):
        return None

    return bms_class


def available_bms() -> frozenset[type[BaseBMS]]:
    """Return all available BMS classes."""
    return frozenset(bms_module.BMS for bms_module in load_bms_plugins())


async def identify(
    adv: AdvertisementData, address: str
) -> list[type[BaseBMS]]:
    """Return the BMS class matching the given advertisement.

    Currently the function is guaranteed to return one match only. This behaviour might change
    in the future to multiple entries, if BMSs cannot be distinguished uniquely using
    their Bluetooth advertisement / OUI (Organizationally Unique Identifier)

    Args:
        adv (AdvertisementData): The advertisement data to match against available BMS plugins.
        address (str): Bluetooth device address to check OUI against, format: "00:11:22:aa:bb:cc"

    Returns:
        list[type[BaseBMS]]: A list of matching BMS class(es) if found, an empty list otherwise.

    """
    loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
    bms_classes: frozenset[type[BaseBMS]] = await loop.run_in_executor(
        None, available_bms
    )
    return [bms_class for bms_class in bms_classes if bms_class.matches(adv, address)]


