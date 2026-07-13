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
    """Bind the caller to the first event loop that calls it.

    Raises RuntimeError on a later call from a different loop. `get_loop`/`set_loop`
    read and write the caller's cached-loop attribute. The inner check re-reads via
    `get_loop()` rather than reusing the outer snapshot, so a thread that loses the
    race to acquire `loop_lock` still sees whichever loop the winner just bound
    (double-checked locking) — the outer unlocked read handles the common
    already-bound case without lock overhead.
    """
    current = asyncio.get_running_loop()
    cached = get_loop()
    if cached is current:
        return
    if cached is not None:
        raise RuntimeError(message_template.format(first=cached, current=current))
    with loop_lock:
        cached = get_loop()
        if cached is None:
            set_loop(current)
        # pragma below: inner double-check-with-lock race arm; only reachable when
        # two threads simultaneously pass the outer check, which single-threaded
        # tests can't trigger.
        elif cached is not current:  # pragma: no cover
            raise RuntimeError(message_template.format(first=cached, current=current))
