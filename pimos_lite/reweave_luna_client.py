"""Minimal Luna HTTP client for Reweave (stdlib only, health probe)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_LUNA_BASE_URL = "http://127.0.0.1:8020"
DEFAULT_TIMEOUT_SECONDS = 2.0
INDEX_PACK_TIMEOUT_SECONDS = 5.0
INDEX_PACK_PATH = "/api/v1/pym/index-pack"
REUSE_PACK_TIMEOUT_SECONDS = 5.0
REUSE_PACK_PATH = "/api/v1/reuse/pack"
GOVERNANCE_PREVIEW_TIMEOUT_SECONDS = 5.0
GOVERNANCE_PREVIEW_PATH = "/api/v1/artifacts/governance/preview-prune"

# Luna mounts GET /health at app root (see Luna/api/routes/health.py).
# Additional paths are probed only as fallbacks for alternate deployments.
HEALTH_PROBE_PATHS: tuple[str, ...] = (
    "/health",
    "/api/v1/health",
    "/api/health",
)


def luna_base_url() -> str:
    raw = os.environ.get("LUNA_BASE_URL", DEFAULT_LUNA_BASE_URL).strip()
    return _local_base_url(raw or DEFAULT_LUNA_BASE_URL)


def admin_api_key() -> str:
    direct = os.environ.get("ADMIN_API_KEY", "").strip()
    if direct:
        return direct
    key_file = os.environ.get("PIMOS_ADMIN_API_KEY_FILE", "").strip()
    for path in [Path(key_file)] if key_file else []:
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            return value
    return ""


def _is_loopback_url(base_url: str) -> bool:
    try:
        host = urllib.parse.urlparse(base_url).hostname
    except ValueError:
        return False
    return host in {"localhost", "127.0.0.1", "::1"}


def _local_base_url(base_url: str) -> str:
    value = base_url.rstrip("/")
    try:
        parsed = urllib.parse.urlparse(value)
        parsed.port
    except ValueError:
        raise ValueError("luna_url_must_be_localhost") from None
    if (
        parsed.scheme not in {"http", "https"}
        or not _is_loopback_url(value)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("luna_url_must_be_localhost")
    return value


class LunaHttpClient:
    """Small JSON HTTP client — no third-party deps."""

    def __init__(self, base_url: str | None = None, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self.base_url = _local_base_url(base_url or luna_base_url())
        self.timeout_seconds = max(0.1, float(timeout_seconds))

    def request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Perform one HTTP request; never raises — returns structured result."""
        method_u = (method or "GET").upper()
        path_norm = path if path.startswith("/") else f"/{path}"
        url = f"{self.base_url}{path_norm}"
        headers = {"Accept": "application/json"}
        if _is_loopback_url(self.base_url):
            api_key = admin_api_key()
            if api_key:
                headers["X-API-Key"] = api_key
        data: bytes | None = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode("utf-8")

        req = urllib.request.Request(url, data=data, headers=headers, method=method_u)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                status_code = int(getattr(resp, "status", 200))
                raw = resp.read().decode("utf-8", errors="replace")
                if not raw.strip():
                    return {
                        "ok": True,
                        "status_code": status_code,
                        "data": {},
                        "endpoint": path_norm,
                        "base_url": self.base_url,
                    }
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    return {
                        "ok": False,
                        "status_code": status_code,
                        "endpoint": path_norm,
                        "base_url": self.base_url,
                        "error": "invalid json response",
                    }
                if not isinstance(parsed, dict):
                    parsed = {"value": parsed}
                return {
                    "ok": True,
                    "status_code": status_code,
                    "data": parsed,
                    "endpoint": path_norm,
                    "base_url": self.base_url,
                }
        except urllib.error.HTTPError as exc:
            short = (exc.reason or "http error")[:200]
            return {
                "ok": False,
                "status_code": exc.code,
                "endpoint": path_norm,
                "base_url": self.base_url,
                "error": short,
            }
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            return {
                "ok": False,
                "endpoint": path_norm,
                "base_url": self.base_url,
                "error": str(reason)[:200],
            }
        except TimeoutError:
            return {
                "ok": False,
                "endpoint": path_norm,
                "base_url": self.base_url,
                "error": "timeout",
            }
        except OSError as exc:
            return {
                "ok": False,
                "endpoint": path_norm,
                "base_url": self.base_url,
                "error": str(exc)[:200],
            }

    def health(self) -> dict[str, Any]:
        """Probe Luna health endpoints; first successful JSON response wins."""
        last_error = "no health endpoint responded"
        for path in HEALTH_PROBE_PATHS:
            result = self.request_json("GET", path)
            if result.get("ok"):
                return {
                    "ok": True,
                    "base_url": self.base_url,
                    "status": "available",
                    "endpoint": result.get("endpoint", path),
                    "details": result.get("data") if isinstance(result.get("data"), dict) else {},
                }
            err = result.get("error")
            if err:
                last_error = str(err)[:200]
        return {
            "ok": False,
            "base_url": self.base_url,
            "status": "unavailable",
            "error": last_error,
        }

    def index_pack(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST /api/v1/pym/index-pack — pack reference only, never dispatch."""
        saved_timeout = self.timeout_seconds
        self.timeout_seconds = max(saved_timeout, INDEX_PACK_TIMEOUT_SECONDS)
        try:
            result = self.request_json("POST", INDEX_PACK_PATH, payload)
        finally:
            self.timeout_seconds = saved_timeout

        if not result.get("ok"):
            return {
                "ok": False,
                "endpoint": INDEX_PACK_PATH,
                "error": str(result.get("error") or "index pack request failed")[:200],
            }

        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        pack_id = data.get("pack_id")
        manifest_path = data.get("manifest_path")
        if not pack_id and isinstance(data.get("index_pack"), dict):
            pack_id = data["index_pack"].get("pack_id")
        if not manifest_path and isinstance(data.get("index_pack"), dict):
            manifest_path = data["index_pack"].get("manifest_path")

        if not pack_id:
            return {
                "ok": False,
                "endpoint": INDEX_PACK_PATH,
                "error": "missing pack_id in response",
                "raw": data,
            }

        return {
            "ok": True,
            "endpoint": INDEX_PACK_PATH,
            "pack_id": str(pack_id),
            "manifest_path": str(manifest_path or ""),
            "raw": data,
        }

    def reuse_pack(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST /api/v1/reuse/pack — read-only ranking, never apply/promote/dispatch."""
        saved_timeout = self.timeout_seconds
        self.timeout_seconds = max(saved_timeout, REUSE_PACK_TIMEOUT_SECONDS)
        try:
            result = self.request_json("POST", REUSE_PACK_PATH, payload)
        finally:
            self.timeout_seconds = saved_timeout

        if not result.get("ok"):
            return {
                "ok": False,
                "endpoint": REUSE_PACK_PATH,
                "error": str(result.get("error") or "reuse pack request failed")[:200],
            }

        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        assets = data.get("assets")
        if not isinstance(assets, list):
            for key in ("candidates", "items", "results"):
                candidate = data.get(key)
                if isinstance(candidate, list):
                    assets = candidate
                    break
            else:
                assets = []

        return {
            "ok": True,
            "endpoint": REUSE_PACK_PATH,
            "assets": assets,
            "raw": data,
        }

    def governance_preview(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """POST preview-prune only — never apply/promote/dispatch."""
        body = dict(payload or {})
        saved_timeout = self.timeout_seconds
        self.timeout_seconds = max(saved_timeout, GOVERNANCE_PREVIEW_TIMEOUT_SECONDS)
        try:
            result = self.request_json("POST", GOVERNANCE_PREVIEW_PATH, body)
        finally:
            self.timeout_seconds = saved_timeout

        if not result.get("ok"):
            return {
                "ok": False,
                "endpoint": GOVERNANCE_PREVIEW_PATH,
                "error": str(result.get("error") or "governance preview request failed")[:200],
            }

        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        return {
            "ok": True,
            "endpoint": GOVERNANCE_PREVIEW_PATH,
            "raw": data,
        }
