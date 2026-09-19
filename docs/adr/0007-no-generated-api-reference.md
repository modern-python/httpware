# No generated API reference

The docs site is hand-written prose. `mkdocstrings` was declined because a generated reference is a
second, lower-quality account of every symbol that outranks the curated page in search and cannot
be edited into shape. The surface is small enough for prose to be complete, and
`tests/test_public_api.py` pins `__all__` so a symbol cannot ship undocumented.
