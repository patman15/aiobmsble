"""Package for battery management systems (BMS) via Bluetooth LE (aiobmsble).

Asynchronous Library to Query Battery Management Systems via Bluetooth LE

This library is intended to query data from battery management systems
that use Bluetooth LE. Stand-alone usage is possible in any Python environment
(with necessary dependencies installed).

User API: data types and BMS discovery. Plugin-author types live in `aiobmsble.plugin`.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from contextlib import suppress
from dataclasses import dataclass
from enum import IntEnum, StrEnum, auto, unique
from importlib.metadata import PackageNotFoundError, version
from typing import Self, TypedDict

__all__ = [
    "BMSConfig",
    "BMSInfo",
    "BMSLimits",
    "BMSMode",
    "BMSProblem",
    "BMSSample",
    "BatterySample",
    "Limit",
    "PackSample",
    "PrbType",
    "Severity",
    "TempSensor",
    "Threshold",
    "__version__",
]

__version__: str = "0.0.0.dev0"
with suppress(PackageNotFoundError):
    __version__ = version("aiobmsble")

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
        """Hash the TempSensor based on its value (consistent with equality to numbers)."""
        return hash(self.value)

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
    SYSTEM_OVERTEMP = auto()
    SYSTEM_UNDERTEMP = auto()
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
    problem_code: int  # BMS specific code, 0 no problem
    problems: list[BMSProblem]  # decoded problem_code, present if plugin defines _PROBLEMS

    # BMS switches
    chrg_mosfet: bool  # True: enabled
    dischrg_mosfet: bool  # True: enabled
    heater: bool  # True: enabled/heating

    # battery pack data
    packs: list[PackSample]  # data from battery sub-systems


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

