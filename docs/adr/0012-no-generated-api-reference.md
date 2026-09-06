# No generated API reference on the docs site

**Decision:** the docs site is hand-written prose pages. `mkdocstrings` and a generated API
reference are declined.

A generated reference is cheap to add and expensive to keep honest. It produces a second,
lower-quality account of every public symbol — signature plus docstring, with no ordering, no
worked example, and no statement of which of two similar methods a reader wants — that
nonetheless outranks the hand-written page for anyone searching a symbol name. Two accounts of the
same API is exactly the failure this repo's docs pass was undoing, and the generated one is the
half that cannot be edited into shape.

The public surface here is also small enough that the prose pages can be complete rather than
selective: the exception tree, the decoder protocol, each resilience middleware, and the client's
own methods each have a page that reads in order. `httpware.__all__` is checked against an
explicit expected set in `tests/test_public_api.py`, so a symbol cannot appear without someone
noticing it is undocumented.

**Revisit trigger:** the public surface outgrowing what prose pages can cover completely — a
plugin-style API with many symbols, or a second package under the same site.
