"""Extra unit tests for CW20 plugin (device info, UUIDs, handlers, async update)."""

from bleak.backends.device import BLEDevice
import pytest

import aiobmsble.bms.cw20_bms as cw20


class DummyClient:
    """Fake BleakClient to bypass real BLE I/O in tests."""

    def __init__(self, *args, **kwargs):
        """Initialize dummy client state."""
        self._is_connected = False

    async def connect(self):
        """Simulate async connect always successful."""
        self._is_connected = True
        return True

    async def disconnect(self):
        """Simulate async disconnect always successful."""
        self._is_connected = False
        return True


def _make_dev():
    """Build BLEDevice compatible with bleak version in use."""
    return BLEDevice(
        address="00:11:22:33:44:55",
        name="ATORCH-CW20",
        details={},
    )


def test_cw20_init(monkeypatch):
    """Cover __init__ path with patched DummyClient."""
    monkeypatch.setattr("aiobmsble.basebms.BleakClient", DummyClient)
    dev = _make_dev()
    bms = cw20.BMS(dev)
    assert isinstance(bms, cw20.BMS)


def test_cw20_device_info_and_uuids():
    """Check device info and UUID functions."""
    info = cw20.BMS.device_info()
    assert info["manufacturer"] == "ATORCH"
    assert "CW20" in info["model"]

    uuids = cw20.BMS.uuid_services()
    assert isinstance(uuids, list)
    assert "ffe0" in uuids[0].lower()

    assert "ffe1" in cw20.BMS.uuid_rx().lower()
    assert cw20.BMS.uuid_tx() == ""


def test_cw20_calc_values():
    """Verify calculated values set contains 'power'."""
    values = cw20.BMS._calc_values()
    assert "power" in values


def test_cw20_notification_handler_valid(monkeypatch):
    """Ensure notification handler stores valid frame."""
    monkeypatch.setattr("aiobmsble.basebms.BleakClient", DummyClient)
    bms = cw20.BMS(_make_dev())
    frame = bytearray.fromhex(
        "ff550102000d44000df700208d00000b2f000064000000000020003b1c1d3c0000000023"
    )
    bms._notification_handler(None, frame)
    assert bms._data_final == frame


def test_cw20_notification_handler_invalid(monkeypatch):
    """Ignore frames without CW20 header."""
    monkeypatch.setattr("aiobmsble.basebms.BleakClient", DummyClient)
    bms = cw20.BMS(_make_dev())
    frame = b"\x01\x02\x03"
    bms._notification_handler(None, frame)
    assert bms._data_final == bytearray()


def test_cw20_notification_handler_short_frame(monkeypatch):
    """Reject CW20 header if frame shorter than INFO_LEN."""
    monkeypatch.setattr("aiobmsble.basebms.BleakClient", DummyClient)
    bms = cw20.BMS(_make_dev())
    short = b"\xFF\x55\x01\x02\x03\x04"
    bms._notification_handler(None, short)
    assert bms._data_final == bytearray()


@pytest.mark.asyncio
async def test_cw20_async_update_empty(monkeypatch):
    """Return empty dict when no data is present."""
    monkeypatch.setattr("aiobmsble.basebms.BleakClient", DummyClient)
    bms = cw20.BMS(_make_dev())
    result = await bms._async_update()
    assert result == {}


@pytest.mark.asyncio
async def test_cw20_async_update_with_data(monkeypatch):
    """Decode frame and calculate power."""
    monkeypatch.setattr("aiobmsble.basebms.BleakClient", DummyClient)
    bms = cw20.BMS(_make_dev())
    frame = bytearray.fromhex(
        "ff550102000d44000df700208d00000b2f000064000000000020003b1c1d3c0000000023"
    )
    bms._notification_handler(None, frame)

    result = await bms._async_update()
    assert "voltage" in result
    assert "current" in result
    assert "power" in result
    assert result["power"] == round(result["voltage"] * result["current"], 2)


@pytest.mark.asyncio
async def test_cw20_async_update_partial_decode(monkeypatch):
    """Decode without current → ensure no power is added."""
    monkeypatch.setattr("aiobmsble.basebms.BleakClient", DummyClient)
    bms = cw20.BMS(_make_dev())
    frame = bytearray.fromhex(
        "ff550102000d44000df700208d00000b2f000064000000000020003b1c1d3c0000000023"
    )
    bms._notification_handler(None, frame)

    def _fake_decode(_fields, _data, *, byteorder="big", offset=0):
        return {"voltage": 12.34}  # no 'current'

    monkeypatch.setattr(cw20.BMS, "_decode_data", staticmethod(_fake_decode))
    result = await bms._async_update()
    assert "voltage" in result and "power" not in result
