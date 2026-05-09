"""Test the aiobmsble library utility functions."""

from types import ModuleType
from typing import Any, Final

import pytest

from aiobmsble import MatcherPattern
from aiobmsble.basebms import BaseBMS
from aiobmsble.test_data import adv_dict_to_advdata, bms_advertisements
from aiobmsble.utils import (
    StreamParser,
    _advertisement_matches,
    bms_cls,
    bms_identify,
    load_bms_plugins,
)


@pytest.fixture(
    name="plugin",
    params=sorted(
        load_bms_plugins(), key=lambda plugin: getattr(plugin, "__name__", "")
    ),
    ids=lambda param: param.__name__.split(".")[-1],
)
def plugin_fixture(request: pytest.FixtureRequest) -> ModuleType:
    """Return module of a BMS."""
    assert isinstance(request.param, ModuleType)
    return request.param


async def test_bms_identify(plugin: ModuleType) -> None:
    """Test that each BMS is correctly detected by a pattern.

    This also ensures that each BMS has at least one advertisement.
    """
    bms_type: str = getattr(plugin, "__name__", "").rsplit(".", 1)[-1]
    adv, mac_addr, _type, _comments = (
        bms_advertisements(bms_type).pop()
        if bms_type != "dummy_bms"
        else (
            adv_dict_to_advdata({"local_name": "dummy"}),
            "cc:cc:cc:cc:cc:cc",
            bms_type,
            "",
        )
    )

    bms_class: type[BaseBMS] | None = await bms_identify(adv, mac_addr)
    assert bms_class == plugin.BMS


async def test_bms_cls(plugin: ModuleType) -> None:
    """Test that a BMS class is correctly returned from its name."""
    # strip _bms to get only type
    bms_type: str = getattr(plugin, "__name__", "").rsplit(".", 1)[-1]
    bms_class: type[BaseBMS] | None = await bms_cls(bms_type)
    assert bms_class == plugin.BMS


@pytest.mark.parametrize("bms_type", ["unavailable_bms", "ignore_me"])
async def test_bms_cls_none(bms_type: str) -> None:
    """Test that a BMS class is None when name is not correct."""
    bms_class: type[BaseBMS] | None = await bms_cls(bms_type)
    assert bms_class is None


async def test_bms_identify_fail() -> None:
    """Test if bms_identify returns None if matching BMS for advertisement does not exist."""
    assert await bms_identify(adv_dict_to_advdata({}), "") is None


@pytest.mark.parametrize(
    ("matcher", "adv_dict", "mac_addr", "expected"),
    [
        (  # Match service_uuid
            {"service_uuid": "1234"},
            {"service_uuids": ["1234"]},
            "",
            True,
        ),
        (  # Do not match service_uuid
            {"service_uuid": "abcd"},
            {"service_uuids": ["1234"]},
            "",
            False,
        ),
        (  # Match service_data_uuid
            {"service_data_uuid": "abcd"},
            {"service_data": {"abcd": b"\x01\x02"}},
            "",
            True,
        ),
        (  # Do not Match service_data_uuid
            {"service_data_uuid": "efgh"},
            {"service_data": {"abcd": b"\x01\x02"}},
            "",
            False,
        ),
        (  # Match manufacturer_id
            {"manufacturer_id": 123},
            {"manufacturer_data": {123: b"\x01\x02"}},
            "",
            True,
        ),
        (  # Do not match manufacturer_id
            {"manufacturer_id": 456},
            {"manufacturer_data": {123: b"\x01\x02"}},
            "",
            False,
        ),
        (  # Match manufacturer_data_start
            {"manufacturer_id": 123, "manufacturer_data_start": b"\x01"},
            {"manufacturer_data": {123: b"\x01\x02"}},
            "",
            True,
        ),
        (  # Do not match manufacturer_data_start
            {"manufacturer_id": 123, "manufacturer_data_start": b"\x02"},
            {"manufacturer_data": {123: b"\x01\x02"}},
            "",
            False,
        ),
        (  # Match local_name with wildcard
            {"local_name": "Test*"},
            {"local_name": "TestDevice"},
            "",
            True,
        ),
        (  # Do not match local_name with wildcard
            {"local_name": "Foo*"},
            {"local_name": "BarDevice"},
            "",
            False,
        ),
        (  # Multiple criteria: all must match
            {
                "service_uuid": "1234",
                "manufacturer_id": 123,
                "local_name": "Dev*",
            },
            {
                "service_uuids": ["1234"],
                "manufacturer_data": {123: b"\x01"},
                "local_name": "Device",
            },
            "",
            True,
        ),
        (
            {
                "service_uuid": "1234",
                "manufacturer_id": 999,
                "local_name": "Dev*",
            },
            {
                "service_uuids": ["1234"],
                "manufacturer_data": {123: b"\x01"},
                "local_name": "Device",
            },
            "",
            False,
        ),
        ({}, {}, "", True),  # Empty matcher matches always
        ({"oui": "00:11:22"}, {}, "00:11:22:aa:bb:cc", True),
        ({"oui": "AA:bb:CC"}, {}, "aa:BB:cc:00:11:22", True),
        ({"oui": "00:11:22-xx:yy:zz"}, {}, "00:11:22:aa:bb:cc", True),
        ({"oui": "00"}, {}, "00:11:22:aa:bb:cc", True),
    ],
    ids=[
        "service_uuid-match",
        "service_uuid-no-match",
        "service_data_uuid-match",
        "service_data_uuid-no-match",
        "manufacturer_id-match",
        "manufacturer_id-no-match",
        "manufacturer_data_start-match",
        "manufacturer_data_start-no-match",
        "local_name-wildcard-match",
        "local_name-wildcard-no-match",
        "multiple-criteria-all-match",
        "multiple-criteria-one-no-match",
        "empty-matcher-always-match",
        "OUI-matches",
        "OUI-match-case-insensitive",
        "OUI-matches-long",
        "OUI-matches-short",
    ],
)
def test_advertisement_matches(
    matcher: MatcherPattern, adv_dict: dict[str, Any], mac_addr: str, expected: bool
) -> None:
    """Test _advertisement_matches() returns the expected result for a given matcher/advertisement.

    Args:
        matcher: The matcher object or criteria used to evaluate the advertisement data.
        adv_dict: The advertisement data dictionary to be checked against the matcher.
        mac_addr: Bluetooth device address
        expected: The expected boolean result indicating if the advertisement matches the criteria.

    Asserts:
        That advertisement_matches(matcher, adv_data) returns the value specified by expected.

    """
    assert (
        _advertisement_matches(matcher, adv_dict_to_advdata(adv_dict), mac_addr)
        is expected
    )


