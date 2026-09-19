# `httpx2` is the public surface

httpware re-exports `httpx2.Request` and `httpx2.Response` and owns no request, response, config,
auth, or transport types. The 0.1.0 wrapper layer was withdrawn in 0.2.0 because two type systems
had to be kept in step across every httpx2 upgrade, every new httpx2 feature needed a translation at
the border, and users who knew httpx had to learn a second vocabulary. Exposing the real response is
also what makes `StatusError` cheap: `exc.response` carries URL, headers, content, and extensions
with no field defined by httpware. The accepted cost is that an httpx2 major version is a breaking
change with no seam to absorb it. `tests/test_public_api.py::test_no_removed_symbols_leaked` keeps
the withdrawn names from returning.
