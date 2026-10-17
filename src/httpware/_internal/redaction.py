"""URL sanitation for logs, telemetry, and error messages.

Strips ``user:pass@`` userinfo and masks every query and fragment parameter
value, keeping the keys, so secrets embedded in URLs do not leak into
observability output. Shared by ``errors.py`` (StatusError messages) and
``observability._emit_event`` (event attributes).
"""

from urllib.parse import urlsplit, urlunsplit


_REDACTED = "REDACTED"


def _reassemble(scheme: str, netloc: str, path: str, query: str, fragment: str) -> str:
    """Like ``urlunsplit``, but return ``scheme:path`` rather than ``scheme:///path`` for an empty authority."""
    if netloc:
        return urlunsplit((scheme, netloc, path, query, fragment))
    tail = path
    if query:
        tail += "?" + query
    if fragment:
        tail += "#" + fragment
    return f"{scheme}:{tail}" if scheme else tail


def _strip_userinfo(url: str) -> str:
    if "@" not in url or "://" not in url:
        return url
    parts = urlsplit(url)
    if parts.username is None and parts.password is None:
        return url
    netloc = parts.netloc.rpartition("@")[2]
    return _reassemble(parts.scheme, netloc, parts.path, parts.query, parts.fragment)


def _mask_component(component: str) -> str:
    """Replace the value of every ``key=value`` pair with ``REDACTED``; a component without ``=`` is kept."""
    if "=" not in component:
        return component
    return "&".join(
        key + "=" + _REDACTED if sep else key for key, sep, _ in (pair.partition("=") for pair in component.split("&"))
    )


def _mask_query(url: str) -> str:
    if "=" not in url:
        return url
    rest, hash_sign, fragment = url.partition("#")
    base, question_mark, query = rest.partition("?")
    return base + question_mark + _mask_component(query) + hash_sign + _mask_component(fragment)


def redact_url(url: str) -> str:
    """Return ``url`` safe for logs, telemetry and error messages.

    Userinfo is stripped and every query and fragment parameter value is
    replaced with ``REDACTED``, keeping the keys as written. A fragment with no
    ``=`` in it, such as ``#section-3``, is kept as it is.
    """
    return _mask_query(_strip_userinfo(url))
