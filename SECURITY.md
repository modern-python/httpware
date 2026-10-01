# Security policy

## Reporting a vulnerability

If you discover a security vulnerability in `httpware`, please report it privately via [GitHub Security Advisories](https://github.com/modern-python/httpware/security/advisories/new).

Do not file a public GitHub issue for security reports.

## Disclosure timeline

- We acknowledge reports within 7 days.
- We aim to provide a fix or a detailed mitigation plan within 30 days of confirming the report.
- We keep a vulnerability and its fix private for 90 days before disclosing them, unless an earlier coordinated disclosure serves users better, for example when the vulnerability is already being exploited.

## Supported versions

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

- Vulnerabilities in dependencies such as `httpx2` or `pydantic`. Report those upstream; once a fix is released there, we will quickly publish an httpware release that requires the patched version.
- Misconfiguration in consuming applications.
