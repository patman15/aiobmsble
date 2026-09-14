"""Base class definition for battery management systems (BMS).

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from collections.abc import Callable, Iterable, Iterator
from typing import Self, overload


class BoundedByteArray:
    """A mutable byte array whose length cannot exceed a fixed limit.

    Mutating operations are atomic: if an operation fails or would cause the
    array to exceed ``maxlen``, the original contents remain unchanged.

    Args:
        maxlen: Maximum number of bytes the instance may contain.
        initial: Initial bytes or an iterable producing integers from 0 to 255.

    Raises:
        ValueError: If ``maxlen`` is negative.
        BufferError: If the initial content is longer than ``maxlen``.
        TypeError: If the initial content cannot initialize a bytearray.
        ValueError: If an integer in ``initial`` is outside the range 0 to 255.
    """

    type BytesLike = bytes | bytearray | memoryview
    type PrefixOrSuffix = BytesLike | tuple[BytesLike, ...]
    type IndexOrSlice = int | slice

    # mutable and therefore intentionally unhashable
    __hash__ = None  # type: ignore[assignment]

    def __init__(
        self,
        maxlen: int,
        initial: BytesLike | Iterable[int] = b"",
    ) -> None:
        """Initialize a bounded byte array.

        Args:
            maxlen: Maximum permitted number of bytes.
            initial: Initial byte content.

        Raises:
            ValueError: If ``maxlen`` is negative or an initial integer is
                outside the byte range.
            BufferError: If the initial content exceeds ``maxlen``.
            TypeError: If an argument has an invalid type.
        """
        if maxlen < 0:
            raise ValueError("maxlen must be non-negative")

        self.maxlen: int = maxlen
        self._data: bytearray = bytearray(initial)
        self._check_size(self._data)

    def _check_size(self, value: bytearray) -> None:
        if len(value) > self.maxlen:
            raise BufferError(f"maximum length is {self.maxlen}, got {len(value)}")

    def _mutate(
        self,
        operation: Callable[[bytearray], object],
    ) -> None:
        # Mutate a copy so failed operations remain atomic.
        candidate: bytearray = self._data.copy()
        operation(candidate)
        self._check_size(candidate)
        self._data = candidate

    def _new(self, value: BytesLike | Iterable[int]) -> Self:
        return type(self)(maxlen=self.maxlen, initial=value)

    def clear(self) -> None:
        """Remove all bytes from the array."""
        self._data.clear()

    def extend(self, values: BytesLike | Iterable[int]) -> None:
        """Append all bytes from an iterable or bytes-like object.

        Args:
            values: Bytes or integers from 0 to 255 to append.

        Raises:
            BufferError: If the resulting content would exceed ``maxlen``.
            TypeError: If ``values`` contains an invalid value or has an
                unsupported type.
            ValueError: If an integer is outside the range 0 to 255.
        """
        self._mutate(lambda data: data.extend(values))

    def append(self, value: int) -> None:
        """Append one byte to the end of the array.

        Args:
            value: Integer from 0 to 255.

        Raises:
            BufferError: If the resulting content would exceed ``maxlen``.
            TypeError: If ``value`` is not an integer.
            ValueError: If ``value`` is outside the range 0 to 255.
        """
        self._mutate(lambda data: data.append(value))

    def insert(self, index: int, value: int) -> None:
        """Insert one byte before an index.

        Args:
            index: Position before which the byte is inserted.
            value: Integer from 0 to 255.

        Raises:
            BufferError: If the resulting content would exceed ``maxlen``.
            TypeError: If an argument has an invalid type.
            ValueError: If ``value`` is outside the range 0 to 255.
        """
        self._mutate(lambda data: data.insert(index, value))

    def startswith(
        self,
        prefix: PrefixOrSuffix,
        start: int = 0,
        end: int | None = None,
    ) -> bool:
        """Return whether the content starts with a prefix.

        Args:
            prefix: A bytes-like prefix or tuple of possible prefixes.
            start: Optional starting index for the comparison.
            end: Optional exclusive ending index for the comparison.

        Returns:
            ``True`` if the selected content starts with a supplied prefix.
        """
        if end is None:
            return self._data.startswith(prefix, start)

        return self._data.startswith(prefix, start, end)

    def endswith(
        self,
        suffix: PrefixOrSuffix,
        start: int = 0,
        end: int | None = None,
    ) -> bool:
        """Return whether the content ends with a suffix.

        Args:
            suffix: A bytes-like suffix or tuple of possible suffixes.
            start: Optional starting index for the comparison.
            end: Optional exclusive ending index for the comparison.

        Returns:
            ``True`` if the selected content ends with a supplied suffix.
        """
        if end is None:
            return self._data.endswith(suffix, start)

        return self._data.endswith(suffix, start, end)

    def find(
        self,
        sub: BytesLike,
        start: int = 0,
        end: int | None = None,
    ) -> int:
        """Find the first occurrence of a byte sequence.

        Args:
            sub: Byte sequence to locate.
            start: Optional starting index for the search.
            end: Optional exclusive ending index for the search.

        Returns:
            The lowest matching index, or ``-1`` if no match is found.
        """
        if end is None:
            return self._data.find(sub, start)

        return self._data.find(sub, start, end)

    def replace(
        self,
        old: BytesLike,
        new: BytesLike,
        count: int = -1,
    ) -> Self:
        """Return a copy with occurrences of one sequence replaced.

        Args:
            old: Byte sequence to replace.
            new: Replacement byte sequence.
            count: Maximum number of replacements. A negative value means
                that all occurrences are replaced.

        Returns:
            A new instance with the replacements applied and the same
            ``maxlen`` value.

        Raises:
            BufferError: If the resulting content would exceed ``maxlen``.
        """
        return self._new(self._data.replace(old, new, count))

    def removesuffix(self, suffix: BytesLike) -> Self:
        """Return a copy with a matching suffix removed.

        Args:
            suffix: Byte sequence to remove from the end.

        Returns:
            A new instance without the suffix if it was present. Otherwise,
            returns a new instance containing unchanged data.
        """
        return self._new(self._data.removesuffix(suffix))

    def strip(self, chars: BytesLike | None = None) -> Self:
        """Return a copy with leading and trailing bytes removed.

        Args:
            chars: Bytes to remove. If omitted, ASCII whitespace is removed.

        Returns:
            A new stripped instance with the same ``maxlen`` value.
        """
        return self._new(self._data.strip(chars))

    def decode(
        self,
        encoding: str = "utf-8",
        errors: str = "strict",
    ) -> str:
        """Decode the content into a string.

        Args:
            encoding: Text encoding used to decode the bytes.
            errors: Error-handling strategy, such as ``"strict"``,
                ``"ignore"``, or ``"replace"``.

        Returns:
            The decoded string.

        Raises:
            LookupError: If ``encoding`` or ``errors`` is unknown.
            UnicodeDecodeError: If decoding fails with strict error handling.
        """
        return self._data.decode(encoding, errors)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, BoundedByteArray):
            return self._data == other._data

        if isinstance(other, (bytes, bytearray, memoryview)):
            return self._data == other

        return NotImplemented

    def __len__(self) -> int:
        """Return the current number of bytes."""
        return len(self._data)

    def __iter__(self) -> Iterator[int]:
        """Iterate over the contained bytes as integers."""
        return iter(self._data)

    @overload
    def __getitem__(self, key: int) -> int: ...

    @overload
    def __getitem__(self, key: slice) -> bytearray: ...

    def __getitem__(self, key: IndexOrSlice) -> int | bytearray:
        """Return a byte or bytearray slice.

        Args:
            key: Integer index or slice.

        Returns:
            An integer for a single index or a ``bytearray`` for a slice.
        """
        return self._data[key]

    def __delitem__(self, key: IndexOrSlice) -> None:
        """Delete one byte or a slice.

        Args:
            key: Integer index or slice to delete.

        Raises:
            IndexError: If an integer index is out of range.
            TypeError: If ``key`` is neither an integer nor a slice.
        """
        del self._data[key]

    def __bytes__(self) -> bytes:
        """Return an immutable copy of the content."""
        return bytes(self._data)

    def __iadd__(self, values: BytesLike | Iterable[int]) -> Self:
        """Append byte values in place.

        Args:
            values: Bytes or integers from 0 to 255 to append.

        Returns:
            This instance after appending the values.

        Raises:
            BufferError: If the resulting content would exceed ``maxlen``.
        """
        self.extend(values)
        return self

    def __repr__(self) -> str:
        """Return an unambiguous representation of the instance."""
        return (
            f"{type(self).__name__}"
            f"(maxlen={self.maxlen}, initial={bytes(self._data)!r})"
        )
