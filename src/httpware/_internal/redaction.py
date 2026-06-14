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


def _mask_component(component: str) -> tuple[str, bool]:
    """Mask sensitive key=value pairs in a query or fragment string.

    Returns ``(masked_component, was_changed)``; when no sensitive key is
    found the original string is returned unchanged (``was_changed=False``).
    """
    pairs = parse_qsl(component, keep_blank_values=True)
    if not any(key.strip().lower() in SENSITIVE_QUERY_KEYS for key, _ in pairs):
        return component, False
    masked = [(key, _REDACTED if key.strip().lower() in SENSITIVE_QUERY_KEYS else value) for key, value in pairs]
    return urlencode(masked), True


def _mask_query(url: str) -> str:
    parts = urlsplit(url)
    has_query = bool(parts.query)
    has_fragment = bool(parts.fragment)

    if not has_query and not has_fragment:
        return url

    new_query = parts.query
    new_fragment = parts.fragment
    changed = False

    if has_query:
        new_query, q_changed = _mask_component(parts.query)
        changed = changed or q_changed

    if has_fragment:
        new_fragment, f_changed = _mask_component(parts.fragment)
        changed = changed or f_changed

    if not changed:
        return url  # common-path guard: nothing sensitive, leave bytes untouched

    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, new_fragment))


def redact_url(url: str) -> str:
    """Return ``url`` safe for logs/telemetry/errors.

    Userinfo is stripped and the values of known-sensitive query parameters are
    replaced with ``REDACTED`` (keys preserved). URLs with no sensitive query
    key are returned byte-identical to the userinfo-stripped input.
    """
    return _mask_query(_strip_userinfo(url))
