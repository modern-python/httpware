# Sync/async parity is hand-maintained, with one named exception

`Client`/`AsyncClient` and each resilience middleware are two hand-written classes. Unasync-style
codegen was rejected because it adds a build step and a generated file that is either committed and
lying or absent from tracebacks, while the duplication that hurts is logic, which is extracted into
shared objects such as `_RetryPolicy` and `_CircuitBreakerState` rather than transformed. The one
deliberate break is `AsyncTimeout` without a sync sibling: sync Python cannot interrupt a blocking
call mid-flight, so a sync `Timeout` would promise a deadline and deliver a suggestion, and `httpx2`'s
per-call timeouts are the documented sync answer. `tests/test_client_parity.py` enforces both halves.
