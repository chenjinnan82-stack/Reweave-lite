from __future__ import annotations

from pathlib import Path


class SafePreviewWriteError(ValueError):
    pass


def write_preview_files(files: dict[str, str], root: str | Path) -> list[str]:
    base = Path(root)
    if base.is_symlink():
        raise SafePreviewWriteError("preview root must not be a symlink")
    base.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for rel, content in files.items():
        target = _target(base, rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written.append(str(rel).replace("\\", "/").strip("/"))
    return written


def _target(root: Path, rel: str) -> Path:
    cleaned = str(rel or "").replace("\\", "/").strip().strip("/\"'`")
    if not cleaned or cleaned.startswith("/") or ".." in cleaned.split("/"):
        raise SafePreviewWriteError(f"unsafe preview path: {rel}")
    base = root.resolve(strict=False)
    current = base
    for part in Path(cleaned).parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise SafePreviewWriteError(f"preview parent is symlink: {rel}")
    candidate = base / cleaned
    if candidate.is_symlink():
        raise SafePreviewWriteError(f"preview target is symlink: {rel}")
    target = candidate.resolve(strict=False)
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise SafePreviewWriteError(f"preview path escapes root: {rel}") from exc
    return target
