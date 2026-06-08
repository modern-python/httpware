# Deferred Work

Items raised in reviews that are real but not actionable now.

As of 0.7.0, all planned epics (3, 4, 5, 6) are closed — see [`engineering.md`](engineering.md) §8. The Open section below is the long-tail register: items that remain technically real but depend on speculative future work, so they're parked here pending a concrete trigger.

## Open

### Decoder-side

- **`_get_adapter` `lru_cache` is module-global, not per-decoder instance** — keyed by `model` only; two `PydanticDecoder()` instances with different configurations (none today) would share adapters, and the cache survives across tests unless explicitly cleared. Revisit if/when a configurable `PydanticDecoder(mode=..., strict=...)` lands. No such configurability is on the roadmap, so this item is dormant unless a real use-case surfaces. (`src/httpware/decoders/pydantic.py:12-14`)

### Client API surface

- **Per-verb-with-response siblings** (`get_with_response`, `post_with_response`, `request_with_response`) — the v0.8.2 spec deliberately ships only `send_with_response`; the verb-method shape would add ~400 LOC of overload boilerplate per side for a pattern (response headers + typed body) that's almost always paired with a GET and `build_request`. Revisit if a concrete consumer demand surfaces. (`src/httpware/client.py`)
