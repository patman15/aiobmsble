"""Test BMSSample calculation helper functions."""

from typing import Final, cast

import pytest

from aiobmsble import BMSSample, BMSValue, _sample_calc
from aiobmsble._sample_calc import _C, _validated_calc_registry, derive_from_packs


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
            "Unknown calculation requirements \\['unknown_requirement'\\] for 'voltage'.",
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
    monkeypatch: pytest.MonkeyPatch,
    registry: tuple[_C, ...],
    error: str,
) -> None:
    """Check invalid calculation registry entries raise errors."""

    def _mock_registry() -> tuple[_C, ...]:
        return registry

    _validated_calc_registry.cache_clear()
    monkeypatch.setattr(_sample_calc, "BMSSample_Calc_registry", _mock_registry)

    with pytest.raises(ValueError, match=error):
        _validated_calc_registry()

    _validated_calc_registry.cache_clear()


def test_validated_calculation_registry_valid_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Check valid calculation registry entries are returned unchanged."""
    registry: Final[tuple[_C, ...]] = (
        _C("voltage", frozenset({"current"}), _noop_formula),
    )

    def _mock_registry() -> tuple[_C, ...]:
        return registry

    _validated_calc_registry.cache_clear()
    monkeypatch.setattr(_sample_calc, "BMSSample_Calc_registry", _mock_registry)

    assert _validated_calc_registry() == registry

    _validated_calc_registry.cache_clear()


# Test derive_from_packs() functionality.


def test_derive_from_packs_no_packs() -> None:
    """Check that data without packs is left unchanged."""
    data: BMSSample = {"voltage": 12.0}
    derive_from_packs(data)
    assert data == {"voltage": 12.0}


def test_derive_from_packs_empty_packs() -> None:
    """Check that data with an empty packs list is left unchanged."""
    data: BMSSample = {"voltage": 12.0, "packs": []}
    derive_from_packs(data)
    assert data == {"voltage": 12.0, "packs": []}


def test_derive_from_packs_pack_delta_and_count() -> None:
    """Check delta_voltage and cell_count are derived per pack."""
    data: BMSSample = {
        "packs": [
            {"cell_voltages": [3.1, 3.3, 3.2]},
            {"cell_voltages": [3.0, 3.4]},
        ]
    }
    derive_from_packs(data)

    assert data == {
        "packs": [
            {"cell_voltages": [3.1, 3.3, 3.2], "delta_voltage": 0.2, "cell_count": 3},
            {"cell_voltages": [3.0, 3.4], "delta_voltage": 0.4, "cell_count": 2},
        ],
        "cell_voltages": [3.1, 3.3, 3.2, 3.0, 3.4],
        "delta_voltage": 0.4,
    }


def test_derive_from_packs_keeps_existing_pack_values() -> None:
    """Check existing per-pack delta_voltage and cell_count are not overwritten."""
    data: BMSSample = {
        "packs": [
            {
                "cell_voltages": [3.1, 3.3, 3.2],
                "delta_voltage": 9.9,
                "cell_count": 99,
            },
        ]
    }
    derive_from_packs(data)

    assert data == {
        "packs": [
            {
                "cell_voltages": [3.1, 3.3, 3.2],
                "delta_voltage": 9.9,
                "cell_count": 99,
            },
        ],
        "cell_count": 99,
        "cell_voltages": [3.1, 3.3, 3.2],
        "delta_voltage": 9.9,
    }


def test_derive_from_packs_skips_packs_without_cell_voltages() -> None:
    """Check packs without cell_voltages get no delta_voltage/cell_count."""
    data: BMSSample = {"packs": [{"voltage": 12.0}]}
    derive_from_packs(data)

    assert data == {"packs": [{"voltage": 12.0}], "voltage": 12.0}


def test_derive_from_packs_aggregate_values() -> None:
    """Check aggregate values are computed across packs."""
    data: BMSSample = {
        "packs": [
            {
                "cell_voltages": [3.1, 3.3],
                "current": 1.0,
                "cycle_charge": 10.0,
                "design_capacity": 100,
                "voltage": 12.0,
            },
            {
                "cell_voltages": [3.0, 3.4],
                "current": 2.0,
                "cycle_charge": 15.0,
                "design_capacity": 100,
                "voltage": 12.4,
            },
        ]
    }
    derive_from_packs(data)

    assert data == {
        "packs": [
            {
                "cell_voltages": [3.1, 3.3],
                "current": 1.0,
                "cycle_charge": 10.0,
                "design_capacity": 100,
                "voltage": 12.0,
                "delta_voltage": 0.2,
                "cell_count": 2,
            },
            {
                "cell_voltages": [3.0, 3.4],
                "current": 2.0,
                "cycle_charge": 15.0,
                "design_capacity": 100,
                "voltage": 12.4,
                "delta_voltage": 0.4,
                "cell_count": 2,
            },
        ],
        "cell_count": 2,
        "cell_voltages": [3.1, 3.3, 3.0, 3.4],
        "current": 3.0,
        "cycle_charge": 25.0,
        "delta_voltage": 0.4,
        "design_capacity": 200,
        "voltage": 12.2,
    }


def test_derive_from_packs_cell_count_mismatch() -> None:
    """Check cell_count is not derived when packs differ in count."""
    data: BMSSample = {
        "packs": [
            {"cell_voltages": [3.1, 3.3]},
            {"cell_voltages": [3.0, 3.4, 3.2]},
        ]
    }
    derive_from_packs(data)

    assert data == {
        "packs": [
            {"cell_voltages": [3.1, 3.3], "delta_voltage": 0.2, "cell_count": 2},
            {"cell_voltages": [3.0, 3.4, 3.2], "delta_voltage": 0.4, "cell_count": 3},
        ],
        "cell_voltages": [3.1, 3.3, 3.0, 3.4, 3.2],
        "delta_voltage": 0.4,
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
            },
            {
                "cell_voltages": [3.0, 3.4],
                "current": 2.0,
                "cycle_charge": 15.0,
                "design_capacity": 100,
                "voltage": 12.4,
            },
        ],
        "current": 99.0,
        "cycle_charge": 99.0,
        "design_capacity": 999,
        "voltage": 99.0,
        "cell_count": 99,
        "delta_voltage": 99.0,
    }
    derive_from_packs(data)

    assert data == {
        "packs": [
            {
                "cell_voltages": [3.1, 3.3],
                "current": 1.0,
                "cycle_charge": 10.0,
                "design_capacity": 100,
                "voltage": 12.0,
                "delta_voltage": 0.2,
                "cell_count": 2,
            },
            {
                "cell_voltages": [3.0, 3.4],
                "current": 2.0,
                "cycle_charge": 15.0,
                "design_capacity": 100,
                "voltage": 12.4,
                "delta_voltage": 0.4,
                "cell_count": 2,
            },
        ],
        "cell_voltages": [3.1, 3.3, 3.0, 3.4],
        "current": 99.0,
        "cycle_charge": 99.0,
        "design_capacity": 999,
        "voltage": 99.0,
        "cell_count": 99,
        "delta_voltage": 99.0,
    }


def test_derive_from_packs_partial_availability() -> None:
    """Check aggregates are skipped if a value is missing in one pack."""
    data: BMSSample = {
        "packs": [
            {"cell_voltages": [3.1, 3.3], "current": 1.0},
            {"cell_voltages": [3.0, 3.4]},  # no current
        ]
    }
    derive_from_packs(data)

    assert data == {
        "packs": [
            {
                "cell_voltages": [3.1, 3.3],
                "current": 1.0,
                "delta_voltage": 0.2,
                "cell_count": 2,
            },
            {"cell_voltages": [3.0, 3.4], "delta_voltage": 0.4, "cell_count": 2},
        ],
        "cell_count": 2,
        "cell_voltages": [3.1, 3.3, 3.0, 3.4],
        "delta_voltage": 0.4,
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
    derive_from_packs(data)

    assert data == {
        "packs": [
            {
                "cell_voltages": [3.1, 3.3],
                "current": 5.0,
                "cycle_charge": 20.0,
                "design_capacity": 100,
                "voltage": 12.0,
                "delta_voltage": 0.2,
                "cell_count": 2,
            },
        ],
        "cell_count": 2,
        "cell_voltages": [3.1, 3.3],
        "current": 5.0,
        "cycle_charge": 20.0,
        "delta_voltage": 0.2,
        "design_capacity": 100,
        "voltage": 12.0,
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
