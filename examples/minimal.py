"""Example of using the aiobmsble library to find a BLE device by name and print its senosr data."""

import asyncio
from typing import Final

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError

from aiobmsble import BMSsample
from aiobmsble.bms.ogt_bms import BMS  # use the right BMS class for your device

NAME: Final[str] = "BT Device Name"  # Replace with the name of your BLE device


async def main(dev_name) -> None:
    """Main function to find a BLE device by name and update its sensor data."""

    device: BLEDevice | None = await BleakScanner.find_device_by_name(dev_name)
    if device is None:
        print(f"Device '{dev_name}' not found.")
        return

    print(f"Found device: {device.name} ({device.address})")
    bms = BMS(ble_device=device, reconnect=True)
    try:
        print("Updating BMS data...")
        data: BMSsample = await bms.async_update()
        print("BMS data: ", repr(data).replace(", ", ",\n\t"))
    except BleakError as ex:
        print(f"Failed to update BMS: {ex}")


asyncio.run(main(NAME))
