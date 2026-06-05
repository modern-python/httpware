"""Full-jitter exponential backoff helper (private)."""

import random
from collections.abc import Callable


def full_jitter_delay(
    attempt_index: int,
    *,
    base_delay: float,
    max_delay: float,
    _random_uniform: Callable[[float, float], float] = random.uniform,
) -> float:
    """Return a backoff delay using AWS's "full jitter" formulation.

    sleep = uniform(0, min(max_delay, base_delay * 2 ** attempt_index))

    `attempt_index` is 0 for the first retry, 1 for the second, etc.
    """
    ceiling = min(max_delay, base_delay * (2**attempt_index))
    return _random_uniform(0.0, ceiling)
