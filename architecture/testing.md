# Testing

- **`pytest-asyncio` auto mode.** Async test functions do not require `@pytest.mark.asyncio`. The setting lives in `pyproject.toml` under `[tool.pytest.ini_options]`.
- **`httpx2.MockTransport` for transport mocking, not `respx`.** Tests construct `httpx2.AsyncClient(transport=httpx2.MockTransport(handler))` and pass it as `httpx2_client=` to `AsyncClient` (or the sync equivalent `httpx2.Client(transport=httpx2.MockTransport(handler))` to `Client`). `MockTransport` is a first-party `httpx2` API; `respx` targets `httpx` (not `httpx2`) and patches its internals directly — see `docs/testing.md` for why.
- **Hypothesis property-based tests** for concurrency-sensitive code: `RetryBudget`, `Bulkhead`, retry interleaving. Files are named `test_*_props.py` so they are easy to grep and treat separately in CI.
- **Performance tests are opt-in.** The `perf` pytest marker is registered in `pyproject.toml`; the default `addopts` line includes `-m 'not perf'`. Run benchmarks explicitly with `pytest -m perf`.
- **Coverage is 100% line coverage.** New code is expected to maintain this.
