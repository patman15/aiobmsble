"""Test BMSSample calculation helper functions."""

from typing import Final, cast

import pytest

from aiobmsble import BMSSample, BMSValue, _sample_calc
from aiobmsble._sample_calc import _C, _validate_calc_registry, derive_missing_fields


def _noop_formula(_data: BMSSample) -> bool:
    """Return no calculated value."""
    return False


@pytest.mark.parametrize(
    ("registry", "error"),
    [
        (
            (
                _C("voltage", frozenset({"current"}), _noop_formula),
                _C("voltage", frozenset({"cycle_charge"}), _noop_formula),
            ),
            "Duplicate calculation output 'voltage'.",
        ),
        (
            (
                _C(
                    cast(BMSValue, "unknown_output"),
                    frozenset({"current"}),
                    _noop_formula,
                ),
            ),
            "Unknown BMSSample output in calculation registry: 'unknown_output'.",
        ),
        (
            (_C("voltage", frozenset({"voltage"}), _noop_formula),),
            "Calculation output 'voltage' cannot depend on itself.",
        ),
        (
            (
                _C(
                    "voltage",
                    frozenset({cast(BMSValue, "unknown_requirement")}),
                    _noop_formula,
                ),
            ),
            "Unknown BMSSample calculation requirements \\['unknown_requirement'\\] for 'voltage'.",
        ),
    ],
    ids=[
        "duplicate_output",
        "unknown_output",
        "self_dependency",
        "unknown_requirement",
    ],
)
def test_validated_calculation_registry_invalid_entries(
    registry: tuple[_C, ...], error: str
) -> None:
    """Check invalid calculation registry entries raise errors."""

    with pytest.raises(ValueError, match=error):
        _validate_calc_registry(registry, BMSSample)


def test_validated_calculation_registry_valid_entry() -> None:
    """Check valid calculation registry entries are returned unchanged."""
    registry: Final[tuple[_C, ...]] = (_C("voltage", frozenset({"current"}), _noop_formula),)

    assert _validate_calc_registry(registry, BMSSample) == registry


def test_derive_from_packs_no_packs() -> None:
    """Check that data without packs is left unchanged."""
    data: BMSSample = {"voltage": 12.0}
    derive_missing_fields(data)
    assert data == {"voltage": 12.0}


def test_derive_from_packs_empty_packs() -> None:
    """Check that data with an empty packs list is left unchanged."""
    data: BMSSample = {"voltage": 12.0, "packs": []}
    derive_missing_fields(data)
    assert data == {"voltage": 12.0, "packs": []}


def test_derive_from_packs_pack_delta_and_count() -> None:
    """Check delta_cell_voltage and cell_count are derived per pack."""
    data: BMSSample = {
        "packs": [
            {"cell_voltages": [3.1, 3.3, 3.2]},
            {"cell_voltages": [3.0, 3.4]},
        ]
    }
    derive_missing_fields(data)

    assert data == {
        "packs": [
            {
                "cell_voltages": [3.1, 3.3, 3.2],
                "delta_cell_voltage": 0.2,
                "cell_count": 3,
                "voltage": 9.6,
            },
            {
                "cell_voltages": [3.0, 3.4],
                "delta_cell_voltage": 0.4,
                "cell_count": 2,
                "voltage": 6.4,
            },
        ],
        "voltage": 8.0,
        "delta_cell_voltage": 0.4,
    }


def test_derive_from_packs_keeps_existing_pack_values() -> None:
    """Check existing per-pack delta_cell_voltage and cell_count are not overwritten."""
    data: BMSSample = {
        "packs": [
            {
                "cell_voltages": [3.1, 3.3, 3.2],
                "delta_cell_voltage": 9.9,
                "cell_count": 99,
            },
        ]
    }
    derive_missing_fields(data)

    assert data == {
        "packs": [
            {
                "cell_voltages": [3.1, 3.3, 3.2],
                "delta_cell_voltage": 9.9,
                "cell_count": 99,
                "voltage": 9.6,
            },
        ],
        "cell_count": 99,
        "voltage": 9.6,
        "delta_cell_voltage": 9.9,
    }


