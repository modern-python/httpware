# Wiring `AsyncClient` into `modern-di`

This recipe registers httpware clients in a [`modern-di`](https://modern-di.modern-python.org/) container, so the container builds each client with its middleware and closes its connection pool on shutdown. Both libraries are part of the [`modern-python`](https://github.com/modern-python) org.

## The minimal wire-up

```python
from modern_di import Container, Group, Scope, providers

from httpware import AsyncClient


class ServiceClients(Group):
    api = providers.Factory(
        scope=Scope.APP,
        creator=AsyncClient,
        kwargs={"base_url": "https://api.example.com"},
        cache_settings=providers.CacheSettings(finalizer=AsyncClient.aclose),
    )


async def main() -> None:
    container = Container(scope=Scope.APP, groups=[ServiceClients])
    try:
        client = container.resolve(AsyncClient)
        response = await client.get("/users/1")
        print(response.status_code)
    finally:
        await container.close_async()  # runs the AsyncClient.aclose finalizer
```

!!! note "modern-di 2.x"
    Resolution is sync: `container.resolve(...)`, with no `await`. Create the root
    container directly and close it with `await container.close_async()`; the
    `async with` form is for `build_child_container(...)`. In modern-di 1.x,
    resolution was awaited.

- `Scope.APP` ties the client to the application's lifetime: one client per process, reusing its connection pool for every call.
- `cache_settings=providers.CacheSettings(...)` makes the provider a singleton. Without it, `Factory` builds a new `AsyncClient` on every resolve.
- `finalizer=AsyncClient.aclose` is the unbound async method. `modern-di` sees that it is async and awaits it when the container closes.

Don't write `finalizer=lambda c: c.aclose()`. The lambda is sync, so `modern-di` calls it without awaiting and the returned coroutine is dropped, leaking the connection pool. Pass the unbound method, or an `async def`.

The [`modern-di` factories docs](https://modern-di.modern-python.org/providers/factories/) cover `CacheSettings` in full, including scopes, `clear_cache`, and sync and async finalizers.

## A second backend collides on type

Registering a second `Factory(creator=AsyncClient, ...)` for another backend fails when the container is built:

```python
class ServiceClients(Group):
    user_api = providers.Factory(
        scope=Scope.APP,
        creator=AsyncClient,
        kwargs={"base_url": "https://users.example.com"},
        cache_settings=providers.CacheSettings(finalizer=AsyncClient.aclose),
    )
    billing_api = providers.Factory(
        scope=Scope.APP,
        creator=AsyncClient,
        kwargs={"base_url": "https://billing.example.com"},
        cache_settings=providers.CacheSettings(finalizer=AsyncClient.aclose),
    )


# At Container(...) construction:
# modern_di.exceptions.DuplicateProviderTypeError: Provider is duplicated by type
# <class 'httpware.client.AsyncClient'>. To resolve this issue: ...
```

`modern-di` resolves dependencies by `bound_type`, which defaults to the creator's return type, so both providers register as `AsyncClient`.

## Fix: one subclass per backend

Subclass `AsyncClient` once per backend so each provider has its own `bound_type`:

```python
from modern_di import Container, Group, Scope, providers

from httpware import AsyncClient


class UserApi(AsyncClient):
    """Typing handle for the User service backend."""


class BillingApi(AsyncClient):
    """Typing handle for the Billing service backend."""


class ServiceClients(Group):
    user_api = providers.Factory(
        scope=Scope.APP,
        creator=UserApi,
        kwargs={"base_url": "https://users.example.com"},
        cache_settings=providers.CacheSettings(finalizer=UserApi.aclose),
    )
    billing_api = providers.Factory(
        scope=Scope.APP,
        creator=BillingApi,
        kwargs={"base_url": "https://billing.example.com"},
        cache_settings=providers.CacheSettings(finalizer=BillingApi.aclose),
    )


async def main() -> None:
    container = Container(scope=Scope.APP, groups=[ServiceClients])
    try:
        users = container.resolve(UserApi)
        billing = container.resolve(BillingApi)
        # ... use them
    finally:
        await container.close_async()
```

The subclasses are empty and exist only as types; they inherit everything from `AsyncClient`. `container.resolve(UserApi)` and `container.resolve(BillingApi)` now reach the right provider. If code asks for `container.resolve(AsyncClient)` when only the subclasses are registered, `modern-di`'s error message suggests the subclasses.

## Middleware in `kwargs=`

A client's middleware is fixed when it is built, and a singleton `Factory` builds it once per container. Pass the middleware list in `kwargs=`:

```python
from httpware import AsyncClient, AsyncBulkhead, AsyncRetry


class ServiceClients(Group):
    user_api = providers.Factory(
        scope=Scope.APP,
        creator=UserApi,
        kwargs={
            "base_url": "https://users.example.com",
            "middleware": [AsyncBulkhead(max_concurrent=10), AsyncRetry()],
        },
        cache_settings=providers.CacheSettings(finalizer=UserApi.aclose),
    )
```

Each client gets its own `AsyncBulkhead` and `AsyncRetry`, so one backend's failures don't use up another's slots or retry budget.

## See also

- [Quickstart](../index.md): the `AsyncClient` API.
- [Resilience](../resilience.md): every resilience middleware and its parameters.
- [`modern-di` factories](https://modern-di.modern-python.org/providers/factories/): `CacheSettings`, scopes and other provider options.
