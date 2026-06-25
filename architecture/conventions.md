# Code conventions

The naming, import, and docstring conventions every module in `src/httpware/`
follows. These are house style, not machine-checked beyond what ruff enforces;
treat a violation as a review blocker.

## Naming

- **Modules**: `snake_case` (`client.py`, `errors.py`, `middleware/chain.py`).
- **Classes**: `PascalCase`. `Http` is two letters: `AsyncClient`, not
  `ASYNCClient`.
- **Methods**: `snake_case`. No `a` prefix on async methods (match `httpx2`);
  `aclose()` is the sole exception.
- **Private symbols**: `_leading_underscore`. Cross-module private code lives in
  `_internal/`.

## Imports

- Absolute paths inside `src/httpware/`; relative imports only within the same
  subpackage.

## Docstrings

- PEP 257. Module / class / public-method docstrings are required; `D1`
  (missing docstring) is ignored, so the requirement is review-enforced.

## Exception construction

Status-keyed `StatusError` subclasses take a single positional
`response: httpx2.Response` and do **not** override `__init__`; non-status
`ClientError` subclasses deliberately do. This invariant — and which subclasses
fall on each side — lives in [`errors.md`](errors.md).
