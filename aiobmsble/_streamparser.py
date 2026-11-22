"""Private stream parser for protocol plugins.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from typing import Final


class StreamParser:
    """Stream parsers with start/end and escape handling."""

    MAX_SIZE: Final[int] = 1024

    def __init__(self, DLE: int = 0x10, STX: int = 0x02, ETX: int = 0x03) -> None:
        """Initialize parser with specified control characters."""
        self.DLE: Final[int] = DLE
        self.STX: Final[int] = STX
        self.ETX: Final[int] = ETX
        self._in_frame: bool = False
        self._escaped: bool = False
        self._buffer: bytearray = bytearray()

    def feed(self, data: bytes | bytearray) -> bytes | None:
        """Feed arbitrary chunks of bytes."""
        result_frame: bytes | None = None
        dle: Final[int] = self.DLE
        stx: Final[int] = self.STX
        etc: Final[int] = self.ETX
        max_size: Final[int] = self.MAX_SIZE
        in_frame: bool = self._in_frame
        escaped: bool = self._escaped
        buffer: bytearray = self._buffer

        for b in data:
            if not in_frame:
                if escaped and b == stx:
                    in_frame = True
                    buffer.clear()
                    escaped = False
                    continue
                escaped = b in (dle, stx, etc)
                continue

            if escaped:
                escaped = False
                if b in (dle, stx):
                    buffer.append(b)
                if b == etc:
                    in_frame = False
                    result_frame = bytes(buffer)
                    buffer.clear()
                continue

            if b in (dle, etc):
                escaped = True
                continue

            buffer.append(b)
            if len(buffer) > max_size:
                in_frame = False
                buffer.clear()
                continue

        self._in_frame = in_frame
        self._escaped = escaped
        return result_frame
