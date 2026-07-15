"""Fixed PySide worker for Stage 3 image cleaning and real QWeb validation."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any


MAX_BYTES = 1024 * 1024
MAX_PIXELS = 16_777_216


def _emit(value: dict[str, Any]) -> None:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_BYTES:
        encoded = json.dumps(
            {
                "schema_version": "pyside_worker.v1",
                "status": "failed",
                "error_code": "worker_output_too_large",
            },
            separators=(",", ":"),
        ).encode("utf-8")
    sys.stdout.buffer.write(encoded)


def _inside_workdir(name: object) -> Path:
    if not isinstance(name, str) or not name or Path(name).is_absolute():
        raise ValueError("worker_path_invalid")
    root = Path.cwd().resolve()
    path = (root / name).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        raise ValueError("worker_path_invalid")
    return path


def _image(request: dict[str, Any]) -> dict[str, Any]:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QImage, QImageReader, QImageWriter, QPainter

    source = _inside_workdir(request.get("input"))
    output = _inside_workdir(request.get("output"))
    raw = source.read_bytes()
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("image_size_forbidden")
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        media_type, qt_format = "image/png", b"png"
    elif raw.startswith(b"\xff\xd8\xff"):
        media_type, qt_format = "image/jpeg", b"jpeg"
    elif len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        media_type, qt_format = "image/webp", b"webp"
    else:
        raise ValueError("image_magic_forbidden")

    reader = QImageReader(str(source))
    reader.setAutoTransform(True)
    detected_format = bytes(reader.format()).lower()
    expected_formats = {
        "image/png": {b"png"},
        "image/jpeg": {b"jpeg", b"jpg"},
        "image/webp": {b"webp"},
    }[media_type]
    if detected_format not in expected_formats:
        raise ValueError("image_format_mismatch")
    size = reader.size()
    if not size.isValid() or size.width() > 4096 or size.height() > 4096 or size.width() * size.height() > MAX_PIXELS:
        raise ValueError("image_dimensions_forbidden")
    image = reader.read()
    if image.isNull():
        raise ValueError("image_decode_failed")
    if image.width() > 4096 or image.height() > 4096 or image.width() * image.height() > MAX_PIXELS:
        raise ValueError("image_dimensions_forbidden")

    clean = QImage(image.size(), QImage.Format.Format_ARGB32)
    clean.fill(0)
    painter = QPainter(clean)
    painter.drawImage(0, 0, image)
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
        raise ValueError("image_encode_failed")
    writer = QImageWriter(buffer, qt_format)
    if media_type in {"image/jpeg", "image/webp"}:
        writer.setQuality(90)
    if not writer.write(clean):
        raise ValueError("image_encode_failed")
    cleaned = bytes(data)
    if not cleaned or len(cleaned) > MAX_BYTES:
        raise ValueError("image_cleaned_size_forbidden")
    output.write_bytes(cleaned)
    return {
        "schema_version": "image_cleaning.v1",
        "status": "passed",
        "media_type": media_type,
        "sha256": hashlib.sha256(cleaned).hexdigest(),
        "size_bytes": len(cleaned),
        "width": clean.width(),
        "height": clean.height(),
    }


def _qweb(request: dict[str, Any]) -> dict[str, Any]:
    from PySide6.QtCore import QTimer, QUrl
    from PySide6.QtWidgets import QApplication
    from PySide6.QtWebEngineCore import (
        QWebEnginePage,
        QWebEngineProfile,
        QWebEngineSettings,
        QWebEngineUrlRequestInterceptor,
    )

    root = Path.cwd().resolve()
    entry = _inside_workdir(request.get("entry"))
    allowed = {_inside_workdir(item) for item in request.get("allow_files", [])}
    if entry not in allowed:
        raise ValueError("qweb_entry_not_allowed")
    blocked: list[dict[str, str]] = []
    console: list[str] = []

    class Interceptor(QWebEngineUrlRequestInterceptor):
        def interceptRequest(self, info: Any) -> None:  # noqa: N802 - Qt callback
            url = info.requestUrl()
            scheme = url.scheme().lower()
            if scheme == "about" and url.toString() == "about:blank":
                return
            if scheme == "file":
                path = Path(url.toLocalFile()).resolve()
                if path in allowed:
                    return
                # Never return an untrusted outside basename: source/customer names can
                # themselves contain sensitive data.  Same-package names are already
                # bounded by the sanitized temporary package.
                logical = path.name if path.parent == root else "<outside>"
            else:
                logical = "<blocked>"
            blocked.append({"scheme": scheme or "unknown", "logical_path": logical})
            info.block(True)

    class Page(QWebEnginePage):
        def javaScriptConsoleMessage(self, _level: Any, message: str, _line: int, _source: str) -> None:  # noqa: N802
            console.append(str(message)[:500])

    app = QApplication.instance() or QApplication(["reweave-qweb-worker"])
    profile = QWebEngineProfile()
    if not profile.isOffTheRecord():
        raise ValueError("qweb_profile_not_off_the_record")
    profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
    profile.setPersistentCookiesPolicy(
        QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies
    )
    interceptor = Interceptor(profile)
    profile.setUrlRequestInterceptor(interceptor)
    page = Page(profile)
    settings = page.settings()
    settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, False)
    settings.setAttribute(QWebEngineSettings.WebAttribute.DnsPrefetchEnabled, False)
    settings.setAttribute(
        QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True
    )
    settings.setAttribute(
        QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False
    )
    result: dict[str, Any] = {
        "schema_version": "qweb_validation.v1",
        "status": "failed",
        "error_code": "qweb_timeout",
    }

    def finish(value: object) -> None:
        nonlocal result
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                value = None
        if isinstance(value, dict):
            result = dict(value)
        else:
            result = {
                "schema_version": "qweb_validation.v1",
                "status": "failed",
                "error_code": "qweb_result_missing",
            }
        QTimer.singleShot(0, app.quit)

    def loaded(ok: bool) -> None:
        if not ok:
            finish(
                {
                    "schema_version": "qweb_validation.v1",
                    "status": "failed",
                    "error_code": "qweb_load_failed",
                }
            )
            return
        page.runJavaScript(
            "JSON.stringify(globalThis.__reweave_result === undefined ? null : globalThis.__reweave_result)",
            finish,
        )

    page.loadFinished.connect(loaded)
    QTimer.singleShot(8000, app.quit)
    page.load(QUrl.fromLocalFile(str(entry)))
    app.exec()
    page.deleteLater()
    profile.deleteLater()
    if blocked:
        result = {
            "schema_version": "qweb_validation.v1",
            "status": "failed",
            "error_code": "qweb_request_blocked",
        }
    elif console:
        result = {
            "schema_version": "qweb_validation.v1",
            "status": "failed",
            "error_code": "qweb_console_error",
        }
    result["blocked_requests"] = blocked
    result["console_messages"] = console
    result["acceptance_scope"] = "real_qwebengine_runtime"
    return result


def main() -> int:
    try:
        raw = sys.stdin.buffer.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("worker_input_too_large")
        request = json.loads(raw)
        mode = request.get("mode")
        if mode == "image":
            result = _image(request)
        elif mode == "qweb":
            result = _qweb(request)
        else:
            raise ValueError("worker_mode_invalid")
        _emit(result)
        return 0
    except Exception as exc:
        code = str(exc) if isinstance(exc, ValueError) else "pyside_worker_failed"
        _emit({"schema_version": "pyside_worker.v1", "status": "failed", "error_code": code})
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
