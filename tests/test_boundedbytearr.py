"""Test aiobmsble BoundedByteArray helper class."""

from typing import Final

import pytest

from aiobmsble._boundedbytearr import BoundedByteArray


def test_negative_maxlen() -> None:
    """Check that a negative maxlen is rejected."""
    with pytest.raises(ValueError, match="maxlen must be non-negative"):
        BoundedByteArray(-1)


def test_initial_exceeds_maxlen() -> None:
    """Check that initial content longer than maxlen is rejected."""
    with pytest.raises(BufferError, match="maximum length is 2, got 3"):
        BoundedByteArray(2, b"\x01\x02\x03")


def test_append() -> None:
    """Check that a single byte is appended."""
    buffer: Final[BoundedByteArray] = BoundedByteArray(3, b"\x01")
    buffer.append(0x02)

    assert bytes(buffer) == b"\x01\x02"


def test_append_exceeds_maxlen() -> None:
    """Check that append keeps content unchanged if maxlen is exceeded."""
    buffer: Final[BoundedByteArray] = BoundedByteArray(2, b"\x01\x02")

    with pytest.raises(BufferError, match="maximum length is 2, got 3"):
        buffer.append(0x03)

    assert bytes(buffer) == b"\x01\x02"


@pytest.mark.parametrize(
    ("value", "error"),
    [(256, ValueError), ("A", TypeError)],
    ids=["out_of_range", "invalid_type"],
)
def test_append_invalid_value(value: object, error: type[Exception]) -> None:
    """Check that invalid append values are rejected atomically."""
    buffer: Final[BoundedByteArray] = BoundedByteArray(4, b"\x01")

    with pytest.raises(error):
        buffer.append(value)  # type: ignore[arg-type]

    assert bytes(buffer) == b"\x01"


def test_insert() -> None:
    """Check that a byte is inserted before the given index."""
    buffer: Final[BoundedByteArray] = BoundedByteArray(4, b"\x01\x03")
    buffer.insert(1, 0x02)

    assert bytes(buffer) == b"\x01\x02\x03"


def test_insert_exceeds_maxlen() -> None:
    """Check that insert keeps content unchanged if maxlen is exceeded."""
    buffer: Final[BoundedByteArray] = BoundedByteArray(2, b"\x01\x02")

    with pytest.raises(BufferError, match="maximum length is 2, got 3"):
        buffer.insert(0, 0x03)

    assert bytes(buffer) == b"\x01\x02"


@pytest.mark.parametrize(
    ("start", "end", "result"),
    [(0, None, True), (1, None, False), (0, 1, False), (0, 2, True)],
    ids=["match", "offset_start", "truncated_end", "exact_end"],
)
def test_startswith(start: int, end: int | None, result: bool) -> None:
    """Check prefix detection with and without an end index."""
    buffer: Final[BoundedByteArray] = BoundedByteArray(8, b"\xde\xad\xbe\xef")

    assert buffer.startswith(b"\xde\xad", start, end) is result


def test_startswith_tuple() -> None:
    """Check prefix detection with a tuple of candidates."""
    buffer: Final[BoundedByteArray] = BoundedByteArray(8, b"\xde\xad")

    assert buffer.startswith((b"\xaa", b"\xde")) is True


@pytest.mark.parametrize(
    ("start", "end", "result"),
    [(0, None, True), (0, 3, False), (0, 4, True), (3, None, False)],
    ids=["match", "truncated_end", "exact_end", "offset_start"],
)
def test_endswith(start: int, end: int | None, result: bool) -> None:
    """Check suffix detection with and without an end index."""
    buffer: Final[BoundedByteArray] = BoundedByteArray(8, b"\xde\xad\xbe\xef")

    assert buffer.endswith(b"\xbe\xef", start, end) is result


def test_endswith_tuple() -> None:
    """Check suffix detection with a tuple of candidates."""
    buffer: Final[BoundedByteArray] = BoundedByteArray(8, b"\xde\xad")

    assert buffer.endswith((b"\xaa", b"\xad")) is True


