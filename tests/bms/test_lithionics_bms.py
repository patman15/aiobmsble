"""Test the Lithionics (Li3) BMS implementation."""

from collections.abc import Buffer
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic

from aiobmsble.bms.lithionics_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient


class MockLithionicsBleakClient(MockBleakClient):
    """Emulate a Lithionics Li3 BLE UART client.

    When the BMS writes b"\\r\\n", the device sends CRLF-terminated ASCII CSV frames
    over notifications on the same characteristic. Frames may arrive split across
    multiple notifications.
    """

    async def write_gatt_char(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        data: Buffer,
        response: bool | None = None,
    ) -> None:
        await super().write_gatt_char(char_specifier, data, response)
        assert self._notify_callback is not None

        # Only respond to the polling write
        if bytes(data) != b"\r\n":
            return

        # Type A telemetry (split into 2 packets like real BLE often does)
        part1 = b"1362,340,341,341,340,37,41,0,99,000000"
        part2 = b"\r\n"
        self._notify_callback("MockLithionicsBleakClient", bytearray(part1[:20]))
        self._notify_callback("MockLithionicsBleakClient", bytearray(part1[20:] + part2))

        # Type B status (optional)
        self._notify_callback(
            "MockLithionicsBleakClient",
            bytearray(b"&,1,317,035859,0136,2300,FF05,8700\r\n"),
        )

        # occasional error line should be ignored
        self._notify_callback("MockLithionicsBleakClient", bytearray(b"ERROR\r\n"))


async def test_update(patch_bleak_client, keep_alive_fixture: bool) -> None:
    """Test Lithionics BMS data update."""
    patch_bleak_client(MockLithionicsBleakClient)

    bms = BMS(generate_ble_device(), keep_alive_fixture)

     # Cover static helpers (needed for 100% coverage gate)
    assert BMS.uuid_services()
    assert BMS.uuid_rx() == "ffe1"
    assert BMS.uuid_tx() == "ffe1"
    assert BMS.matcher_dict_list()


    sample = await bms.async_update()

    assert sample["voltage"] == 13.62
    assert sample["cell_voltages"] == [3.40, 3.41, 3.41, 3.40]
    assert sample["battery_level"] == 99
    assert sample["cell_count"] == 4
    assert sample["temp_values"] == [37, 41]
    assert sample["current"] == 0

    # query again to check already connected state
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()


async def test_device_info(patch_bleak_client) -> None:
    """Test that the BMS returns initialized dynamic device information."""
    patch_bleak_client(MockLithionicsBleakClient)
    bms = BMS(generate_ble_device())
    info = await bms.device_info()
    assert {"default_manufacturer", "default_model"}.issubset(info)

async def test_parsing_edge_cases(patch_bleak_client) -> None:
    """Cover edge cases for feed/parse logic (unicode garbage, short lines, status)."""

    class EdgeCaseClient(MockBleakClient):
        async def write_gatt_char(self, char_specifier, data, response=None) -> None:
            await super().write_gatt_char(char_specifier, data, response)
            assert self._notify_callback is not None

            # invalid bytes before CRLF -> triggers UnicodeDecodeError path
            self._notify_callback("EdgeCaseClient", bytearray(b"\xff\xfe\xfd\r\n"))

            # short / invalid line -> len(parts) < 9 path
            self._notify_callback("EdgeCaseClient", bytearray(b"1,2,3\r\n"))

            # status line path
            self._notify_callback(
                "EdgeCaseClient",
                bytearray(b"&,1,317,035859,0136,2300,FF05,8700\r\n"),
            )

            # finally a valid line so update completes
            self._notify_callback(
                "EdgeCaseClient",
                bytearray(b"1362,340,341,341,340,37,41,0,99,000000\r\n"),
            )

    patch_bleak_client(EdgeCaseClient)
    bms = BMS(generate_ble_device())
    sample = await bms.async_update()
    assert sample["battery_level"] == 99
    await bms.disconnect()

async def test_coverage_branches(patch_bleak_client) -> None:
    """Hit remaining parse/feed branches to satisfy 100% coverage."""

    class CoverageClient(MockBleakClient):
        async def write_gatt_char(self, char_specifier, data, response=None) -> None:
            await super().write_gatt_char(char_specifier, data, response)
            assert self._notify_callback is not None

            if bytes(data) != b"\r\n":
                return

            # empty line branch in _feed_notify (raw == b"")
            self._notify_callback("CoverageClient", bytearray(b"\r\n"))

            # ERROR line branch in _parse_line (early return)
            self._notify_callback("CoverageClient", bytearray(b"ERROR\r\n"))

            # status line FIRST so the next valid sample includes status_raw
            self._notify_callback(
                "CoverageClient",
                bytearray(b"&,1,317,035859,0136,2300,FF05,8700\r\n"),
            )

            # malformed numeric CSV line to trigger ValueError -> except branch (lines 152-153)
            self._notify_callback(
                "CoverageClient",
                bytearray(b"1362,340,341,341,340,37,41,NOTANINT,99,000000\r\n"),
            )

            # finally a valid line so update completes (and includes status_raw)
            self._notify_callback(
                "CoverageClient",
                bytearray(b"1362,340,341,341,340,37,41,0,99,000000\r\n"),
            )

    patch_bleak_client(CoverageClient)
    bms = BMS(generate_ble_device())
    sample = await bms.async_update()
    assert sample["battery_level"] == 99
    # this assertion ensures the status-branch was actually taken
    assert "status_raw" in sample
    await bms.disconnect()
async def test_no_status_line_branch(patch_bleak_client) -> None:
    """Cover the no-status_raw and no-flags_raw branches in _parse_line()."""

    class NoStatusClient(MockBleakClient):
        async def write_gatt_char(self, char_specifier, data, response=None) -> None:
            await super().write_gatt_char(char_specifier, data, response)
            assert self._notify_callback is not None
            if bytes(data) != b"\r\n":
                return

            # valid line immediately, without status line AND without flags field
            self._notify_callback(
                "NoStatusClient",
                bytearray(b"1362,340,341,341,340,37,41,0,99\r\n"),
            )

    patch_bleak_client(NoStatusClient)
    bms = BMS(generate_ble_device())
    sample = await bms.async_update()
    assert sample["battery_level"] == 99
    assert "status_raw" not in sample
    assert "flags_raw" not in sample
    await bms.disconnect()

