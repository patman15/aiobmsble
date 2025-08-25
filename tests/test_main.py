"""Test the package main script."""

import argparse
from collections.abc import Callable
from logging import DEBUG, INFO
import sys
from typing import Final
import unittest
from unittest import TestCase, mock

from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
import pytest

from aiobmsble import BMSsample
import aiobmsble.__main__ as main_mod

from .bluetooth import generate_advertisement_data


async def mock_discover(
    timeout: float = 5.0, *, return_adv: bool = False, **kwargs
) -> dict[str, tuple[BLEDevice, AdvertisementData]]:
    """Mock BleakScanner to avoid actual BLE scanning."""
    mock_mac_unknown: Final[str] = "00:00:00:00:00:00"
    mock_mac: Final[str] = "11:22:33:44:55:66"
    mock_device: BLEDevice = BLEDevice(mock_mac, "Dummy BMS", None)
    mock_adv: AdvertisementData = generate_advertisement_data(local_name="dummy")
    assert timeout >= 0, "timeout cannot be negative."
    assert return_adv, "mock only works with advertisement info."
    return {
        mock_mac_unknown: (
            BLEDevice(mock_mac_unknown, "Unknown Device", None),
            generate_advertisement_data(local_name="unknown_device"),
        ),
        mock_mac: (mock_device, mock_adv),
    }


@pytest.fixture
def mock_setup_logging():
    with mock.patch.object(main_mod, "setup_logging") as m:
        yield m


@pytest.fixture
def mock_asyncio_run():
    with mock.patch("asyncio.run") as m:
        yield m


@pytest.fixture
def mock_detect_bms():
    with mock.patch.object(main_mod, "detect_bms") as m:
        yield m


async def test_detect_bms(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client: Callable[..., None],
    caplog: pytest.LogCaptureFixture,
) -> None:
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


async def test_bms_fail(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client: Callable[..., None],
    caplog: pytest.LogCaptureFixture,
) -> None:

    async def mock_async_update(self) -> BMSsample:
        raise TimeoutError

    monkeypatch.setattr("aiobmsble.__main__.BleakScanner.discover", mock_discover)
    monkeypatch.setattr("aiobmsble.bms.dummy_bms.BMS._async_update", mock_async_update)
    patch_bleak_client()
    with caplog.at_level(INFO):
        await main_mod.detect_bms()
    assert "Found matching BMS type: Dummy Manufacturer dummy model" in caplog.text
    assert "Failed to update BMS: TimeoutError" in caplog.text


def test_main_parses_logfile_and_verbose(
    monkeypatch: pytest.MonkeyPatch, mock_setup_logging, mock_asyncio_run
) -> None:
    """Check that command line parses log file option and verbosity level."""
    monkeypatch.setattr(sys, "argv", ["prog", "-l", "test.log", "-v"])
    main_mod.main()
    args = mock_setup_logging.call_args[0][0]
    assert mock_setup_logging.called
    assert mock_asyncio_run.called
    assert isinstance(args, argparse.Namespace)
    assert args.logfile == "test.log"
    assert args.verbose


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
    mock_file_handler = mock.MagicMock()
    mock_file_handler_cls.return_value = mock_file_handler

    args = argparse.Namespace(verbose=False, logfile="test.log")

    main_mod.setup_logging(args)

    mock_file_handler.setLevel.assert_called_once_with(INFO)
    mock_file_handler.setFormatter.assert_called_once()
    mock_logger.addHandler.assert_called_once_with(mock_file_handler)
    mock_logger.setLevel.assert_called_once_with(INFO)
