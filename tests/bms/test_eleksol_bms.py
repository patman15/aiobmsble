"""Test the Eleksol battery BMS implementation."""

from aiobmsble.bms.eleksol_bms import BMS
from tests.test_basebms import BMSBasicTests


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS
