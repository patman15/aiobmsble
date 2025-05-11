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
    battery_level: int | float  # [%]
    current: float  # [A]
    power: float  # [W]
    temperature: int | float  # [°C]
    voltage: float  # [V]
    cycle_capacity: int | float  # [Wh]
    cycles: int  # [#]
    delta_voltage: float  # [V]
    problem: bool
    runtime: int  # [s]
    # internal
    cell_voltages: list[float]  # [V]
    cycle_charge: int | float  # [Ah]
    design_capacity: int  # [Ah]
    temp_values: list[int | float]  # [°C]
    problem_code: int


class AdvertisementPattern(TypedDict, total=False):
    """Optional patterns that can match Bleak advertisement data."""

    local_name: str  # name pattern that supports Unix shell-style wildcards
    service_uuid: str  # 128-bit UUID that the device must advertise
    service_data_uuid: str  # service data for the service UUID
    manufacturer_id: int  # required manufacturer ID
    manufacturer_data_start: list[int]  # required starting bytes of manufacturer data
