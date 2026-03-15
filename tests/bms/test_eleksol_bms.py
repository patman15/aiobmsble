"""Test the Eleksol battery BMS implementation."""

from aiobmsble.bms.eleksol_bms import BMS
from tests.test_basebms import BMSBasicTests


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


def test_characteristic_uuid() -> None:
    """Test that the characteristic UUIDs are correct and get coverage."""
    assert BMS.uuid_rx() == "ff07"
    assert BMS.uuid_tx() == "ff08"
