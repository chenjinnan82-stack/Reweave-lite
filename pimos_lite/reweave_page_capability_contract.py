"""Pure deterministic Page Capability Contract v2.

This module only compares declared presentation capabilities with declared
interaction requirements. Stage3 is responsible for proving declarations
against sanitized HTML before this contract is integrated into formal flows.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


PAGE_CAPABILITY_CONTRACT_VERSION = "page_capability_contract.v2"
PAGE_CAPABILITY_DECLARATION_VERSION = "page_capability_declaration.v2"
FORMAL_CAPSULE_IDENTITY_VERSION = "formal_capsule_identity.v2"

_MAX_ELEMENTS = 64
_SELECTOR = re.compile(
    r"""\[(data-action|data-ref)=(['"])([A-Za-z_][A-Za-z0-9_-]{0,63})\2\]\Z"""
)
_TAG = re.compile(r"[a-z][a-z0-9-]{0,31}\Z")
_READS = frozenset(
    {"checked", "disabled", "hidden", "selectedIndex", "textContent", "value"}
)
_WRITES = _READS
_EVENTS = frozenset({"change", "click", "input", "reset", "select", "submit"})
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def build_page_capability_contract_v2(
    *,
    presentation_provides: list[dict[str, Any]],
    interaction_requires: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return a canonical contract when every interaction need is provided."""
    provided = _normalize_elements(presentation_provides)
    required = _normalize_elements(interaction_requires)
    by_selector = {row["selector"]: row for row in provided}

    for need in required:
        offer = by_selector.get(need["selector"])
        if offer is None:
            raise ValueError("page_capability_element_missing")
        if offer["tag"] != need["tag"]:
            raise ValueError("page_capability_element_mismatch")
        if not set(need["events"]).issubset(offer["events"]):
            raise ValueError("page_capability_event_missing")
        if not set(need["reads"]).issubset(offer["reads"]):
            raise ValueError("page_capability_read_missing")
        if not set(need["writes"]).issubset(offer["writes"]):
            raise ValueError("page_capability_write_missing")

    body = {
        "schema_version": PAGE_CAPABILITY_CONTRACT_VERSION,
        "presentation": {"provides": provided},
        "interaction": {"requires": required},
    }
    return {**body, "canonical_digest": _canonical_digest(body)}


def build_page_capability_declaration_v2(
    *,
    capability_kind: str,
    elements: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return one canonical Stage3 provider or consumer declaration."""
    if capability_kind not in {"presentation", "interaction"}:
        raise ValueError("page_capability_kind_invalid")
    field = "provides" if capability_kind == "presentation" else "requires"
    body = {
        "schema_version": PAGE_CAPABILITY_DECLARATION_VERSION,
        "capability_kind": capability_kind,
        field: _normalize_elements(elements),
    }
    return {**body, "canonical_digest": _canonical_digest(body)}


def normalize_page_capability_declaration_v2(value: Any) -> dict[str, Any]:
    """Validate and return one canonical persisted declaration."""
    if type(value) is not dict:
        raise ValueError("page_capability_declaration_invalid")
    capability_kind = value.get("capability_kind")
    field = (
        "provides"
        if capability_kind == "presentation"
        else "requires"
        if capability_kind == "interaction"
        else None
    )
    if (
        field is None
        or set(value)
        != {"schema_version", "capability_kind", field, "canonical_digest"}
        or value.get("schema_version") != PAGE_CAPABILITY_DECLARATION_VERSION
    ):
        raise ValueError("page_capability_declaration_invalid")
    expected = build_page_capability_declaration_v2(
        capability_kind=capability_kind,
        elements=value[field],
    )
    if value != expected:
        raise ValueError("page_capability_declaration_invalid")
    return expected


def build_formal_identity_binding_v2(
    *,
    canonical_payload_digest: str,
    page_capability_declaration: dict[str, Any],
) -> dict[str, str]:
    """Bind one canonical payload to one canonical page declaration."""
    if (
        type(canonical_payload_digest) is not str
        or _DIGEST.fullmatch(canonical_payload_digest) is None
    ):
        raise ValueError("formal_capsule_identity_invalid")
    declaration = normalize_page_capability_declaration_v2(
        page_capability_declaration
    )
    body = {
        "schema_version": FORMAL_CAPSULE_IDENTITY_VERSION,
        "canonical_payload_digest": canonical_payload_digest,
        "page_capability_declaration_digest": declaration["canonical_digest"],
    }
    return {**body, "formal_identity_digest": _canonical_digest(body)}


def verify_formal_capsule_identity(
    *,
    capability_kind: str,
    canonical_payload_digest: str,
    stored_canonical_hash: str,
    extraction_summary: dict[str, Any],
) -> dict[str, str] | None:
    """Verify the v1 payload identity or v2 page-capability identity matrix."""
    if (
        capability_kind not in {"presentation", "interaction", "computation"}
        or type(canonical_payload_digest) is not str
        or _DIGEST.fullmatch(canonical_payload_digest) is None
        or type(stored_canonical_hash) is not str
        or _DIGEST.fullmatch(stored_canonical_hash) is None
        or type(extraction_summary) is not dict
    ):
        raise ValueError("formal_capsule_identity_invalid")
    has_declaration = "page_capability_declaration" in extraction_summary
    has_binding = "formal_identity_binding" in extraction_summary
    if not has_declaration and not has_binding:
        if stored_canonical_hash != canonical_payload_digest:
            raise ValueError("formal_capsule_identity_invalid")
        return None
    if not has_declaration or not has_binding or capability_kind == "computation":
        raise ValueError("formal_capsule_identity_invalid")
    declaration = extraction_summary["page_capability_declaration"]
    binding = extraction_summary["formal_identity_binding"]
    if type(binding) is not dict or binding.get("schema_version") != (
        FORMAL_CAPSULE_IDENTITY_VERSION
    ):
        raise ValueError("formal_capsule_identity_invalid")
    normalized_declaration = normalize_page_capability_declaration_v2(declaration)
    if normalized_declaration["capability_kind"] != capability_kind:
        raise ValueError("formal_capsule_identity_invalid")
    expected = build_formal_identity_binding_v2(
        canonical_payload_digest=canonical_payload_digest,
        page_capability_declaration=normalized_declaration,
    )
    if binding != expected or stored_canonical_hash != expected["formal_identity_digest"]:
        raise ValueError("formal_capsule_identity_invalid")
    return expected


def normalize_page_capability_selector(value: Any) -> str:
    if type(value) is not str:
        raise ValueError("page_capability_selector_invalid")
    match = _SELECTOR.fullmatch(value)
    if match is None:
        raise ValueError("page_capability_selector_invalid")
    return f"[{match.group(1)}='{match.group(3)}']"


def _normalize_elements(value: Any) -> list[dict[str, Any]]:
    if type(value) is not list or not 1 <= len(value) <= _MAX_ELEMENTS:
        raise ValueError("page_capability_elements_invalid")
    result: list[dict[str, Any]] = []
    selectors: set[str] = set()
    for item in value:
        if type(item) is not dict or set(item) != {
            "selector",
            "tag",
            "reads",
            "writes",
            "events",
        }:
            raise ValueError("page_capability_element_invalid")
        selector = normalize_page_capability_selector(item["selector"])
        tag = item["tag"]
        if selector in selectors:
            raise ValueError("page_capability_element_duplicate")
        if type(tag) is not str or _TAG.fullmatch(tag) is None:
            raise ValueError("page_capability_tag_invalid")
        selectors.add(selector)
        result.append(
            {
                "selector": selector,
                "tag": tag,
                "reads": _normalize_capabilities(item["reads"], _READS),
                "writes": _normalize_capabilities(item["writes"], _WRITES),
                "events": _normalize_capabilities(item["events"], _EVENTS),
            }
        )
    return sorted(result, key=lambda row: row["selector"])


def _normalize_capabilities(value: Any, allowed: frozenset[str]) -> list[str]:
    if (
        type(value) is not list
        or any(type(item) is not str for item in value)
        or value != sorted(set(value))
        or not set(value).issubset(allowed)
    ):
        raise ValueError("page_capability_operations_invalid")
    return list(value)


def _canonical_digest(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "FORMAL_CAPSULE_IDENTITY_VERSION",
    "PAGE_CAPABILITY_CONTRACT_VERSION",
    "PAGE_CAPABILITY_DECLARATION_VERSION",
    "build_formal_identity_binding_v2",
    "build_page_capability_declaration_v2",
    "build_page_capability_contract_v2",
    "normalize_page_capability_declaration_v2",
    "normalize_page_capability_selector",
    "verify_formal_capsule_identity",
]
