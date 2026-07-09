# Release Notes

## Public Alpha

Reweave-lite turns old project folders into reusable capsules and previewable Task Packs.

### What Works

- Public Source Box examples.
- Local capsule draft, store, retrieval, and Task Pack preview.
- Desktop shell with read-only runtime bridge.
- Desktop smoke: Source Box onboarding loads first; Generate / Export / Open Folder stay hidden until eligible.
- Bridge smoke: Source Box -> scan -> draft -> store -> Task Pack preview works without source writes.
- Public demo script:

```bash
python3 scripts/run_public_reweave_demo.py
```

The demo writes `task_pack.json`, `capsules_used.json`, `provenance.json`, and `snippets_used.json`.

### What Does Not

- Not a full autopilot IDE.
- No automatic multi-file writes.
- No overwrite/delete workflow.
- Real source project writes stay off by default.

### Safety Boundary

Source folders are read as context. The public demo writes only to your system temp folder by default, such as `/tmp/reweave_public_demo` on macOS/Linux or `%TEMP%\reweave_public_demo` on Windows, unless you pass another safe output directory.

Local source paths are redacted from public demo provenance by default.
