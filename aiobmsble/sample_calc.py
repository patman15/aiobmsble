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
class _Calc:
    output: BMSValue
    requires: frozenset[BMSValue]
    formula: Callable[[BMSSample], Any]


def _calc_voltage(data: BMSSample) -> float:
    return round(sum(data.get("cell_voltages", [])), 3)


def _calc_delta_voltage(data: BMSSample) -> float | None:
    cell_voltages: Final[list[float]] = data.get("cell_voltages", [])
    return round(max(cell_voltages) - min(cell_voltages), 3) if cell_voltages else None


def _calc_cycle_charge(data: BMSSample) -> float:
    return (data.get("design_capacity", 0) * data.get("battery_level", 0)) / 100


def _calc_battery_level(data: BMSSample) -> float | None:
    design_capacity: Final[int] = data.get("design_capacity", 0)
    return (
        round(data.get("cycle_charge", 0) / design_capacity * 100, 1)
        if design_capacity
        else None
    )


def _calc_cell_count(data: BMSSample) -> int:
    return len(data.get("cell_voltages", []))


def _calc_cycle_capacity(data: BMSSample) -> float:
    return round(data.get("voltage", 0) * data.get("cycle_charge", 0), 3)


def _calc_cycles(data: BMSSample) -> float | None:
    design_capacity: Final[int] = data.get("design_capacity", 0)
    return data.get("total_charge", 0) // design_capacity if design_capacity else None


def _calc_power(data: BMSSample) -> float:
    return round(data.get("voltage", 0) * data.get("current", 0), 3)


def _calc_battery_charging(data: BMSSample) -> bool:
    return data.get("current", 0) > 0


def _calc_runtime(data: BMSSample) -> int | None:
    current: Final[float] = data.get("current", 0)
    return (
        int(data.get("cycle_charge", 0) / abs(current) * _HRS_TO_SECS)
        if current < 0
        else None
    )


def _calc_temperature(data: BMSSample) -> float | None:
    return (
        round(fmean(data.get("temp_values", [])), 3)
        if data.get("temp_values")
        else None
    )


@lru_cache
def _calculation_registry() -> tuple[_Calc, ...]:
    """Return calculated values with their input requirements and formula."""
    return (
        _Calc("voltage", frozenset({"cell_voltages"}), _calc_voltage),
        _Calc("delta_voltage", frozenset({"cell_voltages"}), _calc_delta_voltage),
        _Calc(
            "cycle_charge",
            frozenset({"design_capacity", "battery_level"}),
            _calc_cycle_charge,
        ),
        _Calc(
            "battery_level",
            frozenset({"design_capacity", "cycle_charge"}),
            _calc_battery_level,
        ),
        _Calc("cell_count", frozenset({"cell_voltages"}), _calc_cell_count),
        _Calc(
            "cycle_capacity",
            frozenset({"voltage", "cycle_charge"}),
            _calc_cycle_capacity,
        ),
        _Calc("cycles", frozenset({"design_capacity", "total_charge"}), _calc_cycles),
        _Calc("power", frozenset({"voltage", "current"}), _calc_power),
        _Calc("battery_charging", frozenset({"current"}), _calc_battery_charging),
        _Calc("runtime", frozenset({"current", "cycle_charge"}), _calc_runtime),
        _Calc("temperature", frozenset({"temp_values"}), _calc_temperature),
    )


@lru_cache
def _validated_calculation_registry() -> tuple[_Calc, ...]:
    """Return calculation registry after basic consistency checks."""
    calculations: Final[tuple[_Calc, ...]] = _calculation_registry()
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
    pending: list[_Calc] = sorted(
        [
            calc
            for calc in _validated_calculation_registry()
            if calc.output not in raw_values and calc.output not in data
        ],
        key=lambda calc: (len(calc.requires), calc.output),
    )

    while pending:
        progress: bool = False
        remaining: list[_Calc] = []

        for calc in pending:
            if not calc.requires.issubset(data):
                remaining.append(calc)
                continue
            if (value := calc.formula(data)) is not None:
                data[calc.output] = value
                progress = True

        if not progress:
            break

        pending = sorted(
            remaining,
            key=lambda calc: (len(calc.requires), calc.output),
        )
