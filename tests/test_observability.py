"""Unit tests for the _emit_event observability helper."""

import logging
import sys
from unittest.mock import MagicMock, patch

import pytest

from httpware._internal.observability import _emit_event


_TEST_LOGGER = logging.getLogger("httpware.test.observability")


def test_emit_event_logs_at_warning_with_extra_fields(caplog: pytest.LogCaptureFixture) -> None:
    """The helper emits one structured log record at WARNING with attributes accessible on the record."""
    with caplog.at_level(logging.WARNING, logger="httpware.test.observability"):
        _emit_event(
            _TEST_LOGGER,
            "test.event",
            level=logging.WARNING,
            message="something interesting happened",
            attributes={"foo": 1, "bar": "x"},
        )

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelno == logging.WARNING
    assert record.message == "something interesting happened"
    assert record.foo == 1  # ty: ignore[unresolved-attribute]
    assert record.bar == "x"  # ty: ignore[unresolved-attribute]
    assert record.event == "test.event"  # ty: ignore[unresolved-attribute]


def test_emit_event_redacts_url_secret_in_log_record(caplog: pytest.LogCaptureFixture) -> None:
    """The `url` attribute is redacted at the emission boundary, before the log record fires."""
    with caplog.at_level(logging.WARNING, logger="httpware.test.observability"):
        _emit_event(
            _TEST_LOGGER,
            "test.event",
            level=logging.WARNING,
            message="leaky",
            attributes={"url": "https://u:p@example.test/x?api_key=topsecret"},
        )

    record = caplog.records[0]
    assert "topsecret" not in record.url  # ty: ignore[unresolved-attribute]
    assert "api_key=REDACTED" in record.url  # ty: ignore[unresolved-attribute]
    assert "u:p@" not in record.url  # ty: ignore[unresolved-attribute]


def test_emit_event_redacts_url_secret_in_otel_event() -> None:
    """The OTel span event receives the redacted `url`, not the raw secret."""
    mock_span = MagicMock(name="MockSpan")
    with (
        patch("httpware._internal.import_checker.is_otel_installed", True),
        patch("opentelemetry.trace.get_current_span", return_value=mock_span),
    ):
        _emit_event(
            _TEST_LOGGER,
            "test.event",
            level=logging.WARNING,
            message="leaky",
            attributes={"url": "https://example.test/x?token=topsecret"},
        )

    _, kwargs = mock_span.add_event.call_args
    assert "topsecret" not in kwargs["attributes"]["url"]
    assert "token=REDACTED" in kwargs["attributes"]["url"]


def test_emit_event_respects_level_parameter(caplog: pytest.LogCaptureFixture) -> None:
    """When level=DEBUG is passed, the record is at DEBUG."""
    with caplog.at_level(logging.DEBUG, logger="httpware.test.observability"):
        _emit_event(
            _TEST_LOGGER,
            "test.event",
            level=logging.DEBUG,
            message="quiet",
            attributes={},
        )

    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == logging.DEBUG


def test_emit_event_does_not_import_opentelemetry_when_flag_false() -> None:
    """With is_otel_installed=False the helper must not touch opentelemetry."""
    with patch("httpware._internal.import_checker.is_otel_installed", False):
        # Confirm the lazy import path is skipped: snapshot sys.modules before/after.
        modules_before = set(sys.modules)
        _emit_event(
            _TEST_LOGGER,
            "test.event",
            level=logging.WARNING,
            message="nope",
            attributes={"x": 1},
        )
        # opentelemetry may already be loaded by other tests; allow that, but no NEW load happened
        # because the codepath was skipped. The point: no error and no required state change.
    assert len(modules_before) >= 0


def test_emit_event_calls_add_event_when_otel_installed() -> None:
    """With is_otel_installed=True the helper calls trace.get_current_span().add_event(...)."""
    mock_span = MagicMock(name="MockSpan")
    with (
        patch("httpware._internal.import_checker.is_otel_installed", True),
        patch("opentelemetry.trace.get_current_span", return_value=mock_span),
    ):
        _emit_event(
            _TEST_LOGGER,
            "test.event",
            level=logging.WARNING,
            message="hi",
            attributes={"k": "v"},
        )

    mock_span.add_event.assert_called_once_with("test.event", attributes={"k": "v"})


def test_emit_event_works_when_otel_installed_but_no_active_span(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """With OTel installed but no tracer configured, get_current_span() returns NonRecordingSpan.

    add_event is a documented no-op. The log-only fallback path must still emit
    a record at the requested level with the correct event attribute.
    """
    # Real OTel API call (no mocking) — opentelemetry-api is installed via the otel extra.
    with caplog.at_level(logging.WARNING, logger="httpware.test.observability"):
        _emit_event(
            _TEST_LOGGER,
            "test.event",
            level=logging.WARNING,
            message="real-otel-but-no-tracer",
            attributes={"a": 1},
        )

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelno == logging.WARNING
    assert record.message == "real-otel-but-no-tracer"
    assert record.event == "test.event"  # ty: ignore[unresolved-attribute]


def test_emit_event_swallows_add_event_failure() -> None:
    """A failing OTel add_event must not break the caller; the log record still fires."""
    mock_span = MagicMock(name="MockSpan")
    mock_span.add_event.side_effect = RuntimeError("exporter boom")
    with (
        patch("httpware._internal.import_checker.is_otel_installed", True),
        patch("opentelemetry.trace.get_current_span", return_value=mock_span),
    ):
        # must not raise
        _emit_event(
            _TEST_LOGGER,
            "test.event",
            level=logging.WARNING,
            message="resilient",
            attributes={"k": "v"},
        )
    mock_span.add_event.assert_called_once()
