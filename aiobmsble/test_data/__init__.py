"""Test advertisements for aiobmsble package.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from collections.abc import Generator
from functools import lru_cache
from importlib import resources
import json
from typing import Any, Literal

from bleak.backends.scanner import AdvertisementData

from aiobmsble.utils import adv_dict_to_advdata

type BmsAdvSample = tuple[AdvertisementData, str, str, list[str]]


def parse_adv_from_json(entry: dict[str, Any], text_key: Literal["type", "reason"]) -> BmsAdvSample:
    """Parse a JSON string into an AdvertisementData instance."""
    assert isinstance(entry, dict)
    assert {"advertisement", text_key, "_comments"}.issubset(entry.keys())
    adv: AdvertisementData = adv_dict_to_advdata(entry["advertisement"])
    mac_addr: str = (
        adv.platform_data[0]
        if isinstance(adv.platform_data, tuple) and isinstance(adv.platform_data[0], str)
        else ""
    )
    bms_type: str = entry[text_key]
    comments: list[str] = entry["_comments"]

    assert isinstance(adv, AdvertisementData)
    assert isinstance(bms_type, str)
    assert isinstance(comments, list)
    assert all(isinstance(c, str) for c in comments)

    return (adv, mac_addr, bms_type, comments)


@lru_cache(maxsize=32)
def bms_advertisements(bms_filter: str | None = None) -> tuple[BmsAdvSample, ...]:
    """Provide all available BMS advertisements from test data directory.

    Load *_bms.json files from the packaged test data directory.
    If no type is given, all available advertisemetns (any type) will be returned.

    Args:
        bms_filter (str|None): BMS type for which the advertisements should be returned.

    Returns:
        tuple[BmsAdvSample, ...]: List of tuples containing advertisement, mac_addr, bms type,
        and a list of comments, i.e. tuple[AdvertisementData, str, str, list[str]]

    """

    def generate_entries() -> Generator[BmsAdvSample, Any, None]:
        for resource in resources.files(__package__).iterdir():
            if bms_filter and not resource.name.startswith(bms_filter):
                continue
            if not resource.name.endswith("_bms.json"):
                continue
            with resource.open("r", encoding="UTF-8") as f:
                raw_data: Any = json.load(f)
                assert isinstance(raw_data, list)

                for entry in raw_data:
                    adv, mac_addr, bms_type, comments = parse_adv_from_json(entry, "type")
                    assert resource.name == f"{bms_type}.json"
                    yield (adv, mac_addr, bms_type, comments)

    return tuple(generate_entries())


def ignore_advertisements() -> tuple[BmsAdvSample, ...]:
    """Provide a list of advertisements that shall not be identified as a valid BMS.

    Load ignore.json files from the packaged test data directory.

    Returns:
        BmsAdvList: List of tuples containing advertisement, reason why not to detect,
        and a list of comments, i.e. list[tuple[AdvertisementData, str, str, list[str]]]

    """

    def generate_entries() -> Generator[BmsAdvSample, Any, None]:
        with resources.files(__package__).joinpath("ignore.json").open("r", encoding="UTF-8") as f:
            raw_data: Any = json.load(f)
            assert isinstance(raw_data, list)

            for entry in raw_data:
                adv, mac_addr, reason, comments = parse_adv_from_json(entry, "reason")
                yield (adv, mac_addr, reason, comments)

    return tuple(generate_entries())
