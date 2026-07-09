"""Test aiobmsble library interface classes."""

from typing import Final

from aiobmsble import TempSensor as TS


def test_TempSensor() -> None:
    """Test correct behaviour of TS and with int | float."""
    # Test equality with float
    assert TS(3.14) == 3.14
    # Test equality with TS of same value and type
    assert TS(3.14, TS.T.GENERIC) == TS(3.14, TS.T.GENERIC)
    # Test inequality due to type mismatch
    assert TS(3.14) != TS(3.14, TS.T.CELL)
    # Test inequality due to value mismatch
    assert TS(3.14) != TS(3.15)
    # Test identity check when type is specified
    assert TS(3.14, TS.T.CELL) == TS(3.14, TS.T.CELL)
    # Test hash consistency
    s1: Final = TS(5.0, TS.T.GENERIC)
    s2: Final = TS(5.0, TS.T.GENERIC)
    assert hash(s1) == hash(s2)
    # Test hash change when type changes
    s3: Final = TS(5.0, TS.T.CELL)
    assert hash(s1) != hash(s3)

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
    assert repr(TS(3.14)) == "TempSensor(3.14, <T.GENERIC: 0>)"
    assert repr(TS(5.0, TS.T.CELL)) == "TempSensor(5.0, <T.CELL: 1>)"
    assert repr(TS(25, TS.T.PCB)) == "TempSensor(25, <T.PCB: 5>)"
