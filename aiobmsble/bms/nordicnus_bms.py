"""Module to support Nordic NUS BLE BMS.

This driver implements the protocol used by various LiFePO4 battery management
systems that communicate via Nordic UART Service (NUS) over Bluetooth LE.

## Hardware Compatibility

**Tested and verified working with:**
- Chins Battery with Nordic NUS BMS (model G-12V300Ah-0345)

**Device Matching:**
The driver matches devices by local_name pattern to avoid conflicts with other
BMSes that also use the Nordic UART Service UUID. Currently supports:
- `G-*` pattern (Chins Battery and compatible devices)

If your Nordic NUS BMS uses a different naming pattern, you can either:
1. Submit a PR to add the pattern to `matcher_dict_list()`
2. Use a custom matcher in your application code

**Note:** The service UUID `6e400001-b5a3-f393-e0a9-e50e24dcca9e` is shared
by multiple BMS types (e.g., Vatrer), so local_name matching is required for
proper device identification.

## Connection Management & Memory Protection

**Critical**: The nRF52 BLE chip in this BMS can experience buffer buildup and
memory exhaustion during long-running connections, leading to BMS lockup.

This driver implements **planned periodic reconnection** every 5 minutes:
- Clean disconnect from BMS
- 5-second wait for BMS buffer flush (critical for nRF52 stability)
- Auto-reconnect on next update cycle
- Returns cached data during reconnection window

This is NOT error recovery—it's a preventive maintenance strategy learned from
extensive field testing. Without this, the BMS can deadlock after hours of
continuous operation.

## Protocol Specification

**Communication:** Nordic UART Service (NUS) over BLE
- Service UUID: `6e400001-b5a3-f393-e0a9-e50e24dcca9e`
- RX Characteristic: `6e400003-b5a3-f393-e0a9-e50e24dcca9e` (notifications from device)
- TX Characteristic: `6e400002-b5a3-f393-e0a9-e50e24dcca9e` (writes to device)

**Frame Format:** 140-byte ASCII hex frames delimited by ':' and '~'
- Header: ':' (0x3A, position 0)
- Data: 138 ASCII hex characters (positions 1-138)
- Footer: '~' (0x7E, position 139)

**Trigger Command:** `:000250000E03~` must be sent every 10 seconds to maintain data flow

## Frame Data Layout

All positions refer to ASCII character positions in the 140-byte frame.

### Critical Data Fields

| Position | Length | Field | Format | Units | Formula |
|----------|--------|-------|--------|-------|---------|
| 0 | 1 | Header | ASCII | - | Must be ':' |
| 1-24 | 24 | Metadata | ASCII hex | - | Frame metadata/padding |
| **25-88** | **64** | **Cell Voltages** | **16×uint16** | **mV** | **big-endian: (hi<<8)|lo** |
| **89-96** | **8** | **Current** | **2×uint16** | **10mA** | **charge/discharge pair** |
| **97-98** | **2** | **Temperature** | **uint8** | **°C** | **value - 40, clamped ≤120** |
| 99-104 | 6 | Reserved | ASCII hex | - | Padding |
| **105-108** | **4** | **Status Code** | **uint16** | **hex** | **State/alarm flags** |
| **109-118** | **10** | **Extended** | **5×uint8** | **mixed** | **heater+energy+cycles** |
| 119-122 | 4 | Reserved | ASCII hex | - | Padding |
| **123-124** | **2** | **SOC** | **uint8** | **%** | **0-100** |
| 125-132 | 8 | Reserved | ASCII hex | - | Padding |
| **133-136** | **4** | **Capacity** | **uint16** | **0.1Ah** | **value/10, clamped ≤1000** |
| 137-138 | 2 | Reserved | ASCII hex | - | Padding |
| 139 | 1 | Footer | ASCII | - | Must be '~' |

### Field Details

#### Cell Voltages [25:88]
- 16 consecutive big-endian 16-bit values (32 bytes = 64 hex chars)
- Each value represents cell voltage in millivolts
- Typical range: 1500-4500 mV for LiFePO4 cells
- Zero values indicate unused cell positions
- Cell count determined by contiguous non-zero values from start

#### Current [89:96]
- Two big-endian 16-bit values (4 bytes = 8 hex chars)
- Bytes 0-1 (positions 89-92): Charge current
- Bytes 2-3 (positions 93-96): Discharge current
- Units: 10mA resolution (multiply by 10 to get mA)
- Net current: (charge - discharge) / 1000 = Amps
- Positive = charging, Negative = discharging, Zero = idle

#### Temperature [97:98]
- Single unsigned byte (1 byte = 2 hex chars)
- Raw value offset by 40°C: actual_temp = raw_value - 40
- Clamped at 120°C maximum to prevent overflow
- Represents BMS internal temperature

#### Status Code [105:108]
- 16-bit status/alarm word (2 bytes = 4 hex chars)
- First hex digit indicates operational state:
  - 'A' = Discharging
  - '5' = Charging
  - 'F' = Idle/Standby (normal)
- Full word indicates alarm conditions:
  - 5800 = Cell overvoltage
  - 5400 = Pack overvoltage
  - A200 = Cell undervoltage
  - A100 = Pack undervoltage
  - 5080 = Charge over-temperature
  - 5020 = Charge under-temperature
  - A010 = Discharge over-temperature
  - 5008 = Discharge under-temperature
  - A004 = Charge overcurrent
  - A006 = Discharge overcurrent
  - A005 = Short circuit protection
  - 5300 = MOS over-temperature
  - CA00 = Cell failure
  - C500 = Communication error

#### Extended Data [109:118]
- Five consecutive bytes (5 bytes = 10 hex chars)
- Byte 0 (positions 109-110): Heater flag (0=off, non-zero=on)
  - Exposed as BMSSample "heater" field
- Bytes 1-2 (positions 111-114): AddElectric - total energy consumed
  - Big-endian uint16, multiply by 10 = milliamp-hours
  - Divide by 1000 = Amp-hours total consumption
  - Exposed as BMSSample "cycle_charge" field
- Bytes 3-4 (positions 115-118): Cycle count
  - Big-endian uint16 = number of charge cycles
  - Exposed as BMSSample "cycles" field

#### State of Charge [123:124]
- Single unsigned byte (1 byte = 2 hex chars)
- Direct percentage value: 0-100%
- No conversion needed
- Exposed as BMSSample "battery_level" field
- Also used to derive "battery_health" (100=Excellent if SOC≥80%, 80=Good if SOC≥60%, 50=Poor if SOC<60%)

#### Capacity [133:136]
- Big-endian 16-bit value (2 bytes = 4 hex chars)
- Units: 0.1 Ah (decidecimal Amp-hours)
- Divide by 10 to get Amp-hours
- Clamped at 1000 Ah maximum
- Exposed as BMSSample "design_capacity" field

## Special Features

- **Automatic cell count detection:** Determines 4-16S configuration from data
- **Frame resynchronization:** Handles split/merged notification packets
- **Voltage validation:** Filters corrupt frames with out-of-range voltages
- **Periodic wake-up:** Requires trigger every 10s to maintain data flow

## Example Frame

Real frame from G-12V300Ah-0345 (4S 300Ah LiFePO4):
```
:008231008C000000000000000CFE0CD50D050CFC0000000000000000...~
                            └─ Cells: 3.326V, 3.285V, 3.333V, 3.324V
```

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

import asyncio
import time
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError

from aiobmsble import BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS


class BMS(BaseBMS):
    """Nordic NUS BLE BMS implementation.

    This BMS uses the Nordic UART Service for communication and requires
    periodic wake-up triggers to maintain data flow. The protocol uses
    ASCII hex frames with automatic resynchronization.
    """

    INFO: BMSInfo = {"default_manufacturer": "Nordic NUS", "default_model": "BLE BMS"}

    # Frame constants
    _FRAME_LEN: Final[int] = 140  # exact ASCII frame length including delimiters
    _MIN_FRAME_LEN: Final[int] = 90  # minimum valid frame length for initial checks
    _HEAD: Final[bytes] = b":"
    _TAIL: Final[bytes] = b"~"
    _TRIGGER: Final[bytes] = b":000250000E03~"
    _TRIGGER_INTERVAL: Final[float] = 10.0  # seconds between triggers

    # Cell voltage validation ranges (millivolts)
    _MIN_CELL_MV: Final[int] = 1500  # 1.5V minimum
    _MAX_CELL_MV: Final[int] = 4500  # 4.5V maximum
    _MIN_CELLS: Final[int] = 4
    _MAX_CELLS: Final[int] = 16

    # Connection management to prevent nRF52 buffer buildup and memory exhaustion
    _PLANNED_RECONNECT_INTERVAL: Final[float] = 300.0  # Reconnect every 5 minutes
    _BUFFER_FLUSH_DELAY: Final[float] = 5.0  # Wait after disconnect for BMS to flush

    def __init__(self, ble_device: BLEDevice, keep_alive: bool = True) -> None:
        """Initialize BMS."""
        super().__init__(ble_device, keep_alive)
        self._nus_buf: bytearray = bytearray()  # accumulation buffer for notifications
        self._last_trigger_time: float = 0.0
        self._cell_count: int = 4  # default, will be detected from first frame
        self._last_valid_data: BMSSample = {}  # cache last valid data
        self._connection_start_time: float = 0.0  # track connection start for periodic reconnect

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition.

        Returns patterns for known Nordic NUS BMS implementations.
        The matcher uses local_name patterns to differentiate from other
        BMSes that also use the Nordic UART Service UUID.

        Known patterns:
        - G-* : Chins Battery (e.g., G-12V300Ah-0345)

        If your Nordic NUS BMS uses a different naming pattern, you can:
        1. Submit a PR to add the pattern here
        2. Use a custom matcher in your application
        """
        return [
            {
                "local_name": "G-*",  # Chins Battery and compatible
                "service_uuid": BMS.uuid_services()[0],
                "connectable": True,
            },
            # Add more patterns here as different hardware is discovered
            # Pattern must be specific enough to not conflict with vatrer_bms
            # which uses: [2-9]???[0-3]?512??00??
        ]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return ("6e400001-b5a3-f393-e0a9-e50e24dcca9e",)

    @staticmethod
    def uuid_rx() -> str:
        """Return 128-bit UUID of characteristic that provides notification/read property."""
        return "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

    @staticmethod
    def uuid_tx() -> str:
        """Return 128-bit UUID of characteristic that provides write property."""
        return "6e400002-b5a3-f393-e0a9-e50e24dcca9e"

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives).

        Accumulates notification chunks and extracts complete frames.
        Uses resynchronization logic to handle multiple headers and
        enforces exact frame length validation.
        """
        self._log.debug("RX BLE data: %s", data)

        # Accumulate notification data
        self._nus_buf.extend(data)

        # Try to extract complete frames
        while True:
            # Resynchronization: keep only data from the last ':' header
            last_start = self._nus_buf.rfind(BMS._HEAD)
            if last_start == -1:
                # No header found, clear buffer if too large
                if len(self._nus_buf) > 512:
                    self._log.debug("No header found, clearing buffer")
                    self._nus_buf.clear()
                break

            if last_start > 0:
                # Discard everything before the latest header
                self._log.debug("Resyncing: discarding %d bytes before header", last_start)
                del self._nus_buf[:last_start]

            # Now search for footer after the header (at index 0)
            end_idx = self._nus_buf.find(BMS._TAIL, 1)
            if end_idx == -1:
                # Wait for more data
                break

            # Extract potential frame
            frame = self._nus_buf[: end_idx + 1]

            # Enforce exact frame length (140 bytes)
            if len(frame) != BMS._FRAME_LEN:
                self._log.debug(
                    "Invalid frame length %d, expected %d, discarding",
                    len(frame),
                    BMS._FRAME_LEN,
                )
                # Discard this frame and continue scanning
                del self._nus_buf[: end_idx + 1]
                continue

            # Valid frame found - consume it and signal
            del self._nus_buf[: end_idx + 1]
            self._log.debug("Valid frame extracted: %s", frame[:40])
            self._frame = frame
            self._msg_event.set()

            # Continue to check for more frames in buffer

    def _parse_frame(self, frame: bytearray) -> BMSSample:  # noqa: C901, PLR0912, PLR0915
        """Parse a complete ASCII hex frame and extract battery data.

        Args:
            frame: 140-byte ASCII frame including ':' and '~' delimiters

        Returns:
            Dictionary containing parsed battery data

        Raises:
            ValueError: If frame is invalid or contains non-hex data
        """
        # Decode to string and strip whitespace/newlines
        try:
            frame_str = bytes(frame).decode("ascii", errors="ignore")
            frame_str = frame_str.replace("\r", "").replace("\n", "")
        except Exception as exc:
            msg = "Frame decode failed"
            raise ValueError(msg) from exc

        # Validate delimiters
        if not frame_str.startswith(":") or not frame_str.endswith("~"):
            msg = "Invalid frame delimiters"
            raise ValueError(msg)

        # Enforce minimum frame length for parsing
        if len(frame_str) < BMS._MIN_FRAME_LEN:
            msg = f"Frame too short: {len(frame_str)} < {BMS._MIN_FRAME_LEN}"
            raise ValueError(msg)

        result: BMSSample = {}

        # Helper functions for hex parsing
        def hex_to_int(hex_str: str) -> int:
            """Convert hex string to integer."""
            if not hex_str:  # pragma: no cover
                # Defensive: Fixed-length string slicing always returns content
                return 0
            try:
                return int(hex_str, 16)
            except ValueError:  # pragma: no cover
                # Defensive: is_hex_str() validation prevents invalid hex
                return 0

        def is_hex_str(text: str) -> bool:
            """Check if string is valid hex."""
            try:
                int(text, 16)
            except ValueError:
                return False
            else:
                return True

        # Parse cell voltages: str[25:89] -> 32 bytes -> 16 big-endian 16-bit values
        cell_hex = frame_str[25:89]
        if len(cell_hex) != 64:  # pragma: no cover
            # Defensive: Fixed slicing [25:89] always yields 64 chars for valid frames
            raise ValueError(f"Invalid cell section length: {len(cell_hex)}, expected 64")
        if not is_hex_str(cell_hex):
            raise ValueError("Invalid hex characters in cell section")

        # Parse all 16 cell registers
        full_values_mv = []
        for i in range(0, 64, 4):
            hi = hex_to_int(cell_hex[i : i + 2])
            lo = hex_to_int(cell_hex[i + 2 : i + 4])
            mv = (hi << 8) | lo
            full_values_mv.append(mv)

        # Detect cell count from contiguous non-zero values
        detected_cells = 0
        for mv in full_values_mv:
            if mv > 0:
                detected_cells += 1
            else:
                break

        # Clamp to valid range
        detected_cells = max(BMS._MIN_CELLS, min(BMS._MAX_CELLS, detected_cells))

        self._cell_count = detected_cells
        result["cell_count"] = detected_cells

        # Find plausible consecutive window of cells
        def is_plausible(mv: int) -> bool:
            return BMS._MIN_CELL_MV <= mv <= BMS._MAX_CELL_MV

        start_index = None
        for start in range(17 - detected_cells):
            window = full_values_mv[start : start + detected_cells]
            if all(is_plausible(v) for v in window):
                start_index = start
                break

        if start_index is None:
            raise ValueError(f"No plausible cell voltage window found for {detected_cells} cells")

        # Extract valid cell voltages
        cell_voltages = []
        pack_mv = 0
        for idx in range(detected_cells):
            mv = full_values_mv[start_index + idx]
            cell_voltages.append(mv / 1000.0)
            pack_mv += mv

        result["cell_voltages"] = cell_voltages

        # Validate pack voltage range
        pack_v = pack_mv / 1000.0
        # For 4S: 8.0-16.8V, scale for other counts
        min_pack_v = detected_cells * 2.0
        max_pack_v = detected_cells * 4.2
        if min_pack_v <= pack_v <= max_pack_v:
            result["voltage"] = round(pack_v, 3)
        else:  # pragma: no cover
            # Defensive: Plausible cell check (2.0-4.2V) ensures pack is always in range
            raise ValueError(
                f"Pack voltage {pack_v}V out of range [{min_pack_v}-{max_pack_v}]V"
            )

        # Parse currents: str[89:97] -> 4 bytes (charge, discharge) in 10mA units
        cur_hex = frame_str[89:97]
        if len(cur_hex) == 8 and is_hex_str(cur_hex):
            chg_raw = hex_to_int(cur_hex[0:4])
            dsg_raw = hex_to_int(cur_hex[4:8])
            chg_ma = chg_raw * 10
            dsg_ma = dsg_raw * 10
            net_ma = chg_ma - dsg_ma
            result["current"] = round(net_ma / 1000.0, 2)

        # Parse temperature: str[97:99] -> 1 byte, value - 40, clamp <= 120
        temp_hex = frame_str[97:99]
        if len(temp_hex) == 2 and is_hex_str(temp_hex):
            temp_c = hex_to_int(temp_hex) - 40
            temp_c = min(temp_c, 120)
            result["temp_values"] = [float(temp_c)]
            result["temperature"] = float(temp_c)

        # Parse SOC: str[123:125]
        soc_hex = frame_str[123:125]
        if len(soc_hex) == 2 and is_hex_str(soc_hex):
            soc = hex_to_int(soc_hex)
            if 0 <= soc <= 100:
                result["battery_level"] = soc

                # Derive battery_health from SOC (UI indicator, not true SoH)
                # This matches the reference implementation's health classification
                if soc >= 80:
                    result["battery_health"] = 100  # Excellent
                elif soc >= 60:
                    result["battery_health"] = 80   # Good
                else:
                    result["battery_health"] = 50   # Poor

                if soc == 0:
                    self._log.warning("Parsed SOC=0%%, frame snippet: %s", frame_str[120:130])

        # Parse status code: str[105:109] -> 2 bytes
        status_hex = frame_str[105:109]
        if len(status_hex) == 4 and is_hex_str(status_hex):
            status_code = hex_to_int(status_hex)

            # Interpret status code for alarms
            # Reference alarm codes from protocol specification
            alarm_codes = {
                0x5800: "Cell overvoltage",
                0x5400: "Pack overvoltage",
                0xA200: "Cell undervoltage",
                0xA100: "Pack undervoltage",
                0x5080: "Charge over-temperature",
                0x5020: "Charge under-temperature",
                0xA010: "Discharge over-temperature",
                0x5008: "Discharge under-temperature",
                0xA004: "Charge overcurrent",
                0xA006: "Discharge overcurrent",
                0xA005: "Short circuit protection",
                0x5300: "MOS over-temperature",
                0xCA00: "Cell failure",
                0xC500: "Communication error",
            }

            # Only set problem_code and problem for actual alarm conditions
            # Operational states (0xF000=Idle, 0x5xxx=Charging, 0xAxxx=Discharging)
            # that are not in the alarm list should not be flagged as problems
            if status_code in alarm_codes:
                result["problem_code"] = status_code
                result["problem"] = True
                self._log.warning("BMS Alarm: %s (code: 0x%04X)", alarm_codes[status_code], status_code)

            # Interpret first digit for operational state (but don't set problem flag)
            # F = Idle/Standby (normal), 5 = Charging, A = Discharging
            # These are normal states, not problems

        # Parse heater flag + AddElectric + Cycle count: str[109:119] -> 5 bytes
        extra_hex = frame_str[109:119]
        if len(extra_hex) == 10 and is_hex_str(extra_hex):
            # Convert to byte array
            extra_bytes = [hex_to_int(extra_hex[i:i+2]) for i in range(0, 10, 2)]

            # Byte 0: heater flag (non-zero = on)
            heater_on = extra_bytes[0] != 0
            result["heater"] = heater_on  # BMSSample standard field

            # Bytes 1-2: AddElectric (total energy consumed in mAh)
            add_electric_raw = ((extra_bytes[1] << 8) | extra_bytes[2]) * 10  # mAh
            result["cycle_charge"] = round(add_electric_raw / 1000.0, 2)  # Convert to Ah

            # Bytes 3-4: cycle count
            cycles = (extra_bytes[3] << 8) | extra_bytes[4]
            result["cycles"] = cycles

        # Parse capacity: str[133:137] -> 2 bytes, divide by 10 -> Ah
        cap_hex = frame_str[133:137]
        if len(cap_hex) == 4 and is_hex_str(cap_hex):
            cap_hi = hex_to_int(cap_hex[0:2])
            cap_lo = hex_to_int(cap_hex[2:4])
            cap_raw = (cap_hi << 8) | cap_lo
            cap_ah = cap_raw / 10.0
            cap_ah = min(cap_ah, 1000)
            result["design_capacity"] = int(round(cap_ah))

        # Set FET status (not exposed by this BMS, default to True)
        result["chrg_mosfet"] = True
        result["dischrg_mosfet"] = True

        return result

    async def _send_trigger(self) -> None:
        """Send wake-up trigger to BMS."""
        try:
            await self._client.write_gatt_char(
                self.uuid_tx(), BMS._TRIGGER, response=False
            )
            self._log.debug("Trigger sent: %s", BMS._TRIGGER)
        except (BleakError, AttributeError, RuntimeError) as exc:
            # BleakError: BLE write failures
            # AttributeError: Client not connected or characteristic not available
            # RuntimeError: Other write failures
            self._log.warning("Failed to send trigger: %s", exc)

    async def _async_update(self) -> BMSSample:
        """Update battery status information.

        Sends periodic wake-up triggers and waits for frame notifications.
        Parses received frames and returns battery data.

        Implements planned periodic reconnection every 5 minutes to prevent
        nRF52 buffer buildup and memory exhaustion that can lock up the BMS.

        Returns:
            Dictionary containing battery measurements

        Raises:
            TimeoutError: If no valid frame received within timeout
        """
        # Planned periodic reconnection to prevent nRF52 buffer buildup
        # The nRF52 BLE chip can deadlock if buffers fill during long connections
        # This is a clean, controlled disconnect/reconnect cycle (not error recovery)
        if self._client.is_connected and self._connection_start_time > 0:
            time_connected = time.time() - self._connection_start_time
            if time_connected >= BMS._PLANNED_RECONNECT_INTERVAL:
                self._log.info(
                    "Planned reconnection after %ds to prevent buffer buildup",
                    int(time_connected)
                )

                # Clean disconnect
                await self.disconnect()

                # Wait for BMS to flush buffers (critical for nRF52 stability)
                await asyncio.sleep(BMS._BUFFER_FLUSH_DELAY)

                # Mark reconnection time and reset connection timer
                # BaseBMS will auto-reconnect on next update cycle
                self._connection_start_time = time.time()

                # Return cached data for this cycle
                if self._last_valid_data:
                    self._log.debug("Returning cached data during reconnection")
                    return self._last_valid_data
                # If no cached data, let the exception propagate to trigger reconnect
                raise TimeoutError("Reconnection in progress, no cached data available")

        # Record connection start time on first update after connection
        if self._client.is_connected and self._connection_start_time == 0:
            self._connection_start_time = time.time()
            self._log.debug("Connection start time recorded")

        now = time.time()

        # Send trigger if interval elapsed
        if now - self._last_trigger_time >= BMS._TRIGGER_INTERVAL:
            await self._send_trigger()
            self._last_trigger_time = now

        # Wait for notification with frame
        # The _notification_handler will set _msg_event when a valid frame arrives
        try:
            await asyncio.wait_for(self._msg_event.wait(), timeout=self.TIMEOUT)
        except TimeoutError as exc:
            # Send trigger again and retry once
            self._log.debug("Timeout waiting for frame, retrying with trigger")
            await self._send_trigger()
            self._last_trigger_time = time.time()
            try:
                await asyncio.wait_for(self._msg_event.wait(), timeout=self.TIMEOUT)
            except TimeoutError:
                msg = "No frame received after trigger retry"
                raise TimeoutError(msg) from exc

        self._msg_event.clear()

        # Parse the frame
        try:
            result = self._parse_frame(self._frame)
            self._last_valid_data = result  # cache for potential future use
            self._log.debug("Parsed data: %s", result)
        except ValueError as exc:
            self._log.warning("Frame parsing failed: %s", exc)
            # If we have cached data, could return it here, but for now raise error
            msg = f"Invalid frame: {exc}"
            raise TimeoutError(msg) from exc
        else:
            return result
