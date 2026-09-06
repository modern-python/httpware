# `__reduce__` is a mixin on six classes, not a method on `ClientError`

**Decision:** `_KeywordReduceMixin` is applied to the six keyword-only `ClientError` subclasses
only. A generic `self.__dict__`-based `__reduce__` on `ClientError` itself is rejected.

Hoisting it to the root looks like the same deduplication done one level higher, and it silently
breaks the classes it would newly cover. `TransportError`, `NetworkError` and httpware's
`TimeoutError` have no custom `__init__`: they are constructed as plain `Exception(message)`, the
message lives in `self.args`, and `self.__dict__` is empty. A root-level `__reduce__` replaying
`self.__dict__` as keyword arguments would reconstruct each of them with *no* arguments and lose
the message — a corruption that only shows up in a process that unpickles, which is rarely the
process the test suite runs in.

The mixin's precondition is what makes it safe: the instance `__dict__` after `__init__` must
mirror the keyword-only `__init__` parameters exactly. `StatusError` is out of scope for the same
kind of reason — it already has one shared mechanism (`_reconstruct_status_error` over a single
positional `response`, inherited by every status-keyed subclass), and it is a different mechanism,
not a duplicate of this one.

`tests/test_errors.py::test_keyword_reduce_classes_dict_mirrors_their_init_parameters` enforces
the precondition for every class carrying the mixin, so adding a seventh class is checked rather
than assumed.

**Revisit trigger:** the argless subclasses gaining keyword-only `__init__`s of their own, which
would make the precondition hold tree-wide and the root method safe.
