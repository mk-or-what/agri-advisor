class AdvisorError(Exception):
    """Base class for all expected application errors."""


class DataUnavailableError(AdvisorError):
    """A required real-world data source returned no usable data."""


class UpstreamTimeoutError(AdvisorError):
    """An external API did not answer in time."""


class SchemaMismatchError(AdvisorError):
    """An external API answered, but not in the shape we expected."""
