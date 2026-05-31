"""Benchmark: single-pass `validate_json` is faster than two-pass (Story 1.5 AC9, NFR3)."""

import gc
import json
import statistics
import time

import pydantic
import pytest
from pytest_benchmark.fixture import BenchmarkFixture

from httpware.decoders.pydantic import PydanticDecoder, _get_adapter


PAYLOAD_ITEMS = 30
PAYLOAD_MIN_BYTES = 4500
PAYLOAD_MAX_BYTES = 5500
SPEEDUP_FLOOR = 1.5  # AC9 fallback per Open Questions item 5 (2x target not hardware-portable).


class _User(pydantic.BaseModel):
    """Benchmark-only User shape: id, name, and a small attribute map."""

    id: int
    name: str
    attributes: dict[str, int]


def _build_payload() -> bytes:
    items = [
        {
            "id": i,
            "name": f"user-{i:03d}",
            "attributes": {f"k{j:02d}": j * 7 for j in range(10)},
        }
        for i in range(PAYLOAD_ITEMS)
    ]
    payload = json.dumps(items).encode("utf-8")
    assert PAYLOAD_MIN_BYTES <= len(payload) <= PAYLOAD_MAX_BYTES, (
        f"payload size {len(payload)} outside acceptance window"
    )
    return payload


@pytest.fixture
def payload() -> bytes:
    return _build_payload()


@pytest.fixture(autouse=True, scope="module")
def _warm_cache() -> None:
    _get_adapter.cache_clear()
    PydanticDecoder().decode(_build_payload(), list[_User])


@pytest.mark.benchmark(group="decoder", disable_gc=True)
def test_bench_single_pass_validate_json(benchmark: BenchmarkFixture, payload: bytes) -> None:
    decoder = PydanticDecoder()
    result = benchmark(decoder.decode, payload, list[_User])
    assert len(result) == PAYLOAD_ITEMS


@pytest.mark.benchmark(group="decoder", disable_gc=True)
def test_bench_two_pass_loads_then_validate(benchmark: BenchmarkFixture, payload: bytes) -> None:
    adapter = pydantic.TypeAdapter(list[_User])

    def two_pass() -> list[_User]:
        return adapter.validate_python(json.loads(payload))

    result = benchmark(two_pass)
    assert len(result) == PAYLOAD_ITEMS


@pytest.mark.perf
def test_single_pass_is_measurably_faster_than_two_pass(payload: bytes) -> None:
    decoder = PydanticDecoder()
    adapter = pydantic.TypeAdapter(list[_User])

    rounds = 60
    iterations = 30

    gc.collect()
    gc_was_enabled = gc.isenabled()
    gc.disable()
    try:
        single_samples: list[float] = []
        for _ in range(rounds):
            start = time.perf_counter_ns()
            for _ in range(iterations):
                decoder.decode(payload, list[_User])
            single_samples.append((time.perf_counter_ns() - start) / iterations)

        two_samples: list[float] = []
        for _ in range(rounds):
            start = time.perf_counter_ns()
            for _ in range(iterations):
                adapter.validate_python(json.loads(payload))
            two_samples.append((time.perf_counter_ns() - start) / iterations)
    finally:
        if gc_was_enabled:
            gc.enable()

    single_mean = statistics.median(single_samples)
    two_mean = statistics.median(two_samples)
    ratio = two_mean / single_mean

    assert ratio >= SPEEDUP_FLOOR, (
        f"NFR3 regression: single-pass {single_mean:.1f} ns/op, "
        f"two-pass {two_mean:.1f} ns/op, ratio={ratio:.2f}x (need ≥ {SPEEDUP_FLOOR}x)"
    )
