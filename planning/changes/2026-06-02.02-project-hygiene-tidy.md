---
summary: Repo hygiene pass
---

# Project hygiene tidy (design)

- **Date:** 2026-06-02
- **Status:** draft, awaiting user review
- **Scope:** Four small cleanups accumulated in `planning/deferred-work.md` from the Story-1-1, Story-1-2, and Story-1-5 reviews. Three are tooling/config; the fourth is a two-line `Response.json()` correctness fix in `src/httpware/response.py`. Bundled as one PR because each is small and they share the same review surface (`pyproject.toml`, `Justfile`, several test files, one source file, CLAUDE.md, `planning/deferred-work.md`). No CI invariants change. No public API break — the `Response.json()` change is strictly additive (charset handling improved; raise contract unchanged).
- **Roadmap pointer:** none — this is project hygiene, not an Epic item. Same shape as the bmad-to-superpowers and docs-reorg cutovers (`2026-05-31-bmad-to-superpowers-transition-design.md`, `2026-06-02-docs-reorg-and-mkdocs-design.md`): one structural PR before Epic 3 (resilience middleware) starts.

## Why

Four small items have accumulated in `planning/deferred-work.md` that are all (a) unrelated to feature work, (b) cheap, (c) defense against future toil. Bundling them avoids four tiny PRs and one shared review pass. None block Epic 3, but Epic 3 will land cleanly on top of them.

The items are detailed below — each in its own subsection because the *why* differs per item and the user asked for the rationale spelled out. Items 1–3 are tooling/config (`pyproject.toml`, `Justfile`, several test files, CLAUDE.md). Item 4 is the only one that touches `src/httpware/` — a deliberate two-line fix in `response.py` that the deferred-work entry itself flagged as "arguably skip the spec and just fix it."

Two items from the prior iteration of this spec were dropped at user direction: a `[test]` dependency-group (extras are small enough; current `--all-extras` works fine) and a ruff/ty version pin (accept the occasional CI break when ruff adds a rule; cheaper than monthly bump PRs). Both stay open in `planning/deferred-work.md` as known-not-acting-on items.

### 1. `just publish` env-var guard (`Justfile:25-29`)

Current recipe:

```just
publish:
    rm -rf dist
    uv version $GITHUB_REF_NAME
    uv build
    uv publish --token $PYPI_TOKEN
```

`uv version $X` is state-mutating: it writes `version = "..."` into `pyproject.toml`. If `GITHUB_REF_NAME` is unset (the normal local-shell case), the recipe runs `uv version ""`, which at minimum produces an error and at worst writes an empty string into the project file. Either way, attempting `just publish` outside CI leaves the working tree dirty with a corrupted version that must be reverted by hand.

The same shape applies to `PYPI_TOKEN`: if it's unset, `uv publish` fails — but only AFTER `uv version` has already modified `pyproject.toml` and `uv build` has produced wheels. The failure happens at the last step; the side effects happen at the first two.

A two-line guard at the top of the recipe (`test -n "$GITHUB_REF_NAME"` and `test -n "$PYPI_TOKEN"`) refuses to proceed when either is missing. Cost: two lines of shell. Benefit: "running this locally is safe to attempt; the worst case is a clear error message before any file mutation." The defensive shift is from "production-only by convention" to "production-only by enforcement."

### 2. `uv_build` version band widening (`pyproject.toml:49`)

Current: `requires = ["uv_build>=0.11,<0.12"]` in `[build-system]`.

A single-minor pin means the moment uv_build 0.12 ships, the build resolver hard-fails on every machine that doesn't already have a resolved `uv.lock`. No grace period. The maintenance treadmill is "watch uv release feed forever, bump every few weeks."

The fix: widen the upper bound to `<1.0`. uv_build is in 0.x — by SemVer convention any 0.x bump can break, but in practice uv treats `uv_build` as a stable internal collaborator and minor releases have been backward-compatible. The cost of accepting all 0.x: a hypothetical 0.13 that does break still surfaces as a build error in CI (loud, not silent). The gain: zero bump PRs between now and uv_build 1.0.

New band: `requires = ["uv_build>=0.11,<1.0"]`.

No CLAUDE.md policy line — the band is now self-explanatory. The bump-when-1.0-ships review happens naturally as part of the 1.0 release notes.

### 3. PLR2004 → `http.HTTPStatus` constants

Current state: 24 `# noqa: PLR2004` instances across the repo. Of those, ~13 protect raw HTTP status-code literals (200, 418, 503, 504, etc.) where a stdlib constant exists. The remaining ~11 protect non-status integers (call counts, list lengths, decoded primitive values) that have no stdlib equivalent and are out of scope for this item.

The fix: replace status-code literals with `http.HTTPStatus.*` constants. Three categories of replacement:

