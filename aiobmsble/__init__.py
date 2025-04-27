"""Package for battery management systems (BMS) via Bluetooth LE."""

from typing import Literal, TypedDict

type BMSvalue = Literal[
    "battery_charging",
    "battery_level",
    "current",
    "power",
    "temperature",
    "voltage",
    "cycles",
    "cycle_capacity",
    "cycle_charge",
    "delta_voltage",
    "problem",
    "runtime",
    "cell_voltages",
    "design_capacity",
    "temp_values",
    "problem_code",
]


class BMSsample(TypedDict, total=False):
    """Dictionary representing a sample of battery management system (BMS) data."""

    battery_charging: bool
    battery_level: int | float
    current: float
    power: float
    temperature: int | float
    voltage: float
    cycle_capacity: int
    cycles: int
    delta_voltage: float
    problem: bool
    runtime: int
    # internal
    cell_voltages: list[float]
    cycle_charge: int
    design_capacity: int
    temp_values: list[int | float]
    problem_code: int


class AdvertisementPattern(TypedDict, total=False):
    """Optional patterns that can match a Bleak advertisement data"""

    local_name: str  # name pattern that supports Unix shell-style wildcards
    service_uuid: str  # 128-bit UUID that the device must advertise
    service_data_uuid: str  # service data for the service UUID
    manufacturer_id: int  # required manufacturer ID
    manufacturer_data_start: list[int]  # required starting bytes of manufacturer data
