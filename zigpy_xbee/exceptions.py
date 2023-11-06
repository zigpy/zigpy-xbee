"""Additional exceptions for XBee."""


class ATCommandException(Exception):
    """Base exception class for AT Command exceptions."""


class ATCommandError(ATCommandException):
    """Exception for AT Command Status 1 (ERROR)."""


class InvalidCommand(ATCommandException):
    """Exception for AT Command Status 2 (Invalid command)."""


class InvalidParameter(ATCommandException):
    """Exception for AT Command Status 3 (Invalid parameter)."""


class TransmissionFailure(ATCommandException):
    """Exception for Remote AT Command Status 4 (Transmission failure)."""
