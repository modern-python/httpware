# Deferred Work

Items raised in reviews that are real but not actionable now.

As of 0.7.0, all planned epics (3, 4, 5, 6) are closed — see [`engineering.md`](engineering.md) §8. The Open section below is the long-tail register: items that remain technically real but depend on speculative future work, so they're parked here pending a concrete trigger.

## Open

### Client API surface

- **Per-verb-with-response siblings** (`get_with_response`, `post_with_response`, `request_with_response`) — the v0.8.2 spec deliberately ships only `send_with_response`; the verb-method shape would add ~400 LOC of overload boilerplate per side for a pattern (response headers + typed body) that's almost always paired with a GET and `build_request`. Revisit if a concrete consumer demand surfaces. (`src/httpware/client.py`)

## Resolved

- **Decoder caches are now per-instance** (was: *`_get_adapter` `lru_cache` is module-global*) — PR #42 (0.9.0) replaced the module-level `@functools.lru_cache` with per-instance `_adapters` / `_msgspec_decoders` dicts on each decoder, so configurations no longer share state across instances and caches don't survive across tests. 0.9.1 added a per-instance `can_decode` verdict cache on the same model. No module-global decoder cache remains.
