# Shared sync/async logic is a module-local function, not a class and not `_internal/`

**Decision:** when logic is extracted so both worlds can share it, it becomes a free function in
the module that already owns the behaviour. Wrapping it in a class, and hoisting it to
`_internal/`, are both rejected by default.

Both alternatives look like consistency arguments, which is what makes them recurring. The class
argument points at `_RetryPolicy` and `_CircuitBreakerState` and asks why this extraction is
different. It is different in the way that made those two classes right: they hold configuration
plus state that evolves across calls, so an object is the thing that carries it. An extraction that
computes a result from its arguments and keeps nothing has no state to hold, and a class around it
is a namespace with a `self` nobody reads — more ceremony at the call site, and a constructor that
exists only so the method can be reached.

The `_internal/` argument is the stronger of the two and still loses. `_internal/` is for logic
shared by modules that are otherwise unrelated — `status.py` and `exception_mapping.py` are used
from across the package, and nothing else would be a natural home. Bulkhead validation is used by
`Bulkhead` and `AsyncBulkhead`; decoder memoization by the two decoders. Moving those to
`_internal/` puts distance between a rule and the only code that obeys it, so a change to the
bulkhead means editing two files in two directories to keep one behaviour consistent. Sharing
between two siblings is not the same relationship as sharing across the package, and only the
second one earns the move.

Two corollaries from applying this repeatedly are worth keeping, because both are easy to
"simplify" back:

- `_emit_bulkhead_rejected` **returns** the exception for the caller to raise instead of raising it
  itself. Raising inside the helper would put the helper's frame in the traceback and silently
  downgrade the async call site's explicit `raise ... from exc` to implicit `__context__` chaining
  — a change to what the user sees, produced by a change that looks purely internal.
- `check_event_loop` takes `get_loop`/`set_loop` closures rather than the instance. A free function
  reaching into `instance._loop` is private access from outside the class, which ruff `SLF001`
  flags and which would make the helper depend on its callers' attribute names.

**Revisit trigger:** an extraction that genuinely accumulates state across calls — that is the
signal for a class, and `_RetryPolicy` is the precedent to copy — or a third, unrelated module
needing the same helper, which is what `_internal/` is for.
