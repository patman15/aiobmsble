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
from enum import IntEnum, auto, unique
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Literal, NamedTuple, Self, TypedDict

__version__: str = "0.0.0.dev0"
with suppress(PackageNotFoundError):
    __version__ = version("aiobmsble")

type CommonValue = Literal[
    "battery_health",
    "battery_level",
    "cell_count",
    "cell_voltages",
    "current",
    "cycle_charge",
    "cycles",
    "delta_voltage",
    "design_capacity",
    "temp_sensors",
    "temp_values",
    "voltage",
]

type BMSValue = CommonValue | Literal[
    "battery_charging",
    "battery_mode",
    "power",
    "temperature",
    "cycle_capacity",
    "total_charge",
    "problem",
    "runtime",
    "balancer",
    "balance_current",
    "pack_count",
    "problem_code",
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


class BatterySample(TypedDict, total=False):
    """Common fields for battery samples."""

    battery_level: float | int  # [%]
    battery_health: float | int  # [%]
    cell_count: int  # [#]
    cell_voltages: list[float]  # [V]
    current: float  # [A]
    cycles: int  # [#]
    cycle_charge: int | float  # [Ah]
    delta_voltage: float  # [V]
    design_capacity: int  # [Ah]
    temp_sensors: int  # [#]
    temp_values: list[TempSensor]  # [°C]
    voltage: float  # [V]


class PackSample(BatterySample, total=False):
    """Dictionary representing a sample of a battery sub-system."""


class BMSSample(BatterySample, total=False):
    """Dictionary representing a sample of battery management system (BMS) data."""

    # BMS-specific fields
    battery_charging: bool  # True: battery charging
    battery_mode: BMSMode  # BMS charging mode
    power: float  # [W] (positive: charging)
    temperature: int | float  # [°C]
    cycle_capacity: int | float  # [Wh]
    problem: bool  # True: problem detected
    runtime: int  # [s]

    # detailed information
    balancer: bool | int  # False: off, True: active or bit mask, 1: enabled/active
    balance_current: float  # [A]
    total_charge: int  # [Ah], overall discharged
    pack_count: int  # [#]
    problem_code: int  # BMS specific code, 0 no problem, max. 64 bit

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

    default_manufacturer: str
    default_model: str
    default_name: str
    fw_version: str
    manufacturer: str
    model: str
    model_id: str
    name: str
    serial_number: str
    sw_version: str
    hw_version: str


class MatcherPattern(TypedDict, total=False):
    """Optional patterns that can match Bleak advertisement data."""

    local_name: str  # name pattern that supports Unix shell-style wildcards
    manufacturer_data_start: list[int]  # start bytes of manufacturer data
    manufacturer_id: int  # required manufacturer ID
    oui: str  # required OUI used in the MAC address (first 3 bytes)
    service_data_uuid: str  # service data for the service UUID
    service_uuid: str  # 128-bit UUID that the device must advertise
    connectable: bool  # True if active connections to the device are required
