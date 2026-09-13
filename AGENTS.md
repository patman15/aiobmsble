# AGENTS.md

## Project overview

`aiobmsble` is an asynchronous Python library for querying battery-management systems (BMSs) over Bluetooth Low Energy (BLE). It uses `asyncio`, Bleak, and `bleak-retry-connector`, and also exposes the `aiobmsble` command-line entry point. The package is used by, but is not limited to, the related BMS_BLE-HA Home Assistant integration.

Treat readings and connection availability as non-safety-critical telemetry. The README explicitly warns that this library must not control actions intended to prevent battery damage, overheating, fire, or similar hazards.

The package requires Python `>=3.12`. It is licensed under Apache-2.0.

## Repository map

- `aiobmsble/__init__.py` — public types and data models, including `BMSSample`, `BMSInfo`, `BMSConfig`, `BMSDp`, and `MatcherPattern`.
- `aiobmsble/basebms.py` — `BaseBMS`, BLE connection/operation behavior, common decoding, integrity helpers, and derived-value support.
- `aiobmsble/bms/` — one plugin module per supported BMS protocol; modules generally expose a `BMS` subclass.
- `aiobmsble/test_data/` — recorded BLE advertisements in JSON, packaged as data by `pyproject.toml`.
- `tests/` — pytest suite; `tests/bms/` contains per-plugin tests, `tests/test_basebms.py` covers shared behavior, and `tests/test_fuzzing.py` exercises notification handlers with Hypothesis.
- `examples/minimal.py` — standalone asynchronous usage example.
- `docs/` — BMS protocol notes, generated API documentation, and `available_bms_data.csv`.
- `scripts/bms_data_table.py` — regenerates `docs/available_bms_data.csv` from plugin definitions and `BMSSample` fields.
- `.github/workflows/` — test/lint CI, fuzzing, documentation deployment, and package publication workflows.
- `CONTRIBUTING.md` — authoritative contribution, plugin, architecture, style, and coverage requirements.
- `pyproject.toml` — build metadata, dependencies, pytest configuration, Ruff, mypy-related project setup, and codespell configuration.

## Environment and setup

Use a Python 3.12+ virtual environment or equivalent isolated environment. From the repository root:

```bash
python -m pip install --upgrade pip
pip install -e ".[dev]"
pre-commit install
```

The development extra installs pytest, pytest-asyncio, pytest-cov, pytest-xdist, Hypothesis, mypy, Ruff, codespell, pdoc, and the other project development dependencies. Runtime dependencies are declared in `pyproject.toml`.

BLE hardware is not required for the normal test suite: tests use mocked Bleak clients and recorded advertisement/frame data. Hardware-facing commands such as `aiobmsble` require a usable BLE environment and a reachable device.

## Common commands

Run these from the repository root.

### Tests and quality checks

```bash
pytest
ruff check .
mypy .
mypy aiobmsble --strict
codespell .
```

`pytest` is configured in `pyproject.toml` to discover `tests/`, run in parallel (`-n auto`), collect branch coverage for `aiobmsble` and `examples`, print missing lines, and fail below 100% branch coverage. The CI workflow runs the commands above (using `python3 -m ruff check .` for Ruff) across its supported Python-version matrix.

For the fuzz test specifically, use the CI-compatible command:

```bash
pytest tests/test_fuzzing.py --no-cov
```

The test configuration supports `--max-examples`; the scheduled fuzzing workflow supplies up to 25,000 examples with a time-derived Hypothesis seed.

### CLI and documentation

```bash
aiobmsble
aiobmsble -v
aiobmsble -v -l debug.log
aiobmsble --json '{"local_name": "dummy"}'
```

The first command scans for reachable supported devices; the JSON form identifies a BMS from advertisement data. These are hardware/environment dependent.

To regenerate the data table and API documentation as the documentation workflow does:

```bash
python3 scripts/bms_data_table.py
pdoc 'aiobmsble' '!aiobmsble.bms' -o docs
```

The documentation workflow runs those commands on pushes to `main`; generated output should be reviewed rather than hand-editing generated API pages.

## Architecture and coding conventions

- New protocol support belongs in `aiobmsble/bms/<name>_bms.py`, with a `BMS` class derived from `BaseBMS`. Use `aiobmsble/bms/dummy_bms.py` as the template.
- A plugin must provide `INFO` with at least `default_manufacturer` and `default_model`, a unique `matcher_dict_list()`, `uuid_services()`, `uuid_rx()`, `uuid_tx()`, `_notification_handler()`, and `_async_update()`.
- Matchers must be unique across plugins so BLE auto-detection is reliable. A matcher can use the `MatcherPattern` fields defined in `aiobmsble/__init__.py`.
- Store returned telemetry in the `BMSSample` `TypedDict`, not a dataclass. Include the required common fields available from the device and use `BaseBMS._add_missing_values()`/the existing calculation helpers for consistent derived values.
- Validate incoming frames according to the protocol (for example, start marker, length, allowed message type, and checksum/CRC). Discard invalid frames; only signal completion when a valid complete response is available.
- Prefer `BaseBMS` helpers such as `_decode_data()`, `_cell_voltages()`, `_temp_values()`, `_check_integrity()`, and `_cmd_modbus()` before duplicating behavior.
- Use recorded frames/advertisements from real devices in tests; do not fabricate protocol frames. Keep names and comments in English, use Google-style docstrings, and do not add `# pragma: no cover` (the contribution guide explicitly prohibits it).
- Follow the Ruff configuration in `pyproject.toml`, including its import sorting, complexity, docstring, async, logging, and typing rules. Tests have a per-file exception for Ruff `SLF`; protected-access is also ignored by the configured pylint plugin for `tests/**`.

## Adding or changing a BMS plugin

1. Create a branch for the change and add the plugin under `aiobmsble/bms/`.
2. Start from `aiobmsble/bms/dummy_bms.py` and implement the required class members and protocol parsing.
3. Add a real-device advertisement to `aiobmsble/test_data/<name>_bms.json`.
4. Add `tests/bms/test_<name>_bms.py`, subclassing `BMSBasicTests` from `tests/test_basebms.py`, and add protocol-specific cases. Use `tests/bms/test_dummy.py` as a template.
5. Add `docs/<name>_bms.md` when detailed device/protocol information is available.
6. If plugin fields or supported data change, run `python3 scripts/bms_data_table.py` and review `docs/available_bms_data.csv`.
7. Run the complete quality gate, including 100% branch coverage, before opening a pull request.

For a new BMS, ensure the sample contains at least the fields required by the contribution guide: overall voltage, signed current direction, and battery fill-level information directly or through the documented capacity fields. Do not introduce persistent values or behavior that depends on storing state across runs.

## Testing and review gates

A pull request is expected to satisfy the repository PR checklist:

- no commented-out code;
- `ruff check .` passes;
- `mypy .` passes (CI additionally runs `mypy aiobmsble --strict`);
- `codespell .` passes;
- `pytest` passes with 100% branch coverage;
- new code has focused tests using recorded device data;
- for a new BMS, the `BMSSample` is populated with available data, frames are validated, and a recorded BLE advertisement is included.

The normal pytest suite is intentionally broad: it covers plugin loading/identification, common base behavior, examples, test data, and each plugin. Keep tests deterministic and mock BLE interactions rather than requiring live radio access.

## Change workflow

- Read `CONTRIBUTING.md` and the PR template before making a change; they are the project-specific source of contribution requirements.
- Keep a change focused on one protocol, bug, or maintenance concern. Update implementation, recorded data, tests, and protocol documentation together when applicable.
- Run pre-commit locally after installing it, or run its configured checks directly:

  ```bash
  pre-commit run --all-files
  ```

- Do not remove or weaken coverage, lint, type, spelling, or frame-validation checks to make a change pass.
- Commit the completed change and open a pull request; use the repository PR checklist to report the checks performed. Contributions are under Apache-2.0.

## Safety and release boundaries

- Never treat BMS values from this library as a safety control signal. Do not add code that claims to guarantee protection against battery damage, overheating, or fire.
- Do not commit secrets, debug logs containing sensitive device information, or live credentials. The CLI's `-l debug.log` output is intended to be attached to support/bug reports only after review.
- Do not modify or push to the upstream repository as part of an agent task unless the task explicitly authorizes it. Work in a local branch/worktree and provide changes for review.
- Do not publish packages or alter release state during normal development. The release workflow builds on a published GitHub release whose tag must match semantic version syntax, then publishes to PyPI using the protected `pypi-release` environment. Test-package publication is a separate manually dispatched workflow targeting TestPyPI.
- Do not manually invent package versions: `pyproject.toml` uses `setuptools-scm` for dynamic versioning. Release/tag changes belong to maintainers and the release workflow.

## Evidence basis

This guidance was cross-checked against the repository at inspection time: `README.md`, `CONTRIBUTING.md`, `pyproject.toml`, `.pre-commit-config.yaml`, `.github/pull_request_template.md`, all workflows under `.github/workflows/`, `aiobmsble/__init__.py`, `aiobmsble/basebms.py`, `aiobmsble/bms/abc_bms.py`, `aiobmsble/bms/dummy_bms.py`, `examples/minimal.py`, `scripts/bms_data_table.py`, `tests/conftest.py`, `tests/test_basebms.py`, `tests/test_fuzzing.py`, and the repository file tree. The inspected checkout was the public `main` branch at commit `5b34df6` (`Fix WS Nova heater readout (#279)`).

## BMS Plugin and Test Patterns

When implementing or modifying a plugin, first inspect two or three existing
plugin/test pairs with a similar protocol. Prefer established repository
patterns over introducing a new abstraction.

### Plugin structure

Plugins live in `aiobmsble/bms/` and generally expose a `BMS` class derived
from `BaseBMS`.

A typical plugin contains:

1. A module docstring identifying the supported BMS.
2. A `BMS(BaseBMS)` implementation.
3. An `INFO` mapping with default manufacturer and model information.
4. Protocol constants annotated with `Final`.
5. A tuple of `BMSDp` definitions for declarative field decoding where the
   protocol permits it.
6. Bluetooth discovery and GATT metadata methods:
   - `matcher_dict_list()`
   - `uuid_services()`
   - `uuid_rx()`
   - `uuid_tx()`
7. A notification handler that assembles and validates incoming frames.
8. A cached command builder where commands are deterministic.
9. `_async_update()` for requesting and decoding a complete sample.
10. `_fetch_device_info()` or `_init_connection()` only when the protocol
    requires additional setup or metadata exchange.

Keep protocol details inside the plugin. Reuse parsing, conversion, checksum,
and connection facilities from `BaseBMS` rather than duplicating them.

### Discovery and UUIDs

- Return normalized service UUIDs using `normalize_uuid_str()`.
- Keep RX and TX UUID methods small and deterministic.
- Match devices using the narrowest reliable combination of local name,
  service UUID, manufacturer ID, service data, and `connectable=True`.
- Return multiple matcher patterns when a protocol is sold under several
  names or manufacturer identifiers.
- Avoid overly broad matchers that could claim unrelated BLE devices.

### Protocol constants and field definitions

- Declare fixed headers, lengths, command identifiers, offsets, masks, and
  response sets as class-level `Final` constants.
- Use hexadecimal notation for protocol bytes and identifiers.
- Use `BMSDp` for fields that can be described by an offset, byte width,
  signedness, conversion function, and optional message index.
- Keep protocol scaling next to the field declaration, for example converting
  millivolts to volts or milliamps to amps.
- Use explicit byte order and signedness when calling `int.from_bytes()` or
  shared decoding helpers.
- Derive secondary values through shared base-class processing where possible;
  plugins should primarily return the raw normalized sample fields needed by
  that processing.

### Command construction

- Implement command generation as a small pure helper, commonly `_cmd()`.
- Use `@staticmethod` when no instance state is required.
- Use `@lru_cache` for deterministic command frames that are reused.
- Validate command arguments with assertions or explicit checks.
- Construct the payload first, then append the protocol checksum or CRC.
- Use checksum helpers from `aiobmsble.basebms` when an applicable
  implementation already exists.

### Notification handling

Notification handlers commonly follow this order:

1. Log received data at debug level.
2. Detect a new frame or append a fragment to the current frame buffer.
3. Reject an invalid start-of-frame marker.
4. Wait until the expected frame length is available.
5. Reject unexpected message types or command identifiers.
6. Trim or reject excess bytes according to the protocol.
7. Validate CRC, checksum, or other integrity data.
8. Store an immutable `bytes` copy of the valid frame.
9. Update expected-response tracking where multiple replies are required.
10. Set `_msg_event` only when enough valid data is available for decoding.

Important rules:

- BLE notifications may split one frame across several callbacks or combine
  multiple protocol messages. Do not assume one callback equals one frame.
- Clear stale frame data when a valid new header indicates resynchronization.
- Do not signal completion for malformed, partial, or unexpected frames.
- Use `_check_integrity()` with a shared checksum function where possible.
- Log rejection reasons at debug level without logging them as operational
  errors.
- Convert mutable notification data to `bytes` before retaining it.

### Update and decoding flow

`_async_update()` should:

- Clear stale per-request state when appropriate.
- Send requests through `_await_msg()`.
- Track all mandatory replies for multi-command protocols.
- Apply timeouts consistently with the base class.
- Reject incomplete datasets rather than returning misleading partial data,
  unless the protocol explicitly defines a field or response as optional.
- Decode scalar fields through `_decode_data()` when possible.
- Decode cell voltages and temperatures using shared helpers where their data
  layout is compatible.
- Return a `BMSSample` using the project's canonical field names.
- Clear or preserve notification state intentionally, depending on whether the
  device responds on demand or publishes continuously.

Use `contextlib.suppress(TimeoutError)` only for genuinely optional replies.
Mandatory response timeouts must remain visible to the caller.

### Device and firmware variations

Some protocols vary by firmware version, hardware generation, frame type, or
available characteristics.

When supporting variants:

- Detect the variant from explicit device information or frame metadata.
- Store the selected offset, frame type, or capability in clearly named
  instance state.
- Keep variant-specific decoding in small helpers.
- Preserve compatibility with already supported variants.
- Add separate test cases and frame samples for every supported layout.
- Treat absent optional sensors or metadata as normal only when confirmed by
  the protocol.

### Plugin test structure

Plugin tests live in `tests/bms/`, normally under a filename corresponding to
the plugin.

A typical test module contains:

1. A module docstring.
2. A `_RESULT_DEFS` constant containing the expected `BMSSample`.
3. A basic contract test class derived from `BMSBasicTests`.
4. A protocol-specific `MockBleakClient` subclass.
5. Captured or constructed byte frames stored as `bytes` or `bytearray`
   constants.
6. Happy-path update tests.
7. Device-information tests when supported.
8. Parameterized malformed-frame and protocol-variant tests.
9. Connection lifecycle assertions, including keep-alive behavior.
10. Explicit cleanup with `await bms.disconnect()`.

For the shared basic checks, use this pattern:

    class TestBasicBMS(BMSBasicTests):
        """Test the basic BMS functionality."""

        bms_class = BMS

### Mock BLE clients

Protocol tests generally emulate the BMS by subclassing `MockBleakClient`.

Mock clients should:

- Inspect the written characteristic and command bytes.
- Return the corresponding protocol response.
- Invoke the registered notification callback to reproduce BLE behavior.
- Preserve realistic packet boundaries when fragmentation matters.
- Expose small class-level switches for optional responses or protocol
  variants.
- Assert that notification setup exists before delivering data.
- Return an empty `bytearray` for unrelated writes unless the real client
  behavior requires an exception.
- Raise `TimeoutError`, `ConnectionError`, or `BleakError` only when testing
  the associated production behavior.

Do not mock internal decoder methods merely to make a test pass. Exercise the
real command, notification, integrity, and decoding path.

### Reference samples

Keep the expected successful sample in `_PROTO_DEFS` when it is reused across
tests.

Reference samples should:

- Use canonical `BMSSample` keys.
- Include derived fields expected from base-class processing.
- Use exact values for integers and booleans.
- Use repository-standard units:
  - voltage in volts
  - current in amperes
  - capacity/charge in ampere-hours
  - temperature in degrees Celsius
- Represent cell voltages and temperature values in protocol order.
- Include `problem` and `problem_code` expectations where applicable.

When only a few fields differ between variants, compose the expectation with
dictionary union rather than copying the entire sample.

### Required test coverage for plugin changes

At minimum, cover:

- A complete valid update.
- Repeated updates on an existing connection.
- Both values of the keep-alive fixture where applicable.
- Correct disconnect behavior.
- Device discovery metadata through the shared basic tests.
- Device information if the plugin implements it.
- Fragmented notifications if frames can span callbacks.
- Multiple frames in one notification if the protocol permits it.
- Invalid frame header.
- Too-short or incomplete frame.
- Incorrect frame length.
- Invalid checksum or CRC.
- Unexpected response or command type.
- Optional response timeout.
- Protocol, hardware, and firmware variants.
- Signed values, scaling boundaries, status flags, and sensor masks relevant
  to the decoder.

Malformed input tests should verify that invalid data is ignored, rejected, or
causes the expected exception without being exposed as a valid sample.

### Parameterization and mutation

Use `pytest.mark.parametrize` for related protocol cases such as:

- valid and invalid checksums
- alternate frame layouts
- optional sensor availability
- fragmented packet boundaries
- charging and discharging values
- firmware-dependent offsets
- invalid headers, lengths, and response types

When modifying a class-level response fixture:

- Copy the source `bytearray` before mutation.
- Recalculate its checksum after changing payload bytes.
- Apply temporary behavior with `monkeypatch`.
- Do not allow mutable test state to leak into another test.

Give parameter cases descriptive IDs when their meaning is not immediately
obvious from the values.

### Testing private helpers

Direct tests of private helpers are acceptable for protocol-critical pure
logic, especially:

- command construction
- checksums and CRC placement
- frame conversion
- temperature conversion
- bit-mask interpretation
- firmware-specific offsets

These tests complement, but do not replace, end-to-end tests through
`async_update()`.

### Plugin checklist

Before finishing a plugin, confirm:

- [ ] The plugin still derives from `BaseBMS`.
- [ ] Discovery matchers are specific and normalized.
- [ ] UUID methods return the correct characteristics.
- [ ] Fixed protocol values use named constants.
- [ ] Existing base-class helpers are reused.
- [ ] Fragmented notifications are handled safely.
- [ ] Invalid frames cannot set the message-complete event.
- [ ] Mandatory and optional replies are distinguished.
- [ ] Returned fields use canonical names and units.
- [ ] A corresponding test module exists.
- [ ] The mock exercises real writes and notifications.
- [ ] Happy paths, malformed frames, and variants are covered.
- [ ] Mutable response data is copied before modification.
- [ ] Connections are explicitly cleaned up in tests.
- [ ] Targeted plugin tests and the full test suite pass.
- [ ] The corresponding plugin test module provides 100% line coverage for the
      modified plugin module.
- [ ] Recorded BLE frames are documented using complete `\xNN` byte notation.