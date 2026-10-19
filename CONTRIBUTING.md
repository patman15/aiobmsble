# Contributing

## Setting Up the Development Environment

```bash
pip install -e ".[dev]"
```

This installs all dependencies needed for linting, type checking, and testing.
Run `pre-commit install` after that to enable automatic checks on each commit.

## Adding a New Battery Management System

 1. Fork the repository and create a branch with the name of the new BMS to add.
 2. Add a new file to the `bms` folder called, e.g. `my_bms.py`.
 3. Populate the file with a class called `BMS` derived from `BaseBMS` (see `basebms.py`).
    A working template is available at [`aiobmsble/bms/dummy_bms.py`](aiobmsble/bms/dummy_bms.py).
    If the device speaks a protocol that an existing plugin already implements, derive
    from that plugin's `BMS` class instead (it transitively derives from `BaseBMS`) and
    override only what differs — see [Deriving from an existing plugin](#deriving-from-an-existing-plugin).
 4. The `BMS` class **must** define the following:
    - `INFO: BMSInfo` — class-level attribute with at minimum `default_manufacturer` and `default_model`.
    - `matcher_dict_list()` — list of [`MatcherPattern`](aiobmsble/__init__.py) dicts used for BLE auto-detection. The pattern **must** be unique across all plugins.
    - `uuid_services()` — tuple of 128-bit UUIDs of the BLE services required by the BMS.
    - `uuid_rx()` — 16/32/128-bit UUID of the characteristic that provides notifications (incoming data).
    - `uuid_tx()` — 16/32/128-bit UUID of the characteristic used to send commands.
    - `_notification_handler()` — callback invoked when a BLE notification arrives; validates the frame and sets `self._msg_event` when a complete, valid frame is available.
    - `_async_update()` — sends command(s) to the BMS, parses the response, and returns a `BMSSample`.
 5. Make sure that the `BMSSample` returned by `_async_update()` contains at minimum the keys listed before the *detailed information* comment in the [`BMSSample`](aiobmsble/__init__.py) class.
 6. Add recorded BLE advertisement from a real device to `aiobmsble/test_data/my_bms.json`.
 7. Add a test file at `tests/bms/test_my_bms.py`. Subclass `BMSBasicTests` (from `tests/test_basebms.py`) and add BMS-specific tests. Use `tests/bms/test_dummy.py` as a template.
    -  Use recorded frames from a real device to mimic exact device behaviour, do **not** artificially generate device frames.
 8. Add a documentation file at `docs/my_bms.md` describing the device and the protocol, if detailed information is available.
 9. Run linting and tests locally and confirm 100% branch coverage:
    ```bash
    ruff check .
    mypy .
    codespell .
    pytest
    ```
10. Commit the changes and open a pull request to the main repository.
11. If you like, add yourself to the `authors` array in `pyproject.toml`.

> [!NOTE]
> Pull requests are required to pass checks for [coding style](#coding-style-guidelines), Python linting, and 100% [branch test coverage](https://coverage.readthedocs.io/en/latest/branch.html#branch) to keep the integration maintainable.

### Dummy BMS Example
A template [example](aiobmsble/bms/dummy_bms.py) for adding a new BMS type is available. To make it work, fill in the `TODO` items: set the UUIDs of the service, the characteristic providing notifications, and the characteristic for sending commands. While the device must be in Bluetooth range, actual communication does not matter — the fixed values in the code will always be returned.

The template also shows optional overrides as comments:
- `_raw_values()` — return a set of `BMSValue` keys that should **not** be auto-calculated by `BaseBMS._add_missing_values()`, e.g. `runtime`.
- `accept_secret` — set to `True` if the BMS requires a password/secret for authentication.
- `_fetch_device_info()` — override to query device information from the BMS directly instead of reading BLE standard service `0x180A`.

### Deriving from an existing plugin

When the target device speaks a protocol that an existing plugin already implements, derive from that plugin's `BMS` class (which itself derives from `BaseBMS`) rather than from `BaseBMS` directly. The criterion is reuse of the parent's *wire protocol*: framing, notification assembly, command construction, checksum/CRC, and connection flow. Derive directly from `BaseBMS` only when introducing genuinely new framing, notification handling, command building, or integrity handling. There are two common patterns:

- **OEM rebrand / twin** (identical protocol and field layout): override only device identity and BLE addressing, i.e. `INFO`, `matcher_dict_list()`, and `uuid_services()`/`uuid_rx()`/`uuid_tx()`. See `ag_bms.py` (from `ej_bms.py`) and `eleksol_bms.py` (from `jbd_bms.py`).
- **Protocol variant** (same transport, different data map or a narrow behavioural tweak): additionally override the declarative field map (`_FIELDS`/`FIELDS`), protocol constants, scaling, and at most a small hook such as `_notification_handler()`, `_async_update()`, `_fetch_device_info()`, or `_init_connection()`. See `pwrboozt_bms.py` (from `ej_bms.py`), `c4s_bms.py` (from `vatrer_bms.py`), `daren_bms.py` (from `jbd_bms.py`), `pwrxtreme_bms.py` (from `topband_bms.py`), and `renogy_pro_bms.py` (from `renogy_bms.py`).

Do not duplicate a parent's notification handler, command builder, or integrity logic in the child; override only what genuinely differs. When writing a plugin intended to be subclassed, expose the field tuple as a plain (non-`Final`) class attribute so a child can replace it or patch entries with `BMSDp._replace()` without touching protocol code.

### Any contributions you make will be under the Apache-2.0 License

In short, when you submit code changes, your submissions are understood to be under the same [Apache-2.0](LICENSE) that covers the project. Feel free to contact the maintainers if that's a concern.

## Coding Style Guidelines

Guidelines closely follow [Home Assistant core integration](https://developers.home-assistant.io/docs/development_guidelines) conventions.

- The code shall pass the automated linting checks:
  - `ruff check .`
  - `mypy .`
  - `codespell .`
- Keep all names and comments in English.
- Do not use `# pragma: no cover`.
- Put documentation of the device / protocol into `docs/my_bms.md`.

## Architecture Guidelines

- Data shall be stored in the `BMSSample(TypedDict)` class. `TypedDict` (not `dataclass`) is used to allow automatic key-based assignment: `bmssample[key_variable] = value`, where `key_variable: BMSValue`.
- This library is about Bluetooth Low Energy (BLE) [battery management systems](#how-to-qualify-as-a-bms). No other device categories are included in order to keep the interface clean.
- The BT pattern matcher (`matcher_dict_list()`) shall return patterns unique to the target device to enable reliable auto-detection.
- Frame parsing shall validate each frame according to the protocol specification (e.g. CRC, length, allowed message types). Invalid frames shall be discarded.
- All plugin classes shall inherit from `BaseBMS`—directly, or via an existing plugin's `BMS` class when reusing that protocol (see [Deriving from an existing plugin](#deriving-from-an-existing-plugin))—and use its helper methods before overriding or replacing behaviour.
- Prefer declarative field decoding: describe scalar values with [`BMSDp`](aiobmsble/__init__.py) entries in a `_FIELDS: tuple[BMSDp, ...]` class attribute and decode them via `BaseBMS._decode_data()` before writing manual parsing. Use per-variant `_FIELDS_*` tuples when the protocol has more than one frame layout.
- If available, data shall be read directly from the device. `BaseBMS._add_missing_values()` is only used to ensure consistent data across all BMS types.
- Where possible, use the utility functions provided by `BaseBMS` (e.g. `_decode_data()`, `_cell_voltages()`, `_temp_values()`, `_check_integrity()`, `_cmd_modbus()`).
- Tests shall use recorded frames from a real device (stored in `aiobmsble/test_data/`) to allow new parsed values to be added at a later point.

to be extended ...

### How to qualify as a BMS

- It shall be used together with a storage element (e.g. a battery).
- It shall provide at minimum:
  - overall `voltage`
  - `current` including direction (charge/discharge)
  - fill level information, i.e.:
    - `battery_level` (SoC), **or**
    - `cycle_charge` (remaining capacity) and `design_capacity`, **or**
    - equivalent values from which stored energy and `battery_level` can be calculated.

See [`BMSSample`](aiobmsble/__init__.py) for all available (optional) values and their descriptions.
