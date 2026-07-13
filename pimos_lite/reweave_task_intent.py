"""Task intent helpers for Reweave preview packs."""

from __future__ import annotations

import re
from typing import Any

from pimos_lite.reweave_project_graph import MAX_RUNTIME_FILES

MAX_TASK_LEN = 240

CAPABILITY_KEYWORDS = {
    "form": ("form", "quote", "input", "submit", "customer", "field", "表单", "报价", "输入", "提交", "客户"),
    "table": ("table", "list", "queue", "record", "calendar", "row", "表格", "列表", "队列", "记录", "日历"),
    "copy": ("copy", "landing", "content", "message", "hero", "story", "文案", "落地页", "内容", "消息"),
    "style": ("style", "css", "brand", "visual", "layout", "design", "样式", "品牌", "视觉", "布局", "设计"),
    "logic": ("logic", "workflow", "action", "filter", "calculate", "triage", "interaction", "逻辑", "流程", "操作", "筛选", "计算", "分流", "交互"),
    "data": ("data", "dashboard", "metric", "status", "chart", "viewer", "panel", "数据", "仪表盘", "指标", "状态", "图表", "查看器", "面板"),
}
SOURCE_DOMAIN_KEYWORDS = {
    "quote": ("quote", "estimate", "estimator", "budget", "price", "cost", "customer", "client", "homeowner", "报价", "估价", "预算", "价格", "成本", "客户", "业主"),
    "calendar": ("calendar", "schedule", "editorial", "publish", "content", "日历", "排期", "编辑", "发布", "内容"),
    "support": ("support", "ticket", "triage", "queue", "resolve", "service", "客服", "工单", "分流", "队列", "处理"),
}
STOP_WORDS = {"a", "an", "and", "as", "build", "from", "for", "into", "old", "project", "the", "this", "to", "with"}


def capsule_match_text(cap: dict[str, Any]) -> str:
    parts = [
        cap.get("id"),
        cap.get("name"),
        cap.get("type"),
        cap.get("role"),
        cap.get("source"),
        cap.get("source_label"),
        cap.get("_behavior_text"),
        " ".join(str(tag) for tag in (cap.get("tags") or []) if tag),
    ]
    return " ".join(str(part or "") for part in parts).lower()


def behavior_contract_search_text(contract: dict[str, Any]) -> str:
    files = contract.get("files") if isinstance(contract.get("files"), dict) else {}
    entry = files.get("entry") if isinstance(files.get("entry"), dict) else {}
    interactions = contract.get("interactions") if isinstance(contract.get("interactions"), dict) else {}
    controls = interactions.get("controls") if isinstance(interactions.get("controls"), list) else []
    parts = [contract.get("entry_path"), entry.get("content")]
    parts.extend(
        " ".join(str(control.get(key) or "") for key in ("id", "name", "text"))
        for control in controls
        if isinstance(control, dict)
    )
    return " ".join(str(part or "") for part in parts).strip()[:12000]


