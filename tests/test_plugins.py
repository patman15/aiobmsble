"""Test the aiobmsble library base class functions."""

from types import ModuleType

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


def test_advertisements_unique() -> None:
    """Check that each advertisement only matches one, the right BMS."""
    for adv, bms_real, _comments in bms_advertisements():
        for bms_under_test in load_bms_plugins():
            supported: bool = bms_supported(bms_under_test.BMS, adv)
            assert supported == (
                f"aiobmsble.bms.{bms_real}" == bms_under_test.__name__
            ), f"{adv} {"incorrectly matches"if supported else "does not match"} {bms_under_test}!"


def test_advertisements_ignore() -> None:
    """Check that each advertisement to be ignored is actually ignored."""
    for adv, reason, _comments in ignore_advertisements():
        for bms_under_test in load_bms_plugins():
            supported: bool = bms_supported(bms_under_test.BMS, adv)
            assert (
                not supported
            ), f"{adv} incorrectly matches {bms_under_test}! {reason=}"