**Test files (~11 instances, all clear wins):**
- `tests/test_transports_httpx2.py:72,103` — `== 200` → `== HTTPStatus.OK`
- `tests/test_transports_httpx2.py:135` — `== 418` → `== HTTPStatus.IM_A_TEAPOT`
- `tests/test_transports_httpx2.py:146` — `== 504` → `== HTTPStatus.GATEWAY_TIMEOUT`
- `tests/test_response.py:111,116` — `== 503` / `== 200` → `HTTPStatus.SERVICE_UNAVAILABLE` / `HTTPStatus.OK`
- `tests/test_middleware.py:67,195,268,335` — mix of 200, 418, 503 → corresponding `HTTPStatus` members

After the substitution, `# noqa: PLR2004` is removed from each line — the constant is no longer a magic number.

**Source file (`src/httpware/transports/httpx2.py:144-147`):**
```python
if 400 <= status < 600:  # noqa: PLR2004
    exc_class = STATUS_TO_EXCEPTION.get(
        status,
        ClientStatusError if status < 500 else ServerStatusError,  # noqa: PLR2004
    )
```

`400` and `500` map cleanly to `HTTPStatus.BAD_REQUEST` and `HTTPStatus.INTERNAL_SERVER_ERROR` (both are `int`-compatible since `HTTPStatus` is an `IntEnum`). `600` has no stdlib constant — it's the synthetic "end of 5xx" bound. The cleanest substitution:

```python
if HTTPStatus.BAD_REQUEST <= status < 600:  # noqa: PLR2004 — 600 is the synthetic 5xx upper bound
    exc_class = STATUS_TO_EXCEPTION.get(
        status,
        ClientStatusError if status < HTTPStatus.INTERNAL_SERVER_ERROR else ServerStatusError,
    )
```

