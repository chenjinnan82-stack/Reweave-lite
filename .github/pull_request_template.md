## Summary


## Checks

- [ ] `python -m pytest tests -q`
- [ ] `node --check reweave_frontend/app.js`

## Safety invariants

- [ ] Does not write to Source Box folders by default.
- [ ] Does not add overwrite/delete flows.
- [ ] Does not expose local paths in shared provenance by default.
- [ ] Does not bypass demo output marker checks.
- [ ] Does not read source file contents during metadata-only scan.
