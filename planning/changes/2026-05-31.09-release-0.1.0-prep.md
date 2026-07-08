---
summary: 0.1.0 released
---

# Release 0.1.0 prep (design)

- **Date:** 2026-05-31
- **Status:** approved, ready for plan
- **Scope:** Prep the repository for the first PyPI release (`0.1.0` alpha). Single PR delivers all repo-side edits; the GitHub Release that triggers the publish workflow is a separate manual action by the maintainer. Out of scope: writing user docs site (Epic 6), Trusted Publishers / Sigstore release flow (Story 6-5), feature work toward v1.0.
- **Why now:** Epic 1 is complete (PRs #1–#13). The middleware foundation (2-1/2-2/2-3) is shipped. `AsyncClient` is the working public surface. Users can do meaningful work with the current API; further iteration benefits from real consumer feedback. Modern-di-style alpha release model: tag now, iterate, no CHANGELOG file (release notes live on GitHub Releases).

## Decisions

| Decision | Choice |
| --- | --- |
| Release model | Alpha. `0.1.0` declares the API in flux until v1.0; minor releases may break things. Matches modern-di's pre-1.0 posture. |
| CHANGELOG.md | **Delete.** modern-di in the same org doesn't have one. Release notes live on GitHub Releases (one entry per tag). |
| README.md | Strict trim: only document what actually ships. Remove the resilience-middleware / observability / OTel bullets. Add an explicit "what's not yet shipped" line under the status banner. |
| pyproject.toml | Untouched. `version = "0"` stays as the placeholder; the publish recipe overrides via `uv version $GITHUB_REF_NAME`. |
| Tag format | Bare `0.1.0` (no `v` prefix). Matches modern-di. |
| Publish workflow | Add `.github/workflows/publish.yml` mirroring modern-di's. Triggered by `release: published`. Runs `just publish`. |
| Justfile | Untouched. `just publish` already does `rm -rf dist && uv version $GITHUB_REF_NAME && uv build && uv publish --token $PYPI_TOKEN`. |
| PyPI name | Must verify ownership of `httpware` on PyPI before tagging. The package URL returns HTTP 200; check via `pypi.org/pypi/httpware/json` whether the owner is `modern-python` (our project) or a third party. |
| Engineering.md roadmap | Unchanged for this PR. Adding "Released" markers is a tiny follow-up commit (not in scope here). |
| Out-of-scope feature work | None added in this PR. The repo ships what's already on `main` at `204d463`. |

## What ships in 0.1.0 — public surface

| Symbol | Import |
| --- | --- |
| `AsyncClient` | `from httpware import AsyncClient` |
| `Request`, `Response`, `StreamResponse` | `from httpware import Request, Response, StreamResponse` |
| `Limits`, `Timeout`, `ClientConfig` | `from httpware import Limits, Timeout, ClientConfig` |
| `Transport`, `Httpx2Transport`, `RecordedTransport` | `from httpware import …` |
| `ResponseDecoder`, `PydanticDecoder` | `from httpware import ResponseDecoder, PydanticDecoder` |
| `MsgspecDecoder` | `from httpware.decoders.msgspec import MsgspecDecoder` (gated by `[msgspec]` extra) |
| `Middleware`, `Next` | `from httpware import Middleware, Next` |
| `before_request`, `after_response`, `on_error` | `from httpware import …` |
| Exception hierarchy | `from httpware import StatusError, TransportError, TimeoutError, ClientError, ServerStatusError, ClientStatusError, STATUS_TO_EXCEPTION, BadRequestError, UnauthorizedError, ForbiddenError, NotFoundError, ConflictError, UnprocessableEntityError, RateLimitedError, InternalServerError, ServiceUnavailableError` |

Behind the seam: `httpware._internal.chain.compose`, `httpware._internal.import_checker`.

## What 0.1.0 does NOT ship

- `auth=` parameter on `AsyncClient` (Story 2-4).
- `data=` / `files=` body params on HTTP methods.
- Transport reference-counting on `with_options` views.
- Retry / timeout / bulkhead / RetryBudget middleware (Epic 3).
- Streaming (`AsyncClient.stream`) — `StreamResponse` is a placeholder stub (Epic 4).
- Observability hooks / OpenTelemetry middleware (Epic 5).
- `niquests` transport (declared as an extra but not yet implemented).
- User documentation site (mkdocs / readthedocs — Epic 6).
- Migration guide from `community-of-python/base-client` (Story 6-1).
- Public benchmark suite (Story 6-3).
- CI enforcement gates beyond what's currently in `ci.yml` (Story 6-4).
- Trusted Publishers + Sigstore release flow (Story 6-5; we use the simpler token-based publish for now).
- CHANGELOG.md.

## Edits in the prep PR

**Deleted files:**
- `CHANGELOG.md` — release notes live on GitHub Releases going forward.

**New files:**
- `.github/workflows/publish.yml` — mirrors modern-di. Triggered by `release: published`, runs `just publish`. Reads `PYPI_TOKEN` from repo secrets.

**Modified files:**
- `README.md` — strict trim per Section 2 of the brainstorm. Remove the "Highlights" bullets for unshipped features. Update the status banner to name the unshipped categories (resilience middleware, streaming, observability). Drop the CHANGELOG link.
- `CONTRIBUTING.md` — check for and remove any reference to `CHANGELOG.md`. If the existing CONTRIBUTING doesn't mention it, no change needed.
- `CLAUDE.md` — same check; remove `CHANGELOG.md` references if present.

**Files NOT touched:**
- `pyproject.toml` — `version = "0"` stays; publish recipe overrides.
- `Justfile` — `publish` recipe already correct.
- `.github/workflows/ci.yml` — no changes to test/lint matrix.
- `src/httpware/**` — no code changes.
- `tests/**` — no test changes.
- `LICENSE`, `SECURITY.md` — unchanged.
- `docs/dev/engineering.md` — internal roadmap stays; "Released" markers are a follow-up.
- `docs/archive/**` — bmad archive untouched.

## `.github/workflows/publish.yml` content

```yaml
name: Publish Package

on:
  release:
    types:
      - published

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: extractions/setup-just@v2
      - uses: astral-sh/setup-uv@v3
      - run: just publish
        env:
          PYPI_TOKEN: ${{ secrets.PYPI_TOKEN }}
```

Byte-for-byte identical to modern-di's `publish.yml`. No customization needed.

## README.md content (final)

```markdown
# httpware

[![Test](https://github.com/modern-python/httpware/actions/workflows/ci.yml/badge.svg)](https://github.com/modern-python/httpware/actions/workflows/ci.yml)
[![PyPI version](https://badge.fury.io/py/httpware.svg)](https://pypi.org/project/httpware/)
[![Python versions](https://img.shields.io/pypi/pyversions/httpware.svg)](https://pypi.org/project/httpware/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Async HTTP client framework for Python.**

`httpware` is a typed, async HTTP client library built on `httpx2` with a protocol-based seam so the transport is swappable. Middleware composes via an onion model. Pydantic and msgspec response decoding ship out of the box. `RecordedTransport` replaces respx for transport-level tests.

> **Status:** Pre-1.0 (0.1.0 alpha). Public API is subject to change between minor releases until v1.0. Resilience middleware (retry / timeout / bulkhead), streaming, and observability are not yet shipped — track progress on GitHub.

## Install

\`\`\`bash
pip install httpware
\`\`\`

Optional extras:

\`\`\`bash
pip install httpware[msgspec]    # MsgspecDecoder
\`\`\`

(`otel`, `niquests`, and `all` extras are declared but their integrations have not shipped yet.)

## Quickstart

\`\`\`python
from httpware import AsyncClient
from pydantic import BaseModel


class User(BaseModel):
    id: int
    name: str


async def main() -> None:
    async with AsyncClient(base_url="https://api.example.com") as client:
        user = await client.get("/users/1", response_model=User)
        print(user.name)
\`\`\`

## What ships in 0.1.0

- **`AsyncClient`** — eight HTTP method shortcuts (`get`, `post`, `put`, `patch`, `delete`, `head`, `options`, `request`) with typed `response_model` overloads; per-call overrides for `headers`, `params`, `cookies`, `timeout`, `json`, `content`; httpx-style `base_url` join; `with_options(...)` returns a view sharing the same transport.
- **Transport-agnostic seam.** `httpx2` is confined to `httpware.transports.httpx2.Httpx2Transport`. Implement the `Transport` protocol to swap backends.
- **Middleware foundation.** `Middleware` protocol, `Next` type alias, recursive-closure `compose()` chain composition, and phase decorators (`@before_request`, `@after_response`, `@on_error`).
- **Pluggable response decoding.** `PydanticDecoder` (default) with cached `TypeAdapter`; `MsgspecDecoder` via `httpware[msgspec]`.
- **`RecordedTransport`** — built-in test double with a route table, observed-request list, and `aclose_calls` counter.
- **Status-keyed exception hierarchy** — `StatusError`, 4xx / 5xx subclasses, plain typed fields (`status: int`, `body: bytes`, `headers`, `json`, `request_method`, `request_url`). Pickleable; userinfo redacted in `__repr__`.
- **No `httpx2` exception types** leak through `httpware`. The transport seam maps them to `httpware` exceptions.

## Part of `modern-python`

Browse the full list of templates and libraries in [`modern-python`](https://github.com/modern-python) — see the org profile for the categorized index.

## License

MIT — see [LICENSE](./LICENSE).
```

The triple-backticks above use backslash-escapes in this spec because the spec itself is markdown; in the actual `README.md` they're real triple-backticks.

## Release execution (post-merge, manual maintainer actions)

These steps are NOT part of the PR. They run after the prep PR merges to `main`.

1. **Verify PyPI name ownership:**

   ```bash
   curl -s https://pypi.org/pypi/httpware/json \
     | python -c "import sys, json; d=json.load(sys.stdin); info=d.get('info', {}); print('home:', info.get('home_page')); print('project_urls:', info.get('project_urls')); print('author:', info.get('author'))"
   ```

   Decision tree:
   - Homepage / project_urls point to `github.com/modern-python/httpware` → name is ours, proceed.
   - Different owner → STOP. Rename or open a PyPI name-transfer request. Don't tag.
   - Returns 404 → name is free, proceed.

2. **Verify `PYPI_TOKEN` secret exists on the repo:**

   ```bash
   gh secret list --repo modern-python/httpware | grep PYPI_TOKEN
   ```

   If absent, add it via `gh secret set PYPI_TOKEN --repo modern-python/httpware` with a PyPI account token scoped to the `httpware` project.

3. **Create the GitHub Release (triggers publish workflow):**

   ```bash
   gh release create 0.1.0 \
     --title "0.1.0 — initial alpha" \
     --notes-file - <<'EOF'
   Initial public alpha of `httpware`.

   **Includes:**
   - AsyncClient with 8 HTTP method shortcuts and typed `response_model` overloads
   - Transport-agnostic seam (`httpx2` confined to `Httpx2Transport`)
   - Middleware foundation: `Middleware` protocol, `compose()`, phase decorators
   - Pluggable response decoders: `PydanticDecoder` (default), `MsgspecDecoder` via `[msgspec]` extra
   - `RecordedTransport` test double
   - Status-keyed exception hierarchy

   **Not yet shipped (next releases):**
   - Resilience middleware (retry, timeout, bulkhead) — Epic 3
   - Streaming (`AsyncClient.stream`) — Epic 4
   - Observability / OpenTelemetry — Epic 5
   - `auth=` parameter on AsyncClient — Story 2-4
   - `data=` / `files=` body params

   Public API is subject to change between minor releases until v1.0.
   EOF
   ```

   The release publication triggers `publish.yml` → `just publish` → `uv version 0.1.0 && uv build && uv publish --token`. The workflow's status appears in the Actions tab.

4. **Smoke-check the published package:**

   ```bash
   # In a fresh venv:
   pip install httpware==0.1.0
   python -c "import httpware; from httpware import AsyncClient, Middleware, RecordedTransport; print('OK:', httpware.__file__)"
   ```

   Expected: `OK: …/site-packages/httpware/__init__.py`. If import fails or names are missing, a `0.1.1` patch follows the same release cycle.

## Constraints and invariants

- **No production code changes.** This PR ships only documentation and CI workflow edits.
- **No `httpx2` import added.** `tests/test_no_httpx2_leakage.py` keeps passing.
- **`just lint-ci` keeps passing.** ruff, ty, eof-fixer all clean.
- **`just test` keeps passing.** 273 tests at 100% line coverage on the source.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| PyPI name `httpware` is owned by someone else. | The maintainer verifies via the PyPI JSON API before tagging. If owned, stop and rename or transfer. No code-level change anticipated for this case. |
| `PYPI_TOKEN` secret missing. | `gh secret list` check before tagging; add via `gh secret set` if absent. |
| The publish workflow fails mid-build (e.g., `uv build` error on a CI runner that differs from local). | The tag stays; the workflow can be re-run from the Actions tab. If a content change is needed, a `0.1.1` follow-up tag publishes the fix. The repo doesn't accumulate state from a failed publish. |
| Users install 0.1.0 and try to use `Retry` / `Timeout` / OTel middleware (which aren't shipped). | README's status banner names the unshipped categories explicitly. Each feature's import would fail loudly (`ImportError`), not silently. |
| Documentation site URL (`https://httpware.readthedocs.io`) referenced in pyproject.toml doesn't resolve. | Keep the URL as a forward-pointer (matches modern-di which has the same pattern). Users see the broken link; not a release blocker. Epic 6's mkdocs site lights it up later. |
| Renaming the package later (if PyPI name is contested) is disruptive. | The maintainer verifies name ownership BEFORE any consumer can depend on the published name. The 0.1.0 wheel never lands on PyPI unless the name is ours. |

## Definition of done

- `CHANGELOG.md` deleted.
- `.github/workflows/publish.yml` exists with the modern-di-pattern content.
- `README.md` updated to the trimmed content from Section 2 of the brainstorm / the README block above.
- `CONTRIBUTING.md` and `CLAUDE.md` checked for `CHANGELOG.md` references; updated if any were present.
- `just test` and `just lint-ci` clean.
- `tests/test_no_httpx2_leakage.py` still passes.
- PR `chore/release-0.1.0-prep` lands on `main` via merge.
- Post-merge actions (PyPI name check, secret verification, GitHub Release creation) execute successfully; `0.1.0` lands on PyPI; `pip install httpware==0.1.0` works in a clean venv.
