"""Test the E&J technology BMS implementation."""

from collections.abc import Buffer
from unittest.mock import patch
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.uuids import normalize_uuid_str
import pytest

from aiobmsble import BMSSample
from aiobmsble.basebms import BaseBMS
from aiobmsble.bms.ej_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import MockBleakClient
from tests.test_basebms import verify_device_info

BT_FRAME_SIZE = 20


class MockEJBleakClient(MockBleakClient):
    """Emulate a E&J technology BMS BleakClient."""

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
    ) -> bytearray:
        if isinstance(char_specifier, str) and normalize_uuid_str(
            char_specifier
        ) != normalize_uuid_str("6e400002-b5a3-f393-e0a9-e50e24dcca9e"):
            return bytearray()
        cmd: int = int(bytearray(data)[3:5], 16)
        if cmd == 0x02:
            return bytearray(
                b":0082310080000101C00000880F540F3C0F510FD70F310F2C0F340F3A0FED0FED0000000000000000"
                b"000000000000000248424242F0000000000000000001AB~"
            )  # TODO: put numbers
        if cmd == 0x10:
            return bytearray(b":009031001E00000002000A000AD8~")  # TODO: put numbers
        return bytearray()

    async def write_gatt_char(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        data: Buffer,
        response: bool | None = None,
    ) -> None:
        """Issue write command to GATT."""
        await super().write_gatt_char(char_specifier, data, response)
        assert self._notify_callback is not None
        self._notify_callback("MockEJBleakClient", bytearray(b"AT\r\n"))
        self._notify_callback("MockEJBleakClient", bytearray(b"AT\r\nillegal"))
        for notify_data in [
            self._response(char_specifier, data)[i : i + BT_FRAME_SIZE]
            for i in range(0, len(self._response(char_specifier, data)), BT_FRAME_SIZE)
        ]:
            self._notify_callback("MockEJBleakClient", notify_data)


class MockEJsfBleakClient(MockEJBleakClient):
    """Emulate a E&J technology BMS BleakClient with single frame protocol."""

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
    ) -> bytearray:
        if isinstance(char_specifier, str) and normalize_uuid_str(
            char_specifier
        ) != normalize_uuid_str("6e400002-b5a3-f393-e0a9-e50e24dcca9e"):
            return bytearray()

        if int(bytearray(data)[3:5], 16) == 0x02:
            return bytearray(
                b":008231008C000000000000000CBF0CC00CEA0CD50000000000000000000000000000000000000000"
                b"00000000008C000041282828F000000000000100004B044C05DC05DCB2~"
            )
        return bytearray()

    @staticmethod
    def values() -> BMSSample:
        """Return correct data sample values for single frame protocol sample."""
        return {
            "voltage": 13.118,
            "current": 1.4,
            "battery_level": 75,
            "cycles": 1,
            "cycle_charge": 110.0,
            "cell_count": 4,
            "cell_voltages": [3.263, 3.264, 3.306, 3.285],
            "delta_voltage": 0.043,
            "temperature": 25,
            "temp_values": [25],
            "cycle_capacity": 1442.98,
            "power": 18.365,
            "battery_charging": True,
            "problem": False,
            "problem_code": 0,
            "balancer": 0,
            "chrg_mosfet": True,
            "dischrg_mosfet": True,
            "heater": False,
            "design_capacity": 150,
        }


class MockEJsfnoCRCBleakClient(MockEJsfBleakClient):
    """Emulate a E&J technology BMS BleakClient with single frame protocol and uncalculated CRC."""

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
    ) -> bytearray:
        ret: bytearray = MockEJsfBleakClient._response(self, char_specifier, data)
        ret[-3:-1] = b"00"  # patch to wrong CRC
        return ret


class MockChinsBleakClient(MockBleakClient):
    """Emulate a Chins Battery BMS BleakClient."""

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
    ) -> bytearray:
        """Return Chins 140-byte frame (same E&J field layout)."""
        if isinstance(char_specifier, str) and normalize_uuid_str(
            char_specifier
        ) != normalize_uuid_str("6e400002-b5a3-f393-e0a9-e50e24dcca9e"):
            return bytearray()

        # Real hardware capture from Chins G-12V300Ah-0345 battery via Cerbo GX
        # 140-byte frame: E&J header + data, no CRC field
        if int(bytearray(data)[3:5], 16) == 0x02:
            return bytearray(
                b":008231008C000000000000000CFE0CD50D050CFC0000000000000000000000000000000000000"
                b"000000000000000000037282828F000000000002C0000590A0A0B5E0BB8BC~"
            )
        return bytearray()

    async def write_gatt_char(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        data: Buffer,
        response: bool | None = None,
    ) -> None:
        """Issue write command to GATT."""
        await super().write_gatt_char(char_specifier, data, response)
        assert self._notify_callback is not None
        for notify_data in [
            self._response(char_specifier, data)[i : i + BT_FRAME_SIZE]
            for i in range(0, len(self._response(char_specifier, data)), BT_FRAME_SIZE)
        ]:
            self._notify_callback("MockChinsBleakClient", notify_data)

    @staticmethod
    def values() -> BMSSample:
        """Return correct data sample values for Chins protocol.

        Based on real hardware capture from Chins G-12V300Ah-0345 battery.
        """
        return {
            "voltage": 13.268,
            "current": 0.0,
            "battery_level": 89,
            "cycles": 44,
            "cycle_charge": 257.0,
            "cycle_capacity": 3409.876,
            "cell_count": 4,
            "cell_voltages": [3.326, 3.285, 3.333, 3.324],
            "delta_voltage": 0.048,
            "temperature": 15.0,
            "temp_values": [15],
            "power": 0.0,
            "battery_charging": False,
            "problem": False,
            "problem_code": 0,
            "chrg_mosfet": True,
            "dischrg_mosfet": True,
            "balancer": False,
            "heater": False,
            "design_capacity": 300,
        }


