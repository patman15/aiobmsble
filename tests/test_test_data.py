"""Test the aiobmsble test data functions."""

from bleak.backends.scanner import AdvertisementData

from aiobmsble.test_data import (
    _json_dict_to_advdata,
    bms_advertisements,
    ignore_advertisements,
)


def test_test_data_availability() -> None:
    """That fixtures work, safety measure to avoid package corruption."""
    assert len(bms_advertisements()) > 0
    assert len(ignore_advertisements()) > 0


def test_json_dict_to_advdata() -> None:
    """Check that conversion delivers correct types."""

    data = {
        "local_name": "dummy_bms",
        "rssi": -73,
        "manufacturer_data": {"12345": "00112233445566778899AABBCCDDEEFF"},
        "service_data": {
            "0000262a-0000-1000-8000-00805f9b34fb": "112233445566778899AABB"
        },
        "service_uuids": ["6e400001-b5a3-f393-e0a9-e50e24dcca9e"],
        "tx_power": 21,
        "platform_data": ("00:11:22:aa:bb:cc", 123, "test", {"check": "ok"}),
    }
    assert _json_dict_to_advdata(data) == AdvertisementData(
        local_name="dummy_bms",
        rssi=-73,
        manufacturer_data={
            12345: b"\x00\x11\x22\x33\x44\x55\x66\x77\x88\x99\xaa\xbb\xcc\xdd\xee\xff"
        },
        service_data={
            "0000262a-0000-1000-8000-00805f9b34fb": b"\x11\x22\x33\x44\x55\x66\x77\x88\x99\xaa\xbb"
        },
        service_uuids=["6e400001-b5a3-f393-e0a9-e50e24dcca9e"],
        tx_power=21,
        platform_data=("00:11:22:aa:bb:cc", 123, "test", {"check": "ok"}),
    )
