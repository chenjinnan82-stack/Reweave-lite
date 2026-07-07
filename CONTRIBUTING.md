# Contributing

Thanks for helping Reweave-lite.

## Setup

```bash
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
node --check reweave_frontend/app.js
```

## Safety Invariants

PRs must not:

- write to Source Box folders by default
- add overwrite/delete flows
- expose local paths in shared provenance by default
- bypass demo output marker checks
- read source file contents during metadata-only scan

For path traversal, source-write, local file exposure, or provenance redaction issues, use the security reporting path in `SECURITY.md`.
