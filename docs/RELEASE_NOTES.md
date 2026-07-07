# Release Notes

## Public Alpha

Reweave-lite turns old project folders into reusable capsules and previewable Task Packs.

### What Works

- Public Source Box examples.
- Local capsule draft, store, retrieval, and Task Pack preview.
- Desktop shell with read-only runtime bridge.
- Public demo script:

```bash
python3 scripts/run_public_reweave_demo.py
```

### What Does Not

- Not a full autopilot IDE.
- No automatic multi-file writes.
- No overwrite/delete workflow.
- Real source project writes stay off by default.

### Safety Boundary

Source folders are read as context. The public demo writes only to your system temp folder by default, such as `/tmp/reweave_public_demo` on macOS/Linux or `%TEMP%\reweave_public_demo` on Windows, unless you pass another safe output directory.

Local source paths are redacted from public demo provenance by default.
