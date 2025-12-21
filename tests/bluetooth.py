"""Test helpers for bluetooth copied from HA 2025.8.3.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
Source: /tests/components/bluetooth/__init__.py
"""

from typing import Any

from bleak.backends.device import BLEDevice


def generate_ble_device(
    address: str = "11:22:33:44:55:66",
    name: str | None = "MockBLEDevice",
    details: Any | None = None,
) -> BLEDevice:
    """Generate a BLEDevice with defaults."""
    return BLEDevice(address, name, details or {"path": ""})
