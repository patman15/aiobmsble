"""Test the package main script."""

import argparse
import asyncio
from collections.abc import Callable
from logging import DEBUG, INFO
import sys
from typing import Any, Final, Literal
from unittest import mock

from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from bleak.exc import BleakError
import pytest

from aiobmsble import BMSSample
import aiobmsble.__main__ as main_mod
from aiobmsble.bms.dummy_bms import BMS as DummyBMS
from aiobmsble.test_data import adv_dict_to_advdata


async def mock_discover(
    timeout: float = 5.0, *, return_adv: bool = False, **kwargs: Any
) -> dict[str, tuple[BLEDevice, AdvertisementData]]:
    """Mock BleakScanner to avoid actual BLE scanning."""
    mock_mac_unknown: Final[str] = "00:00:00:00:00:00"
    mock_mac: Final[str] = "11:22:33:44:55:66"
    mock_device: BLEDevice = BLEDevice(mock_mac, "Dummy BMS", None)
    mock_adv: AdvertisementData = adv_dict_to_advdata({"local_name": "dummy"})
    assert timeout >= 0, "timeout cannot be negative."
    assert return_adv, "mock only works with advertisement info."
    return {
        mock_mac_unknown: (
            BLEDevice(mock_mac_unknown, "Unknown Device", None),
            adv_dict_to_advdata({"local_name": "unknown_device"}),
        ),
        mock_mac: (mock_device, mock_adv),
    }


@pytest.fixture(name="mock_setup_logging")
def setup_logging():
    """Unittest mock for setup_logging to check calls to it."""
    with mock.patch.object(main_mod, "setup_logging") as m:
        yield m


@pytest.fixture(name="mock_asyncio_run")
def asyncio_run():
    """Unittest mock for asyncio_run to check calls to it."""
    with mock.patch("asyncio.run") as m:
        m.side_effect = lambda coro: asyncio.new_event_loop().run_until_complete(coro)
        yield m


