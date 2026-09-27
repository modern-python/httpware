import asyncio
import threading

import pytest

from httpware.middleware.resilience._event_loop_guard import check_event_loop


async def test_raises_when_another_loop_binds_between_unlocked_and_locked_read() -> None:
    other_loop = asyncio.new_event_loop()
    reads = iter([None, other_loop])
    bound: list[asyncio.AbstractEventLoop] = []
    try:
        with pytest.raises(RuntimeError, match="bound to"):
            check_event_loop(
                lambda: next(reads),
                bound.append,
                threading.Lock(),
                "bound to {first}, called from {current}",
            )
    finally:
        other_loop.close()
    assert bound == []
