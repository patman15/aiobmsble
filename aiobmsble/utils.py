"""Utility/Support functions for aiobmsble.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

import asyncio
from collections.abc import Iterable, Sequence
from functools import cache
import importlib
import pkgutil
from string import hexdigits
from types import ModuleType
from typing import Any, Final

from bleak.backends.scanner import AdvertisementData

from aiobmsble import BMSProblem, PrbType, Severity
from aiobmsble.basebms import BaseBMS
import aiobmsble.bms
from aiobmsble.exceptions import BMSConfigError

__all__: list[str] = [
    "adv_dict_to_advdata",
    "available_bms",
    "get_bms",
    "identify",
    "load_bms_plugins",
    "problem_levels",
]

_MODULE_POSTFIX: Final[str] = "_bms"


def _platform_data(pdata: Sequence[Any]) -> tuple[Any, ...]:
    """Validate platform data, the first entry needs to be a MAC address."""
    if not isinstance(pdata[0], str):
        raise BMSConfigError("first entry of platform_data needs to be string.")
    parts: Final[list[str]] = pdata[0].split(":")
    if not (
        len(parts) == 6
        and all(len(part) == 2 and all(c in hexdigits for c in part) for part in parts)
    ):
        raise BMSConfigError("first entry of platform_data only accepts MAC addresses")
    return tuple(pdata)


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
            val_dict["platform_data"] = _platform_data(adv_dict["platform_data"])

        return AdvertisementData(**(advertisement_data_defaults | val_dict))
    except BMSConfigError:
        raise
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise BMSConfigError("Invalid advertisement data.") from exc


@cache
def load_bms_plugins() -> frozenset[ModuleType]:
    """Discover and load all available Battery Management System (BMS) plugin modules.

    This function scans the 'aiobmsble/bms' directory for all Python modules,
    dynamically imports each discovered module, and returns a frozenset containing
    the imported module objects required to end with "_bms" and be subclass of BaseBMS.

    Blocking (imports plugin modules); from async code use `identify()`/`get_bms()` or run
    it in an executor.

    Returns:
        frozenset[ModuleType]: A frozenset of imported BMS plugin modules.

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

    return frozenset(modules)


async def get_bms(bms_type: str) -> type[BaseBMS] | None:
    """Return the BMS class identified by its BMS type.

    Args:
        bms_type: BMS type, i.e. the plugin module name, e.g. `dummy_bms`

    Returns:
        type[BaseBMS] | None: the BMS class if found, None otherwise.

    """
    if not bms_type.endswith(_MODULE_POSTFIX):
        return None
    loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
    try:
        bms_module: ModuleType = await loop.run_in_executor(
            None, importlib.import_module, f"aiobmsble.bms.{bms_type}"
        )
    except ModuleNotFoundError:
        return None

    bms_class: Any = getattr(bms_module, "BMS", None)
    if not (isinstance(bms_class, type) and issubclass(bms_class, BaseBMS)):
        return None

    return bms_class


def available_bms() -> frozenset[type[BaseBMS]]:
    """Return all available BMS classes.

    Blocking (imports plugin modules); from async code use `identify()`/`get_bms()` or run
    it in an executor.
    """
    return frozenset(bms_module.BMS for bms_module in load_bms_plugins())


async def identify(adv: AdvertisementData, address: str) -> list[type[BaseBMS]]:
    """Return the BMS classes matching the given advertisement.

    Currently at most one class matches. This might change in the future, if BMSs
    cannot be distinguished uniquely using their Bluetooth advertisement / OUI
    (Organizationally Unique Identifier).

    Args:
        adv: The advertisement data to match against available BMS plugins.
        address: Bluetooth device address to check OUI against, format: "00:11:22:aa:bb:cc"

    Returns:
        list[type[BaseBMS]]: A list of matching BMS class(es) if found, an empty list otherwise.

    """
    loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
    bms_classes: frozenset[type[BaseBMS]] = await loop.run_in_executor(None, available_bms)
    return [bms_class for bms_class in bms_classes if bms_class.matches(adv, address)]


def problem_levels(problems: Iterable[BMSProblem]) -> dict[PrbType, Severity]:
    """Reduce decoded problems to the worst severity per problem type.

    A BMS can report the same problem type more than once, e.g. as warning and as
    protection. Consumers that track one level per type can use this reduction.

    Args:
        problems: decoded problems, e.g. `BMSSample["problems"]`

    Returns:
        dict[PrbType, Severity]: worst level of each reported problem type

    """
    levels: dict[PrbType, Severity] = {}
    for problem in problems:
        levels[problem.kind] = max(problem.level, levels.get(problem.kind, Severity.OK))
    return levels
