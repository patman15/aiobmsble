"""Test aiobmsble library interface classes."""

from typing import Final

import pytest

import aiobmsble
from aiobmsble import TempSensor as TS, TSKind


def test_dropped_re_exports() -> None:
    """Test that implementation types are imported from their direct modules."""
    assert "BaseBMS" not in aiobmsble.__all__
    assert "bms_identify" not in aiobmsble.__all__
    assert not hasattr(aiobmsble, "BaseBMS")
    assert not hasattr(aiobmsble, "bms_identify")


def test_TempSensor() -> None:
    """Test correct behaviour of TS and with int, float."""
    # Test equality with float
    assert TS(3.14) == 3.14
    assert float(TS(3.14)) == 3.14
    # Test equality with TS of same value and type
    assert TS(3.14, TSKind.GENERIC) == TS(3.14, TSKind.GENERIC)
    # Test inequality due to type mismatch
    assert TS(3.14) != TS(3.14, TSKind.CELL)
    # Test inequality due to value mismatch
    assert TS(3.14) != TS(3.15)
    # Test identity check when type is specified
    assert TS(3.14, TSKind.CELL) == TS(3.14, TSKind.CELL)
    # Test hash consistency
    s1: Final = TS(5.0, TSKind.GENERIC)
    s2: Final = TS(5.0, TSKind.GENERIC)
    assert hash(s1) == hash(s2)
    # Test hash consistent with equality to numbers
    assert hash(s1) == hash(5.0) == hash(5)
    s3: Final = TS(5.0, TSKind.CELL)
    assert s1 != s3
    assert len({s1, s3}) == 2

    # Test comparison when comparing to int
    assert TS(5) == 5
    assert TS(5) == 5.0
    assert TS(5.0) == 5.0
    assert TS(5.0) == 5
    assert TS(5.1) != 5
    assert TS(5.1) != 5.0
    assert TS(5) != "5"
    assert TS(5.0) != "5.0"
    assert TS(5) is not None

    # Compare lists
    assert [TS(5), TS(5.0)] == [5.0, 5]
    assert [TS(5), TS(5.0)] == [TS(5.0), TS(5)]

    # Hash usable in sets
    s: set[TS] = {TS(1.0), TS(1.0)}
    assert len(s) == 1

    # Test __repr__
    assert repr(TS(3.14)) == "TempSensor(3.14, <TSKind.GENERIC: 0>)"
    assert repr(TS(5.0, TSKind.CELL)) == "TempSensor(5.0, <TSKind.CELL: 1>)"
    assert repr(TS(25, TSKind.PCB)) == "TempSensor(25, <TSKind.PCB: 5>)"


def test_TempSensor_conversion() -> None:
    """Test int() and round() operate on the value of TS."""
    assert int(TS(21.6, TSKind.CELL)) == 21
    assert int(TS(-2.7)) == -2
    assert round(TS(21.6)) == 22
    assert round(TS(2.5)) == 2
    assert round(TS(21.66), 1) == 21.7


def test_TempSensor_ordering() -> None:
    """Test ordering of TS by value with TS, int and float."""
    assert TS(1.0, TSKind.CELL) < TS(2.0)
    assert TS(2.0, TSKind.CELL) <= TS(2.0, TSKind.MOSFET)
    assert TS(2.0, TSKind.CELL) >= TS(2.0, TSKind.MOSFET)
    assert TS(3) > 2.5
    assert TS(3) >= 3
    assert 2 < TS(3) <= 3.0
    assert max([TS(1.0), TS(5.0, TSKind.MOSFET), TS(3.0)]) == TS(5.0, TSKind.MOSFET)
    with pytest.raises(TypeError):
        assert TS(1.0) < "2"  # type: ignore[operator]
    with pytest.raises(TypeError):
        assert TS(1.0) <= "2"  # type: ignore[operator]
    with pytest.raises(TypeError):
        assert TS(1.0) > "2"  # type: ignore[operator]
    with pytest.raises(TypeError):
        assert TS(1.0) >= "2"  # type: ignore[operator]
