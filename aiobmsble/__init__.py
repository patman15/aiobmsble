"""Package for battery management systems (BMS) via Bluetooth LE (aiobmsble).

Asynchronous Library to Query Battery Management Systems via Bluetooth LE

This library is intended to query data from battery management systems
that use Bluetooth LE. Stand-alone usage is possible in any Python environment
(with necessary dependencies installed).

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from enum import IntEnum, StrEnum, auto, unique
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Final, Literal, NamedTuple, Self, TypedDict

__version__: str = "0.0.0.dev0"
with suppress(PackageNotFoundError):
    __version__ = version("aiobmsble")

type CommonValue = Literal[
    "battery_health",
    "battery_level",
    "cell_count",
    "cell_voltages",
    "current",
    "cycle_capacity",
    "cycle_charge",
    "cycles",
    "delta_cell_voltage",
    "design_capacity",
    "temp_count",
    "temperature",
    "voltage",
]

type BMSValue = CommonValue | Literal[
    "battery_charging",
    "battery_mode",
    "power",
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

type BMSpackvalue = CommonValue


class BMSMode(IntEnum):
    """Enumeration of BMS modes."""

    UNKNOWN = -1
    BULK = 0x00
    ABSORPTION = 0x01
    FLOAT = 0x02


@dataclass(frozen=True, slots=True)
class TempSensor:
    """Represents a temperature sensor reading from the BMS."""

    @unique
    class T(IntEnum):
        """Enumeration of temperature sensor source types."""

        GENERIC = 0x0
        CELL = auto()
        CELL_MAX = auto()
        CELL_MIN = auto()
        MOSFET = auto()
        PCB = auto()
        HEATER = auto()
        BALANCER = auto()
        AMBIENT = auto()

    value: float
    type: T = T.GENERIC

    def __eq__(self: Self, other: object) -> bool:
        """Compare against other TempSensor including type or int, float."""

        if isinstance(other, TempSensor):
            return (self.type, self.value) == (other.type, other.value)
        if isinstance(other, (int, float)):
            return self.value == other
        return False

    def __float__(self) -> float:
        """Return the temperature value as a float."""
        return float(self.value)

    def __hash__(self) -> int:
        """Hash the TempSensor based on its value and type."""
        return hash((self.value, self.type))

    def __repr__(self) -> str:
        """Return the string representation of the sensor value/type."""
        return f"{self.__class__.__name__}({self.value!r}, {self.type!r})"


class Severity(IntEnum):
    """Problem severity, ordered so that max() yields the worst level."""

    OK = 0
    INFO = 1  # operating state notice, no limit violated
    WARN = 2  # limit approached, BMS still operational
    PROTECT = 3  # protection tripped, charging and/or discharging inhibited
    FAULT = 4  # hardware/internal failure


@unique
class PrbType(StrEnum):
    """Generic problem categories (value = stable key)."""

    CELL_OVERVOLTAGE = auto()
    CELL_UNDERVOLTAGE = auto()
    PACK_OVERVOLTAGE = auto()
    PACK_UNDERVOLTAGE = auto()
    CELL_IMBALANCE = auto()
    CHARGE_OVERCURRENT = auto()
    DISCHARGE_OVERCURRENT = auto()
    SHORT_CIRCUIT = auto()
    CHARGE_OVERTEMP = auto()
    CHARGE_UNDERTEMP = auto()
    DISCHARGE_OVERTEMP = auto()
    DISCHARGE_UNDERTEMP = auto()
    MOSFET_OVERTEMP = auto()
    AMBIENT_OVERTEMP = auto()
    AMBIENT_UNDERTEMP = auto()
    BATTERY_OVERTEMP = auto()  # not specific to charging or discharging
    LOW_SOC = auto()
    FET_LOCKED = auto()
    FET_FAILURE = auto()
    AFE_FAILURE = auto()
    CELL_FAILURE = auto()
    SENSOR_FAILURE = auto()
    COMM_FAILURE = auto()
    FUSE_BLOWN = auto()
    OTHER = auto()  # vendor specific, requires ProblemDef.text
    UNKNOWN = auto()  # bit set but not described by the plugin


class PrbDefault(NamedTuple):
    """Default severity and human readable description of a problem type."""

    level: Severity
    text: str


PROBLEM_DEFAULTS: Final[dict[PrbType, PrbDefault]] = {
    PrbType.CELL_OVERVOLTAGE: PrbDefault(Severity.PROTECT, "Cell overvoltage"),
    PrbType.CELL_UNDERVOLTAGE: PrbDefault(Severity.PROTECT, "Cell undervoltage"),
    PrbType.PACK_OVERVOLTAGE: PrbDefault(Severity.PROTECT, "Pack overvoltage"),
    PrbType.PACK_UNDERVOLTAGE: PrbDefault(Severity.PROTECT, "Pack undervoltage"),
    PrbType.CELL_IMBALANCE: PrbDefault(Severity.WARN, "Cell voltage imbalance"),
    PrbType.CHARGE_OVERCURRENT: PrbDefault(Severity.PROTECT, "Charge overcurrent"),
    PrbType.DISCHARGE_OVERCURRENT: PrbDefault(Severity.PROTECT, "Discharge overcurrent"),
    PrbType.SHORT_CIRCUIT: PrbDefault(Severity.PROTECT, "Short circuit"),
    PrbType.CHARGE_OVERTEMP: PrbDefault(Severity.PROTECT, "Charge over-temperature"),
    PrbType.CHARGE_UNDERTEMP: PrbDefault(Severity.PROTECT, "Charge under-temperature"),
    PrbType.DISCHARGE_OVERTEMP: PrbDefault(Severity.PROTECT, "Discharge over-temperature"),
    PrbType.DISCHARGE_UNDERTEMP: PrbDefault(Severity.PROTECT, "Discharge under-temperature"),
    PrbType.MOSFET_OVERTEMP: PrbDefault(Severity.PROTECT, "MOSFET over-temperature"),
    PrbType.AMBIENT_OVERTEMP: PrbDefault(Severity.PROTECT, "Ambient over-temperature"),
    PrbType.AMBIENT_UNDERTEMP: PrbDefault(Severity.PROTECT, "Ambient under-temperature"),
    PrbType.BATTERY_OVERTEMP: PrbDefault(Severity.PROTECT, "Battery over-temperature"),
    PrbType.LOW_SOC: PrbDefault(Severity.WARN, "Low state of charge"),
    PrbType.FET_LOCKED: PrbDefault(Severity.INFO, "MOSFET locked"),
    PrbType.FET_FAILURE: PrbDefault(Severity.FAULT, "MOSFET failure"),
    PrbType.AFE_FAILURE: PrbDefault(Severity.FAULT, "Analog front-end failure"),
    PrbType.CELL_FAILURE: PrbDefault(Severity.FAULT, "Cell failure"),
    PrbType.SENSOR_FAILURE: PrbDefault(Severity.FAULT, "Sensor failure"),
    PrbType.COMM_FAILURE: PrbDefault(Severity.FAULT, "Internal communication failure"),
    PrbType.FUSE_BLOWN: PrbDefault(Severity.FAULT, "Fuse blown"),
    PrbType.OTHER: PrbDefault(Severity.WARN, "Other problem"),
    PrbType.UNKNOWN: PrbDefault(Severity.WARN, "Unknown problem"),
}
"""Default severity and generic description of each problem type."""


class BMSPrbDef(NamedTuple):
    """Map (a field of) a BMS problem code to a generic problem."""

    mask: int  # bit(s) of problem_code to evaluate
    kind: PrbType
    level: Severity | None = None  # None: use PROBLEM_DEFAULTS[kind].level
    value: int | None = None  # None: any bit of mask set, else (code & mask) == value
    text: str = ""  # vendor specific description, overrides generic text

    @property
    def severity(self) -> Severity:
        """Return the explicit level or the default level of the problem kind."""
        return PROBLEM_DEFAULTS[self.kind].level if self.level is None else self.level

    def matches(self, code: int) -> bool:
        """Return True if this definition applies to the problem code."""
        hit: Final[int] = code & self.mask
        if self.value is None:
            return bool(hit)
        return hit == self.value


@dataclass(frozen=True, slots=True)
class BMSProblem:
    """Decoded problem reported by the BMS."""

    kind: PrbType
    level: Severity
    text: str

    def __str__(self) -> str:
        """Return human readable representation."""
        return f"{self.text} ({self.level.name.lower()})"

    def __repr__(self) -> str:
        """Return compact representation for logging."""
        return f"{self.__class__.__name__}({self.kind.name}, {self.level.name}, {self.text!r})"


class BatterySample(TypedDict, total=False):
    """Common fields for battery samples."""

    battery_level: float | int  # [%]
    battery_health: float | int  # [%]
    cell_count: int  # [#]
    cell_voltages: list[float]  # [V]
    current: float  # [A] (positive: charging)
    cycles: int  # [#]
    cycle_charge: int | float  # [Ah]
    cycle_capacity: int | float  # [Wh]
    delta_cell_voltage: float  # [V]
    design_capacity: int  # [Ah]
    power: float  # [W] (positive: charging)
    temp_count: int  # [#]
    temperature: list[TempSensor]  # [°C]
    voltage: float  # [V]


class PackSample(BatterySample, total=False):
    """Dictionary representing a sample of a battery sub-system."""

    # check pace_bms.py before adding items


class BMSSample(BatterySample, total=False):
    """Dictionary representing a sample of battery management system (BMS) data."""

    # BMS-specific fields
    battery_charging: bool  # True: battery charging
    battery_mode: BMSMode  # BMS charging mode
    problem: bool  # True: problem detected
    runtime: int  # [s]

    # detailed information
    balancer: bool | int  # False: off, True: active or bit mask, 1: enabled/active
    balance_current: float  # [A]
    heater_current: float  # [A]
    total_charge: int  # [Ah], overall discharged
    pack_count: int  # [#]
    problem_code: int  # BMS specific code, 0 no problem, max. 64 bit
    problems: list[BMSProblem]  # decoded problem_code, present if plugin defines _PROBLEMS

    # BMS switches
    chrg_mosfet: bool  # True: enabled
    dischrg_mosfet: bool  # True: enabled
    heater: bool  # True: enabled/heating

    # battery pack data
    packs: list[PackSample]  # data from battery sub-systems


class BMSDp(NamedTuple):
    """Representation of main BMS data point."""

    key: BMSValue
    pos: int  # position within the message
    size: int  # size in bytes
    signed: bool  # signed value
    fct: Callable[[int], Any] = lambda x: x  # conversion function (default do nothing)
    idx: int = -1  # array index containing the message to be parsed


class BMSPDp(NamedTuple):
    """Representation of pack data point."""

    key: BMSpackvalue
    pos: int  # position within the message
    size: int  # size in bytes
    signed: bool  # signed value
    fct: Callable[[int], Any] = lambda x: x  # conversion function (default do nothing)
    idx: int = -1  # array index containing the message to be parsed


@dataclass(slots=True, frozen=True)
class BMSConfig:
    """Configuration for the BMS (connection)."""

    keep_alive: bool = True  # keep connection after querying (enhances stability)
    secret: str = ""  # application level secret for authentication


class BMSInfo(TypedDict, total=False):
    """Human readable information about the BMS device."""

    fw_version: str
    manufacturer: str
    model: str
    model_id: str
    name: str
    serial_number: str
    sw_version: str
    hw_version: str


@unique
class Limit(StrEnum):
    """Protection functions a BMS may implement (value = stable key)."""

    # cell voltage
    CELL_OVP = auto()
    CELL_UVP = auto()
    # pack voltage
    PACK_OVP = auto()
    PACK_UVP = auto()
    # current
    CHARGE_OCP = auto()
    DISCHARGE_OCP = auto()
    # temperature
    CHARGE_OTP = auto()
    CHARGE_UTP = auto()
    DISCHARGE_OTP = auto()
    DISCHARGE_UTP = auto()
    MOS_OTP = auto()


@dataclass(frozen=True, slots=True, kw_only=True)
class Threshold:
    """A single protection threshold as configured in the BMS.

    Trip/release points at which the BMS activates/releases a protection.
    They are not the operating envelope of the battery and must not be used as
    charger/inverter set points.
    """

    trip: float  # trip point [V, A, °C]
    release: float | None = None  # recovery point, if reported
    delay: float | None = None  # [s] trip delay, if reported


type BMSLimits = dict[Limit, Threshold]
"""Thresholds configured in the BMS."""

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
    """Optional patterns that can match Bleak advertisement data."""

    local_name: str  # name pattern that supports Unix shell-style wildcards
    manufacturer_data_start: list[int]  # start bytes of manufacturer data
    manufacturer_id: int  # required manufacturer ID
    oui: str  # required OUI used in the MAC address (first 3 bytes)
    service_data_uuid: str  # service data for the service UUID
    service_uuid: str  # 128-bit UUID that the device must advertise
    connectable: bool  # True if active connections to the device are required
