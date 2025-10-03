"""Package for battery management systems (BMS) via Bluetooth LE (aiobmsble).

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from collections.abc import Callable
from enum import IntEnum
from typing import Any, Literal, NamedTuple, TypedDict

type BMSvalue = Literal[
    "battery_charging",
    "battery_mode",
    "battery_level",
    "current",
    "power",
    "temperature",
    "voltage",
    "cycles",
    "cycle_capacity",
    "cycle_charge",
    "total_charge",
    "delta_voltage",
    "problem",
    "runtime",
    "balance_current",
    "cell_count",
    "cell_voltages",
    "design_capacity",
    "pack_count",
    "temp_sensors",
    "temp_values",
    "problem_code",
]

type BMSpackvalue = Literal[
    "pack_voltages",
    "pack_currents",
    "pack_battery_levels",
    "pack_cycles",
]


class BMSmode(IntEnum):
    """Enumeration of BMS modes."""

    UNKNOWN = -1
    BULK = 0x00
    ABSORPTION = 0x01
    FLOAT = 0x02


class BMSswitches(TypedDict, total=False):
    """Dictionary representing BMS switches."""

    charge_mosfet: bool  # True: enabled
    discharge_mosfet: bool  # True: enabled
    balancer: bool  # True: enabled/active
    dry_contacts: list[bool]  # True: closed/on, False: open/off


class BMSsample(TypedDict, total=False):
    """Dictionary representing a sample of battery management system (BMS) data."""

    battery_charging: bool  # True: battery charging
    battery_mode: BMSmode  # BMS charging mode
    battery_level: int | float  # [%]
    current: float  # [A] (positive: charging)
    power: float  # [W] (positive: charging)
    temperature: int | float  # [°C]
    voltage: float  # [V]
    cycle_capacity: int | float  # [Wh]
    cycles: int  # [#]
    delta_voltage: float  # [V]
    problem: bool  # True: problem detected
    runtime: int  # [s]
    # detailed information
    balance_current: float  # [A]
    cell_count: int  # [#]
    cell_voltages: list[float]  # [V]
    cycle_charge: int | float  # [Ah]
    total_charge: int  # [Ah], overall discharged
    design_capacity: int  # [Ah]
    pack_count: int  # [#]
    switches: BMSswitches  # BMS switches, e.g. (dis)charge MOSFET
    temp_sensors: int  # [#]
    temp_values: list[int | float]  # [°C]
    problem_code: int  # BMS specific code, 0 no problem
    # battery pack data
    pack_voltages: list[float]  # [V]
    pack_currents: list[float]  # [A]
    pack_battery_levels: list[int | float]  # [%]
    pack_cycles: list[int]  # [#]


class BMSdp(NamedTuple):
    """Representation of one BMS data point."""

    key: BMSvalue  # the key of the value to be parsed
    pos: int  # position within the message
    size: int  # size in bytes
    signed: bool  # signed value
    fct: Callable[[int], Any] = lambda x: x  # conversion function (default do nothing)
    idx: int = -1  # array index containing the message to be parsed


class MatcherPattern(TypedDict, total=False):
    """Optional patterns that can match Bleak advertisement data."""

    local_name: str  # name pattern that supports Unix shell-style wildcards
    service_uuid: str  # 128-bit UUID that the device must advertise
    service_data_uuid: str  # service data for the service UUID
    manufacturer_id: int  # required manufacturer ID
    manufacturer_data_start: list[int]  # required starting bytes of manufacturer data
    connectable: bool  # True if active connections to the device are required