def test_single_complete_frame() -> None:
    """Test that a single complete frame is correctly parsed."""
    p = StreamParser()

    # Frame: DLE STX  <data>  DLE ETX
    data: Final[bytes] = bytes([p.STX, p.STX]) + b"ABC" + bytes([p.DLE, p.ETX])

    assert p.feed(data) == b"ABC"


def test_frame_split_across_chunks() -> None:
    """Test that a frame split across multiple chunks is correctly parsed."""
    p = StreamParser()

    chunk1: bytes = bytes([p.STX, p.STX]) + b"A"
    chunk2: bytes = b"BC" + bytes([p.DLE, p.ETX])

    assert p.feed(chunk1) is None
    assert p.feed(chunk2) == b"ABC"


def test_escaped_data_bytes() -> None:
    """Test that escaped special bytes within a frame are correctly handled."""
    p = StreamParser()

    # Inside a frame, DLE STX means literal STX byte
    data: Final[bytes] = (
        bytes([p.STX, p.STX])
        + bytes([p.DLE, p.STX])  # literal STX
        + bytes([p.DLE, p.DLE])  # literal DLE
        + bytes([p.DLE, p.ETX])  # end
    )

    assert p.feed(data) == bytes([p.STX, p.DLE])


def test_multiple_frames_in_one_stream() -> None:
    """Test that multiple frames in a single stream are correctly parsed, with only the last frame returned."""
    p = StreamParser()

    stream: bytes = (
        bytes([p.STX, p.STX])
        + b"ONE"
        + bytes([p.DLE, p.ETX])
        + bytes([p.STX, p.STX])
        + b"TWO"
        + bytes([p.DLE, p.ETX])
    )

    # Only last frame is returned; earlier one is overwritten
    assert p.feed(stream) == b"TWO"


def test_incomplete_frame_returns_none() -> None:
    """Test that an incomplete frame returns None until it is completed."""
    p = StreamParser()

    data: Final[bytes] = bytes([p.STX, p.STX]) + b"HELLO"
    assert p.feed(data) is None


def test_escape_outside_frame_starts_frame() -> None:
    """Test that an escaped STX outside a frame starts a new frame."""
    p = StreamParser()

    # Outside frame: DLE sets escaped=True, next STX starts frame
    assert p.feed(bytes([p.DLE])) is None
    assert p.feed(bytes([p.STX])) is None  # frame started
    assert p.feed(b"A" + bytes([p.DLE, p.ETX])) == b"A"


def test_buffer_overflow_resets_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that if the buffer exceeds MAX_SIZE, the frame is reset and buffer cleared."""
    p = StreamParser()
    monkeypatch.setattr(StreamParser, "MAX_SIZE", 5)  # shrink for test

    data: Final[bytes] = bytes([p.STX, p.STX]) + b"123456"  # 6 bytes → overflow

    assert p.feed(data) is None
    # Parser should now be out of frame and buffer cleared
    assert p._in_frame is False
    assert p._buffer == bytearray()


def test_escape_then_non_special_inside_frame() -> None:
    """Test that an escape byte followed by a non-special byte inside a frame is handled correctly.

    (escape should be cleared, byte included)
    """
    p = StreamParser()

    p.feed(bytes([p.STX, p.STX]))  # Start frame

    # Escape then normal byte → escape cleared, byte ignored
    p.feed(bytes([p.DLE, ord("X")]))

    # End frame -> 'X' should NOT be included
    assert p.feed(bytes([p.DLE, p.ETX])) == b""


def test_escape_then_etx_closes_frame() -> None:
    """Test that an escape byte followed by ETX inside a frame correctly ends the frame and does not include ETX in data."""
    p = StreamParser()

    data: Final[bytes] = bytes([p.STX, p.STX]) + b"DATA" + bytes([p.DLE, p.ETX])

    assert p.feed(data) == b"DATA"
