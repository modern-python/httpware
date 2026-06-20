---
status: shipped
date: 2026-06-07
slug: decoder-error
summary: Shipped 0.8.1 — DecodeError at seam B
supersedes: null
superseded_by: null
pr: 32
outcome: 'Shipped 0.8.1 — DecodeError at seam B'
---

# Spec: `DecodeError` — close the decoder-exception gap at Seam 3

**Date:** 2026-06-07
**Topic slug:** `decoder-error`
**Status:** drafted, awaiting user review
**Target release:** `0.8.1` (patch — the leaked exceptions weren't a documented contract, so wrapping them is a defect fix, not a contract change)

## Purpose

`httpware`'s README and the `Client` / `AsyncClient` class docstrings advertise a single exception tree — `httpware.ClientError` and its subclasses — as the catch-all for HTTP-call failure. Today that promise has a hole: when `response_model=` is passed and the active `ResponseDecoder` fails (malformed JSON, schema mismatch, or anything else), the backing-library exception (`pydantic.ValidationError`, `msgspec.ValidationError`, `msgspec.DecodeError`) propagates out of `Client.send` / `AsyncClient.send` untranslated. `except httpware.ClientError` does not catch it.

This forces every consumer into one of two bad postures:

1. **Skip the decoder entirely** — call `client.send(client.build_request(...))` without `response_model=` and re-decode the raw `httpx2.Response` manually. The installed extra (`httpware[pydantic]` or `[msgspec]`) becomes dead weight; the seam's whole point — decoder swappability — never delivers.
2. **Import the decoder library at the call site** — `except (httpware.ClientError, pydantic.ValidationError)`. Now switching from `PydanticDecoder` to `MsgspecDecoder` is a multi-file rewrite, not a config change.

The fix introduces a new exception class — `httpware.DecodeError` — and a single try/except at the **Seam 3** (`Client/AsyncClient ↔ ResponseDecoder`) boundary. The decoder protocol stays silent on exceptions; the wrapping happens at the seam, in one place per world. After this change, `except httpware.ClientError` catches every failure mode of `client.send(..., response_model=M)`, regardless of which decoder is active.

## Non-goals

- **No change to `PydanticDecoder` or `MsgspecDecoder`.** They continue to raise their backing-library exceptions; the seam translates. Implementers of third-party decoders are not required to import `httpware.DecodeError`.
- **No change to the `ResponseDecoder` protocol signature.** `decode(content: bytes, model: type[T]) -> T` is unchanged. The protocol docstring grows one sentence documenting what the seam does, but the structural contract is unchanged.
- **No streaming-decode support.** `stream()` / `astream()` paths do not accept `response_model=` today, and adding decode support to them is out of scope. Seam 3 covers only the two `send` methods.
- **No mapping table for decoder library exceptions.** No `pydantic.ValidationError → SchemaMismatchError`, no `msgspec.DecodeError → MalformedJSONError`. The single `DecodeError` is enough — the original library exception is exposed via `DecodeError.original` for consumers who want to introspect.
- **No feature flag, env-var toggle, or shim layer.** The wrap is unconditional. Consumers catching pydantic/msgspec exceptions directly downstream of `send(...)` must switch to `except httpware.DecodeError` (or the broader `except httpware.ClientError`).
- **No special-case for nested `DecodeError`.** If a third-party decoder somehow raises `httpware.DecodeError` directly, the seam wrapper will catch and re-wrap it. The chain depth grows by one; `__cause__` still points to the real root. Not worth a guard in v1.
- **No deprecation pass.** The previously-leaking exceptions weren't part of httpware's documented surface, so there is nothing to deprecate.

## Architecture

### The seam — what changes, what doesn't

`AsyncClient.send` (`src/httpware/client.py:147`) and `Client.send` (`src/httpware/client.py:864`) are the only two call sites of `self._decoder.decode(...)`. Both lines today read:

```python
return self._decoder.decode(response.content, response_model)
```

After this change, both wrap the call in a try/except and raise `DecodeError` from any caught `Exception`. The `_dispatch(request)` call stays *outside* the try — transport/status errors are already mapped to `ClientError` subclasses upstream (`_terminal` in `client.py:130` and `client.py:823`) and we do not want to re-wrap those as `DecodeError`.

The `ResponseDecoder` protocol (`src/httpware/decoders/__init__.py`) is unchanged in signature. Its docstring grows one sentence documenting that exceptions are translated by the seam, so implementers know they do not need to raise `DecodeError` themselves.

`PydanticDecoder` and `MsgspecDecoder` are unchanged.

### The exception — placement and shape

`DecodeError` is a direct child of `ClientError`, sibling of `TransportError` / `TimeoutError` / `StatusError` / `RetryBudgetExhaustedError` / `BulkheadFullError`. Caught by `except httpware.ClientError`. The tree becomes:

```text
ClientError
├─ TransportError
│  └─ NetworkError
├─ TimeoutError
├─ StatusError
│  ├─ ClientStatusError → {BadRequest, Unauthorized, Forbidden, NotFound,
│  │                        Conflict, UnprocessableEntity, RateLimited}
│  └─ ServerStatusError → {InternalServer, ServiceUnavailable}
├─ RetryBudgetExhaustedError
├─ BulkheadFullError
└─ DecodeError      ← new
```

`DecodeError` is *not* a `StatusError` subclass: the semantic of `StatusError` is "server signaled error via 4xx/5xx," which is exactly the case `DecodeError` does *not* cover (the request succeeded, the body is wrong). It is also *not* under a new intermediate parent (`PayloadError` or similar) — YAGNI; one-member intermediates rarely grow members.

### Init shape

Keyword-only init with three fields, matching the precedent set by `RetryBudgetExhaustedError` (`errors.py:158`) and `BulkheadFullError` (`errors.py:196`):

```python
def __init__(
    self,
    *,
    response: httpx2.Response,
    model: type,
    original: BaseException,
) -> None:
    ...
```

- `response` — the full `httpx2.Response` returned by `_dispatch`. Carries status code, headers, request URL — everything consumers need for logging or translation. The body has already been fully read by the time `send` reaches the decoder, so there is no streaming-resource concern.
- `model` — the type passed to `response_model=`. Stored for consumer introspection (`if exc.model is MyResponse: …`) and for the error message.
- `original` — the underlying exception caught from the decoder. Typed `BaseException` for type-honest chaining (`raise DecodeError(...) from inner` sets `__cause__`); in practice always an `Exception` subclass because the seam catches `Exception`.

`__reduce__` is implemented for pickle parity with the rest of the tree, following the same module-level `_reconstruct_*` pattern used by `StatusError`, `RetryBudgetExhaustedError`, and `BulkheadFullError`.

Message format: `f"failed to decode response into {model.__name__}: {original}"`. Includes the model name and the original repr — terse enough for log lines, informative enough that an operator can diagnose without expanding the traceback.

### Why `except Exception`, not narrower

The seam wrapper catches `Exception`, not a narrower base. Rationale:

- `pydantic.ValidationError` inherits from `ValueError` but that is a CPython implementation detail.
- `msgspec.ValidationError` and `msgspec.DecodeError` inherit from `Exception` directly.
- A third-party decoder might raise anything — `RuntimeError`, a custom exception, a `LookupError` for a missing field.

Catching `Exception` covers all of these and deliberately leaves `BaseException` subclasses alone — `KeyboardInterrupt`, `SystemExit`, and `asyncio.CancelledError` (which is `BaseException` in 3.11+ when raised from cancel scopes) propagate untouched. This matches the posture of `_httpx2_exception_mapper_sync` already in `client.py`.

## Code change inventory

### `src/httpware/errors.py`

Add `_reconstruct_decode_error` (module-level, used by `__reduce__`) and `DecodeError`:

```python
def _reconstruct_decode_error(
    cls: "type[DecodeError]",
    response: httpx2.Response,
    model: type,
    original: BaseException,
) -> "DecodeError":
    return cls(response=response, model=model, original=original)


class DecodeError(ClientError):
    """Raised when the active ResponseDecoder failed to decode response.content.

    The HTTP call itself succeeded — status was 2xx/3xx and the transport
    delivered the body intact — but the body could not be parsed into the
    requested response_model. Always chained from the underlying library
    exception via `raise ... from exc`; that exception is also exposed as
    `self.original` for structured handling.
    """

    response: httpx2.Response
    model: type
    original: BaseException

    def __init__(
        self,
        *,
        response: httpx2.Response,
        model: type,
        original: BaseException,
    ) -> None:
        self.response = response
        self.model = model
        self.original = original
        super().__init__(f"failed to decode response into {model.__name__}: {original}")

    def __reduce__(self) -> tuple[Any, ...]:
        return (
            _reconstruct_decode_error,
            (type(self), self.response, self.model, self.original),
        )
```

### `src/httpware/client.py`

Both `send` methods change identically. Async (`client.py:147–157`):

```python
async def send(
    self,
    request: httpx2.Request,
    *,
    response_model: type[T] | None = None,
) -> httpx2.Response | T:
    """Send `request` through the middleware chain. Decode if `response_model` is set."""
    response = await self._dispatch(request)
    if response_model is None:
        return response
    try:
        return self._decoder.decode(response.content, response_model)
    except Exception as exc:
        raise DecodeError(response=response, model=response_model, original=exc) from exc
```

Sync (`client.py:864–874`): identical body, with `response = self._dispatch(request)` (no `await`).

Extend the existing `from httpware.errors import TransportError` line at `client.py:19` to also import `DecodeError`.

### `src/httpware/__init__.py`

Add `DecodeError` to the `from httpware.errors import (...)` block and to `__all__`. Slot next to the other `ClientError` children, matching the existing alphabetic-within-group convention.

### `src/httpware/decoders/__init__.py`

Append one sentence to `ResponseDecoder.decode`'s docstring:

> "Any exception raised by `decode` is wrapped by `Client.send` / `AsyncClient.send` into `httpware.DecodeError`; implementers do not need to raise `DecodeError` directly."

No other change. The protocol structure is identical.

### Out of scope (decoder classes themselves)

`src/httpware/decoders/pydantic.py` and `src/httpware/decoders/msgspec.py` are not modified.

## Tests

### `tests/test_errors.py`

Three new cases for `DecodeError`:

- **Construction & fields.** `DecodeError(response=r, model=MyModel, original=exc)` stores all three; `str(err)` includes `MyModel` and `repr(exc)`; `isinstance(err, ClientError)` is true. Negative coverage: passing positional args raises `TypeError` (kwargs-only).
- **Chaining.** When raised via `raise DecodeError(...) from inner`, `err.__cause__ is inner` and `err.original is inner` (the two channels carry the same reference but neither is dropped).
- **Pickle round-trip.** `pickle.loads(pickle.dumps(err))` reconstructs an equal-fielded `DecodeError`. Mirrors the existing `RetryBudgetExhaustedError` and `BulkheadFullError` pickle tests.

### `tests/test_client_response_model.py`

Existing file already exercises the `response_model=` path; extend it with seam-level decode-failure cases. Each case runs against both `Client` and `AsyncClient` (the file already has both variants):

- **Schema mismatch.** 200 OK + `b"null"` body against a model expecting a dict → `DecodeError` raised. Assert `exc.response.status_code == 200`, `exc.model is MyModel`, `isinstance(exc.original, pydantic.ValidationError)`, `exc.__cause__ is exc.original`.
- **Malformed JSON.** 200 OK + `b"{not json"` → `DecodeError` raised; same assertions; original is a `pydantic.ValidationError` (TypeAdapter.validate_json folds both failure modes into ValidationError).
- **`except ClientError` catches.** A test that wraps the schema-mismatch case in `except httpware.ClientError as exc:` and asserts the handler matches and `isinstance(exc, DecodeError)` is true — proves the user-facing promise.

### `tests/test_decoders_msgspec.py`

Existing direct-decoder tests stay as-is. Add one seam-level case that swaps `MsgspecDecoder()` in via the `decoder=` constructor argument, runs the schema-mismatch and malformed-JSON cases above, and asserts `exc.original` is a `msgspec.ValidationError` or `msgspec.DecodeError` respectively. Proves the wrapping is decoder-agnostic.

### `tests/test_decoders_pydantic.py`

No change. Existing tests still assert that `PydanticDecoder.decode(...)` called directly raises `pydantic.ValidationError` — the decoder still does this; the wrapping happens at the seam, not inside the decoder.

### `tests/test_public_api.py`

Extend the public-symbol list to include `DecodeError`.

### Out of scope (testing)

No Hypothesis / property tests. The wrap is deterministic and has no meaningful state space.

## Docs

### `docs/errors.md`

- Update the hierarchy diagram (the one mirroring the README/CLAUDE.md tree) to add `DecodeError` as a leaf sibling of `StatusError` under `ClientError`.
- Add a short "`DecodeError`" subsection following the same density as the existing `RetryBudgetExhaustedError` and `BulkheadFullError` sections. Three to five sentences explaining when it's raised (HTTP call succeeded, decoder failed); list the fields (`response`, `model`, `original`); one minimal `except` snippet.

### `README.md`

Current state (`README.md:54–67` and `README.md:74–87`): two `response_model=` examples exist, neither is wrapped in `try / except`. Do not add a new `try / except` block around either — these snippets are happy-path showcases and pulling them off-balance to demonstrate one error class hurts more than it helps. Instead, add a one-line note immediately after the `response_model=` paragraph (around `README.md:52`) explaining that decode failures raise `httpware.DecodeError` (a `ClientError` subclass), so the same `except httpware.ClientError` catches them. If a follow-up PR adds a dedicated errors section to the README, that section can carry the longer example.

### `planning/engineering.md`

- Add `DecodeError` to the exception-tree summary in the "Exception contract" section.
- Update the Seam-3 contract: "`decode` may raise any `Exception`; `Client.send` / `AsyncClient.send` wrap it as `DecodeError`. Decoder implementers do not need to raise `DecodeError` directly."

### Out of scope (docs)

- No new `docs/recipes/` entry.
- No `docs/decoders.md` — we do not have a decoders docs page today and this fix does not justify creating one.
- No migration guide — additive surface, no consumer code breaks at compile time.

## Backward compatibility

Purely additive at the import surface: `from httpware import DecodeError` is new but no existing import or name is changed.

Behavior change at the runtime surface: code that today catches `pydantic.ValidationError` or `msgspec.ValidationError` / `msgspec.DecodeError` directly downstream of `client.send(...)` will no longer match — those exceptions are now wrapped. That is the intended fix.

Code that today does `try: client.get(..., response_model=M) except httpware.ClientError: ...` continues to work and now actually catches the previously-escaping decode failure.

## Release

Target: **`0.8.1`** patch release.

Release notes:

- **Fix:** decoder exceptions from `response_model=` are now wrapped in a new `httpware.DecodeError` (a `ClientError` subclass), closing the gap where `pydantic.ValidationError` / `msgspec.ValidationError` / `msgspec.DecodeError` would escape `except httpware.ClientError`.
- **New:** `httpware.DecodeError` — direct child of `ClientError`. Fields: `response`, `model`, `original`.
- **Behavior change:** consumers catching pydantic/msgspec exceptions directly need to switch to `except httpware.DecodeError` (or the broader `except httpware.ClientError`). No shim layer; the previously-leaking exceptions weren't a documented contract.