def test_derive_from_packs_skips_packs_without_cell_voltages() -> None:
    """Check packs without cell_voltages get no delta_cell_voltage/cell_count."""
    data: BMSSample = {"packs": [{"voltage": 12.0}]}
    derive_missing_fields(data)

    assert data == {"packs": [{"voltage": 12.0}], "voltage": 12.0}


def test_derive_from_packs_empty_cell_voltages() -> None:
    """Check packs with an empty cell_voltages list do not raise."""
    data: BMSSample = {"packs": [{"cell_voltages": []}]}
    derive_missing_fields(data)

    assert data == {"packs": [{"cell_voltages": []}]}


def test_derive_from_packs_aggregate_values() -> None:
    """Check aggregate values are computed across packs."""
    data: BMSSample = {
        "packs": [
            {
                "battery_health": 99.0,
                "battery_level": 73.0,
                "cell_voltages": [3.1, 3.3],
                "current": -1.0,
                "cycle_charge": 10.0,
                "cycle_capacity": 73.1,
                "cycles": 42,
                "design_capacity": 100,
                "voltage": 12.0,
            },
            {
                "battery_health": 98.0,
                "battery_level": 42.0,
                "cell_voltages": [3.0, 3.4],
                "current": -2.0,
                "cycle_charge": 15.0,
                "cycle_capacity": 42.0,
                "cycles": 123,
                "design_capacity": 150,
                "voltage": 12.4,
            },
        ]
    }
    derive_missing_fields(data)

    assert data == {
        "packs": [
            {
                "battery_health": 99.0,
                "battery_level": 73.0,
                "cell_voltages": [3.1, 3.3],
                "current": -1.0,
                "cycle_charge": 10.0,
                "cycle_capacity": 73.1,
                "cycles": 42,
                "design_capacity": 100,
                "voltage": 12.0,
                "cell_count": 2,
                "delta_cell_voltage": 0.2,
                "power": -12.0,
            },
            {
                "battery_health": 98.0,
                "battery_level": 42.0,
                "cell_voltages": [3.0, 3.4],
                "current": -2.0,
                "cycle_charge": 15.0,
                "cycle_capacity": 42.0,
                "cycles": 123,
                "design_capacity": 150,
                "voltage": 12.4,
                "cell_count": 2,
                "delta_cell_voltage": 0.4,
                "power": -24.8,
            },
        ],
        "cell_count": 2,
        "battery_health": 98.0,
        "current": -3.0,
        "cycle_charge": 25.0,
        "cycle_capacity": 115.1,
        "design_capacity": 250,
        "cycles": 123,
        "delta_cell_voltage": 0.4,
        "voltage": 12.2,
        "battery_level": 54.4,
        "battery_charging": False,
        "power": -36.6,
        "runtime": 30000,
    }


def test_derive_from_packs_cell_count_mismatch() -> None:
    """Check cell_count is not derived when packs differ in count."""
    data: BMSSample = {
        "packs": [
            {"cell_voltages": [3.1, 3.3]},
            {"cell_voltages": [3.0, 3.4, 3.2]},
        ]
    }
    derive_missing_fields(data)

    assert data == {
        "packs": [
            {
                "cell_voltages": [3.1, 3.3],
                "delta_cell_voltage": 0.2,
                "cell_count": 2,
                "voltage": 6.4,
            },
            {
                "cell_voltages": [3.0, 3.4, 3.2],
                "delta_cell_voltage": 0.4,
                "cell_count": 3,
                "voltage": 9.6,
            },
        ],
        "voltage": 8.0,
        "delta_cell_voltage": 0.4,
    }


