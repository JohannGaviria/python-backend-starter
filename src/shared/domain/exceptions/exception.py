class BaseDomainException(Exception):
    """Base class for domain-specific exceptions."""

    pass


class CacheException(BaseDomainException):
    """Exception raised when a cache operation fails.

    Covers the failures caused by the caller: malformed data, a value that
    cannot be serialized, or a bug in the code rebuilding the cached value.
    When the cache backend itself is unreachable, use
    :class:`CacheUnavailableException` instead.

    Attributes:
        detail: What went wrong, including the message of the original error.
        key: The cache key involved in the failure.
    """

    def __init__(self, detail: str, key: str) -> None:
        """Initialize the CacheException.

        Args:
            detail (str): What went wrong, including the message of the
                original error.
            key (str): The cache key involved in the failure.
        """
        self.detail = detail
        self.key = key
        super().__init__(f"{detail} (key: {key})")


class CacheUnavailableException(CacheException):
    """Exception raised when the cache backend is unreachable.

    A separate type from CacheException because it means the dependency is
    down, not that the code is wrong: the caller can retry, and the failure
    maps to a different HTTP status than a bug.
    """
