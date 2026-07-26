"""BMSSample helper functions to complete data set.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from statistics import fmean
from typing import Any, Final, cast, get_type_hints

from aiobmsble import BMSpackvalue, BMSSample, BMSValue, CommonValue, PackSample

_HRS_TO_SECS: Final[int] = 60 * 60


@dataclass(frozen=True, slots=True)
class _C:
    """Definition of a method to derive a BMSSample value from its dependencies.

    The `apply` callable writes directly into the sample using a literal key
    It returns True if a value was assigned, False otherwise.
    """

    output: BMSValue
    requires: frozenset[BMSValue]
    apply: Callable[[BMSSample], bool]


def _c_voltage(data: BMSSample) -> bool:
    data["voltage"] = round(sum(data.get("cell_voltages", [])), 3)
    return True


def _c_delta_voltage(data: BMSSample) -> bool:
    cell_voltages: Final[list[float]] = data.get("cell_voltages", [])
    if not cell_voltages:
        return False
    data["delta_voltage"] = round(max(cell_voltages) - min(cell_voltages), 3)
    return True


def _c_cycle_charge(data: BMSSample) -> bool:
    data["cycle_charge"] = (
        data.get("design_capacity", 0) * data.get("battery_level", 0)
    ) / 100
    return True


def _c_battery_level(data: BMSSample) -> bool:
    design_capacity: Final[int] = data.get("design_capacity", 0)
    if not design_capacity:
        return False
    data["battery_level"] = round(
        data.get("cycle_charge", 0) / design_capacity * 100, 1
    )
    return True


def _c_cell_count(data: BMSSample) -> bool:
    data["cell_count"] = len(data.get("cell_voltages", []))
    return True


def _c_cycle_capacity(data: BMSSample) -> bool:
    data["cycle_capacity"] = round(
        data.get("voltage", 0) * data.get("cycle_charge", 0), 3
    )
    return True


def _c_cycles(data: BMSSample) -> bool:
    design_capacity: Final[int] = data.get("design_capacity", 0)
    if not design_capacity:
        return False
    data["cycles"] = data.get("total_charge", 0) // design_capacity
    return True


def _c_power(data: BMSSample) -> bool:
    data["power"] = round(data.get("voltage", 0) * data.get("current", 0), 3)
    return True


def _c_battery_charging(data: BMSSample) -> bool:
    data["battery_charging"] = data.get("current", 0) > 0
    return True


def _c_runtime(data: BMSSample) -> bool:
    current: Final[float] = data.get("current", 0)
    if current >= 0:
        return False
    data["runtime"] = int(data.get("cycle_charge", 0) / abs(current) * _HRS_TO_SECS)
    return True


def _c_temperature(data: BMSSample) -> bool:
    if not data.get("temp_values"):
        return False
    data["temperature"] = round(fmean(data.get("temp_values", [])), 3)
    return True


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


def derive_from_packs(data: BMSSample) -> None:
    """Derive BMS main values if missing from pack values."""
    packs: list[PackSample] | None = data.get("packs")
    if not packs:
        return

    def _can_calc(key: CommonValue) -> bool:
        # not native, but available for all packs
        return key not in data and all(key in pack for pack in packs)

    def _pvalues(key: BMSpackvalue) -> list[Any]:
        return [pack.get(key, 0) for pack in packs]

    for pack in packs:
        if "cell_voltages" not in pack:
            continue
        if "delta_voltage" not in pack:
            pack["delta_voltage"] = round(
                max(pack["cell_voltages"]) - min(pack["cell_voltages"]), 3
            )
        if "cell_count" not in pack:
            pack["cell_count"] = len(pack["cell_voltages"])

    if _can_calc("cell_voltages"):
        data["cell_voltages"] = [
            v for pack in packs for v in pack.get("cell_voltages", [])
        ]
    if _can_calc("cell_count") and len(set(_pvalues("cell_count"))) == 1:
        data["cell_count"] = _pvalues("cell_count")[0]
    if _can_calc("current"):
        data["current"] = sum(_pvalues("current"))
    if _can_calc("cycle_charge"):
        data["cycle_charge"] = sum(_pvalues("cycle_charge"))
    if _can_calc("delta_voltage"):
        data["delta_voltage"] = max(_pvalues("delta_voltage"))
    if _can_calc("design_capacity"):
        data["design_capacity"] = sum(_pvalues("design_capacity"))
    if _can_calc("voltage"):
        data["voltage"] = fmean(_pvalues("voltage"))


def derive_missing_fields(
    data: BMSSample, raw_values: frozenset[BMSValue] = frozenset()
) -> None:
    """Apply dependency-driven calculations to the provided data mapping."""

    derive_from_packs(data)

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
            progress |= calc.apply(data)

        if not progress:
            break

        pending = sorted(
            remaining,
            key=lambda calc: (len(calc.requires), calc.output),
        )
