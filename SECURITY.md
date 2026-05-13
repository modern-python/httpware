# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in `httpware`, please report it privately via [GitHub Security Advisories](https://github.com/modern-python/httpware/security/advisories/new).

**Do not file a public GitHub issue for security reports.**

## Disclosure Timeline

- We commit to acknowledging your report within **7 days**.
- We aim to provide a fix or detailed mitigation plan within **30 days** of confirmation.
- We follow a **90-day private disclosure window** before public disclosure of the vulnerability and fix, unless a coordinated earlier disclosure is in the interest of users (e.g., the vulnerability is already being actively exploited).

## Supported Versions

Security fixes are provided for:

- The latest minor release on the current major version line.
- The previous minor release for a 90-day grace period after a new minor ships.

Older versions are not supported with security backports. Users on unsupported versions should upgrade.

## Scope

In scope:

- Vulnerabilities in `httpware` source code.
- Vulnerabilities in `httpware`'s default behavior that could leak secrets, bypass TLS verification, or otherwise compromise the security of consuming applications.
- Supply-chain integrity of the published wheel and sdist on PyPI.

Out of scope:

- Vulnerabilities in transitive dependencies (`httpx2`, `pydantic`, etc.) — report those upstream. We will fast-track a `httpware` release pinning the patched version once an upstream fix is available.
- Misconfiguration in consuming applications.
