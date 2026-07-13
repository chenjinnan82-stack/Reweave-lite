# Security Policy

Reweave-lite is a public alpha. Please report security issues against the latest `main` branch or latest public alpha release.

## Reporting a Vulnerability

Please do not open public issues for path traversal, source-write, local file exposure, or provenance redaction vulnerabilities.

Use **Report a vulnerability** on the repository Security Advisories page.

## Security Boundaries

- Source projects are read-only by default.
- Public demo provenance redacts local paths by default.
- Demo output refuses repository, home, filesystem root, and non-demo overwrite targets.
- No automatic overwrite, delete, or multi-file apply flow is included in the public release surface.
