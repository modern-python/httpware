# Changelog

All notable changes to `httpware` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Initial project scaffold: `src/httpware/` package, `py.typed` marker, `pyproject.toml` with `uv_build` backend.
- Org conventions ported from `modern-python/modern-di`: `Justfile`, `.github/workflows/ci.yml`, `[tool.ruff]` config, `[tool.pytest.ini_options]`, dev and lint dep groups.
- Declared dependencies: `httpx2>=2.0.0,<3.0`, `pydantic>=2.0,<3.0`.
- Declared install extras: `[msgspec]`, `[otel]`, `[niquests]`, `[all]`.
- `SECURITY.md` with 90-day private-disclosure window.
- `CONTRIBUTING.md` with development workflow.
- `CLAUDE.md` with AI-agent guidance.
- Core data types: `Request`, `Response`, `Limits`, `Timeout`, `ClientConfig` — frozen+slotted dataclasses with `with_*` immutability helpers on `Request` and computed `text`/`json()` accessors on `Response` (Story 1.2).

[Unreleased]: https://github.com/modern-python/httpware/commits/main