def task_terms(task: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", task.lower()) if len(word) > 2 and word not in STOP_WORDS}


def task_capabilities(task: str) -> list[str]:
    text = task.lower()
    return [
        name
        for name, words in CAPABILITY_KEYWORDS.items()
        if any(word in text for word in words)
    ]


def score_capsule_for_task(task: str, cap: dict[str, Any], *, enrichable: bool = False) -> int:
    # ponytail: metadata scoring; add embeddings only after real tasks beat this.
    text = capsule_match_text(cap)
    score = 2 if enrichable else 0
    score += sum(3 for term in task_terms(task) if term in text)
    for capability in task_capabilities(task):
        words = CAPABILITY_KEYWORDS[capability]
        if capability in text:
            score += 6
        score += sum(2 for word in words if word in text)
    return score


def source_domain_score(task: str, cap: dict[str, Any]) -> int:
    task_text = task.lower()
    source_text = " ".join(str(cap.get(key) or "").lower() for key in ("source", "source_label"))
    return 30 if any(
        any(word in task_text for word in words) and any(word in source_text for word in words)
        for words in SOURCE_DOMAIN_KEYWORDS.values()
    ) else 0


def source_label_score(task: str, cap: dict[str, Any]) -> int:
    source_terms = re.findall(r"[a-z0-9]+", str(cap.get("source") or cap.get("source_label") or "").lower())
    return 12 * sum(
        1
        for task_term in task_terms(task)
        for source_term in source_terms
        if len(source_term) >= 3
        and (task_term == source_term or task_term.startswith(source_term) or source_term.startswith(task_term))
    )


def select_capsules_for_task(
    task: str,
    capsules: list[dict[str, Any]],
    *,
    limit: int = 3,
) -> list[dict[str, Any]]:
    ranked: list[tuple[int, int, str, dict[str, Any]]] = []
    for position, cap in enumerate(capsules):
        if not isinstance(cap, dict):
            continue
        enrichment = cap.get("content_enrichment")
        score = score_capsule_for_task(
            task,
            cap,
            enrichable=False,
        )
        score += source_domain_score(task, cap)
        score += source_label_score(task, cap)
        if score <= 0:
            continue
        if isinstance(enrichment, dict) and enrichment.get("status") == "enriched":
            score += 2
        if cap.get("_closed_behavior") is True:
            score += 1
        source_id = str(cap.get("source_id") or cap.get("source") or "")
        ranked.append((score, -position, source_id, cap))
    if not ranked:
        return []
    source_scores: dict[str, float] = {}
    for source_id in {item[2] for item in ranked}:
        scores = sorted((item[0] for item in ranked if item[2] == source_id), reverse=True)
        top_scores = scores[: max(1, limit)]
        source_scores[source_id] = sum(top_scores) / len(top_scores)
    primary_source = max(source_scores, key=source_scores.get)
    primary = [item for item in ranked if item[2] == primary_source]
    primary.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [dict(item[3]) for item in primary[: max(1, limit)]]


def ensure_complete_project_capsule(
    selected: list[dict[str, Any]],
    capsules: list[dict[str, Any]],
    complete_capsule_ids: set[str],
) -> list[dict[str, Any]]:
    """Keep the complete project capsule for the selected source in the bounded result."""
    if not selected:
        return []
    source_id = str(selected[0].get("source_id") or selected[0].get("source") or "")
    required = next(
        (
            cap
            for cap in capsules
            if str(cap.get("id") or "") in complete_capsule_ids
            and str(cap.get("source_id") or cap.get("source") or "") == source_id
        ),
        None,
    )
    if required is None or any(item.get("id") == required.get("id") for item in selected):
        return selected
    return [dict(required), *[item for item in selected if item.get("id") != required.get("id")]][: len(selected)]


def capsule_reason(cap: dict[str, Any], capabilities: list[str]) -> str:
    text = capsule_match_text(cap)
    matched = [capability for capability in capabilities if capability in text]
    if matched:
        return "matches " + ", ".join(matched[:3]) + " need"
    return str(cap.get("role") or "selected for source-backed task context")


def _project_context(project_graph: dict[str, Any] | None) -> dict[str, Any] | None:
    if not project_graph or project_graph.get("project_kind") != "react_vite":
        return None
    nodes = [item for item in project_graph.get("nodes", []) if isinstance(item, dict)]
    nodes_by_path = {str(item.get("path") or ""): item for item in nodes}
    runtime_files = [str(path) for path in project_graph.get("runtime_files", []) if path]
    ordered = [nodes_by_path[path] for path in runtime_files if path in nodes_by_path]
    if not ordered:
        for kind in ("entry", "component", "style", "module"):
            ordered.extend(item for item in nodes if item.get("kind") == kind)
    candidate_files = []
    seen: set[str] = set()
    for node in ordered:
        path = str(node.get("path") or "")
        if not path or path in seen:
            continue
        seen.add(path)
        candidate_files.append(
            {
                "path": path,
                "kind": str(node.get("kind") or "module"),
                "write_mode": "preview_only",
            }
        )
        if len(candidate_files) == MAX_RUNTIME_FILES:
            break
    return {
        "project_kind": "react_vite",
        "graph_status": project_graph.get("status"),
        "entrypoints": list(project_graph.get("entrypoints") or []),
        "runtime_file_count": len(runtime_files),
        "runtime_closure_bounded": len(runtime_files) <= MAX_RUNTIME_FILES,
        "candidate_files": candidate_files,
        "source_project_write": False,
    }


def build_task_intent(
    task: str,
    capsules: list[dict[str, Any]],
    *,
    project_graph: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # ponytail: keyword intent is enough for v0; replace with parser only when real tasks beat it.
    task_text = (task or "").lower()
    text = " ".join(
        [task or ""]
        + [capsule_match_text(cap) for cap in capsules if isinstance(cap, dict)]
    ).lower()
    capabilities = [
        name
        for name, words in CAPABILITY_KEYWORDS.items()
        if any(word in text for word in words)
    ] or ["copy", "style"]
    if any(word in task_text for word in ("component", "react", "tsx", "widget")):
        output_type = "component"
    elif any(word in task_text for word in ("doc", "document", "report", "readme")):
        output_type = "document"
    elif any(word in task_text for word in ("dashboard", "panel", "viewer", "table", "calendar", "data")):
        output_type = "data_panel"
    elif any(word in task_text for word in ("tool", "form", "quote", "interaction")):
        output_type = "tool"
    else:
        output_type = "page"
    intent = {
        "schema_version": "reweave_task_intent.v1",
        "task": (task or "Build a small project pack")[:MAX_TASK_LEN],
        "goal": (task or "Build a small project pack")[:MAX_TASK_LEN],
        "output_type": output_type,
        "needed_files": ["index.html", "styles.css", "app.js"],
        "capabilities": capabilities,
        "retrieved_capsules": [
            {
                "id": cap.get("id"),
                "name": cap.get("name"),
                "source_id": cap.get("source_id"),
                "reason": capsule_reason(cap, capabilities),
            }
            for cap in capsules
            if isinstance(cap, dict)
        ],
        "source_project_write": False,
    }
    context = _project_context(project_graph)
    if context:
        intent["project_context"] = context
    return intent


def build_task_profile(
    task: str,
    capsules: list[dict[str, Any]] | None = None,
    *,
    task_intent: dict[str, Any] | None = None,
) -> dict[str, object]:
    intent = task_intent or build_task_intent(task, capsules or [])
    output_type = str(intent["output_type"])
    capabilities = [str(item) for item in intent["capabilities"]]
    return {
        "id": "task_driven",
        "label": "Task Intent",
        "output_label": output_type.replace("_", " ").title(),
        "action": "Review output",
        "summary": "A runnable small project pack assembled from the task, selected capsules, and source excerpts.",
        "steps": [
            "Check task goal",
            "Review " + ", ".join(capabilities[:3]) + " output",
            "Try the main action",
            "Check page copy and layout",
            "Confirm original project stays unchanged",
        ],
        "output_kinds": (f"{output_type}_html", "task_style", "task_runtime"),
    }
