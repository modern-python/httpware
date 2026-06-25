default: install lint test

install:
    uv lock --upgrade
    uv sync --all-extras --frozen --group lint

lint:
    uv run eof-fixer .
    uv run ruff format
    uv run ruff check --fix
    uv run ty check

lint-ci:
    uv run eof-fixer . --check
    uv run ruff format --check
    uv run ruff check --no-fix
    uv run ty check
    uv run python planning/index.py --check

# Print the planning change index (flat, newest-first) to stdout.
index:
    uv run python planning/index.py

# Validate planning bundles + decisions; CI runs this via lint-ci.
check-planning:
    uv run python planning/index.py --check

test *args:
    uv run --no-sync pytest {{ args }}

test-branch:
    @just test --cov-branch

publish:
    @test -n "${GITHUB_REF_NAME:-}" || (echo "GITHUB_REF_NAME is required; refusing to run outside CI" >&2; exit 1)
    @test -n "${PYPI_TOKEN:-}" || (echo "PYPI_TOKEN is required; refusing to run outside CI" >&2; exit 1)
    rm -rf dist
    uv version $GITHUB_REF_NAME
    uv build
    uv publish --token $PYPI_TOKEN

# Build the docs site, failing on broken links / nav warnings; CI runs this on every PR.
docs-build:
    uvx --with-requirements docs/requirements.txt mkdocs build --strict
