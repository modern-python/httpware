# Deferred Work

Items raised in reviews that are real but not actionable now.

## Deferred from: code review of story-1-1 (2026-05-13)

- **Codecov upload fails on fork PRs** — fork PRs cannot access `CODECOV_TOKEN`; matches modern-di pattern, accepted tradeoff. (`.github/workflows/ci.yml:46-52`)
- **`just publish` lacks env-var validation** — recipe assumes `GITHUB_REF_NAME` and `PYPI_TOKEN` are set; running locally could corrupt the version. Add `test -n "$GITHUB_REF_NAME"` guard before release work. (`Justfile:25-29`)
- **`uv_build>=0.11,<0.12` narrow window** — single-minor band will expire as soon as uv_build 0.12 ships; bump when that happens. (`pyproject.toml:54`)
- **Python 3.14 wheel availability risk** — `httpx2` / `pydantic` / `uv_build` may not have 3.14 wheels yet, breaking the matrix entry. Watch CI red on 3.14. (`.github/workflows/ci.yml:30-33`)
- **Unpinned `ruff`/`ty` with `select=["ALL"]`** — any new ruff release adds rules and can break CI overnight. Pin major versions or pin specific rules when a regression occurs. (`pyproject.toml:70-72, 84-85`)
- **No `[test]` extra; CI uses `--all-extras`** — future heavy extras will be installed in every CI run. Declare a `test` extra and switch CI to `--extra test`. (`pyproject.toml:35-47`)
