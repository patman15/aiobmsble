"""Test helpers for bluetooth copied from HA 2025.8.3.

Source: /tests/components/bluetooth/__init__.py
"""

from typing import Any

from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

ADVERTISEMENT_DATA_DEFAULTS = {
    "local_name": "",
    "manufacturer_data": {},
    "service_data": {},
    "service_uuids": [],
    "rssi": -127,
    "platform_data": ((),),
    "tx_power": -127,
}


def generate_advertisement_data(**kwargs: Any) -> AdvertisementData:
    """Generate advertisement data with defaults."""
    new = kwargs.copy()
    for key, value in ADVERTISEMENT_DATA_DEFAULTS.items():
        new.setdefault(key, value)
    return AdvertisementData(**new)


def generate_ble_device(
    address: str = "11:22:33:44:55:66",
    name: str | None = "MockBLEDevice",
    details: Any | None = None,
) -> BLEDevice:
    """Generate a BLEDevice with defaults."""
    return BLEDevice(address, name, details)
