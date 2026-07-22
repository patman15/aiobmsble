"""BMSSample helper functions to complete data set.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from statistics import fmean
from typing import Any, Final, cast, get_type_hints

from aiobmsble import BMSSample, BMSValue

_HRS_TO_SECS: Final[int] = 60 * 60


@dataclass(frozen=True, slots=True)
class _C:
    """Definition of a method to derive BMSSample values from its dependencies."""

    output: BMSValue
    requires: frozenset[BMSValue]
    formula: Callable[[BMSSample], Any]


def _c_voltage(data: BMSSample) -> float:
    return round(sum(data.get("cell_voltages", [])), 3)


def _c_delta_voltage(data: BMSSample) -> float | None:
    cell_voltages: Final[list[float]] = data.get("cell_voltages", [])
    return round(max(cell_voltages) - min(cell_voltages), 3) if cell_voltages else None


def _c_cycle_charge(data: BMSSample) -> float:
    return (data.get("design_capacity", 0) * data.get("battery_level", 0)) / 100


def _c_battery_level(data: BMSSample) -> float | None:
    design_capacity: Final[int] = data.get("design_capacity", 0)
    return (
        round(data.get("cycle_charge", 0) / design_capacity * 100, 1)
        if design_capacity
        else None
    )


def _c_cell_count(data: BMSSample) -> int:
    return len(data.get("cell_voltages", []))


def _c_cycle_capacity(data: BMSSample) -> float:
    return round(data.get("voltage", 0) * data.get("cycle_charge", 0), 3)


def _c_cycles(data: BMSSample) -> float | None:
    design_capacity: Final[int] = data.get("design_capacity", 0)
    return data.get("total_charge", 0) // design_capacity if design_capacity else None


def _c_power(data: BMSSample) -> float:
    return round(data.get("voltage", 0) * data.get("current", 0), 3)


def _c_battery_charging(data: BMSSample) -> bool:
    return data.get("current", 0) > 0


def _c_runtime(data: BMSSample) -> int | None:
    current: Final[float] = data.get("current", 0)
    return (
        int(data.get("cycle_charge", 0) / abs(current) * _HRS_TO_SECS)
        if current < 0
        else None
    )


def _c_temperature(data: BMSSample) -> float | None:
    return (
        round(fmean(data.get("temp_values", [])), 3)
        if data.get("temp_values")
        else None
    )


@lru_cache
def BMSSample_Calc_registry() -> tuple[_C, ...]:
    """Return calculated values with their input requirements and formula."""
    fs = frozenset
    return (
        _C("voltage", fs({"cell_voltages"}), _c_voltage),
        _C("delta_voltage", fs({"cell_voltages"}), _c_delta_voltage),
        _C("cycle_charge", fs({"design_capacity", "battery_level"}), _c_cycle_charge),
        _C("battery_level", fs({"design_capacity", "cycle_charge"}), _c_battery_level),
        _C("cell_count", fs({"cell_voltages"}), _c_cell_count),
        _C("cycle_capacity", fs({"voltage", "cycle_charge"}), _c_cycle_capacity),
        _C("cycles", fs({"design_capacity", "total_charge"}), _c_cycles),
        _C("power", fs({"voltage", "current"}), _c_power),
        _C("battery_charging", fs({"current"}), _c_battery_charging),
        _C("runtime", fs({"current", "cycle_charge"}), _c_runtime),
        _C("temperature", fs({"temp_values"}), _c_temperature),
    )


@lru_cache
def _validated_calculation_registry() -> tuple[_C, ...]:
    """Return calculation registry after basic consistency checks."""
    calculations: Final[tuple[_C, ...]] = BMSSample_Calc_registry()
    known_values: Final[frozenset[BMSValue]] = cast(
        frozenset[BMSValue], frozenset(get_type_hints(BMSSample))
    )
    outputs: set[BMSValue] = set()

    for calc in calculations:
        if calc.output in outputs:
            raise ValueError(f"Duplicate calculation output '{calc.output}'.")
        if calc.output not in known_values:
            raise ValueError(
                f"Unknown BMSSample output in calculation registry: '{calc.output}'."
            )
        if calc.output in calc.requires:
            raise ValueError(
                f"Calculation output '{calc.output}' cannot depend on itself."
            )
        unknown_requirements: set[BMSValue] = set(calc.requires) - set(known_values)
        if unknown_requirements:
            raise ValueError(
                "Unknown calculation requirements "
                f"{sorted(unknown_requirements)} for '{calc.output}'."
            )
        outputs.add(calc.output)

    return calculations


def derive_missing_fields(
    data: BMSSample, raw_values: frozenset[BMSValue] = frozenset()
) -> None:
    """Apply dependency-driven calculations to the provided data mapping."""
    pending: list[_C] = sorted(
        [
            calc
            for calc in _validated_calculation_registry()
            if calc.output not in raw_values and calc.output not in data
        ],
        key=lambda calc: (len(calc.requires), calc.output),
    )

    while pending:
        progress: bool = False
        remaining: list[_C] = []

        for calc in pending:
            if not calc.requires.issubset(data):
                remaining.append(calc)
                continue
            key: BMSValue = calc.output
            if (value := calc.formula(data)) is not None:
                data[key] = value
                progress = True

        if not progress:
            break

        pending = sorted(
            remaining,
            key=lambda calc: (len(calc.requires), calc.output),
        )