class MockEJinvalidBleakClient(MockEJBleakClient):
    """Emulate a E&J technology BMS BleakClient without sending second frame."""

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str | UUID, data: Buffer
    ) -> bytearray:
        if isinstance(char_specifier, str) and normalize_uuid_str(
            char_specifier
        ) != normalize_uuid_str("6e400002-b5a3-f393-e0a9-e50e24dcca9e"):
            return bytearray()

        return bytearray(
            b":0082310080000101C00000880F540F3C0F510FD70F310F2C0F340F3A0FED0FED0000000000000000"
            b"000000000000000248424242F0000000000000000001AB~"
        )  # TODO: put numbers


async def test_update(patch_bleak_client, keep_alive_fixture: bool) -> None:
    """Test E&J technology BMS data update."""

    patch_bleak_client(MockEJBleakClient)

    bms = BMS(generate_ble_device(), keep_alive_fixture)

    assert await bms.async_update() == {
        "voltage": 39.517,
        "current": -0.02,
        "battery_level": 1,
        "cycles": 0,
        "cycle_charge": 0.2,
        "cell_count": 10,
        "cell_voltages": [
            3.924,
            3.900,
            3.921,
            4.055,
            3.889,
            3.884,
            3.892,
            3.898,
            4.077,
            4.077,
        ],
        "delta_voltage": 0.193,
        "temperature": 32,
        "temp_values": [32],
        "cycle_capacity": 7.903,
        "power": -0.79,
        "runtime": 36000,
        "battery_charging": False,
        "problem": False,
        "problem_code": 0,
        "balancer": False,
        "chrg_mosfet": True,
        "dischrg_mosfet": True,
        "heater": False,
    }

    # query again to check already connected state
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()


async def test_device_info(patch_bleak_client) -> None:
    """Test that the BMS returns initialized dynamic device information."""
    await verify_device_info(patch_bleak_client, MockEJBleakClient, BMS)


async def test_update_single_frame(
    patch_bleak_client, keep_alive_fixture: bool
) -> None:
    """Test E&J technology BMS data update."""

    patch_bleak_client(MockEJsfBleakClient)

    bms = BMS(generate_ble_device(), keep_alive_fixture)

    assert await bms.async_update() == MockEJsfBleakClient.values()

    # query again to check already connected state
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()


async def test_update_sf_no_crc(patch_bleak_client) -> None:
    """Test E&J technology BMS data update with no CRC."""

    patch_bleak_client(MockEJsfnoCRCBleakClient)

    bms = BMS(generate_ble_device("cc:cc:cc:cc:cc:cc", "libattU_MockBLEDevice"), True)

    assert await bms.async_update() == MockEJsfnoCRCBleakClient.values()

    await bms.disconnect()


async def test_update_chins(
    patch_bleak_client, keep_alive_fixture: bool
) -> None:
    """Test Chins Battery BMS data update."""

    patch_bleak_client(MockChinsBleakClient)

    bms = BMS(
        generate_ble_device("05:23:01:64:00:C3", "G-12V300Ah-0345"),
        keep_alive_fixture,
        periodic_reconnect=True,
    )

    result = await bms.async_update()
    expected = MockChinsBleakClient.values()

    # Check all expected fields are present
    assert result == expected

    # query again to check already connected state
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()


async def test_chins_reconnect(patch_bleak_client) -> None:
    """Test periodic reconnection for Chins devices to prevent buffer buildup."""

    patch_bleak_client(MockChinsBleakClient)

    bms = BMS(
        generate_ble_device("05:23:01:64:00:C3", "G-12V300Ah-0345"),
        True,
        periodic_reconnect=True,
    )

    # First update initializes connection timestamp
    result = await bms.async_update()
    assert result == MockChinsBleakClient.values()

    # Simulate elapsed time exceeding reconnection interval (300s)
    with patch("aiobmsble.bms.ej_bms.time") as mock_time:
        mock_time.monotonic.side_effect = [
            bms._connection_start_time + 901,  # elapsed check
            1000.0,  # new connection timestamp after reconnect
        ]
        result = await bms.async_update()
        # Should return cached data during reconnection
        assert result == MockChinsBleakClient.values()

    await bms.disconnect()


