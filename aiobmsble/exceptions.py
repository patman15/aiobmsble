"""Exceptions raised by aiobmsble.

All public BMS operations (`aiobmsble.basebms.BaseBMS.update()`,
`aiobmsble.basebms.BaseBMS.device_info()`, `aiobmsble.basebms.BaseBMS.limits()` and
`async with bms:`) raise only subclasses of `BMSError`. Bleak and other low-level errors
are translated and remain available as `__cause__`. Exceptions to this rule are
`asyncio.CancelledError` and programming errors such as `TypeError` or `AssertionError`.

| Exception | Meaning | `retryable` |
|---|---|---|
| `BMSConnectionError` | BLE link could not be established or was lost | yes |
| `BMSTimeoutError` | no valid reply from the BMS in time | yes |
| `BMSDataError` | reply incomplete or inconsistent | yes |
| `BMSAuthError` | secret/PIN missing or rejected | no |
| `BMSConfigError` | invalid `aiobmsble.BMSConfig` or API usage | no |
| `BMSUnsupportedError` | required GATT service/characteristic missing | no |
| `BMSCommandRejectedError` | BMS refused a command | no |

Most exceptions also derive from the matching built-in exception (e.g. `BMSTimeoutError`
is a `TimeoutError`), so existing `except` clauses keep working. `BMSCommandRejectedError`
has no built-in counterpart and derives from `BMSError` only.

Retries are already done inside the library. Retry a failed call at the next poll
interval if `BMSError.retryable` is `True`; otherwise user action is required.

```python
from aiobmsble import BMSAuthError, BMSError

try:
    data = await bms.update()
except BMSAuthError:
    ...  # ask the user for a (new) secret, stop polling
except BMSError as exc:
    if exc.retryable:
        ...  # mark device unavailable, try again at the next poll
    else:
        ...  # wrong plugin or unsupported device, stop polling
```

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""


class BMSError(Exception):
    """Base class for all aiobmsble errors.

    Catch this class to handle every error raised by the library.
    """

    retryable: bool = True
    """`True` if the failure is temporary and the call may be repeated at the next poll."""

    default_msg: str = "BMS operation failed."
    """Message used if the exception is raised without one."""

    def __init__(
        self, msg: str = "", *, bms_type: str | None = None, address: str | None = None
    ) -> None:
        """Initialize an aiobmsble error with optional device context.

        Args:
            msg: error description; `default_msg` is used if empty
            bms_type: BMS type (plugin module name, e.g. `dummy_bms`), set by the library if omitted
            address: Bluetooth address of the device, set by the library if omitted

        """
        super().__init__(msg or self.default_msg)
        self.bms_type: str | None = bms_type
        """BMS type (plugin module name, e.g. `dummy_bms`) that raised the error."""
        self.address: str | None = address
        """Bluetooth address of the device that raised the error."""


class BMSConnectionError(BMSError, ConnectionError):
    """BLE link could not be established or was lost.

    Typical causes: device out of range, switched off, or connected to another client.
    """

    default_msg = "BLE connection failed."


class BMSTimeoutError(BMSError, TimeoutError):
    """Device connected but did not send a valid reply in time.

    Raised after the internal retries are used up.
    """

    default_msg = "BMS did not send a valid reply in time."


class BMSDataError(BMSError, ValueError):
    """Reply received but incomplete or inconsistent.

    With `aiobmsble.BMSConfig.keep_alive` enabled the connection is kept for the next poll.
    """

    default_msg = "BMS data incomplete."


class BMSAuthError(BMSError, PermissionError):
    """Secret/PIN missing or rejected by the device.

    Provide a valid `aiobmsble.BMSConfig.secret` before trying again.
    """

    retryable = False
    default_msg = "Authentication failed."


class BMSConfigError(BMSError, ValueError):
    """Invalid `aiobmsble.BMSConfig` or API usage.

    Examples: a badly formatted secret, `async with` without `keep_alive=True`, or
    malformed advertisement data passed to `aiobmsble.utils.adv_dict_to_advdata()`.
    """

    retryable = False
    default_msg = "Invalid configuration."


class BMSUnsupportedError(BMSError, ConnectionError):
    """Device lacks a required GATT service or characteristic.

    Usually the wrong BMS plugin was selected or the firmware is not supported.
    """

    retryable = False
    default_msg = "Required GATT service or characteristic not found."


class BMSCommandRejectedError(BMSError):
    """Device actively refused a command (error reply)."""

    retryable = False
    default_msg = "Command rejected by BMS."
