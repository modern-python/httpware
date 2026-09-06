"""Sync/async feature parity across the two client surfaces."""

import inspect

import pytest

import httpware
from httpware.middleware import resilience


_ASYNC_ONLY_NAMES = {"aclose"}
_SYNC_ONLY_NAMES = {"close"}


def _public_methods(cls: type) -> dict[str, inspect.Signature]:
    return {
        name: inspect.signature(getattr(cls, name))
        for name in dir(cls)
        if not name.startswith("_") and callable(getattr(cls, name))
    }


def _parameter_shape(signature: inspect.Signature) -> list[tuple[str, str]]:
    return [(p.name, p.kind.name) for p in signature.parameters.values()]


def test_client_and_asyncclient_expose_the_same_public_methods() -> None:
    """INVARIANT: Client and AsyncClient carry identical features; only close/aclose differ.

    Parity is hand-maintained rather than generated (see docs/adr/0009), so the only thing
    standing between the two surfaces and a slow drift is this comparison. A feature added to
    AsyncClient alone still ships, still passes its own tests, and still type-checks — sync
    callers simply never get it, and nobody finds out until one of them goes looking. The
    naming exceptions are enumerated rather than pattern-matched so that inventing a third
    one is a deliberate edit here, not a silent convention.
    """
    sync = set(_public_methods(httpware.Client))
    asynchronous = set(_public_methods(httpware.AsyncClient))

    assert sync - asynchronous == _SYNC_ONLY_NAMES, (
        f"Client has unmirrored public methods: {sorted(sync - asynchronous - _SYNC_ONLY_NAMES)}"
    )
    assert asynchronous - sync == _ASYNC_ONLY_NAMES, (
        f"AsyncClient has unmirrored public methods: {sorted(asynchronous - sync - _ASYNC_ONLY_NAMES)}"
    )


@pytest.mark.parametrize(
    "name",
    sorted(set(_public_methods(httpware.Client)) & set(_public_methods(httpware.AsyncClient))),
)
def test_mirrored_client_methods_take_the_same_parameters(name: str) -> None:
    """INVARIANT: a method present on both clients takes the same parameters in the same order.

    Matching method names are the cheap half of parity and the half that drifts least. The
    expensive half is the signature: a keyword added to `AsyncClient.post` and forgotten on
    `Client.post` leaves both surfaces looking complete while one of them silently cannot
    express the option. Only names, order and kind are compared — the two worlds legitimately
    annotate `middleware` and every return type differently, and pinning those here would
    make the test fail on changes that preserve the parity it exists to protect.
    """
    sync = inspect.signature(getattr(httpware.Client, name))
    asynchronous = inspect.signature(getattr(httpware.AsyncClient, name))

    assert _parameter_shape(sync) == _parameter_shape(asynchronous)


def test_client_constructors_take_the_same_parameters() -> None:
    """INVARIANT: Client and AsyncClient are configured through the same constructor keywords.

    The constructor is where a client's behaviour is settled — decoders and the middleware
    chain are both frozen there — so an option that reaches only one world is a feature that
    exists for half the users of the library. It is checked apart from the mirrored-method
    sweep because `__init__` is not a public name and that sweep never sees it.
    """
    sync = inspect.signature(httpware.Client.__init__)
    asynchronous = inspect.signature(httpware.AsyncClient.__init__)

    assert _parameter_shape(sync) == _parameter_shape(asynchronous)


def test_every_resilience_middleware_ships_both_worlds_except_timeout() -> None:
    """INVARIANT: each resilience middleware has a sync and an Async* form; Timeout is the sole exception.

    A sync sibling cannot be written for the total deadline — sync Python cannot interrupt a
    blocking call mid-flight — and docs/adr/0003 records that as a deliberate, argued break.
    The risk is that one argued exception becomes cover for unargued ones: the next
    async-only middleware is far easier to justify once the suite is already asymmetric. The
    exception is therefore named, not inferred, so a second gap has to be added to this set
    by someone who has read why the first one is there.
    """
    exported = {name for name in resilience.__all__ if name != "CircuitState"}
    async_forms = {name for name in exported if name.startswith("Async")}
    sync_forms = exported - async_forms - {"RetryBudget"}

    assert {name.removeprefix("Async") for name in async_forms} - sync_forms == {"Timeout"}
    assert sync_forms - {name.removeprefix("Async") for name in async_forms} == set()
