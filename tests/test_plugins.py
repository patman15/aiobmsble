"""Test the aiobmsble library base class functions."""

# Discover all subclasses of BaseBMS in the aiobmsble package
import importlib
import inspect
import pkgutil
from types import ModuleType
from typing import Final

import aiobmsble
from aiobmsble.basebms import BaseBMS
from aiobmsble.test_data import bms_advertisements, ignore_advertisements
from aiobmsble.utils import bms_supported, load_bms_plugins


def test_advertisements_unique() -> None:
    """Check that each advertisement only matches one, the right BMS."""
    for adv, mac_addr, bms_real, _comments in bms_advertisements():
        for bms_under_test in load_bms_plugins():
            supported: bool = bms_supported(bms_under_test.BMS, adv, mac_addr)
            assert supported == (
                f"aiobmsble.bms.{bms_real}" == bms_under_test.__name__
            ), f"{adv} {"incorrectly matches"if supported else "does not match"} {bms_under_test}!"


def test_advertisements_ignore() -> None:
    """Check that each advertisement to be ignored is actually ignored."""
    for adv, mac_addr, reason, _comments in ignore_advertisements():
        for bms_under_test in load_bms_plugins():
            supported: bool = bms_supported(bms_under_test.BMS, adv, mac_addr)
            assert (
                not supported
            ), f"{adv} incorrectly matches {bms_under_test}! {reason=}"


def get_defined_methods(cls) -> list[str]:
    """Return method/property names defined directly in the class, in source order."""

    def first_lineno(obj) -> int | None:
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


def test_subclass_method_order() -> None:
    """Verify subclass method override order matches the base class."""
    parent_methods: Final[list[str]] = get_defined_methods(BaseBMS)
    subclasses: list[tuple[type[BaseBMS], str]] = []

    # Find all subclasses of BaseBMS
    for _, module_name, _ in pkgutil.walk_packages(
        aiobmsble.__path__, aiobmsble.__name__ + "."
    ):
        module: ModuleType = importlib.import_module(module_name)
        for _name, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, BaseBMS) and obj is not BaseBMS:
                file_path: str = inspect.getsourcefile(obj) or "<unknown>"
                subclasses.append((obj, file_path))

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
