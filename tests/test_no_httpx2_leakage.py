"""CI-invariant guard: only `transports/httpx2.py` may import `httpx2`."""

import re
from pathlib import Path

import pytest


_PATTERN = re.compile(r"^\s*(?:import|from)\s+httpx2\b", re.MULTILINE)
_SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "httpware"
_SOURCES = sorted(_SRC_ROOT.rglob("*.py"))
_ALLOWED = _SRC_ROOT / "transports" / "httpx2.py"

assert _SOURCES, f"leakage test discovered no source files under {_SRC_ROOT}"


@pytest.mark.parametrize("path", _SOURCES, ids=lambda p: p.relative_to(_SRC_ROOT.parent).as_posix())
def test_only_httpx2_transport_imports_httpx2(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if _PATTERN.search(text):
        assert path == _ALLOWED, f"unexpected httpx2 import in {path}"
