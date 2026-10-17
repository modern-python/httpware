"""Single-event-loop guard for async resilience middleware (private, shared)."""

import asyncio
import threading
from collections.abc import Callable


def check_event_loop(
    get_loop: Callable[[], asyncio.AbstractEventLoop | None],
    set_loop: Callable[[asyncio.AbstractEventLoop], None],
    loop_lock: threading.Lock,
    message_template: str,
) -> None:
    """Bind the caller to the running loop if it has none yet, else raise RuntimeError.

    The slow path of the caller's unlocked `self._loop is asyncio.get_running_loop()` check.
    `get_loop`/`set_loop` read and write the caller's cached-loop attribute; the read under
    `loop_lock` sees a loop that another thread bound after the caller's unlocked read.
    """
    current = asyncio.get_running_loop()
    with loop_lock:
        cached = get_loop()
        if cached is None:
            set_loop(current)
            return
    if cached is not current:
        raise RuntimeError(message_template.format(first=cached, current=current))
