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
import sys
from importlib.metadata import distribution
from unittest.mock import patch

import pytest

from httpware._internal import import_checker
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


def test_is_otel_installed_uses_opentelemetry_trace_probe() -> None:
    """The install probe must use the package registry, not find_spec on the namespace.

    `opentelemetry` is a PEP 420 namespace — instrumentation packages create the
    directory even when `opentelemetry-api` is absent. find_spec("opentelemetry")
    returns non-None regardless, giving a false positive.

    find_spec("opentelemetry.trace") would fix the false-positive but causes CPython
    to load the opentelemetry namespace package into sys.modules as a side-effect,
    breaking the transitive-import isolation guarantee.

    importlib.metadata.distribution("opentelemetry-api") probes the package registry
    directly: no sys.modules side-effects, and it raises PackageNotFoundError when
    opentelemetry-api is absent. This test pins that contract.
    """
    # In CI (opentelemetry-api IS installed), distribution succeeds.
    assert distribution("opentelemetry-api") is not None
    assert import_checker.is_otel_installed is True

    # The structural assertion: the constant must be derived from the metadata probe.
    # This ensures a future revert to find_spec trips the regression guard.
    source = __import__("inspect").getsource(import_checker)
    assert 'distribution("opentelemetry-api")' in source, (
        "import_checker must probe via importlib.metadata.distribution('opentelemetry-api') "
        "(PEP 420 namespace hazard + sys.modules side-effect); "
        "see planning/audit/2026-06-07-deep-audit.md (Low finding on import_checker.py:8)."
    )


def test_emit_event_survives_lazy_import_failure(caplog: pytest.LogCaptureFixture) -> None:
    """_emit_event degrades to log-only when the lazy OTel import fails.

    When is_otel_installed=True but ``from opentelemetry import trace`` raises
    ImportError, _emit_event must not crash — it emits the structured log record
    and returns.

    Simulates the partial-install case: opentelemetry/ namespace directory exists
    (created by some instrumentation package) but opentelemetry-api is missing or
    broken, so importing ``trace`` from it fails.
    """

    class _BrokenOpenTelemetry:
        """Stand-in for opentelemetry/ namespace directory without working api."""

        def __getattr__(self, name: str) -> object:
            msg = f"cannot import name {name!r} from 'opentelemetry'"
            raise ImportError(msg)

    # Save and replace the real opentelemetry module for the duration of the test.
    saved = sys.modules.pop("opentelemetry", None)
    sys.modules["opentelemetry"] = _BrokenOpenTelemetry()  # ty: ignore[invalid-assignment]
    try:
        with (
            patch("httpware._internal.import_checker.is_otel_installed", True),
            caplog.at_level(logging.WARNING, logger="httpware.test.otel_missing"),
        ):
            _emit_event(
                _TEST_LOGGER,
                "test.event",
                level=logging.WARNING,
                message="survives broken otel",
                attributes={"k": "v"},
            )
    finally:
        if saved is not None:
            sys.modules["opentelemetry"] = saved
        else:
            sys.modules.pop("opentelemetry", None)

    # The structured log record still fired despite the OTel branch failing.
    assert any(r.message == "survives broken otel" for r in caplog.records)
