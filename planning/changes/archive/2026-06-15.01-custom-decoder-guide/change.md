---
status: shipped
date: 2026-06-15
slug: custom-decoder-guide
supersedes: null
superseded_by: null
pr: 67
outcome: Shipped docs/decoders.md (the Seam B "write your own ResponseDecoder" guide); closed deferred item G6.
---

# Change: Add a "Writing a custom decoder" guide

**Lane:** lightweight — docs-only. New page + one-line nav edit + an
`architecture/decoders.md` cross-link on ship. No source change, no public-API
change. Mirrors the existing `docs/middleware.md` extension-seam guide.

Closes deferred item **G6** (custom-`ResponseDecoder` guide), the
[2026-06-13 docs audit](../../../audits/2026-06-13-docs-audit.md) finding parked
in [`deferred.md`](../../../deferred.md). Revisit trigger now met: the guide was
explicitly requested.

## Goal

Seam B (`ResponseDecoder`) is a documented extension point, but unlike
middleware it has no "write your own" guide. Add `docs/decoders.md` showing the
`can_decode` / `decode` protocol, how `decoders=[...]` ordering resolves a
model, and a worked custom-decoder example. Prose carries the signatures — no
mkdocstrings / auto API reference (per the `2026-06-14.01` docs-UX decision).

## Approach

A prose + code-block page modeled on `docs/middleware.md`, the sibling
"write your own" guide for Seam A. Sections, scaled to complexity:

1. **Intro / when to write one** — Seam B in a paragraph; reach for a custom
   decoder when you need a body *format* (non-JSON) or a *type system* the
   pydantic/msgspec built-ins don't cover.
2. **The protocol** — the `ResponseDecoder` Protocol verbatim from
   `src/httpware/decoders/__init__.py`; `can_decode(model) -> bool`
   (first-match dispatch, claim broadly but reject other libraries' native
   types, **MUST NOT raise** — runs outside the `DecodeError` wrap, decline by
   returning False) and `decode(content: bytes, model) -> T` (raw bytes in;
   any exception is auto-wrapped as `DecodeError`, so don't raise it yourself).
3. **How the client resolves a model** — `decoders=[...]` order = preference,
   first claimer wins; `decoders=None` default is pydantic-first;
   `MissingDecoderError` fires *before* the HTTP call when nothing claims; the
   `MissingDecoderError` (no decoder) vs `DecodeError` (decoder ran, payload
   bad) distinction and their distinct corrective actions.
4. **Sync, not async** (callout) — one sync protocol shared by `Client` *and*
   `AsyncClient`; there is no async `decode`, in contrast to middleware's two
   flavors. `decode` runs synchronously after the body is read.
5. **Worked example: a CSV decoder** — `text/csv` bytes → `list[<dataclass>]`.
   Chosen because both built-ins are JSON, so the highest-value lesson is that
   the seam is raw-bytes-in / typed-object-out and **not** JSON-bound. Stdlib
   `csv` only (a reader runs it with zero extra installs), naturally
   single-pass. `can_decode` claims `list[<dataclass>]` and rejects everything
   else; wired as `decoders=[CsvDecoder(), PydanticDecoder()]`.
6. **A note on claiming the right models** — the `can_decode` discrimination
   obligation (claiming too broadly steals models from later decoders in the
   list); how an adapter for another type system (e.g. cattrs/attrs) narrows
   its claim to its own types; and that the single-pass rule is a *built-in
   performance choice*, not a hard protocol obligation — a custom decoder may
   go two-pass (`json.loads` → structure) at the cost of one extra allocation.
7. **When NOT to write a decoder** — the built-ins already cover
   pydantic/msgspec/dataclasses/primitives; if you only want raw bytes or text,
   use `response.content` / `response.text` without `response_model=`.
8. **See also** — `architecture/decoders.md` (Seam B, the formal contract),
   the built-in adapters (`decoders/pydantic.py`, `decoders/msgspec.py`) as
   reference implementations, the Quick-Start typed-response example.

Truth home: [`architecture/decoders.md`](../../../../architecture/decoders.md)
— Seam B's contract does not move; on ship, add a cross-link from it to the new
guide.

## Files

- `docs/decoders.md` — new guide (the work).
- `mkdocs.yml` — add `- Decoders: decoders.md` after the Middleware nav entry.
- `planning/deferred.md` — remove the G6 entry (closed).

No `architecture/decoders.md` cross-link: `architecture/middleware.md` does not
link to its `docs/middleware.md` guide either, so adding one only for decoders
would break that symmetry. Seam B's contract is unchanged, so `architecture/`
needs no promotion edit.

## Verification

- [ ] Every code block in the guide is runnable as written — the CSV
      `can_decode` predicate and `decode` body type-check and execute against
      the real `ResponseDecoder` protocol (manually exercised, not a doctest).
- [ ] `uv run mkdocs build --strict` — clean (no broken internal links, nav
      resolves).
- [ ] `just lint` — clean (eof-fixer / formatting on the new markdown).
- [ ] Cross-references resolve: links to `architecture/decoders.md`,
      `middleware.md`, and `index.md` are valid.