def test_derive_from_packs_does_not_override_native_values() -> None:
    """Check that values already present in data are not overwritten."""
    data: BMSSample = {
        "packs": [
            {
                "cell_voltages": [3.1, 3.3],
                "current": 1.0,
                "cycle_charge": 10.0,
                "design_capacity": 100,
                "voltage": 12.0,
                "power": -3.14,
            },
            {
                "cell_voltages": [3.0, 3.4],
                "current": 2.0,
                "cycle_charge": 15.0,
                "design_capacity": 100,
                "voltage": 12.4,
                "power": -2.3,
            },
        ],
        "current": 99.0,
        "cycle_charge": 99.0,
        "design_capacity": 999,
        "voltage": 99.0,
        "cell_count": 99,
        "delta_cell_voltage": 99.0,
    }
    derive_missing_fields(data)

    assert data == {
        "packs": [
            {
                "cell_voltages": [3.1, 3.3],
                "current": 1.0,
                "cycle_charge": 10.0,
                "design_capacity": 100,
                "voltage": 12.0,
                "cell_count": 2,
                "delta_cell_voltage": 0.2,
                "battery_level": 10.0,
                "cycle_capacity": 120.0,
                "power": -3.14,
            },
            {
                "cell_voltages": [3.0, 3.4],
                "current": 2.0,
                "cycle_charge": 15.0,
                "design_capacity": 100,
                "voltage": 12.4,
                "cell_count": 2,
                "delta_cell_voltage": 0.4,
                "battery_level": 15.0,
                "cycle_capacity": 186.0,
                "power": -2.3,
            },
        ],
        "current": 99.0,
        "cycle_charge": 99.0,
        "design_capacity": 999,
        "voltage": 99.0,
        "cell_count": 99,
        "delta_cell_voltage": 99.0,
        "cycle_capacity": 306.0,
        "battery_level": 2.5,
        "battery_charging": True,
        "power": 9801.0,
    }


def test_derive_from_packs_partial_availability() -> None:
    """Check aggregates are skipped if a value is missing in one pack."""
    data: BMSSample = {
        "packs": [
            {"cell_voltages": [3.1, 3.3], "current": 1.0},
            {"cell_voltages": [3.0, 3.4]},  # no current
        ]
    }
    derive_missing_fields(data)

    assert data == {
        "packs": [
            {
                "cell_voltages": [3.1, 3.3],
                "cell_count": 2,
                "current": 1.0,
                "delta_cell_voltage": 0.2,
                "voltage": 6.4,
                "power": 6.4,
            },
            {
                "cell_count": 2,
                "cell_voltages": [3.0, 3.4],
                "delta_cell_voltage": 0.4,
                "voltage": 6.4,
            },
        ],
        "cell_count": 2,
        "delta_cell_voltage": 0.4,
        "voltage": 6.4,
    }


def test_derive_from_packs_single_pack() -> None:
    """Check aggregates work correctly with a single pack."""
    data: BMSSample = {
        "packs": [
            {
                "cell_voltages": [3.1, 3.3],
                "current": 5.0,
                "cycle_charge": 20.0,
                "design_capacity": 100,
                "voltage": 12.0,
            },
        ]
    }
    derive_missing_fields(data)

    assert data == {
        "packs": [
            {
                "cell_voltages": [3.1, 3.3],
                "current": 5.0,
                "cycle_charge": 20.0,
                "design_capacity": 100,
                "voltage": 12.0,
                "cell_count": 2,
                "delta_cell_voltage": 0.2,
                "battery_level": 20.0,
                "cycle_capacity": 240.0,
                "power": 60.0,
            },
        ],
        "cell_count": 2,
        "current": 5.0,
        "cycle_charge": 20.0,
        "cycle_capacity": 240.0,
        "design_capacity": 100,
        "delta_cell_voltage": 0.2,
        "voltage": 12.0,
        "battery_level": 20.0,
        "battery_charging": True,
        "power": 60.0,
    }


def test_battery_level_missing_design_capacity() -> None:
    """Check battery_level is not derived when design_capacity is absent."""
    data: BMSSample = {"cycle_charge": 20.0}
    _sample_calc.derive_missing_fields(data)

    assert data == {"cycle_charge": 20.0}


def test_cycles_missing_design_capacity() -> None:
    """Check cycles is not derived when design_capacity is absent."""
    data: BMSSample = {"total_charge": 500}
    _sample_calc.derive_missing_fields(data)

    assert data == {"total_charge": 500}


def test_design_capacity_zero_multiple_calcs() -> None:
    """Check no design_capacity dependent values are derived when it is zero."""
    data: BMSSample = {
        "design_capacity": 0,
        "cycle_charge": 20.0,
        "total_charge": 500,
    }
    _sample_calc.derive_missing_fields(data)

    assert data == {
        "design_capacity": 0,
        "cycle_charge": 20.0,
        "total_charge": 500.0,
    }
