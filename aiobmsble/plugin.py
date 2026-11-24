"""Plugin-author API for aiobmsble: types and helpers to implement BMS plugins.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from itertools import takewhile
from typing import Any, Final, Literal, NamedTuple, TypedDict

from aiobmsble import BMSProblem, Limit, PrbType, Severity

__all__: list[str] = [
    "BMSDp",
    "BMSPackValue",
    "BMSPrbDef",
    "BMSValue",
    "CommonValue",
    "LimitDp",
    "MatcherPattern",
    "ThresholdAttr",
    "b2str",
    "crc8",
    "crc_modbus",
    "crc_sum",
    "crc_xmodem",
    "decode_problems",
    "lrc_modbus",
    "lstr2int",
    "swap32",
]

type CommonValue = Literal[
    "battery_health",
    "battery_level",
    "cell_count",
    "cell_voltages",
    "current",
    "cycle_energy",
    "cycle_charge",
    "cycles",
    "delta_cell_voltage",
    "design_capacity",
    "power",
    "temp_count",
    "temperature",
    "voltage",
]

type BMSValue = Literal[
    CommonValue,
    "battery_charging",
    "battery_mode",
    "total_charge",
    "problem",
    "runtime",
    "balancer",
    "balance_current",
    "heater_current",
    "pack_count",
    "problem_code",
    "problems",
    "chrg_mosfet",
    "dischrg_mosfet",
    "heater",
]

type BMSPackValue = CommonValue


class BMSPrbDef(NamedTuple):
    """Map (a field of) a BMS problem code to a generic problem."""

    mask: int  # bit(s) of problem_code to evaluate
    kind: PrbType
    level: Severity | None = None  # None: default level of kind, see BMSProblem
    value: int | None = None  # None: any bit of mask set, else (code & mask) == value
    text: str = ""  # vendor specific description, empty: generic text of kind

    def matches(self, code: int) -> bool:
        """Return True if this definition applies to the problem code."""
        hit: Final[int] = code & self.mask
        if self.value is None:
            return bool(hit)
        return hit == self.value


@dataclass(frozen=True, slots=True)
class BMSDp[K: (BMSValue, BMSPackValue)]:
    """Representation of main BMS data point."""

    key: K
    pos: int  # position within the message
    size: int  # size in bytes
    signed: bool  # signed value
    fct: Callable[[int], Any] = lambda x: x  # conversion function (default do nothing)
    idx: int = -1  # array index containing the message to be parsed


type ThresholdAttr = Literal["trip", "release", "delay"]


@dataclass(frozen=True, slots=True)
class LimitDp:
    """Location and conversion of one threshold value in a raw frame."""

    prot: Limit
    attr: ThresholdAttr
    pos: int  # byte offset in frame
    size: int = 2  # size in bytes
    scale: float = 1.0  # value = raw * scale - offset
    offset: float = 0.0
    signed: bool = False
    invalid: int | None = None  # sentinel raw value meaning "disabled"


class MatcherPattern(TypedDict, total=False):
    """Optional patterns that can match Bleak advertisement data.

    All given keys must match (logical AND); omitted keys are not checked.

    - `service_data_uuid`: an empty string requires that the advertisement carries no service data.
    - `manufacturer_data_start`: only evaluated together with `manufacturer_id`.
    - `connectable`: compared to the `connectable` attribute of the advertisement, which
      is only provided by some Bluetooth stacks (e.g. Home Assistant); if the attribute is
      missing, the advertisement is treated as connectable.
    - `local_name`: case-sensitive.
    """

    local_name: str  # name pattern that supports Unix shell-style wildcards
    manufacturer_data_start: list[int]  # start bytes of manufacturer data
    manufacturer_id: int  # required manufacturer ID
    oui: str  # required OUI used in the MAC address (first 3 bytes)
    service_data_uuid: str  # service data for the service UUID
    service_uuid: str  # 128-bit UUID that the device must advertise
    connectable: bool  # True if active connections to the device are required


def decode_problems(code: int, defs: Iterable[BMSPrbDef]) -> list[BMSProblem]:
    """Translate a BMS problem code into generic problems.

    Bits not explained by a matching definition are reported as UNKNOWN problems: a
    value coded field (definitions with `value`) holding an undefined value is reported
    once with its value, any other bit is reported individually. Problems with the same
    kind and text are reported once, with the highest severity.

    Args:
        code: BMS specific problem code, 0 means no problem
        defs: definitions mapping (fields of) the code to generic problems

    Returns:
        list[BMSProblem]: decoded problems in order of first occurrence

    """
    problems: list[BMSProblem] = []
    explained: int = 0
    fields: dict[int, bool] = {}  # mask of value coded field: definition matched
    for d in defs:
        hit: bool = d.matches(code)
        if d.value is not None:
            fields[d.mask] = fields.get(d.mask, False) or hit
        if hit:
            explained |= d.mask
            problems.append(BMSProblem(d.kind, d.level, d.text))
    unknown: Final[str] = BMSProblem(PrbType.UNKNOWN).text
    for mask, matched in fields.items():
        if not matched and code & mask:
            explained |= mask
            value: int = (code & mask) >> ((mask & -mask).bit_length() - 1)
            problems.append(BMSProblem(PrbType.UNKNOWN, text=f"{unknown} value {value:#04x}"))
    remaining: Final[int] = code & ~explained
    problems.extend(
        BMSProblem(PrbType.UNKNOWN, text=f"{unknown} bit {bit}")
        for bit in range(remaining.bit_length())
        if remaining >> bit & 1
    )
    # deduplicate problems by kind and text
    worst: dict[tuple[PrbType, str], BMSProblem] = {}
    for problem in problems:
        key: tuple[PrbType, str] = (problem.kind, problem.text)
        if key not in worst or problem.level > worst[key].level:
            worst[key] = problem
    return list(worst.values())


def b2str(b: bytes | bytearray) -> str:
    """Decode bytes to string, stopping at the first non-printable character."""
    s: Final[str] = b.decode("ascii", errors="ignore")
    for i, c in enumerate(s):
        if not c.isprintable():
            return s[:i].strip()
    return s.strip()


def lstr2int(string: str) -> int:
    """Convert the beginning of a string to an integer, till first non-digit is found."""
    return int("".join(takewhile(str.isdigit, string)))


def swap32(value: int, signed: bool = False) -> int:
    """Swap high and low 16bit in 32bit integer."""
    value = ((value >> 16) & 0xFFFF) | (value & 0xFFFF) << 16
    if signed and value & 0x80000000:
        value -= 0x100000000
    return value


def crc_modbus(data: bytes | bytearray) -> int:
    """Calculate CRC-16-CCITT MODBUS."""
    crc: int = 0xFFFF
    for i in data:
        crc ^= i & 0xFF
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc % 2 else (crc >> 1)
    return crc & 0xFFFF


def lrc_modbus(data: bytes | bytearray) -> int:
    """Calculate MODBUS LRC."""
    return ((sum(data) ^ 0xFFFF) + 1) & 0xFFFF


def crc_xmodem(data: bytes | bytearray) -> int:
    """Calculate CRC-16-CCITT XMODEM."""
    crc: int = 0x0000
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = (crc << 1) ^ 0x1021 if (crc & 0x8000) else (crc << 1)
    return crc & 0xFFFF


def crc8(data: bytes | bytearray) -> int:
    """Calculate CRC-8/MAXIM-DOW."""
    crc: int = 0x00

    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8C if crc & 0x1 else crc >> 1

    return crc & 0xFF


def crc_sum(data: bytes | bytearray, size: int = 1) -> int:
    """Calculate the sum of the data bytes truncated to the specified size.

    Args:
        data: the input data for which the sum is to be calculated
        size: the size of the sum in bytes (default: 1)

    Returns:
        int: sum of all bytes modulo 2^(8 * size)

    """
    return sum(data) & ((1 << (8 * size)) - 1)
