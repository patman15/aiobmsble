[![GitHub Release][releases-shield]](https://pypi.org/p/aiobmsble/)
[![License][license-shield]](LICENSE)

# Aiobmsble
Requires Python 3 and uses [asyncio](https://pypi.org/project/asyncio/) and [bleak](https://pypi.org/project/bleak/)

## Asynchronous Library to Query Battery Management Systems via Bluetooth LE
This library is intended to query data from battery management systems that use Bluetooth LE. This library can be used stand-alone in any Python environment (with necessary dependencies installed). It is developed to support [BMS_BLE-HA integration](https://github.com/patman15/BMS_BLE-HA/) that was written to make BMS data available to Home Assistant, but can be hopefully usefull for other use-cases as well.

* [Features](#features)
* [Usage](#usage)
* [Installation](#installation)
* [Troubleshooting](#troubleshooting)

## Features
- Support for autodetecting compatible BLE BMSs
- Automatic detection of compatible BLE write mode
- Asynchronous operation using [asyncio](https://pypi.org/project/asyncio/)
- Any number of batteries in parallel
- 100% test coverage plus fuzz tests for BLE data

### Supported Devices
The [list of supported devices](https://github.com/patman15/BMS_BLE-HA?tab=readme-ov-file#supported-devices) is maintained in the repository of the related [Home Assistant integration](https://github.com/patman15/BMS_BLE-HA).

## Usage
In order to identify all devices that are reachable and supported by the library, simply run
```bash
aiobmsble
```
from the command line after [installation](#installation). 

### From your Python code
In case you need a reference to include the code into your library, please see [\_\_main\_\_.py](/aiobmsble/__main__.py).

### From a Script
This example can also be found as an [example](/examples/minimal.py) in the respective [folder](/main/examples).
```python
"""Example of using the aiobmsble library to find a BLE device by name and print its sensor data.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

import asyncio
import logging
from typing import Final

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError

from aiobmsble import BMSsample
from aiobmsble.bms.dummy_bms import BMS  # TODO: use the right BMS class for your device

NAME: Final[str] = "BT Device Name"  # TODO: replace with the name of your BLE device

# Configure logging
logging.basicConfig(level=logging.INFO)
logger: logging.Logger = logging.getLogger(__name__)


async def main(dev_name) -> None:
    """Find a BLE device by name and update its sensor data."""

    device: BLEDevice | None = await BleakScanner.find_device_by_name(dev_name)
    if device is None:
        logger.error("Device '%s' not found.", dev_name)
        return

    logger.info("Found device: %s (%s)", device.name, device.address)
    try:
        async with BMS(ble_device=device) as bms:
            logger.info("Updating BMS data...")
            data: BMSsample = await bms.async_update()
            logger.info("BMS data: %s", repr(data).replace(", ", ",\n\t"))
    except BleakError as ex:
        logger.error("Failed to update BMS: %s", type(ex).__name__)


if __name__ == "__main__":
    asyncio.run(main(NAME))  # pragma: no cover
```

### Testing
For integrations tests (using pytest) the library provides advertisement data that can be used to verify detection of BMSs. For your tests you can use

```python
from aiobmsble.test_data import bms_advertisements

def test_advertisements() -> None:
    """Run some tests with the advertisements"""
    for advertisement, bms_type, _comments in bms_advertisements():
        ...
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

## Troubleshooting
In case you have problems with the library, please enable debug logging. You can also run `aiobmsble -v` from the command line in order to query all known BMS that are reachable.

### In case you have troubles you'd like to have help with 

- please record a debug log using `aiobmsble -v -l debug.log`,
- [open an issue](https://github.com/patman15/aiobmsble/issues/new?assignees=&labels=question&projects=&template=support.yml) with a good description of what your question/issue is and attach the log, or
- [open a bug](https://github.com/patman15/aiobmsble/issues/new?assignees=&labels=Bug&projects=&template=bug.yml) if you think the behaviour you see is misbehaviour of the library, including a good description of what happened, your expectations,
- and put the `debug.log` **as attachement** to the issue.

[license-shield]: https://img.shields.io/github/license/patman15/aiobmsble?style=for-the-badge&cacheSeconds=86400
[releases-shield]: https://img.shields.io/pypi/v/aiobmsble?style=for-the-badge
