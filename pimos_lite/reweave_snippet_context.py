"""Reweave snippet context for content-aware generate — app state only."""

from __future__ import annotations

from typing import Any

from pimos_lite.reweave_capsule_content import content_rel_path, load_capsule_content
from pimos_lite.reweave_capsule_warehouse import get_capsule, is_generate_eligible
from pimos_lite.reweave_task_intent import score_capsule_for_task

MAX_CAPSULES = 3
MAX_SNIPPETS_PER_CAPSULE = 2
MAX_CHARS_PER_SNIPPET = 1200
MAX_TOTAL_CHARS = 6000

CONTEXT_LIMITS = {
    "max_capsules": MAX_CAPSULES,
    "max_snippets_per_capsule": MAX_SNIPPETS_PER_CAPSULE,
    "max_chars_per_snippet": MAX_CHARS_PER_SNIPPET,
    "max_total_chars": MAX_TOTAL_CHARS,
}


def _is_enriched(cap: dict[str, Any]) -> bool:
    enrichment = cap.get("content_enrichment") if isinstance(cap.get("content_enrichment"), dict) else None
    return bool(enrichment and str(enrichment.get("status") or "") == "enriched")


def _truncate_excerpt(text: str, max_snippet: int, remaining_total: int) -> tuple[str, bool]:
    limit = min(max_snippet, max(0, remaining_total))
    if limit <= 0:
        return "", True
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def build_snippet_context(capsule_ids: list[str], *, task: str = "") -> dict[str, Any]:
    """Build bounded snippet context from capsule_contents app state only."""
    warnings: list[str] = []
    capsules_out: list[dict[str, Any]] = []
    total_chars = 0
    seen_capsules = 0

    for cap_id in capsule_ids:
        if seen_capsules >= MAX_CAPSULES:
            warnings.append("max_capsules_reached")
            break

        cap = get_capsule(cap_id)
        if not cap:
            warnings.append(f"capsule_not_found:{cap_id}")
            continue
        if not is_generate_eligible(cap):
            warnings.append(f"skipped_inactive:{cap_id}")
            continue
        if not _is_enriched(cap):
            warnings.append(f"not_enriched:{cap_id}")
            continue

        record = load_capsule_content(cap_id)
        if not record:
            warnings.append(f"content_missing:{cap_id}")
            continue
        raw_snippets = record.get("snippets") if isinstance(record.get("snippets"), list) else []
        snippet_entries: list[dict[str, Any]] = []

        for snip in raw_snippets[:MAX_SNIPPETS_PER_CAPSULE]:
            if total_chars >= MAX_TOTAL_CHARS:
                warnings.append("max_total_chars_reached")
                break
            if not isinstance(snip, dict):
                continue
            preview = str(snip.get("preview") or "")
            remaining = MAX_TOTAL_CHARS - total_chars
            excerpt, truncated = _truncate_excerpt(preview, MAX_CHARS_PER_SNIPPET, remaining)
            if not excerpt:
                if remaining <= 0:
                    warnings.append("max_total_chars_reached")
                continue
            total_chars += len(excerpt)
            file_truncated = bool(snip.get("truncated")) or truncated
            snippet_entries.append(
                {
                    "relative_path": snip.get("relative_path"),
                    "language_hint": snip.get("language_hint"),
                    "preview_excerpt": excerpt,
                    "excerpt_chars": len(excerpt),
                    "truncated": file_truncated,
                    "redacted": bool(snip.get("redacted")),
                }
            )

        if not snippet_entries:
            warnings.append(f"no_snippets_for:{cap_id}")
            continue

        enrichment = cap.get("content_enrichment") if isinstance(cap.get("content_enrichment"), dict) else {}
        capsules_out.append(
            {
                "capsule_id": cap_id,
                "name": cap.get("name"),
                "content_path": str(enrichment.get("content_path") or content_rel_path(cap_id)),
                "snippets": snippet_entries,
            }
        )
        seen_capsules += 1

    behavior_candidates: list[tuple[int, int, str, dict[str, Any]]] = []
    for position, cap_id in enumerate(capsule_ids):
        cap = get_capsule(cap_id)
        record = load_capsule_content(cap_id)
        candidate = record.get("behavior_contract") if isinstance(record, dict) else None
        if not cap or not is_generate_eligible(cap) or not isinstance(candidate, dict):
            continue
        if candidate.get("status") != "closed":
            continue
        behavior_candidates.append(
            (score_capsule_for_task(task, cap, enrichable=True), -position, cap_id, candidate)
        )
    behavior_contract = None
    if behavior_candidates:
        score, _position, cap_id, candidate = max(behavior_candidates, key=lambda item: (item[0], item[1]))
        behavior_contract = dict(candidate)
        behavior_contract["selection"] = {
            "capsule_id": cap_id,
            "score": score,
            "reason": "highest task metadata match among closed behavior modules",
        }

    return {
        "mode": "content_aware_preview",
        "capsules": capsules_out,
        "behavior_contract": behavior_contract,
        "limits": dict(CONTEXT_LIMITS),
        "warnings": warnings,
    }


def build_snippets_used_manifest(context: dict[str, Any]) -> dict[str, Any]:
    """Manifest for snippets_used.json — metadata only, no full excerpt text."""
    snippets: list[dict[str, Any]] = []
    for cap in context.get("capsules") if isinstance(context.get("capsules"), list) else []:
        if not isinstance(cap, dict):
            continue
        cap_id = str(cap.get("capsule_id") or "")
        for snip in cap.get("snippets") if isinstance(cap.get("snippets"), list) else []:
            if not isinstance(snip, dict):
                continue
            snippets.append(
                {
                    "capsule_id": cap_id,
                    "relative_path": snip.get("relative_path"),
                    "language_hint": snip.get("language_hint"),
                    "excerpt_chars": snip.get("excerpt_chars"),
                    "truncated": snip.get("truncated"),
                    "redacted": snip.get("redacted"),
                }
            )
    return {
        "schema_version": 1,
        "mode": "content_aware_preview",
        "source": "enriched_capsule_content",
        "snippets": snippets,
        "safety": {
            "source_folder_read_at_generate_time": False,
            "used_app_state_content_only": True,
            "llm_called": False,
            "dispatch_called": False,
        },
    }


def count_snippets(context: dict[str, Any]) -> int:
    total = 0
    for cap in context.get("capsules") if isinstance(context.get("capsules"), list) else []:
        if isinstance(cap, dict):
            total += len(cap.get("snippets") or [])
    return total
