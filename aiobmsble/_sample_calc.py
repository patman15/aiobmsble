"""BMSSample helper functions to complete data set.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import lru_cache
from statistics import fmean
from typing import Any, Final, cast, get_type_hints

from aiobmsble import BMSpackvalue, BMSSample, BMSValue, CommonValue, PackSample

_HRS_TO_SECS: Final[int] = 60 * 60

# Shared helpers only touch keys that exist in both TypedDicts.
_Sample = BMSSample | PackSample


def _as_dict(data: _Sample) -> dict[str, Any]:
    """View a TypedDict as a plain dict for dynamic-key access (single cast point)."""
    return cast(dict[str, Any], data)


# --------------------------------------------------------------------------- #
# Calculation definitions
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class _C:
    """Definition of a method to derive a sample value from its dependencies.

    `apply` writes directly into the sample and returns True if a value was
    assigned, False otherwise.
    """

    output: BMSValue
    requires: frozenset[BMSValue]
    apply: Callable[[Any], bool]


def _c_voltage(data: _Sample) -> bool:
    if not (cells := data.get("cell_voltages")):
        return False
    data["voltage"] = round(sum(cells), 3)
    return True


def _c_delta_cell_voltage(data: _Sample) -> bool:
    if not (cells := data.get("cell_voltages")):
        return False
    data["delta_cell_voltage"] = round(max(cells) - min(cells), 3)
    return True


def _c_cell_count(data: _Sample) -> bool:
    if not (cells := data.get("cell_voltages")):
        return False
    data["cell_count"] = len(cells)
    return True


def _c_cycle_charge(data: _Sample) -> bool:
    data["cycle_charge"] = (data.get("design_capacity", 0) * data.get("battery_level", 0)) / 100
    return True


def _c_battery_level(data: _Sample) -> bool:
    if not (design_capacity := data.get("design_capacity", 0)):
        return False
    data["battery_level"] = round(data.get("cycle_charge", 0) / design_capacity * 100, 1)
    return True


def _c_cycle_capacity(data: _Sample) -> bool:
    data["cycle_capacity"] = round(data.get("voltage", 0) * data.get("cycle_charge", 0), 3)
    return True


def _c_cycles(data: BMSSample) -> bool:
    if not (design_capacity := data.get("design_capacity", 0)):
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


# --------------------------------------------------------------------------- #
# Registries
# --------------------------------------------------------------------------- #
def _fs(*values: BMSValue) -> frozenset[BMSValue]:
    return frozenset(values)


# Calculations valid for both the main sample and each pack
_COMMON_CALCS: Final[tuple[_C, ...]] = (
    _C("voltage", _fs("cell_voltages"), _c_voltage),
    _C("delta_cell_voltage", _fs("cell_voltages"), _c_delta_cell_voltage),
    _C("cell_count", _fs("cell_voltages"), _c_cell_count),
    _C("cycle_charge", _fs("design_capacity", "battery_level"), _c_cycle_charge),
    _C("battery_level", _fs("design_capacity", "cycle_charge"), _c_battery_level),
    _C("cycle_capacity", _fs("voltage", "cycle_charge"), _c_cycle_capacity),
    _C("power", _fs("voltage", "current"), _c_power),
)

# Calculations only meaningful on the main sample
_BMS_ONLY_CALCS: Final[tuple[_C, ...]] = (
    _C("cycles", _fs("design_capacity", "total_charge"), _c_cycles),
    _C("battery_charging", _fs("current"), _c_battery_charging),
    _C("runtime", _fs("current", "cycle_charge"), _c_runtime),
)


def _validate_calc_registry(calculations: tuple[_C, ...], sample_type: type) -> tuple[_C, ...]:
    """Validate a calculation registry against its sample type."""
    name: Final[str] = sample_type.__name__
    known: Final[frozenset[BMSValue]] = cast(
        frozenset[BMSValue], frozenset(get_type_hints(sample_type))
    )
    outputs: set[BMSValue] = set()

    for calc in calculations:
        if calc.output in outputs:
            raise ValueError(f"Duplicate calculation output '{calc.output}'.")
        if calc.output not in known:
            raise ValueError(f"Unknown {name} output in calculation registry: '{calc.output}'.")
        if calc.output in calc.requires:
            raise ValueError(f"Calculation output '{calc.output}' cannot depend on itself.")
        if unknown := calc.requires - known:
            raise ValueError(
                f"Unknown {name} calculation requirements {sorted(unknown)} for '{calc.output}'."
            )
        outputs.add(calc.output)

    return calculations


@lru_cache
def _bms_registry() -> tuple[_C, ...]:
    """Return the validated registry for BMSSample."""
    return _validate_calc_registry(_COMMON_CALCS + _BMS_ONLY_CALCS, BMSSample)


@lru_cache
def _pack_registry() -> tuple[_C, ...]:
    """Return the validated registry for PackSample."""
    return _validate_calc_registry(_COMMON_CALCS, PackSample)


# --------------------------------------------------------------------------- #
# Dependency-driven calculation engine
# --------------------------------------------------------------------------- #
def _apply_calculations(
    data: _Sample,
    calculations: tuple[_C, ...],
    raw_values: frozenset[BMSValue] = frozenset(),
) -> None:
    """Fill missing values of `data` using the given calculations.

    Values already present in `data` are never overwritten.
    """

    def _order(calcs: Iterable[_C]) -> list[_C]:
        return sorted(calcs, key=lambda c: (len(c.requires), c.output))

    available: Final[dict[str, Any]] = _as_dict(data)
    pending: list[_C] = _order(c for c in calculations if c.output not in raw_values)

    while pending:
        progress: bool = False
        remaining: list[_C] = []
        for calc in pending:
            if calc.output in available:  # never overwrite an existing value
                continue
            if calc.requires.issubset(available):
                progress |= calc.apply(data)
            else:
                remaining.append(calc)
        if not progress:
            break
        pending = _order(remaining)


# --------------------------------------------------------------------------- #
# Pack aggregation
# --------------------------------------------------------------------------- #
_PACK_AGGREGATES: Final[dict[BMSpackvalue, Callable[[list[Any]], Any]]] = {
    "battery_health": min,
    "current": lambda v: round(sum(v), 3),
    "cycle_charge": lambda v: round(sum(v), 3),
    "cycle_capacity": lambda v: round(sum(v), 3),
    "design_capacity": sum,
    "cycles": max,
    "delta_cell_voltage": max,
    "voltage": lambda v: round(fmean(v), 3),
}


def _aggregate_packs(data: BMSSample, packs: list[PackSample]) -> None:
    """Fill missing main values from (already completed) pack values."""
    if not packs:
        return

    def _can_calc(key: CommonValue) -> bool:
        return key not in data and all(key in pack for pack in packs)

    def _pvalues(key: BMSpackvalue) -> list[Any]:
        return [pack.get(key, 0) for pack in packs]

    if _can_calc("cell_count") and len(set(counts := _pvalues("cell_count"))) == 1:
        data["cell_count"] = counts[0]

    for field, aggregate in _PACK_AGGREGATES.items():
        if _can_calc(field):
            data[field] = aggregate(_pvalues(field))

    if _can_calc("battery_level") and (capacity := data.get("design_capacity")):
        data["battery_level"] = round(
            sum(
                lev * cap
                for lev, cap in zip(
                    _pvalues("battery_level"), _pvalues("design_capacity"), strict=True
                )
            )
            / capacity,
            1,
        )


def derive_missing_fields(data: BMSSample, raw_values: frozenset[BMSValue] = frozenset()) -> None:
    """Complete the sample: packs → main (from packs) → main (from itself)."""
    packs: Final[list[PackSample]] = data.get("packs", [])

    for pack in packs:  # step 1: complete packs
        _apply_calculations(pack, _pack_registry())

    _aggregate_packs(data, packs)  # step 2: packs -> main
    _apply_calculations(data, _bms_registry(), raw_values)  # step 3: complete main
