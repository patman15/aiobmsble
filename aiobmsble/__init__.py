"""Asynchronous library to query battery management systems (BMS) via Bluetooth LE.

This library is intended to query data from battery management systems
that use Bluetooth LE. Stand-alone usage is possible in any Python environment
(with necessary dependencies installed).

**Warning:** BMS readings are telemetry only. Do not use them to control actions that
are safety relevant, e.g. prevent battery damage, overheating, or fire.

.. include:: ../docs/quickstart.md

## Modules

- `aiobmsble`: data types returned by a BMS (`BMSSample`, `BMSInfo`, `BMSLimits`, ...)
  and the connection configuration `BMSConfig`.
- `aiobmsble.basebms`: `aiobmsble.basebms.BaseBMS`, the interface all BMS classes implement.
- `aiobmsble.exceptions`: errors raised by BMS operations, also exported here.
- `aiobmsble.utils`: helpers to find the BMS class for a device (`available_bms()`,
  `load_bms_plugins()`), convert advertisement dictionaries (`adv_dict_to_advdata()`),
  and summarize problems (`problem_levels()`).
- `aiobmsble.test_data`: recorded advertisements for integration tests.
- `aiobmsble.plugin`: types for plugin authors.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from enum import IntEnum, StrEnum, auto, unique
from importlib.metadata import PackageNotFoundError, version
from types import MappingProxyType
from typing import Final, NamedTuple, Self, TypedDict

from aiobmsble.exceptions import (
    BMSAuthError,
    BMSCommandRejectedError,
    BMSConfigError,
    BMSConnectionError,
    BMSDataError,
    BMSError,
    BMSTimeoutError,
    BMSUnsupportedError,
)

__all__: list[str] = [
    "PROBLEM_DEFAULTS",
    "BMSAuthError",
    "BMSCommandRejectedError",
    "BMSConfig",
    "BMSConfigError",
    "BMSConnectionError",
    "BMSDataError",
    "BMSError",
    "BMSInfo",
    "BMSLimits",
    "BMSMode",
    "BMSProblem",
    "BMSSample",
    "BMSTimeoutError",
    "BMSUnsupportedError",
    "BatterySample",
    "Limit",
    "PackSample",
    "PrbDefault",
    "PrbType",
    "Severity",
    "TSKind",
    "TempSensor",
    "Threshold",
    "__version__",
]

__version__: str = "0.0.0.dev0"
with suppress(PackageNotFoundError):
    __version__ = version("aiobmsble")


@unique
class BMSMode(IntEnum):
    """Enumeration of BMS modes."""

    UNKNOWN = -1
    BULK = 0x00
    ABSORPTION = 0x01
    FLOAT = 0x02


@unique
class TSKind(IntEnum):
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


@dataclass(frozen=True, slots=True)
class TempSensor:
    """Represents a temperature sensor reading from the BMS.

    Instances compare equal to plain numbers by value, but to other `TempSensor`
    instances by value and type. Ordering (`<`, `max()`, ...) uses the value only.

    Note: equality is not transitive. For example, `TempSensor(1, CELL) == 1` and
    `1 == TempSensor(1, GENERIC)` are both `True`, yet
    `TempSensor(1, CELL) != TempSensor(1, GENERIC)`. Do not rely on transitivity
    when comparing mixed sensor types and plain numbers. Hashing uses the value only,
    so sensors of different types with equal values may share a hash bucket.
    """

    value: float
    kind: TSKind = TSKind.GENERIC

    def __eq__(self: Self, other: object) -> bool:
        """Compare against other TempSensor including type or int, float."""

        if isinstance(other, TempSensor):
            return (self.kind, self.value) == (other.kind, other.value)
        if isinstance(other, (int, float)) and not isinstance(other, bool):
            return self.value == other
        return NotImplemented

    def __float__(self) -> float:
        """Return the temperature value as a float."""
        return float(self.value)

    @staticmethod
    def _cmp_value(other: object) -> float | None:
        if isinstance(other, TempSensor):
            return other.value
        if isinstance(other, (int, float)) and not isinstance(other, bool):
            return other
        return None

    def __lt__(self, other: object) -> bool:
        """Compare temperature value."""
        if (val := self._cmp_value(other)) is None:
            return NotImplemented
        return self.value < val

    def __le__(self, other: object) -> bool:
        """Compare temperature value."""
        if (val := self._cmp_value(other)) is None:
            return NotImplemented
        return self.value <= val

    def __gt__(self, other: object) -> bool:
        """Compare temperature value."""
        if (val := self._cmp_value(other)) is None:
            return NotImplemented
        return self.value > val

    def __ge__(self, other: object) -> bool:
        """Compare temperature value."""
        if (val := self._cmp_value(other)) is None:
            return NotImplemented
        return self.value >= val

    def __hash__(self) -> int:
        """Hash the TempSensor based on its value (consistent with equality to numbers)."""
        return hash(self.value)

    def __repr__(self) -> str:
        """Return the string representation of the sensor value/type."""
        return f"{self.__class__.__name__}({self.value!r}, {self.kind!r})"


@unique
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

    CELL_OV = auto()
    CELL_UV = auto()
    PACK_OV = auto()
    PACK_UV = auto()
    CELL_IMBALANCE = auto()
    CHARGE_OC = auto()
    DISCHARGE_OC = auto()
    SHORT_CIRCUIT = auto()
    CHARGE_OT = auto()
    CHARGE_UT = auto()
    DISCHARGE_OT = auto()
    DISCHARGE_UT = auto()
    MOSFET_OT = auto()
    SYSTEM_OT = auto()
    SYSTEM_UT = auto()
    LOW_SOC = auto()
    FET_LOCKED = auto()
    FET_FAILURE = auto()
    AFE_FAILURE = auto()
    CELL_FAILURE = auto()
    SENSOR_FAILURE = auto()
    COMM_FAILURE = auto()
    FUSE_BLOWN = auto()
    OTHER = auto()  # vendor specific, requires BMSPrbDef.text
    UNKNOWN = auto()  # bit set but not described by the plugin


class PrbDefault(NamedTuple):
    """Default severity and human readable description of a problem type."""

    level: Severity
    text: str


PROBLEM_DEFAULTS: Final[Mapping[PrbType, PrbDefault]] = MappingProxyType(
    {
        PrbType.CELL_OV: PrbDefault(Severity.PROTECT, "Cell overvoltage"),
        PrbType.CELL_UV: PrbDefault(Severity.PROTECT, "Cell undervoltage"),
        PrbType.PACK_OV: PrbDefault(Severity.PROTECT, "Pack overvoltage"),
        PrbType.PACK_UV: PrbDefault(Severity.PROTECT, "Pack undervoltage"),
        PrbType.CELL_IMBALANCE: PrbDefault(Severity.WARN, "Cell voltage imbalance"),
        PrbType.CHARGE_OC: PrbDefault(Severity.PROTECT, "Charge overcurrent"),
        PrbType.DISCHARGE_OC: PrbDefault(Severity.PROTECT, "Discharge overcurrent"),
        PrbType.SHORT_CIRCUIT: PrbDefault(Severity.PROTECT, "Short circuit"),
        PrbType.CHARGE_OT: PrbDefault(Severity.PROTECT, "Charge overtemperature"),
        PrbType.CHARGE_UT: PrbDefault(Severity.PROTECT, "Charge undertemperature"),
        PrbType.DISCHARGE_OT: PrbDefault(Severity.PROTECT, "Discharge overtemperature"),
        PrbType.DISCHARGE_UT: PrbDefault(Severity.PROTECT, "Discharge undertemperature"),
        PrbType.MOSFET_OT: PrbDefault(Severity.PROTECT, "MOSFET overtemperature"),
        # examples for SYSTEM_*: ambient, PCB, board, battery temperature. NOT: MOSFET temperature
        PrbType.SYSTEM_OT: PrbDefault(Severity.PROTECT, "System overtemperature"),
        PrbType.SYSTEM_UT: PrbDefault(Severity.PROTECT, "System undertemperature"),
        PrbType.LOW_SOC: PrbDefault(Severity.WARN, "Low state of charge"),
        PrbType.FET_LOCKED: PrbDefault(Severity.INFO, "MOSFET locked"),
        PrbType.FET_FAILURE: PrbDefault(Severity.FAULT, "MOSFET"),
        PrbType.AFE_FAILURE: PrbDefault(Severity.FAULT, "Analog front-end"),
        PrbType.CELL_FAILURE: PrbDefault(Severity.FAULT, "Cell"),
        PrbType.SENSOR_FAILURE: PrbDefault(Severity.FAULT, "Sensor"),
        PrbType.COMM_FAILURE: PrbDefault(Severity.FAULT, "Internal communication"),
        PrbType.FUSE_BLOWN: PrbDefault(Severity.FAULT, "Fuse blown"),
        PrbType.OTHER: PrbDefault(Severity.WARN, "Other problem"),
        PrbType.UNKNOWN: PrbDefault(Severity.WARN, "Unknown problem"),
    }
)
"""Default severity and description per problem type (read-only)."""


@dataclass(frozen=True, slots=True, init=False)
class BMSProblem:
    """Decoded problem reported by the BMS."""

    kind: PrbType
    """Generic problem category."""
    level: Severity
    """Severity of the problem."""
    text: str
    """Human readable (vendor specific) description."""

    def __init__(self, kind: PrbType, level: Severity | None = None, text: str = "") -> None:
        """Create a problem, omitted level and text default to those of the problem kind."""
        default: Final[PrbDefault] = PROBLEM_DEFAULTS[kind]
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "level", default.level if level is None else level)
        object.__setattr__(self, "text", text or default.text)

    def __str__(self) -> str:
        """Return human readable representation."""
        return f"{self.text} ({self.level.name.lower()})"

    def __repr__(self) -> str:
        """Return compact representation for logging."""
        return f"{self.__class__.__name__}({self.kind.name}, {self.level.name}, {self.text!r})"


class BatterySample(TypedDict, total=False):
    """Common fields for battery samples.

    Units: voltage [V], current [A], charge [Ah], energy [Wh], power [W], temperature [°C],
    level/health [%]. Current and power are positive while charging.
    Only fields that the BMS provides (or that can be derived) are present.
    """

    battery_level: float | int  # [%]
    battery_health: float | int  # [%]
    cell_count: int  # [#]
    cell_voltages: list[float]  # [V]
    current: float  # [A] (positive: charging)
    cycles: int  # [#]
    cycle_charge: float | int  # [Ah]
    cycle_energy: float | int  # [Wh]
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
    total_charge: int  # [Ah], charge discharged over lifetime
    pack_count: int  # [#]
    problem_code: int  # BMS specific code, 0 no problem
    problems: list[BMSProblem]  # decoded problem_code and failed value sanity checks

    # BMS switches
    chrg_mosfet: bool  # True: enabled
    dischrg_mosfet: bool  # True: enabled
    heater: bool  # True: enabled/heating

    # battery pack data
    packs: list[PackSample]  # data from battery sub-systems


@dataclass(slots=True, frozen=True)
class BMSConfig:
    """Configuration for the BMS (connection)."""

    keep_alive: bool = True
    """Keep the connection open between calls (faster, more stable)."""
    secret: str = ""
    """Application level secret/PIN, only used if the BMS class sets `ACCEPT_SECRET`."""


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

    trip: float
    """Trip point [V, A, °C]."""
    release: float | None = None
    """Recovery point, if reported."""
    delay: float | None = None
    """Trip delay [s], if reported."""


type BMSLimits = dict[Limit, Threshold]
"""Thresholds configured in the BMS, returned by `aiobmsble.basebms.BaseBMS.limits()`."""
