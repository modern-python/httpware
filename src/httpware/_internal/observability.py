"""Observability emission helper — structured logging + opt-in OpenTelemetry span events.

See planning/specs/2026-06-05-observability-design.md for the contract.

Logger names (``httpware.retry``, ``httpware.bulkhead``, ``httpware.circuit_breaker``,
``httpware.timeout``) and event names (``retry.giving_up``, ``bulkhead.rejected``,
``circuit.opened``, ``timeout.exceeded``, etc.) are the public observability
surface. They are stable: renames are breaking changes.
"""

import contextlib
import logging
import typing

from httpware._internal import import_checker


def _emit_event(
    logger: logging.Logger,
    event_name: str,
    *,
    level: int,
    message: str,
    attributes: dict[str, typing.Any],
) -> None:
    """Emit one observability event to both channels.

    1. Always emits a structured log record at ``level`` with ``extra=attributes``
       (so log aggregators that index ``extra`` see structured fields).
    2. If ``opentelemetry-api`` is installed, calls
       ``trace.get_current_span().add_event(event_name, attributes=attributes)``.
       When no tracer is active, ``get_current_span()`` returns a ``NonRecordingSpan``
       whose ``add_event`` is a documented no-op — so the call is unconditional
       behind the install gate. If the install gate is wrong (the namespace exists
       but the api package is missing or broken), the lazy import raises
       ``ImportError``; we degrade silently to log-only emission.

    The lazy ``from opentelemetry import trace`` inside the if-block preserves
    the optional-extras isolation invariant: ``import httpware`` must not pull
    ``opentelemetry`` into ``sys.modules`` when the extra is absent.
    """
    logger.log(level, message, extra={**attributes, "event": event_name})
    if import_checker.is_otel_installed:
        try:
            from opentelemetry import trace  # noqa: PLC0415 — lazy by design (optional-extras isolation)
        except ImportError:
            # opentelemetry namespace exists but the api package is broken or missing —
            # degrade to log-only emission. The structured log record above has already fired.
            return
        # Observability must never break the request path — suppress any failure from
        # add_event (e.g. a recording span with a broken exporter or attribute validation).
        # The structured log record above has already fired; CancelledError/KeyboardInterrupt
        # are not Exception subclasses and will still propagate.
        with contextlib.suppress(Exception):
            trace.get_current_span().add_event(event_name, attributes=attributes)
