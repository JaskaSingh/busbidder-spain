"""Exception hierarchy for BusBidder Spain.

Every project-specific error inherits from BusBidderError, so the command-line
layer can catch all expected failures in one place and show a clear message,
while genuine bugs still produce a full traceback.
"""


class BusBidderError(Exception):
    """Base class for all expected failures in the application."""


class DataFileError(BusBidderError):
    """A required input file is missing, unreadable or has the wrong columns."""

    def __init__(self, path, reason):
        self.path = str(path)
        self.reason = reason
        super().__init__(f"{self.path}: {reason}")


class InvalidValueError(BusBidderError):
    """A single field holds a value that breaks a validation rule."""

    def __init__(self, field, value, reason):
        self.field = field
        self.value = value
        self.reason = reason
        super().__init__(f"{field} = {value!r}: {reason}")


class ConfigError(BusBidderError):
    """A traveller profile or other configuration is invalid."""

    def __init__(self, source, reason):
        self.source = str(source)
        self.reason = reason
        super().__init__(f"{self.source}: {reason}")


class RegistryError(BusBidderError):
    """A name is missing from, or registered twice in, a registry."""

    def __init__(self, name, reason):
        self.name = name
        self.reason = reason
        super().__init__(f"{name!r} {reason}")


class BookingError(BusBidderError):
    """A booking cannot be made, for example because too few seats are left."""
