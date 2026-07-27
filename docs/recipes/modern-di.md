# Wiring `AsyncClient` into `modern-di`

If you wire your app's dependencies with [`modern-di`](https://modern-di.modern-python.org/) and want connection-pool teardown and middleware composition to flow through the container's lifecycle, this is the bridge. Both libraries ship under the [`modern-python`](https://github.com/modern-python) org.

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

> **modern-di 2.x.** Resolution is sync — `container.resolve(...)`, no `await`.
> The root container is created plainly and torn down with `await
> container.close_async()` (the `async with` form is for
> `build_child_container(...)`, not the root). On modern-di 1.x, resolution was
> awaited; pin accordingly if you are still on 1.x.

Breaking that down:

- **`Scope.APP`** ties the client to the application lifetime. One client per process; the connection pool is reused across all calls.
- **`cache_settings=providers.CacheSettings(...)`** is what makes the provider a singleton. Without it, `Factory` returns a fresh `AsyncClient` on every resolve.
- **`finalizer=AsyncClient.aclose`** is the unbound async method. `modern-di` detects the async finalizer and `await`s it on container teardown (here, on `close_async()`).

A common first instinct here is `finalizer=lambda c: c.aclose()`. **That does not work** — the lambda itself is sync, so `modern-di` calls it synchronously and discards the returned coroutine unawaited. The underlying connection pool leaks. Pass the unbound async method directly, or wrap in `async def`.

See the [`modern-di` factories docs](https://modern-di.modern-python.org/providers/factories/) for the broader `CacheSettings` story (scopes, `clear_cache`, sync vs async finalizers).

## Adding a second backend hits a type collision

The obvious move when you talk to a second backend — register another `Factory(creator=AsyncClient, ...)` — fails at container construction:

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

`modern-di` resolves dependencies by `bound_type`, which defaults to the creator's return type. Both providers default to `bound_type=AsyncClient` and collide in the providers registry.

## Fix: one wrapper subclass per backend

Give each provider a distinct `bound_type` by subclassing `AsyncClient`:

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

A couple of notes:

- Subclasses are **typing-only**. Empty body, no overrides. They inherit `__init__`, `aclose`, and every HTTP method unchanged.
- Each `Factory` now has a distinct `bound_type`, so `container.resolve(UserApi)` and `container.resolve(BillingApi)` route to the right provider.
- `modern-di`'s error suggestions are subclass-aware. If a caller asks for `container.resolve(AsyncClient)` after only the subclasses are registered, the error message points them at the right subclass.

## Middleware in `kwargs=`

`AsyncClient`'s middleware chain is composed once at construction and frozen for the client's lifetime. With a singleton-scoped `Factory`, "once at construction" means "once per container build." Drop the middleware list into `kwargs=`:

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

Each cached singleton owns its own `AsyncBulkhead` and `AsyncRetry` state — what you want when different backends have different reliability profiles.

## See also

- **[Quick-Start](../index.md)** — the base `AsyncClient` API.
- **[Middleware guide](../middleware.md)** — what `AsyncBulkhead` and `AsyncRetry` are doing in `kwargs[middleware]`.
- **[Resilience reference](../resilience.md)** — every parameter on `AsyncRetry`, `RetryBudget`, `AsyncBulkhead`.
- **[`modern-di` factories](https://modern-di.modern-python.org/providers/factories/)** — `CacheSettings`, scopes, the broader provider story.
