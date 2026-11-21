## Quick start

```python
import asyncio

from bleak import BleakScanner
from aiobmsble import BMSError, BMSSample
from aiobmsble.utils import identify


async def main() -> None:
    for device, adv in (await BleakScanner.discover(return_adv=True)).values():
        if not (bms_classes := await identify(adv, device.address)):
            continue
        try:
            async with bms_classes[0](ble_device=device) as bms:
                print(await bms.device_info())
                data: BMSSample = await bms.update()
                print(data)
        except BMSError as exc:
            print(f"{device.address}: query failed: {exc}")


asyncio.run(main())
```

If the BMS type is known, import its class directly, e.g.
`from aiobmsble.bms.dummy_bms import BMS`.

## Continuous polling

Create one BMS instance and call `aiobmsble.basebms.BaseBMS.update()` periodically.
With the default `BMSConfig(keep_alive=True)` the connection stays open between calls
and is re-established automatically after it was lost.

```python
import asyncio

from bleak import BleakScanner
from aiobmsble import BMSError, BMSSample
from aiobmsble.bms.dummy_bms import BMS  # use the class for your device

ADDRESS = "00:11:22:33:44:55"  # Bluetooth address of your BMS
INTERVAL = 30  # [s] between queries


async def poll() -> None:
    if (device := await BleakScanner.find_device_by_address(ADDRESS)) is None:
        raise SystemExit(f"{ADDRESS} not found")

    bms = BMS(ble_device=device)
    try:
        while True:
            try:
                data: BMSSample = await bms.update()
                print(data.get("voltage"), data.get("current"), data.get("battery_level"))
            except BMSError as exc:
                if not exc.retryable:  # e.g. wrong secret or unsupported device
                    print(f"stop polling: {exc}")
                    break
                print(f"query failed, retrying at next interval: {exc}")
            await asyncio.sleep(INTERVAL)
    finally:
        await bms.disconnect()


asyncio.run(poll())
```

Retries are already done inside `update()`, so do not retry immediately after an error.

The quick start uses `async with`, which connects when the block is entered and raises
if the device is not reachable at that moment. That suits a one-off query. The polling
example deliberately uses `try`/`finally` instead: the first connection is only made by
`update()`, so a device that is unreachable at startup is just a failed poll that is
retried at the next interval. Once connected, both variants behave the same.
