## Lithionics BMS Protocol

Lithionics BMS units can emit their serial stream in more than one layout,
selected by the device's own `Serial Data Format` setting (parameter 42:
`0` fixed width, `1` comma, `2` fixed-length comma delimited).

The current parser handles the plain comma-delimited variant. My **48 V / 16S**
pack (`Li3-`, firmware `9.0.04`) emits the zero-padded fixed-length variant,
which has the *same field count* but a different field order:

```
comma        (12 V, 4 cells):  1399,350,350,350,349,55,48,-3,99,000000
fixed-length (48 V, 16 cells): 1,01594,0525,048,048,0,00000,000000,080,000100
```

### Status Code

Status codes are masked with `_PROBLEM_MASK` so only genuine fault bits raise
`problem`. Benign state bits (notably byte 1 bit 0, "AUX Contacts State", set in
the normal idle value) no longer trip it.
For details, see Lithionics' `RV-C J1939 PGN Table Rev4`, section 6 *UART-CAN Mapping* and the *BMS Status Code Flags* table.

### Field semantics

```
1,01594,0525,048,048,0,00000,000000,080,000100
| |     |    |   |   | |     |      |   `- status flags (3 bytes, hex)
| |     |    |   |   | |     |      `----- temperature (degF)
| |     |    |   |   | |     `------------ power (1 W/bit)
| |     |    |   |   | `------------------ current (0.1 A/bit)
| |     |    |   |   `-------------------- 1: charging, 0: discharging
| |     |    |   `------------------------ second SoC-like field (see below)
| |     |    `---------------------------- state of charge (%)
| |     `--------------------------------- voltage (0.1 V/bit)
| `--------------------------------------- charge remaining (0.1 Ah/bit)
`----------------------------------------- battery ID (instance)
```

The trace line ends with lowest/highest/average cell voltage, giving
`delta_voltage`:

```
&,1,0525,0525,078,2,075845,0576,3300,FF03,0000,00,327,328,328
                                              low ^   ^   ^ avg
```

### Verified against the vendor app

Every value was cross-checked against the Lithionics app reading the same pack
at the same time:

| Field | App | Parsed |
| --- | --- | --- |
| Voltage | 52.5 V | 52.5 V |
| SOC | 48 % | 48 |
| Remaining AH | 159 Ah | 159.4 |
| Battery temperature | 80 F | 26.667 degC (= 80.0 F) |
| Status code | 000100 | `0x000100`, masked to 0 |

The trace line independently corroborates: `0576` → CAN Charger 57.60 V,
`3300` → 330 A, `FF03` → charger status FF03, `2` → Modules Count 2 — all
matching the app's diagnostics page.

There is also a `52.5 V / 16 cells = 3.281 V` vs the BMS's own reported
`3.27-3.28 V` per cell cross-check, from two unrelated fields.

### Deliberately not included

- **`fields[4]`** reads identically to SoC in every sample captured, and the
  app shows no second percentage, so it cannot be identified yet. It is left
  unexposed rather than guessed at.
- **Per-module cell voltages.** This firmware also emits `#` lines carrying
  full per-module data (2 modules x 16 cells here), decoded and confirmed
  against the app but out of scope for this PR. Happy to follow up:
  ```
  #,1,1,00,40,16,27,31,328,328,328,0000,84,<16 cell voltages>
    | |  |  |  |  |  `- BMS temp (degC)  `- FW      low/high/avg ^
    | |  |  |  |  `---- cell temp (degC)
    | |  |  |  `------- cell count
    | |  |  `---------- last code
    | |  `------------- status code
    | `---------------- module ID
    `------------------ battery ID
  ```

### Known limitation

Temperature units are **device-configurable** (the app has a C/F toggle), and
the stream carries no unit indicator.