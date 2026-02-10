"""Test the Lithionics BMS implementation."""

from bleak.uuids import normalize_uuid_str

from aiobmsble.bms.lithionics_bms import BMS
from aiobmsble.test_data import adv_dict_to_advdata
from aiobmsble.utils import bms_supported
from tests.bluetooth import generate_ble_device
from tests.bms.test_roypow_bms import MockRoyPowBleakClient, ref_value
from tests.test_basebms import verify_device_info


async def test_update(patch_bleak_client, keep_alive_fixture: bool) -> None:
    """Test Lithionics BMS data update."""

    patch_bleak_client(MockRoyPowBleakClient)

    bms = BMS(generate_ble_device(name="Lithionics"), keep_alive_fixture)

    assert await bms.async_update() == ref_value()

    # query again to check already connected state
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()


async def test_device_info(patch_bleak_client) -> None:
    """Test that the BMS returns initialized dynamic device information."""
    await verify_device_info(patch_bleak_client, MockRoyPowBleakClient, BMS)


def test_matcher() -> None:
    """Test Bluetooth matcher for Lithionics patterns."""
    adv = adv_dict_to_advdata(
        {
            "local_name": "Lithionics 12V",
            "service_uuids": [normalize_uuid_str("ffe0")],
        }
    )

    assert bms_supported(BMS, adv, "00:11:22:33:44:55")
