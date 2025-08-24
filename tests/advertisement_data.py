"""Test data for BLE Battery Management System integration config flow."""

from typing import Final

from tests.bluetooth import AdvertisementData, generate_advertisement_data

ADVERTISEMENTS: Final[list[tuple[AdvertisementData, str]]] = [
    (  # source LOG
        generate_advertisement_data(
            local_name="SmartBat-B15051",
            service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
            tx_power=3,
            rssi=-66,
        ),
        "ogt_bms",
    ),
]
