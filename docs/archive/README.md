# Archive

This directory contains the bmad-era planning artifacts for `httpware`:

- `prd.md` — 47 functional and 25 non-functional requirements.
- `architecture.md` — twelve architectural decisions, the five protocol seams, full module layout.
- `epics.md` — six epics with 32 stories.
- `product-brief-httpware.md` and `product-brief-httpware-distillate.md` — executive brief and detail pack from the predecessor `community-of-python/base-client` scoping exercise.
- `stories/` — per-story specs (1-1 through 1-5) and the retired `sprint-status.yaml`.

These files are **historical reference, not authoritative**. The load-bearing decisions were distilled into [`../engineering.md`](../engineering.md) on 2026-05-31 when the project switched workflows from bmad to superpowers. Consult these archived files only when you need:

- Original rationale behind a decision (e.g., "why did we choose `httpx2` over `aiohttp`?").
- The specific FR/NFR numbers that a future spec wants to cite (e.g., `archive/prd.md#NFR-12`).
- The Given/When/Then acceptance criteria from a completed story.

For everything else — invariants, seams, module layout, conventions, the remaining roadmap — read `../engineering.md` and `../../CLAUDE.md`.
