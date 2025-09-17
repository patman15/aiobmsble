# Contributing

## Adding a new battery management system

 1. Fork the repository and create a branch with the name of the new BMS to add.
 2. Add a new file to the `bms` folder called, e.g. `my_bms.py`
 3. Populate the file with class called `BMS` derived from `BaseBMS`(see basebms.py). A dummy implementation without the actual functionality to query the BMS can be found below in section [Dummy BMS Example](#dummy-bms-example).
 4. Make sure that the dictionary returned by `async_update()` has the keys listed in `BMSsample` class before the comment for *detailed information*.
 5. Test and commit the changes to the branch and create a pull request to the main repository.
 6. Please check if you follow the [architecture guidelines](#architecture-guidelines)
 7. If you like, add yourself to the `pyproject.toml` `author` array.

> [!NOTE]
> In order to keep maintainability of this integration, pull requests are required to pass checks for the [coding style](#coding-style-guidelines), Python linting, and 100% [branch test coverage](https://coverage.readthedocs.io/en/latest/branch.html#branch).

### Dummy BMS Example
A template [example](aiobmsble/bms/dummy_bms.py) for adding a new BMS type is available. In order to make it work, you need to set the UUIDs of the service, the characteristic providing notifications, and the characteristic for sending commands to. While the device must be in Bluetooth range, the actual communication does not matter. Always the fixed values in the code will be shown.

### Any contributions you make will be under the Apache-2.0 License

In short, when you submit code changes, your submissions are understood to be under the same [Apache-2.0](LICENSE) that covers the project. Feel free to contact the maintainers if that's a concern.

## Coding Style Guidelines

In general I use guidelines very close to the ones that Home Assistant uses for core integrations. Thus, the code shall pass
- `ruff check .`
- `mypy .`

## Architecture Guidelines
- This library is about Bluetooth Low Energy (BLE) battery management systems, no other devices are included to keep the interface clean.
- The BT pattern matcher shall be unique to allow auto-detecting devices.
- Frame parsing shall check the validity of a frame according to the protocol type, e.g. CRC, length, allowed type
- All plugin classes shall inherit from `BaseBMS` and use the functions from there before overriding or replacing.
- If available the data shall be read from the device, the `BaseBMS._add_missing_values()` functionality is only to have consistent data over all BMS types.
- Where possible, use the functions provided by the `BaseBMS` class.
- Tests shall use recorded frames from a real device to allow for adding new parsed values at a later point in time.

to be extended ...

