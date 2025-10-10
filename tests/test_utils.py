"""Test the aiobmsble library utility functions."""

from types import ModuleType

from bleak.backends.scanner import AdvertisementData
import pytest

from aiobmsble import MatcherPattern
from aiobmsble.basebms import BaseBMS
from aiobmsble.test_data import bms_advertisements
from aiobmsble.utils import (
    _advertisement_matches,
    bms_cls,
    bms_identify,
    load_bms_plugins,
)
from tests.bluetooth import generate_advertisement_data


@pytest.fixture(
    name="plugin",
    params=sorted(
        load_bms_plugins(), key=lambda plugin: getattr(plugin, "__name__", "")
    ),
    ids=lambda param: param.__name__.split(".")[-1],
)
def plugin_fixture(request: pytest.FixtureRequest) -> ModuleType:
    """Return module of a BMS."""
    return request.param


def get_advertisement_by_type(advertisements, name: str) -> AdvertisementData | None:
    """Return advertisement for a specific BMS type."""
    for ad_data, ad_name, _ in advertisements:
        if ad_name == name:
            return ad_data
    return None


async def test_bms_identify(plugin: ModuleType) -> None:
    """Test that each BMS is correctly detected by a pattern.

    This also ensures that each BMS has at least one advertisement.
    """
    bms_type: str = getattr(plugin, "__name__", "").rsplit(".", 1)[-1]
    (adv, mac_addr, _type, _comments) = (
        bms_advertisements(bms_type).pop()
        if bms_type != "dummy_bms"
        else (
            generate_advertisement_data(local_name="dummy"),
            "cc:cc:cc:cc:cc:cc",
            bms_type,
            "",
        )
    )

    bms_class: type[BaseBMS] | None = await bms_identify(adv, mac_addr)
    assert bms_class == plugin.BMS


async def test_bms_cls(plugin: ModuleType) -> None:
    """Test that a BMS class is correctly returned from its name."""
    # strip _bms to get only type
    bms_type: str = getattr(plugin, "__name__", "").rsplit(".", 1)[-1]
    bms_class: type[BaseBMS] | None = await bms_cls(bms_type)
    assert bms_class == plugin.BMS


@pytest.mark.parametrize("bms_type", ["unavailable_bms", "ignore_me"])
async def test_bms_cls_none(bms_type: str) -> None:
    """Test that a BMS class is None when name is not correct."""
    bms_class: type[BaseBMS] | None = await bms_cls(bms_type)
    assert bms_class is None


async def test_bms_identify_fail() -> None:
    """Test if bms_identify returns None if matching BMS for advertisement does not exist."""
    assert await bms_identify(generate_advertisement_data(), "") is None


@pytest.mark.parametrize(
    ("matcher", "adv_data", "mac_addr", "expected"),
    [
        (  # Match service_uuid
            {"service_uuid": "1234"},
            generate_advertisement_data(service_uuids=["1234"]),
            "",
            True,
        ),
        (  # Do not match service_uuid
            {"service_uuid": "abcd"},
            generate_advertisement_data(service_uuids=["1234"]),
            "",
            False,
        ),
        (  # Match service_data_uuid
            {"service_data_uuid": "abcd"},
            generate_advertisement_data(service_data={"abcd": b"\x01\x02"}),
            "",
            True,
        ),
        (  # Do not Match service_data_uuid
            {"service_data_uuid": "efgh"},
            generate_advertisement_data(service_data={"abcd": b"\x01\x02"}),
            "",
            False,
        ),
        (  # Match manufacturer_id
            {"manufacturer_id": 123},
            generate_advertisement_data(manufacturer_data={123: b"\x01\x02"}),
            "",
            True,
        ),
        (  # Do not match manufacturer_id
            {"manufacturer_id": 456},
            generate_advertisement_data(manufacturer_data={123: b"\x01\x02"}),
            "",
            False,
        ),
        (  # Match manufacturer_data_start
            {"manufacturer_id": 123, "manufacturer_data_start": b"\x01"},
            generate_advertisement_data(manufacturer_data={123: b"\x01\x02"}),
            "",
            True,
        ),
        (  # Do not match manufacturer_data_start
            {"manufacturer_id": 123, "manufacturer_data_start": b"\x02"},
            generate_advertisement_data(manufacturer_data={123: b"\x01\x02"}),
            "",
            False,
        ),
        (  # Match local_name with wildcard
            {"local_name": "Test*"},
            generate_advertisement_data(local_name="TestDevice"),
            "",
            True,
        ),
        (  # Do not match local_name with wildcard
            {"local_name": "Foo*"},
            generate_advertisement_data(local_name="BarDevice"),
            "",
            False,
        ),
        (  # Multiple criteria: all must match
            {
                "service_uuid": "1234",
                "manufacturer_id": 123,
                "local_name": "Dev*",
            },
            generate_advertisement_data(
                service_uuids=["1234"],
                manufacturer_data={123: b"\x01"},
                local_name="Device",
            ),
            "",
            True,
        ),
        (
            {
                "service_uuid": "1234",
                "manufacturer_id": 999,
                "local_name": "Dev*",
            },
            generate_advertisement_data(
                service_uuids=["1234"],
                manufacturer_data={123: b"\x01"},
                local_name="Device",
            ),
            "",
            False,
        ),
        (  # Empty matcher always matches
            {},
            generate_advertisement_data(),
            "",
            True,
        ),
        (
            {"oui": "00:11:22"},
            generate_advertisement_data(),
            "00:11:22:aa:bb:cc",
            True,
        ),
        (
            {"oui": "00:11:22-xx:yy:zz"},
            generate_advertisement_data(),
            "00:11:22:aa:bb:cc",
            True,
        ),
        (
            {"oui": "00"},
            generate_advertisement_data(),
            "00:11:22:aa:bb:cc",
            True,
        ),
    ],
    ids=[
        "service_uuid-match",
        "service_uuid-no-match",
        "service_data_uuid-match",
        "service_data_uuid-no-match",
        "manufacturer_id-match",
        "manufacturer_id-no-match",
        "manufacturer_data_start-match",
        "manufacturer_data_start-no-match",
        "local_name-wildcard-match",
        "local_name-wildcard-no-match",
        "multiple-criteria-all-match",
        "multiple-criteria-one-no-match",
        "empty-matcher-always-match",
        "OUI-matches",
        "OUI-matches-long",
        "OUI-matches-short",
    ],
)
def test_advertisement_matches(
    matcher: MatcherPattern, adv_data: AdvertisementData, mac_addr, expected: bool
):
    """Test _advertisement_matches() returns the expected result for a given matcher/advertisement.

    Args:
        matcher: The matcher object or criteria used to evaluate the advertisement data.
        adv_data: The advertisement data to be checked against the matcher.
        mac_addr: Bluetooth device address
        expected: The expected boolean result indicating if the advertisement matches the criteria.

    Asserts:
        That advertisement_matches(matcher, adv_data) returns the value specified by expected.

    """
    assert _advertisement_matches(matcher, adv_data, mac_addr) is expected
