"""Public exception types for aiobmsble."""


class BMSError(Exception):
    """Base class for all aiobmsble errors."""

    retryable: bool = True

    def __init__(
        self, msg: str = "", *, bms_id: str | None = None, address: str | None = None
    ) -> None:
        """Initialize an aiobmsble error with optional device context."""
        super().__init__(msg)
        self.bms_id: str | None = bms_id
        self.address: str | None = address


class BMSConnectionError(BMSError, ConnectionError):
    """BLE link could not be established or was lost."""


class BMSTimeoutError(BMSError, TimeoutError):
    """Device connected but did not send a valid reply in time."""


class BMSDataError(BMSError, ValueError):
    """Reply received but incomplete or inconsistent."""


class BMSAuthError(BMSError, PermissionError):
    """Secret/PIN missing or rejected by the device."""

    retryable = False


class BMSConfigError(BMSError, ValueError):
    """Invalid BMSConfig or API usage."""

    retryable = False


class BMSUnsupportedError(BMSConnectionError):
    """Device lacks a required GATT service or characteristic."""

    retryable = False


class BMSCommandRejectedError(BMSError):
    """Device actively refused a command."""

    retryable = False
