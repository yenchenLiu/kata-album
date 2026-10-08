"""Exception types separating retryable from fatal failures."""


class KataError(Exception):
    """Base error. Messages must never contain credentials."""


class AuthRejected(KataError):
    """refreshToken explicitly rejected or unsupported branch (e.g. 2006)."""


class CloudError(KataError):
    """Transient cloud/network failure."""


class LocalError(KataError):
    """Local service unreachable or rejected the request."""


class LocalServiceDisabled(LocalError):
    """9230 reports is_enable=false; reopening it (1021) is the remedy."""


class NotConfigured(KataError):
    """Required setting (e.g. MQTT callback) missing."""