async def test_chins_no_reconnect(patch_bleak_client) -> None:
    """Test that periodic reconnection is disabled by default."""

    patch_bleak_client(MockChinsBleakClient)

    bms = BMS(
        generate_ble_device("05:23:01:64:00:C3", "G-12V300Ah-0345"),
        keep_alive=True,
    )

    # First update should work normally
    result = await bms.async_update()
    assert result == MockChinsBleakClient.values()

    # Simulate elapsed time exceeding reconnection interval
    # With periodic_reconnect=False, it should NOT trigger reconnection
    with patch("aiobmsble.bms.ej_bms.time") as mock_time:
        mock_time.monotonic.return_value = 99999.0  # way past any interval
        result = await bms.async_update()
        # Should still return fresh data, not cached (no reconnection happened)
        assert result == MockChinsBleakClient.values()

    await bms.disconnect()


async def test_chins_stale_recovery(patch_bleak_client) -> None:
    """Test stale connection recovery for Chins devices.

    If the BMS does not respond (TimeoutError), the driver should
    disconnect, wait for buffer flush, reconnect, and retry.
    """

    call_count = 0
    # _await_msg tries 2 write modes x 3 retries = 6 writes before TimeoutError
    stale_writes = 2 * BaseBMS.MAX_RETRY

    class MockChinsStaleClient(MockChinsBleakClient):
        """Simulate a stale BMS that ignores writes until reconnection."""

        async def write_gatt_char(
            self,
            char_specifier: BleakGATTCharacteristic | int | str | UUID,
            data: Buffer,
            response: bool | None = None,
        ) -> None:
            nonlocal call_count
            call_count += 1
            if call_count <= stale_writes:
                # Stale: accept the write but send no notifications (triggers timeout)
                return
            await super().write_gatt_char(char_specifier, data, response)

    patch_bleak_client(MockChinsStaleClient)

    bms = BMS(
        generate_ble_device("05:23:01:64:00:C3", "G-12V300Ah-0345"),
        True,
        periodic_reconnect=True,
    )

    # Should recover from stale connection and return valid data
    result = await bms.async_update()
    assert result == MockChinsBleakClient.values()

    await bms.disconnect()


async def test_invalid(patch_bleak_client) -> None:
    """Test E&J technology BMS data update."""

    patch_bleak_client(MockEJinvalidBleakClient)

    bms = BMS(generate_ble_device())

    assert await bms.async_update() == {}
    await bms.disconnect()


@pytest.fixture(
    name="wrong_response",
    params=[
        (b"x009031001E0000001400080016F4~", "wrong SOI"),
        (b":009031001E0000001400080016F4x", "wrong EOI"),
        (b":009031001D0000001400080016F4~", "wrong length"),
        (b":009031001E00000002000A000AD9~", "wrong CRC"),
        (b":009031001E000X001400080016F4~", "wrong encoding"),
    ],
    ids=lambda param: param[1],
)
def fix_response(request: pytest.FixtureRequest) -> bytes:
    """Return faulty response frame."""
    assert isinstance(request.param[0], bytes)
    return request.param[0]


async def test_invalid_response(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    patch_bms_timeout,
    wrong_response: bytes,
) -> None:
    """Test data up date with BMS returning invalid data."""

    patch_bms_timeout()

    monkeypatch.setattr(
        MockEJBleakClient, "_response", lambda _s, _c, _d: wrong_response
    )

    patch_bleak_client(MockEJBleakClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = {}
    with pytest.raises(TimeoutError):
        result = await bms.async_update()

    assert not result
    await bms.disconnect()


@pytest.fixture(
    name="problem_response",
    params=[
        (
            bytearray(
                b":008231008C000000000000000CBF0CC00CEA0CD50000000000000000000000000000000000000000"
                b"00000000008C000041282828F004000000000100004B044C05DC05DCAE~"
            ),
            "first_bit",
        ),
        (
            bytearray(
                b":008231008C000000000000000CBF0CC00CEA0CD50000000000000000000000000000000000000000"
                b"00000000008C000041282828F800000000000100004B044C05DC05DCAA~"
            ),
            "last_bit",
        ),
    ],
    ids=lambda param: param[1],
)
def prb_response(request: pytest.FixtureRequest) -> tuple[bytearray, str]:
    """Return faulty response frame."""
    return request.param


async def test_problem_response(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    problem_response: tuple[bytearray, str],
) -> None:
    """Test data update with BMS returning error flags."""

    monkeypatch.setattr(
        MockEJBleakClient, "_response", lambda _s, _c, _d: problem_response[0]
    )

    patch_bleak_client(MockEJBleakClient)

    bms = BMS(generate_ble_device())

    result: BMSSample = await bms.async_update()
    assert result.get("problem", False)  # we expect a problem
    assert result.get("problem_code", 0) == (
        0x4 if problem_response[1] == "first_bit" else 0x800
    )

    await bms.disconnect()
