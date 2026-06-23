"""Hypothesis property tests for the pure _accumulate_capped core.

The one subtle invariant of the response-body cap is chunk-boundary
independence: the accumulator must behave identically no matter how the decoded
body is split into chunks. It must raise _CapExceeded iff the total decoded
length exceeds the cap, and otherwise return the body byte-for-byte.
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from httpware.client import _accumulate_capped, _CapExceeded


def _partition(body: bytes, sizes: list[int]) -> list[bytes]:
    """Split `body` into chunks following `sizes` (remainder becomes a final chunk)."""
    chunks: list[bytes] = []
    pos = 0
    for size in sizes:
        if pos >= len(body):
            break
        chunks.append(body[pos : pos + size])
        pos += size
    if pos < len(body):
        chunks.append(body[pos:])
    return chunks


@given(
    body=st.binary(max_size=2048),
    sizes=st.lists(st.integers(min_value=1, max_value=64), max_size=64),
    cap=st.integers(min_value=1, max_value=4096),
)
def test_accumulate_capped_chunk_boundary_independence(body: bytes, sizes: list[int], cap: int) -> None:
    chunks = _partition(body, sizes)
    if len(body) > cap:
        with pytest.raises(_CapExceeded) as caught:
            _accumulate_capped(chunks, cap)
        assert caught.value.read > cap
    else:
        assert _accumulate_capped(chunks, cap) == body


@given(body=st.binary(min_size=2, max_size=512))
def test_accumulate_capped_trips_at_one_below_length(body: bytes) -> None:
    cap = len(body) - 1
    with pytest.raises(_CapExceeded):
        _accumulate_capped([body], cap)


@given(body=st.binary(max_size=512))
def test_accumulate_capped_passes_at_exact_length(body: bytes) -> None:
    cap = max(1, len(body))
    assert _accumulate_capped([body], cap) == body
