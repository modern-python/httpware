"""Fail-soft tests for the otel optional-extra (0.6.0).

opentelemetry-api IS installed in the CI test environment via `--all-extras`.
To simulate the "extra not installed" case, patch
`httpware._internal.import_checker.is_otel_installed = False` for the
duration of the test.

The contract: observability emission (the structured log record half) must
work regardless of whether opentelemetry-api is available. The OTel half is
silently skipped when the flag is False.
"""

import logging
from unittest.mock import patch

import pytest

from httpware._internal.observability import _emit_event


_TEST_LOGGER = logging.getLogger("httpware.test.otel_missing")


def test_emit_event_logs_record_without_otel(caplog: pytest.LogCaptureFixture) -> None:
    """The structured log record is emitted even when opentelemetry-api is 'missing'."""
    with (
        patch("httpware._internal.import_checker.is_otel_installed", False),
        caplog.at_level(logging.WARNING, logger="httpware.test.otel_missing"),
    ):
        _emit_event(
            _TEST_LOGGER,
            "test.event",
            level=logging.WARNING,
            message="works without otel",
            attributes={"x": 1},
        )

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.message == "works without otel"
    assert record.x == 1  # ty: ignore[unresolved-attribute]


def test_emit_event_does_not_call_opentelemetry_apis_when_flag_false() -> None:
    """With is_otel_installed=False, no opentelemetry.trace call is made."""
    with (
        patch("httpware._internal.import_checker.is_otel_installed", False),
        patch("opentelemetry.trace.get_current_span") as mock_get_span,
    ):
        _emit_event(
            _TEST_LOGGER,
            "test.event",
            level=logging.WARNING,
            message="silent on otel",
            attributes={},
        )

    mock_get_span.assert_not_called()
