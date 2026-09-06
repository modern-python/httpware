# `_RetryPolicy.decide` returns a delay or raises; no outcome sum type

**Decision:** the shared retry decision returns a `float` delay for "retry after this long" and
raises for every terminal case. A `_Sleep | _Stop` sum type returned to the caller is rejected.

The sum type is the more functional-looking design and the one a refactor tends to reach for: keep
`decide` pure, let the driver decide what to do. It does not survive contact with exception
context. `decide` is called from inside the driver's `except` block, which is exactly why raising
there is free — `__context__` is set implicitly and `raise ... from exc` chains explicitly, the
same as if the wrapper had raised itself. Returning a `_Stop` defers the raise to *after* the
`except` block, where the active exception is gone and the chain has to be rebuilt by hand. The
machinery that would exist to do that exists only to undo a choice made a few lines earlier.

The asymmetry (return a value, or raise) is also the established shape in this codebase, not a
one-off: `_CircuitBreakerState.admit()` raises `CircuitOpenError` rather than returning a rejected
verdict. Two resilience components deciding in the same way is worth more than either of them
being independently elegant.

**Revisit trigger:** a caller that must inspect the terminal decision without the exception being
raised — for example a dry-run or policy-explanation mode — where catching the raise is
demonstrably worse than a returned verdict.
