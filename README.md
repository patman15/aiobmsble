[![License][license-shield]](LICENSE)

# Aiobmsble
Requires Python 3 and uses [asyncio](https://pypi.org/project/asyncio/) and [bleak](https://pypi.org/project/bleak/)
> [!IMPORTANT]
> At the moment the library is under development and not all BMS classes have been ported over from the [BMS_BLE-HA integration](https://github.com/patman15/BMS_BLE-HA/)!
> Please do not (yet) report missing BMS support or bugs here. Instead please raise an issue at the integration till the library reached at least development status *beta*.
> Plan is to support all BMSs that are listed for [BMS_BLE-HA](https://github.com/patman15/BMS_BLE-HA/tree/main?tab=readme-ov-file#supported-devices).

## Asynchronous Library to Query Battery Management Systems via Bluetooth LE
This library is intended to query data from battery management systems that use Bluetooth LE. It is developed to support [BMS_BLE-HA integration](https://github.com/patman15/BMS_BLE-HA/) that was written to make BMS data available to Home Assistant. While the integration depends on Home Assistant, this library can be used stand-alone in any Python environment (with necessary dependencies installed).

## Usage
In order to identify all devices that are reachable and supported by the library, simply run
```bash
aiobmsble
```
from the command line after [installation](#installation). In case you need the code as reference, please see [\_\_main\_\_.py](/aiobmsble/__main__.py).

### From a Script
This example can also be found as an [example](/examples/minimal.py) in the respective [folder](/main/examples).
```python
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
```

## Installation
Install python and pip if you have not already, then run:
```bash
pip3 install pip --upgrade
pip3 install wheel
```

### For Production:

```bash
pip3 install aiobmsble
```
This will install the latest library release and all of it's python dependencies.

### For Development:
```bash
git clone https://github.com/patman15/aiobmsble.git
cd aiobmsble
pip3 install -e .[dev]
```
This gives you the latest library code from the main branch.

[license-shield]: https://img.shields.io/github/license/patman15/aiobmsble.svg?style=for-the-badge&cacheSeconds=86400
