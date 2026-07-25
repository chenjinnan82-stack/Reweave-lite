"""Pure canonical JSON and formal capsule payload helpers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


_CANONICAL_CAPSULE_FIELDS = frozenset(
    {
        "capability_kind",
        "activation",
        "input_contract",
        "output_contract",
        "error_contract",
        "runtime_allowlist",
        "dom_scope",
        "usage_scope",
        "html",
        "css",
        "javascript_modules",
        "assets",
    }
)
_CAPABILITY_KINDS = frozenset({"presentation", "interaction", "computation"})
_MEDIA_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})


@dataclass(frozen=True)
class CanonicalCapsule:
    payload: dict[str, Any]
    json_bytes: bytes
    sha256: str


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_json_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def canonicalize_capsule(payload: dict[str, Any]) -> CanonicalCapsule:
    if type(payload) is not dict:
        raise ValueError("canonical payload must be an object")
    missing = _CANONICAL_CAPSULE_FIELDS - payload.keys()
    extra = payload.keys() - _CANONICAL_CAPSULE_FIELDS
    if missing or extra:
        raise ValueError(
            "canonical payload fields mismatch: "
            f"missing={sorted(missing)}, extra={sorted(extra)}"
        )

    normalized = _normalize_json(payload, "$")
    if normalized["capability_kind"] not in _CAPABILITY_KINDS:
        raise ValueError("invalid capability_kind")
    for key in (
        "activation",
        "input_contract",
        "output_contract",
        "error_contract",
        "dom_scope",
        "usage_scope",
    ):
        if type(normalized[key]) is not dict:
            raise ValueError(f"{key} must be an object")
    for key in ("html", "css"):
        if type(normalized[key]) is not str:
            raise ValueError(f"{key} must be a string")
        normalized[key] = _normalize_source_text(normalized[key])

    normalized["runtime_allowlist"] = _sorted_unique_strings(
        normalized["runtime_allowlist"],
        "runtime_allowlist",
    )
    dom_scope = normalized["dom_scope"]
    for key in ("selectors", "classes", "attributes", "events"):
        dom_scope[key] = _sorted_unique_strings(
            dom_scope.get(key, []),
            f"dom_scope.{key}",
        )

    entry_module = normalized["activation"].get("entry_module")
    if entry_module is not None:
        validate_logical_path(entry_module, "activation.entry_module")

    normalized["input_contract"] = _normalize_contract(
        normalized["input_contract"]
    )
    normalized["output_contract"] = _normalize_contract(
        normalized["output_contract"]
    )
    normalized["error_contract"] = _normalize_contract(
        normalized["error_contract"]
    )
    normalized["javascript_modules"] = _normalize_modules(
        normalized["javascript_modules"]
    )
    normalized["assets"] = _normalize_assets(normalized["assets"])

    try:
        json_bytes = canonical_json_bytes(normalized)
    except (TypeError, UnicodeEncodeError, ValueError) as exc:
        raise ValueError("canonical payload is not strict UTF-8 JSON") from exc
    return CanonicalCapsule(
        payload=normalized,
        json_bytes=json_bytes,
        sha256=hashlib.sha256(json_bytes).hexdigest(),
    )


def _normalize_json(value: Any, location: str) -> Any:
    if value is None or type(value) is bool or type(value) is int:
        return value
    if type(value) is float:
        raise ValueError(f"float is forbidden at {location}")
    if type(value) is str:
        return value
    if type(value) is list:
        return [
            _normalize_json(item, f"{location}[{index}]")
            for index, item in enumerate(value)
        ]
    if type(value) is dict:
        result: dict[str, Any] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError(f"non-string key at {location}")
            if _contains_forbidden_control(key):
                raise ValueError(f"control character in key at {location}")
            normalized_key = key.replace("\r\n", "\n").replace("\r", "\n")
            if normalized_key in result:
                raise ValueError(f"normalized key collision at {location}")
            result[normalized_key] = _normalize_json(
                item,
                f"{location}.{normalized_key}",
            )
        return result
    raise ValueError(f"non-JSON value at {location}: {type(value).__name__}")


def _normalize_contract(value: Any) -> Any:
    if type(value) is list:
        return [_normalize_contract(item) for item in value]
    if type(value) is not dict:
        return value
    result = {key: _normalize_contract(item) for key, item in value.items()}
    if "required" in result:
        result["required"] = _sorted_unique_strings(
            result["required"],
            "contract.required",
        )
    if "enum" in result:
        if type(result["enum"]) is not list:
            raise ValueError("contract.enum must be an array")
        by_json: dict[str, Any] = {}
        for item in result["enum"]:
            encoded = json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            by_json[encoded] = item
        result["enum"] = [by_json[key] for key in sorted(by_json)]
    return result


def _sorted_unique_strings(value: Any, location: str) -> list[str]:
    if type(value) is not list or any(type(item) is not str for item in value):
        raise ValueError(f"{location} must be an array of strings")
    if any(_contains_forbidden_control(item) for item in value):
        raise ValueError(f"{location} contains a control character")
    return sorted(set(value))


def _contains_forbidden_control(value: str) -> bool:
    return any(
        ord(character) < 0x20 or ord(character) == 0x7F
        for character in value
    )


def _normalize_source_text(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _normalize_modules(value: Any) -> list[dict[str, str]]:
    if type(value) is not list:
        raise ValueError("javascript_modules must be an array")
    modules: list[dict[str, str]] = []
    paths: set[str] = set()
    for item in value:
        if type(item) is not dict or set(item) != {"path", "source"}:
            raise ValueError(
                "each JavaScript module must contain only path and source"
            )
        path = item["path"]
        source = item["source"]
        validate_logical_path(path, "javascript_modules.path")
        if type(source) is not str:
            raise ValueError("javascript_modules.source must be a string")
        if path in paths:
            raise ValueError(f"duplicate JavaScript module path: {path}")
        paths.add(path)
        modules.append(
            {"path": path, "source": _normalize_source_text(source)}
        )
    return sorted(modules, key=lambda item: item["path"])


def _normalize_assets(value: Any) -> list[dict[str, str]]:
    if type(value) is not list:
        raise ValueError("assets must be an array")
    assets: list[dict[str, str]] = []
    paths: set[str] = set()
    for item in value:
        if type(item) is not dict or set(item) != {
            "logical_path",
            "media_type",
            "sha256",
        }:
            raise ValueError(
                "each asset must contain logical_path, media_type, and sha256"
            )
        logical_path = item["logical_path"]
        media_type = item["media_type"]
        digest = item["sha256"]
        validate_logical_path(logical_path, "assets.logical_path")
        if media_type not in _MEDIA_TYPES:
            raise ValueError(f"invalid asset media_type: {media_type}")
        if (
            type(digest) is not str
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise ValueError(
                "asset sha256 must be 64 lowercase hexadecimal characters"
            )
        if logical_path in paths:
            raise ValueError(f"duplicate asset path: {logical_path}")
        paths.add(logical_path)
        assets.append(
            {
                "logical_path": logical_path,
                "media_type": media_type,
                "sha256": digest,
            }
        )
    return sorted(
        assets,
        key=lambda item: (
            item["logical_path"],
            item["media_type"],
            item["sha256"],
        ),
    )


def validate_logical_path(value: Any, location: str) -> None:
    if (
        type(value) is not str
        or not value
        or _contains_forbidden_control(value)
        or "\\" in value
        or value.startswith("/")
    ):
        raise ValueError(f"invalid logical path at {location}")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError(f"invalid logical path at {location}")


__all__ = [
    "CanonicalCapsule",
    "canonical_json_bytes",
    "canonical_json_digest",
    "canonicalize_capsule",
    "validate_logical_path",
]