async def test_detect_bms(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client: Callable[..., None],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify log output for working BMS update query."""

    monkeypatch.setattr("aiobmsble.__main__.BleakScanner.discover", mock_discover)
    patch_bleak_client()
    with caplog.at_level(INFO):
        await main_mod.detect_bms()
    assert "Found matching BMS type: Dummy Manufacturer dummy model" in caplog.text
    assert (
        "BMS data: {'voltage': 12,\n\t'current': 1.5,\n\t'temperature': 27.182,\n"
        "\t'power': 18.0,\n\t'battery_charging': True,\n\t'problem': False}\n"
        in caplog.text
    )


async def test_scan_devices_fail(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Verify log output for working BMS update query."""

    async def mock_discover_fail(
        timeout: float = 5.0, *, return_adv: bool = False, **kwargs: Any
    ) -> dict[str, tuple[BLEDevice, AdvertisementData]]:
        raise BleakError("No BT adapters.")

    monkeypatch.setattr("aiobmsble.__main__.BleakScanner.discover", mock_discover_fail)

    with caplog.at_level(INFO):
        await main_mod.scan_devices()
    assert "Could not scan for BT devices: No BT adapters." in caplog.text


async def test_bms_fail(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client: Callable[..., None],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Check that an error message is given if BMS update query fails (TimeoutError)."""

    async def mock_async_update(self) -> BMSSample:
        raise TimeoutError

    monkeypatch.setattr("aiobmsble.__main__.BleakScanner.discover", mock_discover)
    monkeypatch.setattr("aiobmsble.bms.dummy_bms.BMS._async_update", mock_async_update)
    patch_bleak_client()
    with caplog.at_level(INFO):
        await main_mod.detect_bms()
    assert "Found matching BMS type: Dummy Manufacturer dummy model" in caplog.text
    assert "Failed to query BMS: TimeoutError" in caplog.text


async def test_bms_retry_with_secret(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client: Callable[..., None],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify that a failed query will be retried when a BMS accepts a secret.

    The first call to ``_async_update`` simulates a timeout while no secret is
    supplied. ``detect_bms`` should catch the error, prompt for a secret via
    :func:`getpass.getpass`, and attempt the query again with the provided
    value.  The second attempt returns a valid sample which is logged.
    """

    # prepare BLE scanning and client patching as in other tests
    monkeypatch.setattr("aiobmsble.__main__.BleakScanner.discover", mock_discover)

    DummyBMS.accept_secret = True
    orig_init = DummyBMS.__init__

    def init_with_secret(self, ble_device, keep_alive=True, secret="") -> None:
        # call original initializer and remember the secret
        orig_init(self, ble_device, keep_alive)
        self._secret = secret

    monkeypatch.setattr(DummyBMS, "__init__", init_with_secret)

    attempts: list[str] = []

    async def fake_update(self) -> BMSSample:
        # record the secret used for each invocation
        attempts.append(getattr(self, "_secret", ""))
        if not getattr(self, "_secret", ""):
            raise TimeoutError
        return {"voltage": 99}

    monkeypatch.setattr(DummyBMS, "_async_update", fake_update)

    # patch getpass to avoid interactive prompt
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "secret123")

    patch_bleak_client()
    with caplog.at_level(INFO):
        await main_mod.detect_bms()

    assert "Failed to query BMS: TimeoutError" in caplog.text
    assert "Querying BMS with secret..." in caplog.text
    assert "BMS data" in caplog.text
    # ensure we attempted without and then with the secret
    assert attempts == ["", "secret123"]


def test_main_parses_logfile_and_verbose(
    monkeypatch: pytest.MonkeyPatch,
    mock_setup_logging: mock.MagicMock | mock.AsyncMock,
    mock_asyncio_run: mock.MagicMock | mock.AsyncMock,
) -> None:
    """Check that command line parses log file option and verbosity level."""

    async def patch_scan_devices() -> dict[str, tuple[BLEDevice, AdvertisementData]]:
        return {}

    monkeypatch.setattr(sys, "argv", ["prog", "-l", "test.log", "-v"])
    monkeypatch.setattr(main_mod, "scan_devices", patch_scan_devices)
    main_mod.main()
    args = mock_setup_logging.call_args[0][0]
    assert mock_setup_logging.called
    assert mock_asyncio_run.called
    assert isinstance(args, argparse.Namespace)
    assert args.logfile == "test.log"
    assert args.verbose


def test_main_parses_json(
    monkeypatch: pytest.MonkeyPatch,
    mock_setup_logging: mock.MagicMock | mock.AsyncMock,
    mock_asyncio_run: mock.MagicMock | mock.AsyncMock,
) -> None:
    """Check that command line parses the JSON option and calls identify_bms_from_json."""

    called: dict[str, bool] = {"identified": False}

    async def patch_identify_bms_from_json(json_str: str) -> None:
        assert json_str == '{"local_name":"dummy"}'
        called["identified"] = True

    monkeypatch.setattr(sys, "argv", ["prog", "--json", '{"local_name":"dummy"}'])
    monkeypatch.setattr(
        main_mod, "identify_bms_from_json", patch_identify_bms_from_json
    )

    main_mod.main()

    assert mock_setup_logging.called
    assert mock_asyncio_run.called
    assert called["identified"]


async def test_identify_bms_from_json_invalid(caplog: pytest.LogCaptureFixture) -> None:
    """Check that invalid JSON input is handled gracefully."""
    await main_mod.identify_bms_from_json("not-a-json")
    assert "Failed to parse JSON" in caplog.text


async def test_identify_bms_from_json_no_match(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Check that no match found is logged when no BMS can be identified."""

    async def fake_bms_identify(adv, addr) -> None:
        return None

    monkeypatch.setattr(main_mod, "bms_identify", fake_bms_identify)

    await main_mod.identify_bms_from_json('{"local_name": "dummy"}')
    assert "No matching BMS type found" in caplog.text


async def test_identify_bms_from_json_match(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Check that a matching BMS is identified and logged correctly."""

    class FakeBMSClass:
        @staticmethod
        def bms_id() -> Literal["SimpleBMS"]:
            return "SimpleBMS"

    async def fake_bms_identify(adv, addr) -> type[FakeBMSClass]:
        return FakeBMSClass

    monkeypatch.setattr(main_mod, "bms_identify", fake_bms_identify)

    await main_mod.identify_bms_from_json(
        '{"name":"dummy","address":"AA:BB:CC:DD:EE:FF"}'
    )
    assert "BMS Type: SimpleBMS" in caplog.text


async def test_identify_bms_from_json_invalid_advdata(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Check that invalid advertisement data in JSON input is handled gracefully."""
    await main_mod.identify_bms_from_json(
        '{"local_name":"dummy","platform_data":["bad"]}'
    )
    assert "Failed to convert advertisement data" in caplog.text


@mock.patch("aiobmsble.__main__.logger")
def test_logging_wo_file(mock_logger) -> None:
    """Check default log level."""
    args = argparse.Namespace(verbose=False, logfile=None)

    main_mod.setup_logging(args)

    assert mock_logger.setLevel.call_args[0][0] == INFO
    mock_logger.addHandler.assert_not_called()


@mock.patch("aiobmsble.__main__.logger")
def test_verbose_logging_wo_file(mock_logger) -> None:
    """Check verbose log level."""
    args = argparse.Namespace(verbose=True, logfile=None)

    main_mod.setup_logging(args)

    assert mock_logger.setLevel.call_args[0][0] == DEBUG
    mock_logger.addHandler.assert_not_called()


@mock.patch("aiobmsble.__main__.logging.FileHandler")
@mock.patch("aiobmsble.__main__.logger")
def test_logging_with_logfile(mock_logger, mock_file_handler_cls) -> None:
    """Check that logging goes to file if log file is given."""
    mock_file_handler = mock.MagicMock()
    mock_file_handler_cls.return_value = mock_file_handler

    args = argparse.Namespace(verbose=False, logfile="test.log")

    main_mod.setup_logging(args)

    mock_file_handler.setLevel.assert_called_once_with(INFO)
    mock_file_handler.setFormatter.assert_called_once()
    mock_logger.addHandler.assert_called_once_with(mock_file_handler)
    mock_logger.setLevel.assert_called_once_with(INFO)
