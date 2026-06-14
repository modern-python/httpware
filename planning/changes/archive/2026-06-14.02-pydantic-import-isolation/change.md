---
status: shipped
date: 2026-06-14
slug: pydantic-import-isolation
supersedes: null
superseded_by: null
pr: 62
outcome: Shipped via #62 — pydantic import guarded behind is_pydantic_installed so the decoder module loads without the extra; the architecture/extras.md Seam-C isolation invariant is now true for pydantic. Closed deep-audit High + 2 folded Mediums.
---

# Change: Guard the pydantic import so the decoder module loads without the extra

**Lane:** lightweight — ≲30 LOC net, 2 files, no new file, no public-API
change, a single straightforward test.

## Goal

Fix the 2026-06-14 deep-audit **High** finding (and the two folded **Medium**
findings sharing its root cause): `decoders/pydantic.py:13` imports
`from pydantic import TypeAdapter` unconditionally at module top, so
`import httpware.decoders.pydantic` raises a bare `ModuleNotFoundError` when
the extra is absent — *before* the friendly `ImportError` guard in
`PydanticDecoder.__init__` can run. This also makes the Seam-C isolation
invariant documented in [`architecture/extras.md`](../../../../architecture/extras.md)
false for pydantic (only msgspec matched it).

## Approach

Mirror the `decoders/msgspec.py` pattern exactly: import `import_checker`
first, then guard the hard import behind `is_pydantic_installed`, and quote
the one class annotation that references `TypeAdapter` as a forward-ref so the
class body does not evaluate the name at definition time when the extra is
absent. Runtime uses of `TypeAdapter` (inside methods) are only reachable when
pydantic is installed, so they need no change.

After this fix the documented invariant becomes true with **no doc edit
needed**: `grep -rnE 'from pydantic|import pydantic' src/httpware/ | grep -v
import_checker` returns exactly one indented line — the guarded import — which
is precisely what `architecture/extras.md` already claims. The High finding is
resolved by making the code match the (correct) doc.

## Files

- `src/httpware/decoders/pydantic.py` — reorder imports; guard
  `from pydantic import TypeAdapter` behind `if import_checker.is_pydantic_installed:`;
  quote the `_adapters` class annotation's `TypeAdapter` reference.
- `tests/test_optional_extras_pydantic_missing.py` — add a fresh-subprocess
  test proving the module imports cleanly when pydantic is genuinely absent
  and that `PydanticDecoder()` then raises the friendly extra-missing error.

## Verification

- [ ] Failing test first — `just test tests/test_optional_extras_pydantic_missing.py -k module_imports_when_pydantic_absent` fails (module load raises under simulated absence).
- [ ] Apply the change.
- [ ] Test passes — same command.
- [ ] `grep -rnE 'from pydantic|import pydantic' src/httpware/ | grep -v import_checker` returns exactly one indented line.
- [ ] `just test` — full suite green.
- [ ] `just lint` — clean.
