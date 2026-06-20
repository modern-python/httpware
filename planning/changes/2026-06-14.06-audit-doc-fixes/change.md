---
status: shipped
date: 2026-06-14
slug: audit-doc-fixes
summary: Closed the [deep-audit](audits/2026-06-14-deep-audit.md) doc-accuracy findings: `Client.stream()` docs, terminal-call attribution, the four auto-raise sites, the pydantic upper bound, and root import paths.
supersedes: null
superseded_by: null
pr: 66
outcome: Shipped via #66 - 5 doc-accuracy findings (Client.stream docs, terminal attribution, errors auto-raise sites, pydantic upper bound, root import paths).
---

# Change: Deep-audit documentation accuracy fixes

**Lane:** docs/docstring-only; spec is the [2026-06-14 deep audit](../../../audits/2026-06-14-deep-audit.md).

## Goal

Close the remaining confirmed documentation-accuracy findings.

## Findings

- **M4** — `architecture/client.md` streaming section omitted `Client.stream()` → now documents both `Client.stream()` and `AsyncClient.stream()`.
- **L13** — `architecture/client.md` attributed the `httpx2.*.send` call to `Client.send`/`AsyncClient.send` → corrected to the internal `_terminal` (and `.send()` enters the chain first).
- **Nit4** — `src/httpware/errors.py` module docstring attributed auto-raise to `AsyncClient`'s terminal only → now lists all four raise sites (both terminals + both `stream()` methods).
- **Nit15** — `architecture/extras.md` showed `pydantic>=2` without the `<3.0` ceiling → synced to `pydantic>=2.0,<3.0` (matches `pyproject.toml`).
- **Nit14** — `docs/middleware.md` and `docs/recipes/phase-decorator-patterns.md` imported root-`__all__` symbols via submodule paths → standardized to `from httpware import X`.

(Nit2 — `_is_streaming_body_async` reliance note — moot: PR #64 symmetrized the code instead.)

## Verification

- [ ] `just lint-ci` clean (CI-exact, no autofix); `just test` 100% (docstring change adds no lines).
