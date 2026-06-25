# Architecture

This directory is the **living per-capability truth** about what `httpware`
does *now* — one file per capability, living prose, dated by git (no
frontmatter). It is the promotion target on every ship: the *why* and *how it
got here* live in [`planning/`](../planning/), the *what it is today* lives
here.

## Capability files

- **[overview.md](overview.md)** — what `httpware` is (a thin `httpx2` wrapper)
  and the cross-cutting architectural invariants.
- **[client.md](client.md)** — the sync `Client` / async `AsyncClient` pair and
  their parity contract (typed decoding, middleware chain, resilience, `stream()`).
- **[middleware.md](middleware.md)** — Seam A: the middleware protocol, `Next`
  type, and chain composition at client construction.
- **[decoders.md](decoders.md)** — Seam B: the `ResponseDecoder` protocol and
  the pydantic / msgspec decoder resolution.
- **[errors.md](errors.md)** — the status-keyed exception tree raised on 4xx/5xx
  and the `StatusError` construction invariant.
- **[resilience.md](resilience.md)** — the stdlib resilience suite (retry, retry
  budget, bulkhead, circuit breaker, timeout) composed via the middleware chain.
- **[extras.md](extras.md)** — Seam C: optional dependencies imported only inside
  their dedicated modules.
- **[conventions.md](conventions.md)** — house code conventions: naming, imports,
  docstrings, exception construction.
- **[testing.md](testing.md)** — the testing conventions (`pytest-asyncio` auto
  mode, mock transports, property-based tests).

## Promotion rule

When a change alters a capability's behavior, **hand-edit the matching
`architecture/<capability>.md` in the same PR** — the edit rides in the same
diff and is reviewed with the code, never applied as a separate post-merge step.
That promotion is what keeps this directory true; code that changes without it
silently rots the truth home.
