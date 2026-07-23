"""Test BMSSample calculation helper functions."""

from typing import Final, cast

import pytest

from aiobmsble import BMSSample, BMSValue, sample_calc
from aiobmsble.sample_calc import _C, _validated_calculation_registry


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

    _validated_calculation_registry.cache_clear()
    monkeypatch.setattr(sample_calc, "BMSSample_Calc_registry", _mock_registry)

    with pytest.raises(ValueError, match=error):
        _validated_calculation_registry()

    _validated_calculation_registry.cache_clear()


def test_validated_calculation_registry_valid_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Check valid calculation registry entries are returned unchanged."""
    registry: Final[tuple[_C, ...]] = (
        _C("voltage", frozenset({"current"}), _noop_formula),
    )

    def _mock_registry() -> tuple[_C, ...]:
        return registry

    _validated_calculation_registry.cache_clear()
    monkeypatch.setattr(sample_calc, "BMSSample_Calc_registry", _mock_registry)

    assert _validated_calculation_registry() == registry

    _validated_calculation_registry.cache_clear()
