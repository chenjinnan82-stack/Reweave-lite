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
    "PAGE_CAPABILITY_CONTRACT_VERSION",
    "PAGE_CAPABILITY_DECLARATION_VERSION",
    "build_page_capability_declaration_v2",
    "build_page_capability_contract_v2",
    "normalize_page_capability_selector",
]
