"""URL sanitation for logs, telemetry, and error messages.

Strips ``user:pass@`` userinfo and masks the values of known-sensitive query
parameters so secrets embedded in URLs do not leak into observability output.
Shared by ``errors.py`` (StatusError messages) and the resilience middleware
(event attributes).
"""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


SENSITIVE_QUERY_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "token",
        "secret",
        "client_secret",
        "password",
        "passwd",
        "pwd",
        "auth",
        "authorization",
        "sig",
        "signature",
        "key",
        "private_key",
        "session",
        "sessionid",
        "x-api-key",
    }
)

_REDACTED = "REDACTED"


def _strip_userinfo(url: str) -> str:
    if "@" not in url or "://" not in url:
        return url
    parts = urlsplit(url)
    if parts.username is None and parts.password is None:
        return url
    hostname = parts.hostname or ""
    if ":" in hostname:  # IPv6 literal — re-wrap in brackets
        hostname = f"[{hostname}]"
    netloc = hostname
    if parts.port is not None:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _mask_query(url: str) -> str:
    parts = urlsplit(url)
    if not parts.query:
        return url
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    if not any(key.lower() in SENSITIVE_QUERY_KEYS for key, _ in pairs):
        return url  # common-path guard: nothing sensitive, leave bytes untouched
    masked = [(key, _REDACTED if key.lower() in SENSITIVE_QUERY_KEYS else value) for key, value in pairs]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(masked), parts.fragment))


def redact_url(url: str) -> str:
    """Return ``url`` safe for logs/telemetry/errors.

    Userinfo is stripped and the values of known-sensitive query parameters are
    replaced with ``REDACTED`` (keys preserved). URLs with no sensitive query
    key are returned byte-identical to the userinfo-stripped input.
    """
    return _mask_query(_strip_userinfo(url))
