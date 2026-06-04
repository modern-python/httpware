"""Verify that `import httpware` does not transitively load opt-in extras."""

import subprocess
import sys


def test_importing_httpware_does_not_import_msgspec() -> None:
    """Fresh subprocess: msgspec must NOT appear in sys.modules after `import httpware`.

    msgspec IS installed in the test environment (via `--all-extras`), so this
    test runs in a subprocess with a clean interpreter to verify that nothing
    in the httpware import chain pulls msgspec in.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import httpware; import sys; sys.exit(0 if 'msgspec' not in sys.modules else 1)",
        ],
        check=False,
        capture_output=True,
    )
    assert result.returncode == 0, (
        f"msgspec was loaded transitively by `import httpware`; stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_importing_httpware_does_not_import_pydantic() -> None:
    """Fresh subprocess: pydantic must NOT appear in sys.modules after `import httpware`.

    pydantic IS installed in the test environment (via `--all-extras`), so this
    test runs in a subprocess with a clean interpreter to verify that nothing
    in the httpware import chain pulls pydantic in.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import httpware; import sys; sys.exit(0 if 'pydantic' not in sys.modules else 1)",
        ],
        check=False,
        capture_output=True,
    )
    assert result.returncode == 0, (
        f"pydantic was loaded transitively by `import httpware`; stdout={result.stdout!r} stderr={result.stderr!r}"
    )
