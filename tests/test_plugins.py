"""Test the aiobmsble library base class functions."""

from string import hexdigits
from types import ModuleType
from uuid import UUID

from netaddr import OUI, NotRegisteredError

from aiobmsble.basebms import BaseBMS
from aiobmsble.test_data import bms_advertisements, ignore_advertisements
from aiobmsble.utils import bms_supported, load_bms_plugins


def test_bms_id(plugin_fixture: ModuleType) -> None:
    """Test that the BMS returns default information."""
    bms_class: type[BaseBMS] = plugin_fixture.BMS
    for key in ("default_manufacturer", "default_model"):
        assert key in bms_class.INFO
        assert bms_class.INFO[key].strip()
    assert len(bms_class.bms_id().strip())


def test_matcher_dict(plugin_fixture: ModuleType) -> None:
    """Test that the BMS returns BT matcher."""
    bms_class: type[BaseBMS] = plugin_fixture.BMS
    assert len(bms_class.matcher_dict_list())
    for matcher in bms_class.matcher_dict_list():

        if manufacturer_id := matcher.get("manufacturer_id"):
            assert (
                manufacturer_id == manufacturer_id & 0xFFFF
            ), f"incorrect {manufacturer_id=}"

        if service_uuid := matcher.get("service_uuid"):
            assert UUID(service_uuid), f"incorrect {service_uuid=}"

        if manufacturer_data_start := matcher.get("manufacturer_data_start"):
            assert all(
                byte == byte & 0xFF for byte in manufacturer_data_start
            ), "manufacturer_data_start needs to contain Byte values!"

        if oui := matcher.get("oui"):
            parts = oui.split(":")
            assert len(parts) == 3 and all(
                len(part) == 2 and all(c in hexdigits for c in part) for part in parts
            ), f"incorrect {oui=}"
            try:
                OUI(oui.replace(":", "-"))
            except NotRegisteredError:
                assert (int(parts[0], 16) & 0xC0) not in (
                    0x00,  # Non-resolvable random private address
                    0x40,  # Resolvable random private address
                    # 0x80,  # 	Reserved for future use
                    # 0xC0,  # Static random device address
                ), f"random private address OUI ({oui}) cannot be used for filtering!"


def test_advertisements_unique() -> None:
    """Check that each advertisement only matches one, the right BMS."""
    for adv, mac_addr, bms_real, _comments in bms_advertisements():
        for bms_under_test in load_bms_plugins():
            supported: bool = bms_supported(bms_under_test.BMS, adv, mac_addr)
            assert supported == (
                f"aiobmsble.bms.{bms_real}" == bms_under_test.__name__
            ), f"{adv} {"incorrectly matches"if supported else "does not match"} {bms_under_test}!"


def test_advertisements_ignore() -> None:
    """Check that each advertisement to be ignored is actually ignored."""
    for adv, mac_addr, reason, _comments in ignore_advertisements():
        for bms_under_test in load_bms_plugins():
            supported: bool = bms_supported(bms_under_test.BMS, adv, mac_addr)
            assert (
                not supported
            ), f"{adv} incorrectly matches {bms_under_test}! {reason=}"
