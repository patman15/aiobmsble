"""Test the Dyness Jun BMS implementation."""

from aiobmsble.bms.dyness_jun_bms import BMS
from tests.test_basebms import BMSBasicTests


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS
