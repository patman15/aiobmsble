"""Test the common functionality of aiobmsble library plugins."""

from collections.abc import Awaitable, Callable
import importlib
import inspect
from pathlib import Path
import pkgutil
import random
from types import ModuleType
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.service import BleakGATTService
import pytest

import aiobmsble
from aiobmsble.basebms import BaseBMS
from aiobmsble.test_data import bms_advertisements, ignore_advertisements
from aiobmsble.utils import bms_supported, load_bms_plugins
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient


def test_advertisements_unique() -> None:
    """Check that each advertisement only matches one, the right BMS."""
    for adv, mac_addr, bms_real, _comments in bms_advertisements():
        for bms_under_test in load_bms_plugins():
            supported: bool = bms_supported(bms_under_test.BMS, adv, mac_addr)
            assert supported == (
                f"aiobmsble.bms.{bms_real}" == bms_under_test.__name__
            ), f"{adv} {"incorrectly matches"if supported else "does not match"} {bms_under_test.__name__}!"


def test_advertisements_ignore() -> None:
    """Check that each advertisement to be ignored is actually ignored."""
    for adv, mac_addr, reason, _comments in ignore_advertisements():
        for bms_under_test in load_bms_plugins():
            supported: bool = bms_supported(bms_under_test.BMS, adv, mac_addr)
            assert not supported, f"{adv} incorrectly matches {bms_under_test.__name__}! {reason=}"


def get_defined_methods(cls: type) -> list[str]:
    """Return method/property names defined directly in the class, in source order."""

    def first_lineno(obj: object) -> int | None:
        """Extract the first line number from functions, staticmethods, classmethods, or properties."""
        if inspect.isfunction(obj):
            return obj.__code__.co_firstlineno

        if isinstance(obj, (staticmethod, classmethod)):
            func = obj.__func__
            if inspect.isfunction(func):
                return func.__code__.co_firstlineno

        if isinstance(obj, property) and obj.fget and inspect.isfunction(obj.fget):
            return obj.fget.__code__.co_firstlineno

        return None

    methods: list[tuple[int, str]] = [
        (lineno, name)
        for name, obj in cls.__dict__.items()
        if (lineno := first_lineno(obj)) is not None
    ]

    return [name for _, name in sorted(methods)]


def _get_bms_subclasses() -> list[tuple[type[BaseBMS], str]]:
    """Find all subclasses of BaseBMS and their source files."""
    subclasses: list[tuple[type[BaseBMS], str]] = []

    # Find all subclasses of BaseBMS
    for _, module_name, _ in pkgutil.walk_packages(aiobmsble.__path__, aiobmsble.__name__ + "."):
        module: ModuleType = importlib.import_module(module_name)
        for _name, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, BaseBMS) and obj is not BaseBMS:
                file_path: str = inspect.getsourcefile(obj) or "<unknown>"
                subclasses.append((obj, file_path))

    return subclasses


def test_subclass_method_order() -> None:
    """Verify subclass method override order matches the base class."""
    parent_methods: Final[list[str]] = get_defined_methods(BaseBMS)
    subclasses: list[tuple[type[BaseBMS], str]] = _get_bms_subclasses()

    assert subclasses, "No subclasses of BaseBMS found to test."

    for subclass, file_path in subclasses:
        subclass_methods: list[str] = get_defined_methods(subclass)

        # Only consider methods that override parent methods
        overridden: list[str] = [m for m in subclass_methods if m in parent_methods]

        # Expected relative order from parent
        expected_order: list[str] = [m for m in parent_methods if m in overridden]

        assert overridden == expected_order, (
            f"Method order mismatch in subclass {subclass.__name__}\n"
            f"File: {file_path}\n"
            f"Expected relative order: {expected_order}\n"
            f"Actual overridden order: {overridden}\n"
            f"All subclass methods: {subclass_methods}"
        )


async def test_stale_data_cleared(
    monkeypatch: pytest.MonkeyPatch, plugin_fixture: ModuleType
) -> None:
    """Verify that sustained max-size random notifications never raise BufferError.

    Delivers more BLE_MAX_ATTR_SIZE chunks of random (invalid) data than the frame
    buffer can hold, to check that each plugin discards stale data instead of
    overflowing its buffer.
    """

    async def patch_init() -> None:
        """Skip the connection init to allow direct notification delivery."""

    monkeypatch.setattr("aiobmsble.basebms.BleakClient", MockBleakClient)

    bms: BaseBMS = plugin_fixture.BMS(generate_ble_device(name="MockChunk BMS"))
    # skip connection init (e.g. JK BMS overloads) to allow direct notification delivery
    monkeypatch.setattr(bms, "_init_connection", patch_init)

    char = BleakGATTCharacteristic(
        None, 1, "fff4", ["notify"], lambda: 512, BleakGATTService(None, 0, "fff0")
    )
    handler: Callable[..., None | Awaitable[None]] = bms._notification_handler  # type: ignore[attr-defined]
    rng = random.Random(42)

    # buffer capacity is max(_MAX_MSG_LEN, BLE_MAX_ATTR_SIZE) * 2, so delivering
    # this many chunks overflows it unless stale data is cleared
    size = BaseBMS.BLE_MAX_ATTR_SIZE
    chunk_count = max(BaseBMS._MAX_MSG_LEN, size) // size + 2

    await bms._connect()
    try:
        for _ in range(chunk_count):
            try:
                if inspect.isawaitable(result := handler(char, bytearray(rng.randbytes(size)))):
                    await result
            except BufferError as exc:
                pytest.fail(f"{plugin_fixture.__name__}: {exc!r}")
    finally:
        await bms.disconnect()


def test_alive_interval_requires_alive_override() -> None:
    """Verify plugins with an alive interval override the keep-alive hook."""
    subclasses: list[tuple[type[BaseBMS], str]] = _get_bms_subclasses()

    for subclass, file_path in subclasses:
        if subclass.ALIVE_INTERVAL is not None:
            assert "_alive" in subclass.__dict__, (
                f"{subclass.__name__} sets ALIVE_INTERVAL but does not override _alive\n"
                f"File: {file_path}"
            )


def test_no_pragma_no_cover() -> None:
    """Check that BMS plugin files do not use pragma no cover declarations."""
    pragma_no_cover_files: list[tuple[str, int]] = []
    subclasses: list[tuple[type[BaseBMS], str]] = _get_bms_subclasses()

    # Check each subclass file for pragma no cover
    for _subclass, file_path_str in subclasses:
        file_path = Path(file_path_str)
        if file_path.exists():
            content: str = file_path.read_text()
            for line_num, line in enumerate(content.splitlines(), start=1):
                if "pragma" in line and "no cover" in line:
                    pragma_no_cover_files.append((file_path.name, line_num))

    assert not pragma_no_cover_files, f"Found pragma no cover in: {pragma_no_cover_files}"
