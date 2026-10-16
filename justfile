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

adr_check_source := "https://raw.githubusercontent.com/modern-python/.github/main/tests/test_adr_citations.py"

# Tracks main on purpose: the shared check is unpinned.
adr-check:
    #!/usr/bin/env sh
    set -eu
    dir="$(mktemp -d .adr-check.XXXXXX)"
    trap 'rm -rf "$dir"' EXIT
    curl -fsSL "{{ adr_check_source }}" -o "$dir/test_adr_citations.py"
    uv run --no-sync pytest --rootdir=. --noconftest -o addopts= "$dir/test_adr_citations.py"

test *args:
    uv run --no-sync pytest {{ args }}

test-ci:
    uv run --no-sync pytest --cov=. --cov-report term-missing --cov-report xml

test-branch:
    @just test --cov=. --cov-branch

# Auth via PyPI Trusted Publishing (OIDC); uv publish auto-detects the CI id-token.
publish:
    @test -n "${GITHUB_REF_NAME:-}" || (echo "GITHUB_REF_NAME is required; refusing to run outside CI" >&2; exit 1)
    rm -rf dist
    uv version $GITHUB_REF_NAME
    uv build
    uv publish

# Build the docs site, failing on broken links / nav warnings; CI runs this on every PR.
docs-build:
    uvx --with-requirements docs/requirements.txt mkdocs build --strict

playwright := "playwright==1.64.0"

# Install the Chromium that docs-demos drives; --with-deps adds its system libraries on Linux.
docs-demos-browser:
    uvx --from {{ playwright }} playwright install --with-deps chromium

# Play every demo tour at phone and desktop width and fail on layout breakage or page errors.
docs-demos: docs-build
    uvx --with {{ playwright }} python -I scripts/check_demos.py site