@pytest.mark.parametrize(
    ("sub", "start", "end", "result"),
    [
        (b"\xbe", 0, None, 2),
        (b"\xde", 1, None, -1),
        (b"\xbe", 0, 2, -1),
        (b"\xad", 0, 2, 1),
        (b"\xff", 0, None, -1),
    ],
    ids=["found", "offset_start", "truncated_end", "exact_end", "not_found"],
)
def test_find(sub: bytes, start: int, end: int | None, result: int) -> None:
    """Check searching for a byte sequence with and without an end index."""
    buffer: Final[BoundedByteArray] = BoundedByteArray(8, b"\xde\xad\xbe\xef")

    assert buffer.find(sub, start, end) == result


def test_iter() -> None:
    """Check that iteration yields the contained bytes as integers."""
    buffer: Final[BoundedByteArray] = BoundedByteArray(8, b"\xde\xad\xbe\xef")

    assert list(iter(buffer)) == [0xDE, 0xAD, 0xBE, 0xEF]


@pytest.mark.parametrize(
    ("key", "result"),
    [(0, b"\xad\xbe\xef"), (-1, b"\xde\xad\xbe"), (slice(1, 3), b"\xde\xef")],
    ids=["index", "negative_index", "slice"],
)
def test_delitem(key: int | slice, result: bytes) -> None:
    """Check deletion of a single byte and of a slice."""
    buffer: Final[BoundedByteArray] = BoundedByteArray(8, b"\xde\xad\xbe\xef")

    del buffer[key]

    assert bytes(buffer) == result


@pytest.mark.parametrize(
    ("key", "error"),
    [(9, IndexError), ("A", TypeError)],
    ids=["out_of_range", "invalid_type"],
)
def test_delitem_invalid_key(key: object, error: type[Exception]) -> None:
    """Check that invalid deletion keys are rejected."""
    buffer: Final[BoundedByteArray] = BoundedByteArray(8, b"\xde\xad")

    with pytest.raises(error):
        del buffer[key]  # type: ignore[arg-type]

    assert bytes(buffer) == b"\xde\xad"


def test_iadd() -> None:
    """Check that in-place addition appends and returns the same instance."""
    buffer: BoundedByteArray = BoundedByteArray(4, b"\x01")
    original: Final[BoundedByteArray] = buffer

    buffer += b"\x02\x03"

    assert buffer is original
    assert bytes(buffer) == b"\x01\x02\x03"


def test_iadd_iterable() -> None:
    """Check that in-place addition accepts an iterable of integers."""
    buffer: BoundedByteArray = BoundedByteArray(4)

    buffer += [0x01, 0x02]

    assert bytes(buffer) == b"\x01\x02"


def test_iadd_exceeds_maxlen() -> None:
    """Check that in-place addition keeps content unchanged on overflow."""
    buffer: BoundedByteArray = BoundedByteArray(2, b"\x01")

    with pytest.raises(BufferError, match="maximum length is 2, got 3"):
        buffer += b"\x02\x03"

    assert bytes(buffer) == b"\x01"


def test_eq_bytes_like() -> None:
    """Check comparison against common bytes-like objects."""
    buffer: Final[BoundedByteArray] = BoundedByteArray(8, b"\xde\xad")

    assert buffer == b"\xde\xad"
    assert buffer == bytearray(b"\xde\xad")
    assert buffer == memoryview(b"\xde\xad")
    assert (buffer == b"\xde\xae") is False


def test_eq_boundedbytearray() -> None:
    """Check comparison against another bounded array by value."""
    left: Final[BoundedByteArray] = BoundedByteArray(8, b"\x01\x02")
    right: Final[BoundedByteArray] = BoundedByteArray(4, b"\x01\x02")
    other: Final[BoundedByteArray] = BoundedByteArray(8, b"\x01\x03")

    assert left == right
    assert (left == other) is False


def test_eq_unsupported_type() -> None:
    """Check comparison with unsupported types returns False."""
    buffer: Final[BoundedByteArray] = BoundedByteArray(8, b"\x01")

    assert (buffer == "01") is False


def test_hash_unhashable() -> None:
    """Check that mutable bounded arrays are intentionally unhashable."""
    buffer: Final[BoundedByteArray] = BoundedByteArray(8, b"\x01")

    with pytest.raises(TypeError, match="unhashable type"):
        hash(buffer)
