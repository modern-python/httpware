"""Detect optional extras without importing them. Used by adapter modules to gate hard imports."""

from importlib.metadata import PackageNotFoundError, distribution
from importlib.util import find_spec


def _is_distribution_installed(name: str) -> bool:
    """Probe the package registry for a distribution by name. No sys.modules side effects."""
    try:
        distribution(name)
    except PackageNotFoundError:
        return False
    return True


is_msgspec_installed = find_spec("msgspec") is not None
is_pydantic_installed = find_spec("pydantic") is not None
# opentelemetry/ is a PEP 420 namespace package — instrumentation packages create the
# directory even without opentelemetry-api. find_spec("opentelemetry") therefore returns
# non-None regardless of whether the api package is present, and
# find_spec("opentelemetry.trace") populates sys.modules with the namespace parent as a
# CPython side-effect, breaking the isolation guarantee.
# importlib.metadata.distribution probes the package registry instead: it returns the
# distribution when opentelemetry-api is installed and raises PackageNotFoundError when
# it is absent, with no sys.modules side effects.
is_otel_installed = _is_distribution_installed("opentelemetry-api")