The `< 600` literal keeps its noqa (with an inline justification, per the user's lint-suppression hierarchy where per-line + justification is the preferred form). The `< 500` literal is replaced and loses its noqa.

**Non-status-code PLR2004 (out of scope for this item):**
Counts like `assert calls == 2`, primitive decodes like `assert result == 42`, list lengths, `elapsed == 0.5`, intentionally-invalid `status == 99` (testing `with_status(99)`) — all stay as-is. The user's instruction was specifically about status codes; the other instances are a separate concern that the deferred-work entry can carry forward if it matters.

Why include the source-file change alongside the test cleanup: it's the same conceptual fix (status-code literal → stdlib constant), it lives in the same conceptual seam (HTTP-status decisions), and bundling avoids one drive-by edit in the next PR that touches `transports/httpx2.py`. Cost: three lines edited in `src/`.

### 4. `Response.json()` charset + docstring fix (`src/httpware/response.py:50-52`)

Current implementation:

```python
def json(self) -> Any:  # noqa: ANN401
    """Parse `content` as JSON."""
    return json.loads(self.content)
```

Two real problems, both raised in deferred-work entries (the retro of 2026-05-31 and the original story-1-2 review of 2026-05-13):

1. **Ignores declared charset.** `json.loads(bytes)` auto-detects only UTF-8 / UTF-16 / UTF-32 via BOM. Real-world APIs sometimes serve `Content-Type: application/json; charset=iso-8859-1` (older Japanese, Latin-1, GB-encoded APIs); on such bodies, `json.loads(bytes)` raises a confusing UnicodeDecodeError-via-JSONDecodeError or silently mis-decodes. Meanwhile `Response.text` (lines 41-48) already does the correct thing: `_parse_charset(_get_content_type(self.headers)) or "utf-8"`. The fix is to route `.json()` through `.text` so it inherits the same charset handling.

2. **Raw `json.JSONDecodeError` raise.** The transport's `_try_decode_json` never raises (returns `None` on failure). `Response.json()` raises a stdlib exception, which is inconsistent and leaks an implementation detail (callers have to import `json` to catch it). The proper fix is to wrap in a domain exception — but that's a new exception class, beyond a "two-liner." For this PR, the docstring becomes explicit about the contract (`Raises: json.JSONDecodeError`) so callers at least aren't surprised; a wrapped-exception design is left for a future spec when the response API needs a real revision.

The actual change:

```python
def json(self) -> Any:  # noqa: ANN401
    """Parse `content` as JSON using the declared charset (default UTF-8).

    Raises:
        json.JSONDecodeError: if the body is not valid JSON.
    """
    return json.loads(self.text)
```

Two lines of behavior change (docstring + body). Strict improvement: ASCII / UTF-8 / UTF-16 / UTF-32 bodies still parse identically (since `self.text` decodes them losslessly and `json.loads(str)` accepts any JSON string); bodies with a non-UTF charset that previously failed now succeed. No call-site change required.

Why include this in a hygiene PR rather than wait for "the next response-API touch" as the deferred entry suggested: the next response-API touch is in Epic 4 (streaming, Story 4.1) which is a much larger surface; piggy-backing a two-line correctness fix on a multi-week feature is the wrong shape. This PR's review is already touching configuration and lint hygiene — the marginal cost of one extra two-line code change with one extra test is essentially zero, and it closes two deferred-work entries instead of dragging them forward.

A new test in `tests/test_response.py` covers the charset case: construct a `Response` with `headers={"content-type": "application/json; charset=iso-8859-1"}`, body encoded as Latin-1, assert `.json()` returns the expected Python value. The existing UTF-8 happy-path test is unchanged.

## Decisions

| Decision | Choice |
| --- | --- |
| Add env-var guard to `just publish` | Yes — `test -n "$GITHUB_REF_NAME"` and `test -n "$PYPI_TOKEN"` as the first two lines of the recipe (before `rm -rf dist`). |
| `uv_build` band bump | Widen to `>=0.11,<1.0`. Accept all 0.x; breakage surfaces as a loud build error in CI. No CLAUDE.md policy line needed. |
| `[test]` dependency-group | **Dropped at user direction.** Current `--all-extras` install is fine for now; revisit if extras grow heavier. The deferred-work entry stays open as a known-not-acting-on item. |
| ruff / ty pinning | **Dropped at user direction.** Leave unpinned; treat lint CI failures as the upgrade signal. The deferred-work entry stays open. |
| PLR2004 → `HTTPStatus` (tests) | Yes — substitute `http.HTTPStatus.*` for status-code literals in `test_transports_httpx2.py`, `test_response.py`, `test_middleware.py`; remove the corresponding `# noqa: PLR2004` from each line. ~11 instances. |
| PLR2004 → `HTTPStatus` (source) | Yes — substitute in `src/httpware/transports/httpx2.py:144-147` for the 400 and 500 bounds; keep the `< 600` literal with a justified per-line noqa (no stdlib constant for the synthetic 5xx upper bound). |
| Non-status PLR2004 noqas | Out of scope. Counts, primitive decodes, list lengths, `elapsed == 0.5`, intentionally-invalid `status == 99` all stay as-is. Separate concern; the deferred-work entry can carry it forward if it matters. |
| `Response.json()` change | Two-line fix: route through `self.text` (honors charset); update docstring to explicitly name `json.JSONDecodeError` as the raise type. Wrapping `JSONDecodeError` in a domain exception is deferred. |
| `Response.json()` test coverage | Add one new test case in `tests/test_response.py` for `Response(headers={"content-type": "application/json; charset=iso-8859-1"}, body=<latin-1-encoded JSON>).json()`. Existing UTF-8 happy-path tests unchanged. |
| Update `planning/deferred-work.md` | Yes — remove the closed entries: `just publish` env-var validation; `uv_build` narrow window; `Response.json()` raises raw + ignores charset (consolidated retro bullet + story-1-2 entry). Reword PLR2004 entry to reflect HTTPStatus-substitution approach and note remaining non-status instances are still open. |
| Bundle vs split PR | One PR. All four items touch related review surface and the test files overlap; splitting adds four rebases for no review-quality gain. Matches user preference for clean-cutover ordering: hygiene before substantive Epic-3 work. |

## File structure

**Modified files:**

- `Justfile` — env-var guards added to the `publish` recipe.
- `pyproject.toml` — `[build-system] requires` widened to `uv_build>=0.11,<1.0`.
- `src/httpware/transports/httpx2.py` — `import http` (or `from http import HTTPStatus`); two literal substitutions in the status-code dispatch block at lines 144-147.
- `src/httpware/response.py` — `Response.json()` two-line change (body + docstring).
- `tests/test_transports_httpx2.py` — `from http import HTTPStatus`; 4 status-code substitutions (lines 72, 103, 135, 146); 4 noqa removals.
- `tests/test_response.py` — `from http import HTTPStatus`; 3 status-code substitutions (lines 111, 116; line 123 `== 99` is intentionally invalid and stays); 3 noqa removals; new test case for `.json()` charset handling.
- `tests/test_middleware.py` — `from http import HTTPStatus`; 4 status-code substitutions (lines 67, 195, 268, 335); 4 noqa removals.
- `planning/deferred-work.md` — remove closed entries (`just publish`, `uv_build`, `Response.json()`); reword PLR2004 entry.

**New files:** none.

**Deleted files:** none.

**Out-of-scope test files (unchanged):**
- `tests/test_decoders_pydantic.py`, `tests/test_decoders_msgspec.py`, `tests/test_client_methods.py`, `tests/test_internal_auth.py`, `tests/test_transports_recorded.py`, `tests/test_client_lifecycle.py` — all hold non-status PLR2004 noqas (counts, decoded values) that stay as-is.

## Verification

- `just lint-ci` exits 0. Specifically: ruff does not flag any `# noqa: PLR2004` as unused (any noqa that loses its trigger must be removed in the same commit; ruff's `RUF100` catches this).
- `just test` exits 0. The HTTPStatus substitutions are behavior-preserving (HTTPStatus members are `int`-compatible), so existing test assertions pass unchanged.
- New `Response.json()` test passes: Latin-1 body with `charset=iso-8859-1` returns the expected Python value.
- Empty-environment publish test: `env -i PATH=$PATH HOME=$HOME just publish` exits non-zero **before** `uv version` runs (verify by `git status pyproject.toml` showing no diff).
- `uv lock --upgrade` succeeds with the widened `uv_build` band.
- Manual: `grep -rn 'PLR2004' tests/ src/` returns only non-status instances plus the one justified `< 600` noqa in `transports/httpx2.py`; no bare status-code noqas remain.
- Manual: `git grep "just publish\|uv_build\|Response\.json" planning/deferred-work.md` returns no live items.

## Out of scope

- **`[test]` dependency-group.** Dropped at user direction. Extras stay user-facing in `[project.optional-dependencies]`; `just install --all-extras` continues. Revisit if extras grow heavier.
- **Pinning `ruff` / `ty`.** Dropped at user direction. Lint CI failures from new ruff rules will be triaged as they happen.
- **Non-status PLR2004 noqas.** Counts, list lengths, primitive-decode assertions, `elapsed == 0.5`, intentionally-invalid `status == 99`. Separate concern; the deferred-work entry can carry it forward.
- **Wrapping `json.JSONDecodeError` in a domain exception.** Item 4 fixes charset handling and documents the raise contract, but introducing a new `httpware.JSONDecodeError` (or similar) is a deliberate API addition that belongs in a future response-API revision.
- **Other deferred-work bundles.** Input-validation pass, Redactor middleware — separate specs, separate PRs.
- **`src/` flat-layout flip, ruff rule audit, ty config tightening, pre-commit hooks, dependabot, CI matrix changes** — all unchanged.

## Risks

- **`uv version ""` behavior.** The env-var guard rationale assumes `uv version ""` is at minimum noisy and at worst destructive. If `uv version` silently no-ops on empty input, the guard is still correct but the urgency framing is weaker. Mitigation: implementer reproduces the behavior locally before locking in the guard wording; the guard ships regardless.
- **`HTTPStatus` membership for unusual codes.** Every status code touched in the substitutions (200, 418, 503, 504) is a member of `http.HTTPStatus` in Python 3.11+. Confirmed before listing in the spec. If a future test uses an exotic status without an HTTPStatus member (e.g., 418 was a notable late add; 451 was added in 3.6), the implementer falls back to a per-line justified noqa for that one line.
- **Widening `uv_build` to `<1.0` accepts an unknown future 0.13 / 0.14 / etc.** Real risk: any 0.x bump that breaks build configuration would surface as a broken build, but only AFTER it ships. Mitigation: build error is loud (not silent); CI catches on the next PR; rollback is a one-line band tightening. Net risk is bounded; the maintenance saving outweighs it.
- **`Response.json()` route through `self.text` changes the BOM-detection path.** `json.loads(bytes)` consults BOM markers to pick UTF-8/16/32; `json.loads(str)` after `bytes.decode(charset)` does not. For bodies *without* a declared charset, both paths default to UTF-8 and produce identical results for valid JSON. The change only matters for the (uncommon, broken-by-spec) case of a body with no declared charset AND a UTF-16/32 BOM — in which case the previous code worked via BOM detection and the new code would mis-decode as UTF-8. Mitigation: the new test asserts the charset-declared path; the BOM-without-declaration case is exotic enough that "raise" is acceptable behavior. If it surfaces in practice, the wrapped-exception spec is the right place to fix it.
- **`planning/deferred-work.md` PLR2004 reword.** Original deferred entry's "idiomatic fix is `per-file-ignores`" proposal is rejected (conflicts with user's lint-suppression hierarchy where per-file-ignores is the *least*-preferred form). The reworded entry will document the HTTPStatus-substitution approach for status codes and leave the remaining ~11 non-status PLR2004 instances as a known-open item.

## Related work

- `planning/deferred-work.md` — source of all four items; gets edited (entries removed and reworded) as part of this PR.
- `2026-06-02-docs-reorg-and-mkdocs-design.md` — the previous hygiene cutover. Same shape: one structural PR before substantive feature work resumes.
- User memory `user_lint_suppression_principle` — establishes the per-line > project > per-file hierarchy. Item 3's approach (replace the literal with a constant so the noqa is gone entirely) is the *first* tier of that hierarchy ("fix the design"), which makes it strictly better than either per-line + justification or per-file-ignores.
