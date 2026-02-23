#!/usr/bin/env python3
"""Generates a markdown table of natively reported data from the BMSs.

Lines are BMS types (from aiobmsble/bms/*_bms.py)
Columns are the fields in `BMSSample` directly filled from received data
A "✓" means that the data is natively available.
A "." means that the data is not natively available, but all required fields for its calculation are available.
Empty means that the data is not available at all.
"""
import csv
from importlib import import_module
from pathlib import Path
import re
from types import ModuleType
from typing import Final

from aiobmsble import BMSSample, BMSValue
from aiobmsble.basebms import BaseBMS

ALWAYS_CALC: Final[frozenset[str]] = frozenset({"problem"})
ROOT: Final = Path(__file__).parents[1]
BMS_DIR: Final = ROOT / "aiobmsble" / "bms"
CSV_FILE: Final = ROOT / "docs" / "available_bms_data.csv"
INIT: Final = "aiobmsble"


def get_bmssample_fields(init_module: str) -> tuple[BMSValue, ...]:
    """Return the field names of the BMSSample dataclass."""

    module: ModuleType = import_module(init_module)
    return tuple(module.BMSSample.__annotations__.keys())


def file_has_field(path: Path, field: str) -> bool:
    """Check if the given BMS module file references the specified field."""

    txt: Final[str] = path.read_text(encoding="utf8")
    patterns: Final[list[str]] = [
        rf'BMSDp\(\s*["\']{re.escape(field)}["\']',  # field in _FIELDS via BMSDp(...)
        rf'\bresult\[\s*["\']{re.escape(field)}["\']\s*\]',  # result["field"]
        rf'\bdata\[\s*["\']{re.escape(field)}["\']\s*\]',  # data["field"]
        rf'["\']{re.escape(field)}["\']\s*:',  # dict literal 'field': ...
        rf'\("{re.escape(field)}", \d+, ',  # tuples ("field", pos, ...
        # rf"\b{re.escape(field)}\b",  # fallback bareword
    ]
    return any(re.search(p, txt) for p in patterns)


def get_bms_info(path: Path) -> tuple[str, str]:
    """Extract default_manufacturer and default_model from BMS INFO class variable."""

    module: ModuleType = import_module(f"aiobmsble.bms.{path.stem}")
    return module.BMS.INFO.get("default_manufacturer"), module.BMS.INFO.get(
        "default_model"
    )


def main() -> None:
    """Generate and print a markdown table of BMS data availability."""

    fields: Final[tuple[BMSValue, ...]] = tuple(
        field for field in get_bmssample_fields(INIT)
    )
    bms_files: Final[list[Path]] = sorted(
        p for p in BMS_DIR.glob("*_bms.py") if p.is_file()
    )
    header: Final[tuple[str, ...]] = (
        "BMS",
        *(field.replace("_", " ") for field in fields),
    )
    rows: list[list[str]] = []

    calculations: Final = BaseBMS._calculation_registry(BMSSample())  # noqa: SLF001

    for f in bms_files:
        manufacturer, model = get_bms_info(f)
        bms_name: str = (
            f"{manufacturer} ({model})"
            if manufacturer and model
            else f.name.removesuffix("_bms.py")
        )
        marks: tuple[str, ...] = tuple(
            ("✓" if file_has_field(f, field) else "." if field in ALWAYS_CALC else "")
            for field in fields
        )

        available_fields: list[BMSValue] = [
            field for field in fields if file_has_field(f, field)
        ]
        for field, (required_fields, _calc_func) in calculations.items():
            if required_fields.issubset(available_fields):
                # If all required fields for a calculated field are available,
                # we consider the calculated field as available too
                available_fields.append(field)

        for field, mark in zip(fields, marks, strict=True):
            if mark:
                continue
            if field not in available_fields:
                continue
            marks = tuple(
                ("." if fld == field else mk)
                for fld, mk in zip(fields, marks, strict=True)
            )

        rows.append([bms_name, *marks])

    with Path.open(CSV_FILE, "w", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(header)
        writer.writerows(rows)


if __name__ == "__main__":
    main()
