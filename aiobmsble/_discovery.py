"""Private helpers for BMS discovery.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""
from fnmatch import translate
import re

from bleak.backends.scanner import AdvertisementData

from aiobmsble.plugin import MatcherPattern


def advertisement_matches(
    matcher: MatcherPattern, adv_data: AdvertisementData, mac_addr: str
) -> bool:
    """Determine whether advertisement data matches a BMS discovery pattern."""
    service_uuid: str | None = matcher.get("service_uuid")
    service_data_uuid: str | None = matcher.get("service_data_uuid")
    oui: str | None = matcher.get("oui")
    manufacturer_id: int | None = matcher.get("manufacturer_id")
    local_name: str | None = matcher.get("local_name")

    matched: bool = not service_uuid or service_uuid in adv_data.service_uuids
    if service_data_uuid is not None:
        matched = matched and (
            service_data_uuid in adv_data.service_data
            if service_data_uuid
            else not adv_data.service_data
        )
    matched = matched and (
        not oui or mac_addr.lower().startswith(oui.lower()[:8])
    )
    if manufacturer_id is not None:
        matched = matched and manufacturer_id in adv_data.manufacturer_data
        if manufacturer_data_start := matcher.get("manufacturer_data_start"):
            if manufacturer_id in adv_data.manufacturer_data:
                matched = matched and adv_data.manufacturer_data[
                    manufacturer_id
                ].startswith(bytes(manufacturer_data_start))
    if "connectable" in matcher:
        matched = matched and (
            getattr(adv_data, "connectable", True) == matcher["connectable"]
        )
    if local_name:
        matched = matched and bool(
            re.compile(translate(local_name)).match(adv_data.local_name or "")
        )
    return matched
