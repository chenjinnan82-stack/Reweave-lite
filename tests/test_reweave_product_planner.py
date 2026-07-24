from __future__ import annotations

import copy
import json
import os
import shutil
from pathlib import Path

import pytest

import pimos_lite.reweave_product_planner as product_planner_module
from pimos_lite.reweave_plan_execution import (
    build_candidate_acceptance_confirmation,
)
from pimos_lite.reweave_product_planner import (
    FORMAL_MODEL_TIMEOUT_SECONDS,
    HTTP_TIMEOUT_SECONDS,
    MAX_MODEL_PARAMETERS,
    ProductPlanner,
    ProductPlanningError,
    SECTION_IDS,
)


SMALL_DIGEST = "a" * 64
LARGE_DIGEST = "b" * 64


class StubPlanner(ProductPlanner):
    def __init__(
        self,
        root: Path,
        *,
        counts: dict[str, int | None] | None = None,
        model_infos: dict[str, dict[str, object]] | None = None,
    ) -> None:
        super().__init__(root)
        self.counts = counts or {
            "small:1.5b": 1_543_714_304,
            "large:7b": 7_615_616_512,
        }
        self.digests = {
            "small:1.5b": SMALL_DIGEST,
            "large:7b": LARGE_DIGEST,
        }
        self.model_infos = model_infos or {}
        self.generation_outputs: list[dict[str, object]] = []
        self.requests: list[tuple[str, object]] = []
        self.request_timeouts: list[tuple[str, int]] = []

    def _request(
        self,
        path,
        payload=None,
        cancel_check=None,
        timeout_seconds=None,
    ):
        if timeout_seconds is None:
            timeout_seconds = HTTP_TIMEOUT_SECONDS
        self.requests.append((path, copy.deepcopy(payload)))
        self.request_timeouts.append((path, timeout_seconds))
        evidence = {"input_bytes": 100, "output_bytes": 100, "duration_ms": 1}
        if path == "/api/tags":
            return {
                "models": [
                    {"name": name, "digest": self.digests[name]}
                    for name in sorted(self.counts)
                ]
            }, evidence
        if path == "/api/show":
            name = payload["model"]
            count = self.counts[name]
            info = dict(self.model_infos.get(name, {}))
            if count is not None:
                info["general.parameter_count"] = count
            return {
                "model_info": info,
                "details": {"parameter_size": name.split(":")[-1]},
            }, evidence
        if path == "/api/generate":
            if not self.generation_outputs:
                raise AssertionError("unexpected model generation")
            output = self.generation_outputs.pop(0)
            return {"response": json.dumps(output, ensure_ascii=False)}, evidence
        raise AssertionError(path)


def probe() -> dict[str, str]:
    return {
        "schema_version": "product_plan_probe.v1",
        "status": "ready",
        "role": "product_planner",
    }


def outline(*, clarification: bool = False) -> dict[str, object]:
    questions: list[dict[str, object]] = []
    if clarification:
        questions = [
            {
                "ref": "tenant_isolation",
                "prompt": "租户隔离应采用哪种策略？",
                "options": [
                    {
                        "ref": "row_level",
                        "label": "行级隔离",
                        "impact": "共享数据库并显式约束租户键。",
                        "recommended": True,
                        "forms_gap": False,
                    },
                    {
                        "ref": "database_per_tenant",
                        "label": "每租户数据库",
                        "impact": "隔离更强，但会形成当前运维能力缺口。",
                        "recommended": False,
                        "forms_gap": True,
                    },
                ],
                "allow_custom": True,
            }
        ]
    return {
        "schema_version": "product_plan_outline.v1",
        "product_name": "中小企业多租户中台",
        "language": "zh",
        "requirements": [
            {"ref": "r_frontend", "statement": "提供可访问的管理工作台", "source": "goal"},
            {"ref": "r_backend", "statement": "提供租户与权限服务", "source": "goal"},
            {"ref": "r_data", "statement": "使用 PostgreSQL 保存审计事实", "source": "goal"},
            {"ref": "r_infra", "statement": "支持备份和私有部署", "source": "goal"},
        ],
        "needs_clarification": clarification,
        "questions": questions,
    }


def section(section_id: str, candidate_ref: str = "") -> dict[str, object]:
    requirement = {
        "frontend": "r_frontend",
        "backend": "r_backend",
        "data": "r_data",
        "infrastructure": "r_infra",
    }[section_id]
    return {
        "schema_version": "product_plan_section_draft.v2",
        "section_id": section_id,
        "summary": f"{section_id} 交付与验证意图",
        "work_items": [
            {
                "title": f"{section_id} 能力一",
                "summary": "实现可审阅的能力边界。",
                "requirement_refs": [requirement],
                "delivery_wave": 1,
                "acceptance_intent": "以结构化行为证据验收。",
                "candidate_ref": candidate_ref,
                "gap_reason": "" if candidate_ref else "当前没有合格的正式胶囊。",
            },
            {
                "title": f"{section_id} 能力二",
                "summary": "补齐下游能力与约束。",
                "requirement_refs": [requirement],
                "delivery_wave": 2,
                "acceptance_intent": "依赖满足后可独立验收。",
                "candidate_ref": "",
                "gap_reason": "当前没有合格的正式胶囊。",
            },
            {
                "title": f"{section_id} 能力三",
                "summary": "定义失败关闭和恢复行为。",
                "requirement_refs": [requirement],
                "delivery_wave": 3,
                "acceptance_intent": "失败路径可证伪。",
                "candidate_ref": "",
                "gap_reason": "当前没有合格的正式胶囊。",
            },
        ],
    }


def catalog(*, with_capsule: bool = True) -> dict[str, object]:
    capsules = []
    if with_capsule:
        capsules.append(
            {
                "capsule_id": "capsule_formal",
                "version_id": "version_exact",
                "display_name": "正式工作台胶囊",
                "capability_key": "workspace_ui",
                "role_key": "primary",
                "variant_key": "default",
                "capability_kind": "presentation",
                "canonical_hash": "c" * 64,
                "identity_status": "formal_exact_version",
            }
        )
    return {"warehouse_revision": 7, "capsules": capsules}


def select_small(planner: StubPlanner) -> None:
    planner.generation_outputs.append(probe())
    selected = planner.select_model("small:1.5b", SMALL_DIGEST)
    assert selected["ok"] is True


def queue_plan(planner: StubPlanner, *, with_capsule: bool = True) -> None:
    planner.generation_outputs.append(outline())
    original = planner._generate_json

    def generated(model, call_type, request_value, cancel_check=None):
        if call_type.startswith("section_"):
            candidate_ref = (
                request_value["candidate_catalog"][0]["candidate_ref"]
                if with_capsule and request_value["candidate_catalog"]
                else ""
            )
            planner.generation_outputs.insert(
                0,
                section(request_value["section_id"], candidate_ref),
            )
        return original(model, call_type, request_value, cancel_check)

    planner._generate_json = generated  # type: ignore[method-assign]


def queue_revision_update(
    planner: StubPlanner,
    *,
    title: str,
    summary: str,
    acceptance_intent: str,
    delivery_wave: int = 1,
    target_section_id: str = "frontend",
) -> None:
    original = planner._generate_json

    def generated(model, call_type, request_value, cancel_check=None):
        if call_type == "plan_revision_proposal":
            planner._generate_json = original  # type: ignore[method-assign]
            target_section = next(
                section
                for section in request_value["current_plan"]["sections"]
                if section["section_id"] == target_section_id
            )
            item = target_section["work_items"][0]
            planner.generation_outputs.insert(
                0,
                {
                    "operations": [
                        {
                            "op": "update",
                            "binding_ref": item["binding_ref"],
                            "title": title,
                            "summary": summary,
                            "acceptance_intent": acceptance_intent,
                            "delivery_wave": delivery_wave,
                        }
                    ],
                },
            )
        return original(model, call_type, request_value, cancel_check)

    planner._generate_json = generated  # type: ignore[method-assign]


def revision_request(
    planner: StubPlanner,
    token: str,
    plan: dict[str, object],
    message: str,
    *,
    selected_action: str,
    suggested_action: str | None = None,
    target_section_id: str = "frontend",
) -> dict[str, object]:
    original = planner._generate_json

    def generated(model, call_type, request_value, cancel_check=None):
        if call_type == "plan_action_suggestion":
            planner._generate_json = original  # type: ignore[method-assign]
            planner.generation_outputs.insert(
                0,
                {"suggested_action": suggested_action or selected_action},
            )
        return original(model, call_type, request_value, cancel_check)

    planner._generate_json = generated  # type: ignore[method-assign]
    suggestion = planner.suggest_action(token, message)
    assert suggestion["ok"] is True
    suggestion_data = suggestion["data"]
    result: dict[str, object] = {
        "action": "request",
        "message": message,
        "reviewed_plan": plan,
        "selected_action": selected_action,
        "suggestion_receipt": suggestion_data["suggestion_receipt"],
        "suggestion_digest": suggestion_data["suggestion_digest"],
    }
    if selected_action == "propose_revision":
        result["target_section_id"] = target_section_id
    return result


def seed_revision_question_set(
    planner: StubPlanner,
    token: str,
    *,
    target_section_id: str = "frontend",
    feedback: str = "按用户已经确认的动作继续修订",
) -> dict[str, object]:
    workspace = planner._workspace_by_token(token)
    questions = planner._validate_questions(outline(clarification=True)["questions"])
    question_set = planner._question_set(
        questions,
        purpose="revision",
        target_section_id=target_section_id,
    )
    workspace["question_history"].append(question_set["digest"])
    workspace["current_question_set"] = question_set
    workspace["pending_revision_feedback"] = feedback
    workspace["status"] = "needs_clarification"
    workspace["phase"] = "revision"
    with planner._lock:
        planner._save_workspace(workspace)
    return copy.deepcopy(question_set)


def test_action_suggestion_and_explicit_revision_schemas_are_strict() -> None:
    assert (
        product_planner_module.REVISION_PROMPT_VERSIONS[
            "plan_revision_proposal"
        ]
        == "product_plan_revision_proposal_prompt.v2"
    )
    assert (
        product_planner_module.REVISION_SCHEMA_VERSIONS[
            "plan_revision_proposal"
        ]
        == "product_plan_revision_proposal.v3"
    )
    suggestion = product_planner_module._structured_output_schema(
        "plan_action_suggestion", {}
    )
    assert suggestion["properties"]["suggested_action"]["enum"] == [
        "ask_plan",
        "propose_revision",
        "edit_goal",
    ]
    assert suggestion["additionalProperties"] is False

    fields = product_planner_module._structured_output_schema(
        "plan_revision_fields", {}
    )
    assert set(fields["properties"]) == {
        "title",
        "summary",
        "acceptance_intent",
        "delivery_wave",
    }
    assert set(fields["required"]) == set(fields["properties"])
    assert fields["additionalProperties"] is False
    assert fields["properties"]["title"]["maxLength"] == 180
    assert fields["properties"]["summary"]["maxLength"] == 800
    assert fields["properties"]["acceptance_intent"]["maxLength"] == 500
    assert fields["properties"]["delivery_wave"]["enum"] == [1, 2, 3, 4]
    serialized_fields = json.dumps(fields, sort_keys=True)
    for forbidden in (
        '"op"',
        '"section_id"',
        '"binding_ref"',
        '"requirement_refs"',
        '"work_item_id"',
        '"depends_on"',
        '"operations"',
        '"questions"',
        '"explanation"',
    ):
        assert forbidden not in serialized_fields

    modification_request = {
        "target_section_id": "data",
        "current_plan": {
            "requirements": [
                {"requirement_ref": "R1"},
                {"requirement_ref": "R2"},
            ],
            "sections": [
                {
                    "section_id": "frontend",
                    "work_items": [
                        {"binding_ref": "W1", "requirement_refs": ["R1"]}
                    ],
                    "gaps": [],
                },
                {
                    "section_id": "data",
                    "work_items": [
                        {"binding_ref": "W2", "requirement_refs": ["R2"]}
                    ],
                    "gaps": [],
                },
            ],
        }
    }
    revision = product_planner_module._structured_output_schema(
        "plan_revision_proposal", modification_request
    )
    assert set(revision["properties"]) == {"operations"}
    assert revision["required"] == ["operations"]
    assert revision["additionalProperties"] is False
    operations = revision["properties"]["operations"]["items"]["oneOf"]
    assert len(operations) == 3
    add, update_w2, remove_w2 = operations
    assert add["properties"]["op"]["enum"] == ["add"]
    assert set(add["required"]) == set(add["properties"])
    assert set(add["properties"]) == {
        "op",
        "section_id",
        "title",
        "summary",
        "requirement_refs",
        "delivery_wave",
        "acceptance_intent",
    }
    assert add["properties"]["section_id"]["enum"] == ["data"]
    assert add["properties"]["requirement_refs"]["items"]["enum"] == ["R2"]
    assert update_w2["required"] == ["op", "binding_ref"]
    assert update_w2["minProperties"] == 3
    assert update_w2["properties"]["binding_ref"]["enum"] == ["W2"]
    assert set(update_w2["properties"]) == {
        "op",
        "binding_ref",
        "title",
        "summary",
        "acceptance_intent",
        "delivery_wave",
    }
    assert "section_id" not in update_w2["properties"]
    assert "requirement_refs" not in update_w2["properties"]
    assert "depends_on" not in update_w2["properties"]
    assert set(remove_w2["properties"]) == {"op", "binding_ref"}
    assert remove_w2["properties"]["binding_ref"]["enum"] == ["W2"]
    serialized = json.dumps(revision, sort_keys=True)
    assert "W1" not in serialized
    assert "R1" not in serialized
    for forbidden in (
        '"questions"',
        '"explanation"',
        '"intent"',
        '"kind"',
        '"outcome"',
    ):
        assert forbidden not in serialized


def revision_prompt_plan() -> dict[str, object]:
    return {
        "sections": [
            {
                "section_id": "data",
                "work_items": [
                    {
                        "binding_ref": "B1",
                        "title": "原备份策略",
                        "summary": "原交付意图。",
                        "requirement_refs": ["R1"],
                        "delivery_wave": 2,
                        "acceptance_intent": "原验收意图。",
                    }
                ],
            }
        ]
    }


def test_scoped_revision_requires_a_valid_target_before_consuming_suggestion(
    tmp_path: Path,
) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    select_small(planner)
    queue_plan(planner)
    created = planner.start("规划企业中台", catalog())
    request = revision_request(
        planner,
        created["data"]["plan_token"],
        created["data"]["plan"],
        "调整数据备份策略",
        selected_action="propose_revision",
        target_section_id="data",
    )
    receipt = request["suggestion_receipt"]

    missing = copy.deepcopy(request)
    missing.pop("target_section_id")
    missing_result = planner.revise(
        created["data"]["plan_token"], missing, catalog()
    )
    assert missing_result["error"]["code"] == "product_plan_revision_invalid"
    assert receipt in planner._action_suggestions

    unknown = copy.deepcopy(request)
    unknown["target_section_id"] = "unknown"
    unknown_result = planner.revise(
        created["data"]["plan_token"], unknown, catalog()
    )
    assert unknown_result["error"]["code"] == "product_plan_revision_invalid"
    assert receipt in planner._action_suggestions

    with pytest.raises(ProductPlanningError) as mismatch:
        planner._revision_target_section(
            {"sections": [{"section_id": "frontend"}]},
            "data",
        )
    assert mismatch.value.code == "product_plan_revision_invalid"
    assert mismatch.value.rule_code == "diff.target_section_mismatch"


@pytest.mark.parametrize(
    "operation",
    [
        {"op": "update", "binding_ref": "B1", "summary": "跨章更新。"},
        {"op": "remove", "binding_ref": "B1"},
        {
            "op": "add",
            "section_id": "frontend",
            "title": "跨章新增",
            "summary": "不得进入数据章修订。",
            "requirement_refs": ["R1"],
            "delivery_wave": 2,
            "acceptance_intent": "拒绝跨章操作。",
        },
        {
            "op": "add",
            "section_id": "data",
            "title": "错误需求引用",
            "summary": "不得引用前端需求。",
            "requirement_refs": ["R1"],
            "delivery_wave": 2,
            "acceptance_intent": "拒绝跨章需求引用。",
        },
    ],
)
def test_scoped_revision_translation_rejects_cross_section_operations(
    tmp_path: Path,
    operation: dict[str, object],
) -> None:
    planner = ProductPlanner(tmp_path / "scope")
    prompt_plan = {
        "sections": [
            {
                "section_id": "frontend",
                "work_items": [
                    {
                        "binding_ref": "B1",
                        "title": "前端工作项",
                        "summary": "前端说明。",
                        "requirement_refs": ["R1"],
                        "delivery_wave": 1,
                        "acceptance_intent": "前端验收。",
                    }
                ],
                "gaps": [],
            },
            {
                "section_id": "data",
                "work_items": [
                    {
                        "binding_ref": "B2",
                        "title": "数据工作项",
                        "summary": "数据说明。",
                        "requirement_refs": ["R2"],
                        "delivery_wave": 1,
                        "acceptance_intent": "数据验收。",
                    }
                ],
                "gaps": [],
            },
        ]
    }
    with pytest.raises(ProductPlanningError) as captured:
        planner._translate_revision_operations(
            [operation],
            {
                "binding_refs": {
                    "B1": "work_item_frontend",
                    "B2": "work_item_data",
                },
                "requirement_refs": {
                    "R1": "requirement_frontend",
                    "R2": "requirement_data",
                },
            },
            prompt_plan,
            "data",
        )
    assert captured.value.code == "product_plan_diff_invalid"
    assert captured.value.rule_code == "diff.target_section_mismatch"


def test_scoped_revision_rejects_cross_section_dependency_recompile(
    tmp_path: Path,
) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    select_small(planner)
    queue_plan(planner)
    created = planner.start("规划企业中台", catalog())
    plan = created["data"]["plan"]
    workspace = planner._workspace_by_token(created["data"]["plan_token"])
    item = plan["sections"][0]["work_items"][0]
    with pytest.raises(ProductPlanningError) as captured:
        planner._apply_revision_operations(
            plan,
            [
                {
                    "op": "update",
                    "work_item_id": item["work_item_id"],
                    "section_id": "frontend",
                    "title": item["title"],
                    "description": item["description"],
                    "requirement_ids": item["requirement_ids"],
                    "delivery_wave": 4,
                    "acceptance_intent": item["acceptance_intent"],
                }
            ],
            workspace["delivery_waves"],
            "frontend",
        )
    assert captured.value.code == "product_plan_diff_invalid"
    assert captured.value.rule_code == "diff.target_section_mismatch"


def test_targeted_revision_add_edit_and_reject_keep_base_plan(
    tmp_path: Path,
) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    select_small(planner)
    queue_plan(planner)
    created = planner.start("规划企业中台", catalog())
    token = created["data"]["plan_token"]
    base_plan = copy.deepcopy(created["data"]["plan"])
    requirement_id = next(
        requirement["requirement_id"]
        for requirement in base_plan["requirements"]
        if "PostgreSQL" in requirement["statement"]
    )
    planner.generation_outputs.append(
        {
            "title": "模型备份建议",
            "summary": "生成一份可人工审阅的备份建议。",
            "acceptance_intent": "验证备份建议。",
            "delivery_wave": 2,
        }
    )
    calls_before = sum(path == "/api/generate" for path, _ in planner.requests)
    proposed = planner.revise(
        token,
        {
            "action": "request",
            "message": "新增数据备份工作项",
            "target_section_id": "data",
            "target_operation": "add",
            "requirement_refs": [requirement_id],
        },
        catalog(),
    )

    assert proposed["data"]["status"] == "plan_diff_review"
    assert proposed["data"]["plan"] == base_plan
    assert sum(path == "/api/generate" for path, _ in planner.requests) - calls_before == 1
    assert planner._workspace_by_token(token)["model_calls"][-1]["call_type"] == (
        "plan_revision_fields"
    )
    diff = proposed["data"]["plan_diff"]
    assert diff["schema_version"] == "product_plan_diff.v3"
    assert diff["target_section_id"] == "data"
    assert diff["target_operation"] == "add"
    assert diff["target_binding_ref"] is None
    assert diff["editable_before"] is None
    assert diff["editable_after"]["title"] == "模型备份建议"
    pending = planner._workspace_by_token(token)["pending_diff"]
    assert pending["edit_scope"] == {
        "schema_version": "product_plan_diff_edit_scope.v1",
        "target_operation": "add",
        "target_section_id": "data",
        "target_binding_ref": None,
        "requirement_refs": [requirement_id],
    }
    prompt = next(
        payload["prompt"]
        for path, payload in reversed(planner.requests)
        if path == "/api/generate"
    )
    assert requirement_id not in prompt
    assert all(
        item["work_item_id"] not in prompt
        for section in base_plan["sections"]
        for item in section["work_items"]
    )

    workspace_path = next(planner.root.glob("workspace_*/workspace.json"))
    before_invalid_edit = workspace_path.read_bytes()
    for invalid_fields in (
        copy.deepcopy(diff["editable_after"]),
        {
            key: value
            for key, value in diff["editable_after"].items()
            if key != "title"
        },
        {**diff["editable_after"], "target_section_id": "frontend"},
    ):
        invalid_edit = planner.revise(
            token,
            {
                "action": "edit_diff",
                "expected_diff_digest": diff["diff_digest"],
                "fields": invalid_fields,
            },
            catalog(),
        )
        assert invalid_edit["error"]["code"] == "product_plan_revision_invalid"
        assert workspace_path.read_bytes() == before_invalid_edit

    edited_fields = {
        "title": "数据备份与恢复",
        "summary": "每日增量备份，每周全量备份，并保留执行记录。",
        "acceptance_intent": "完成恢复演练并记录结果。",
        "delivery_wave": 3,
    }
    edited = planner.revise(
        token,
        {
            "action": "edit_diff",
            "expected_diff_digest": diff["diff_digest"],
            "fields": edited_fields,
        },
        catalog(),
    )
    assert edited["data"]["plan"] == base_plan
    assert edited["data"]["plan_diff"]["diff_digest"] != diff["diff_digest"]
    assert edited["data"]["plan_diff"]["editable_after"] == edited_fields
    assert sum(path == "/api/generate" for path, _ in planner.requests) - calls_before == 1
    edited_pending = planner._workspace_by_token(token)["pending_diff"]
    assert product_planner_module._DIGEST.fullmatch(
        edited_pending["user_edit_digest"]
    )
    stale_edit = planner.revise(
        token,
        {
            "action": "edit_diff",
            "expected_diff_digest": diff["diff_digest"],
            "fields": edited_fields,
        },
        catalog(),
    )
    assert stale_edit["error"]["code"] == "product_plan_diff_stale"
    tampered_edit = planner.revise(
        token,
        {
            "action": "edit_diff",
            "expected_diff_digest": edited["data"]["plan_diff"]["diff_digest"],
            "fields": {**edited_fields, "section_id": "frontend"},
        },
        catalog(),
    )
    assert tampered_edit["error"]["code"] == "product_plan_revision_invalid"
    assert planner._workspace_by_token(token)["pending_diff"] == edited_pending
    rejected = planner.revise(
        token,
        {
            "action": "reject_diff",
            "base_plan_digest": edited["data"]["plan_diff"]["base_plan_digest"],
            "diff_digest": edited["data"]["plan_diff"]["diff_digest"],
            "reviewed_plan": edited["data"]["plan"],
            "reviewed_diff": edited["data"]["plan_diff"],
        },
        catalog(),
    )
    assert rejected["data"]["plan"] == base_plan
    assert rejected["data"]["plan_diff"] is None


def test_targeted_revision_update_accept_and_confirm_are_separate(
    tmp_path: Path,
) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    select_small(planner)
    queue_plan(planner)
    created = planner.start("规划企业中台", catalog())
    token = created["data"]["plan_token"]
    base_plan = copy.deepcopy(created["data"]["plan"])
    data_item = next(
        item
        for section in base_plan["sections"]
        if section["section_id"] == "data"
        for item in section["work_items"]
    )
    planner.generation_outputs.append(
        {
            "title": "数据审计与恢复",
            "summary": "更新数据审计与恢复交付说明。",
            "acceptance_intent": "审计与恢复路径可验收。",
            "delivery_wave": 3,
        }
    )
    proposed = planner.revise(
        token,
        {
            "action": "request",
            "message": "修改数据审计工作项",
            "target_section_id": "data",
            "target_operation": "update",
            "target_binding_ref": data_item["work_item_id"],
        },
        catalog(),
    )
    assert proposed["data"]["plan"] == base_plan
    assert proposed["data"]["plan_diff"]["target_operation"] == "update"
    assert proposed["data"]["plan_diff"]["target_binding_ref"] == (
        data_item["work_item_id"]
    )
    assert proposed["data"]["plan_diff"]["editable_before"]["title"] == (
        data_item["title"]
    )
    pending = planner._workspace_by_token(token)["pending_diff"]
    assert pending["edit_scope"]["target_binding_ref"] == data_item["work_item_id"]
    assert pending["edit_scope"]["requirement_refs"] == data_item["requirement_ids"]
    restored = StubPlanner(planner.root).get(token)
    assert restored["data"]["plan_diff"]["target_binding_ref"] == (
        data_item["work_item_id"]
    )

    workspace_path = next(planner.root.glob("workspace_*/workspace.json"))
    before_revert = workspace_path.read_bytes()
    reverted = planner.revise(
        token,
        {
            "action": "edit_diff",
            "expected_diff_digest": proposed["data"]["plan_diff"]["diff_digest"],
            "fields": proposed["data"]["plan_diff"]["editable_before"],
        },
        catalog(),
    )
    assert reverted["error"]["code"] == "product_plan_diff_invalid"
    assert workspace_path.read_bytes() == before_revert

    accepted = planner.revise(
        token,
        {
            "action": "accept_diff",
            "base_plan_digest": proposed["data"]["plan_diff"]["base_plan_digest"],
            "diff_digest": proposed["data"]["plan_diff"]["diff_digest"],
            "reviewed_plan": proposed["data"]["plan"],
            "reviewed_diff": proposed["data"]["plan_diff"],
        },
        catalog(),
    )
    assert accepted["data"]["status"] == "plan_review"
    assert accepted["data"]["plan"]["plan_version"] == 2
    assert accepted["data"]["plan"]["canonical_digest"] != (
        base_plan["canonical_digest"]
    )
    assert accepted["data"]["confirmation"] is None
    confirmed = planner.confirm(
        token,
        accepted["data"]["plan"]["canonical_digest"],
        accepted["data"]["plan"],
        catalog(),
    )
    assert confirmed["data"]["status"] == "confirmed"
    assert confirmed["data"]["confirmation"]["product_generated"] is False


@pytest.mark.parametrize(
    "revision_request",
    [
        {
            "action": "request",
            "message": "新增数据工作项",
            "target_section_id": "data",
            "target_operation": "add",
            "requirement_refs": [],
        },
        {
            "action": "request",
            "message": "新增数据工作项",
            "target_section_id": "data",
            "target_operation": "add",
            "requirement_refs": ["unknown_requirement"],
        },
        {
            "action": "request",
            "message": "新增数据工作项",
            "target_section_id": "data",
            "target_operation": "add",
            "requirement_refs": [
                "requirement_00000000000000000000",
                "requirement_00000000000000000000",
            ],
        },
    ],
)
def test_targeted_revision_rejects_invalid_add_scope_without_model_call(
    tmp_path: Path,
    revision_request: dict[str, object],
) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    select_small(planner)
    queue_plan(planner)
    created = planner.start("规划企业中台", catalog())
    workspace_path = next(planner.root.glob("workspace_*/workspace.json"))
    before = workspace_path.read_bytes()
    calls_before = sum(path == "/api/generate" for path, _ in planner.requests)
    result = planner.revise(
        created["data"]["plan_token"],
        revision_request,
        catalog(),
    )
    assert result["error"]["code"] == "product_plan_revision_invalid"
    assert workspace_path.read_bytes() == before
    assert sum(path == "/api/generate" for path, _ in planner.requests) == calls_before


def test_targeted_revision_rejects_mismatched_update_and_zero_effect(
    tmp_path: Path,
) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    select_small(planner)
    queue_plan(planner)
    created = planner.start("规划企业中台", catalog())
    token = created["data"]["plan_token"]
    plan = created["data"]["plan"]
    frontend_item = plan["sections"][0]["work_items"][0]
    mismatched = planner.revise(
        token,
        {
            "action": "request",
            "message": "修改数据工作项",
            "target_section_id": "data",
            "target_operation": "update",
            "target_binding_ref": frontend_item["work_item_id"],
        },
        catalog(),
    )
    assert mismatched["error"]["code"] == "product_plan_revision_invalid"

    data_item = plan["sections"][2]["work_items"][0]
    delivery_wave = planner._workspace_by_token(token)["delivery_waves"][
        data_item["work_item_id"]
    ]
    planner.generation_outputs.append(
        {
            "title": data_item["title"],
            "summary": data_item["description"],
            "acceptance_intent": data_item["acceptance_intent"],
            "delivery_wave": delivery_wave,
        }
    )
    unchanged = planner.revise(
        token,
        {
            "action": "request",
            "message": "保持数据工作项不变",
            "target_section_id": "data",
            "target_operation": "update",
            "target_binding_ref": data_item["work_item_id"],
        },
        catalog(),
    )
    assert unchanged["error"]["code"] == "product_plan_diff_invalid"
    assert unchanged["data"]["plan"] == plan
    assert unchanged["data"]["plan_diff"] is None


def test_targeted_revision_rejects_duplicate_requirements_without_model_call(
    tmp_path: Path,
) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    select_small(planner)
    queue_plan(planner)
    created = planner.start("规划企业中台", catalog())
    requirement_id = created["data"]["plan"]["requirements"][0]["requirement_id"]
    calls_before = sum(path == "/api/generate" for path, _ in planner.requests)

    result = planner.revise(
        created["data"]["plan_token"],
        {
            "action": "request",
            "message": "新增重复需求工作项",
            "target_section_id": "data",
            "target_operation": "add",
            "requirement_refs": [requirement_id, requirement_id],
        },
        catalog(),
    )

    assert result["error"]["code"] == "product_plan_revision_invalid"
    assert sum(path == "/api/generate" for path, _ in planner.requests) == calls_before


def test_targeted_revision_allows_wave_only_update_and_locks_replay(
    tmp_path: Path,
) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    select_small(planner)
    queue_plan(planner)
    created = planner.start("规划企业中台", catalog())
    token = created["data"]["plan_token"]
    plan = created["data"]["plan"]
    data_item = plan["sections"][2]["work_items"][0]
    base_wave = planner._workspace_by_token(token)["delivery_waves"][
        data_item["work_item_id"]
    ]
    new_wave = 4 if base_wave != 4 else 3
    planner.generation_outputs.append(
        {
            "title": data_item["title"],
            "summary": data_item["description"],
            "acceptance_intent": data_item["acceptance_intent"],
            "delivery_wave": new_wave,
        }
    )

    result = planner.revise(
        token,
        {
            "action": "request",
            "message": "只调整交付波次",
            "target_section_id": "data",
            "target_operation": "update",
            "target_binding_ref": data_item["work_item_id"],
        },
        catalog(),
    )

    assert result["ok"] is True
    diff = result["data"]["plan_diff"]
    assert diff["editable_before"]["delivery_wave"] == base_wave
    assert diff["editable_after"]["delivery_wave"] == new_wave
    pending_workspace = planner._workspace_by_token(token)
    tampered = copy.deepcopy(pending_workspace["pending_diff"])
    tampered["proposed_plan"]["product_name"] = "被篡改的产品名"
    tampered["proposed_plan"]["canonical_digest"] = planner._plan_digest(
        tampered["proposed_plan"]
    )
    tampered["public_diff"] = planner._targeted_plan_diff(
        pending_workspace["plan"],
        tampered["proposed_plan"],
        tampered["base_delivery_waves"],
        tampered["proposed_delivery_waves"],
        tampered["edit_scope"],
    )
    with pytest.raises(ProductPlanningError, match="product_plan_diff_invalid"):
        planner._validate_pending_diff(pending_workspace["plan"], tampered)

    corrupted_workspace = copy.deepcopy(pending_workspace)
    first_work_item_id = next(iter(corrupted_workspace["delivery_waves"]))
    corrupted_workspace["pending_diff"]["base_delivery_waves"][
        first_work_item_id
    ] = 4 if corrupted_workspace["delivery_waves"][first_work_item_id] != 4 else 3
    with pytest.raises(ProductPlanningError, match="product_workspace_corrupt"):
        planner._validate_workspace(corrupted_workspace)


def test_targeted_revision_cancellation_records_one_call_without_pending_diff(
    tmp_path: Path,
) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    select_small(planner)
    queue_plan(planner)
    created = planner.start("规划企业中台", catalog())
    token = created["data"]["plan_token"]
    requirement_id = created["data"]["plan"]["requirements"][0]["requirement_id"]
    planner.generation_outputs.append(
        {
            "title": "模型建议",
            "summary": "形成可审阅建议。",
            "acceptance_intent": "验证建议。",
            "delivery_wave": 2,
        }
    )
    checks = 0

    def cancelled_after_generation() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 2

    result = planner.revise(
        token,
        {
            "action": "request",
            "message": "新增数据工作项",
            "target_section_id": "data",
            "target_operation": "add",
            "requirement_refs": [requirement_id],
        },
        catalog(),
        cancelled_after_generation,
    )

    assert result["error"]["code"] == "product_plan_cancelled"
    workspace = planner._workspace_by_token(token)
    assert workspace["status"] == "interrupted"
    assert workspace["pending_diff"] is None
    assert workspace["model_calls"][-1]["call_type"] == "plan_revision_fields"


def test_action_suggestion_is_ephemeral_and_user_choice_is_authoritative(
    tmp_path: Path,
) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    select_small(planner)
    queue_plan(planner)
    created = planner.start("规划企业中台", catalog())
    token = created["data"]["plan_token"]
    plan = created["data"]["plan"]
    workspace_path = next(planner.root.glob("workspace_*/workspace.json"))
    before = workspace_path.read_bytes()
    planner.generation_outputs.append({"suggested_action": "edit_goal"})

    suggestion = planner.suggest_action(
        token,
        "解释基础设施缺口，不要修改计划。",
    )

    assert suggestion["ok"] is True
    assert suggestion["data"]["suggested_action"] == "edit_goal"
    assert workspace_path.read_bytes() == before
    assert all(
        call["call_type"] != "plan_action_suggestion"
        for call in planner._workspace_by_token(token)["model_calls"]
    )
    planner.generation_outputs.append(
        {"explanation": "基础设施缺口来自当前正式能力边界。"}
    )
    explained = planner.revise(
        token,
        {
            "action": "request",
            "message": "解释基础设施缺口，不要修改计划。",
            "reviewed_plan": plan,
            "selected_action": "ask_plan",
            "suggestion_receipt": suggestion["data"]["suggestion_receipt"],
            "suggestion_digest": suggestion["data"]["suggestion_digest"],
        },
        catalog(),
    )
    assert explained["data"]["revision_result"]["kind"] == "explanation"
    assert planner._workspace_by_token(token)["model_calls"][-1]["call_type"] == (
        "plan_revision_explanation"
    )
    assert set(explained["data"]["developer_evidence"]["model_calls"][-1]) == {
        "call_type",
        "input_bytes",
        "output_bytes",
        "duration_ms",
        "structured_response_digest",
    }
    assert "revision_request_digest" not in json.dumps(
        explained["data"]["developer_evidence"], sort_keys=True
    )
    reused = planner.revise(
        token,
        {
            "action": "request",
            "message": "解释基础设施缺口，不要修改计划。",
            "reviewed_plan": plan,
            "selected_action": "ask_plan",
            "suggestion_receipt": suggestion["data"]["suggestion_receipt"],
            "suggestion_digest": suggestion["data"]["suggestion_digest"],
        },
        catalog(),
    )
    assert reused["error"]["code"] == "product_plan_action_suggestion_stale"
    assert reused["data"]["plan"] == plan


def test_action_suggestion_failure_keeps_fixed_choices_available_without_write(
    tmp_path: Path,
) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    select_small(planner)
    queue_plan(planner)
    created = planner.start("规划企业中台", catalog())
    workspace_path = next(planner.root.glob("workspace_*/workspace.json"))
    before = workspace_path.read_bytes()

    def unavailable(*_args, **_kwargs):
        raise ProductPlanningError("ollama_unavailable", "ollama.timeout")

    planner._generate_json = unavailable  # type: ignore[method-assign]
    suggestion = planner.suggest_action(
        created["data"]["plan_token"],
        "解释基础设施缺口，不要修改计划。",
    )
    assert suggestion["ok"] is True
    assert suggestion["data"]["recommendation_available"] is False
    assert suggestion["data"]["suggested_action"] is None
    assert suggestion["data"]["suggestion_receipt"].startswith(
        "suggestion_receipt_"
    )
    assert workspace_path.read_bytes() == before


def test_edit_goal_authority_uses_receipt_and_zero_revision_model_calls(
    tmp_path: Path,
) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    select_small(planner)
    queue_plan(planner)
    created = planner.start("规划企业中台", catalog())
    token = created["data"]["plan_token"]
    plan = created["data"]["plan"]
    workspace_path = next(planner.root.glob("workspace_*/workspace.json"))
    before = workspace_path.read_bytes()
    request = revision_request(
        planner,
        token,
        plan,
        "我要改写产品目标",
        selected_action="edit_goal",
        suggested_action="ask_plan",
    )
    calls_before = sum(path == "/api/generate" for path, _ in planner.requests)
    result = planner.revise(token, request, catalog())
    calls_after = sum(path == "/api/generate" for path, _ in planner.requests)
    assert result["data"]["revision_result"] == {
        "kind": "edit_goal",
        "plan_changed": False,
    }
    assert calls_after == calls_before
    assert workspace_path.read_bytes() == before


@pytest.mark.parametrize(
    ("operation", "rule_code"),
    [
        (
            {"op": "update", "binding_ref": "UNKNOWN", "summary": "更新。"},
            "diff.binding_ref_unknown",
        ),
        (
            {
                "op": "add",
                "section_id": "data",
                "title": "备份",
                "summary": "定义备份策略。",
                "requirement_refs": ["UNKNOWN"],
                "delivery_wave": 3,
                "acceptance_intent": "验证恢复演练。",
            },
            "diff.requirement_ref_unknown",
        ),
    ],
)
def test_revision_reference_rule_codes_are_stable(
    tmp_path: Path,
    operation: dict[str, object],
    rule_code: str,
) -> None:
    planner = ProductPlanner(tmp_path / rule_code)
    with pytest.raises(ProductPlanningError) as captured:
        planner._translate_revision_operations(
            [operation],
            {
                "binding_refs": {"B1": "work_item_1"},
                "requirement_refs": {"R1": "requirement_1"},
            },
            revision_prompt_plan(),
        )
    assert captured.value.code == "product_plan_diff_invalid"
    assert captured.value.rule_code == rule_code


@pytest.mark.parametrize(
    ("raw_operation", "rule_code"),
    [
        ("untrusted model text", "diff.operation_not_object"),
        (
            {
                "op": "update",
                "summary": "定义备份策略。",
            },
            "diff.operation_required_key_missing.binding_ref",
        ),
        (
            {
                "binding_ref": "B1",
                "summary": "定义备份策略。",
            },
            "diff.operation_required_key_missing.op",
        ),
        (
            {
                "op": "update",
                "binding_ref": "B1",
                "section_id": "data",
                "untrusted_model_field": "untrusted model value",
            },
            "diff.operation_extra_key",
        ),
        (
            {"op": "update", "binding_ref": "B1"},
            "diff.update_fields_empty",
        ),
    ],
)
def test_revision_operation_shape_rule_codes_are_stable_and_private(
    tmp_path: Path,
    raw_operation: object,
    rule_code: str,
) -> None:
    planner = ProductPlanner(tmp_path / rule_code)
    with pytest.raises(ProductPlanningError) as captured:
        planner._translate_revision_operations(
            [raw_operation],
            {
                "binding_refs": {"B1": "work_item_1"},
                "requirement_refs": {"R1": "requirement_1"},
            },
            revision_prompt_plan(),
        )
    assert captured.value.code == "product_plan_diff_invalid"
    assert captured.value.rule_code == rule_code
    error_text = f"{captured.value} {captured.value.rule_code}"
    assert "untrusted model" not in error_text
    assert "untrusted_model_field" not in error_text


def test_revision_modification_v3_applies_only_mutable_update_fields(
    tmp_path: Path,
) -> None:
    planner = ProductPlanner(tmp_path / "valid-operation")
    translated = planner._translate_revision_operations(
        [
            {
                "op": "update",
                "binding_ref": "B1",
                "summary": "定义备份策略。",
                "acceptance_intent": "验证恢复演练。",
            }
        ],
        {
            "binding_refs": {"B1": "work_item_1"},
            "requirement_refs": {"R1": "requirement_1"},
        },
        revision_prompt_plan(),
    )
    assert translated == [
        {
            "op": "update",
            "work_item_id": "work_item_1",
            "section_id": "data",
            "title": "原备份策略",
            "description": "定义备份策略。",
            "requirement_ids": ["requirement_1"],
            "delivery_wave": 2,
            "acceptance_intent": "验证恢复演练。",
        }
    ]


def test_revision_update_section_mismatch_rule_code_is_stable(
    tmp_path: Path,
) -> None:
    planner = ProductPlanner(tmp_path / "section-mismatch")
    plan = {
        "requirements": [{"requirement_id": "requirement_1"}],
        "sections": [
            {"section_id": "frontend", "work_items": []},
            {
                "section_id": "data",
                "work_items": [
                    {"work_item_id": "work_item_1", "depends_on": []}
                ],
            },
        ],
    }
    with pytest.raises(ProductPlanningError) as captured:
        planner._apply_revision_operations(
            plan,
            [
                {
                    "op": "update",
                    "work_item_id": "work_item_1",
                    "section_id": "frontend",
                    "title": "备份策略",
                    "description": "定义备份策略。",
                    "requirement_ids": ["requirement_1"],
                    "delivery_wave": 2,
                    "acceptance_intent": "验证恢复演练。",
                }
            ],
            {"work_item_1": 1},
        )
    assert captured.value.code == "product_plan_diff_invalid"
    assert captured.value.rule_code == "diff.update_section_mismatch"


def test_model_metadata_gate_is_exact_and_selection_is_private(tmp_path: Path) -> None:
    assert MAX_MODEL_PARAMETERS == 15_000_000_000
    planner = StubPlanner(tmp_path / "product_workspaces")
    listed = planner.list_models()
    assert listed["ok"] is True
    models = {item["name"]: item for item in listed["data"]["models"]}
    assert models["small:1.5b"]["eligible_small_model"] is True
    assert models["small:1.5b"]["parameter_count"] == 1_543_714_304
    assert models["large:7b"]["eligible_small_model"] is True
    assert models["large:7b"]["parameter_count"] == 7_615_616_512
    assert not planner.root.exists(), "listing must not create planner state"

    qwen3 = StubPlanner(
        tmp_path / "qwen3",
        counts={"qwen3:14b": 14_768_307_200},
    )
    qwen3.digests = {"qwen3:14b": LARGE_DIGEST}
    assert qwen3.list_models()["data"]["models"][0]["eligible_small_model"] is True

    too_large = StubPlanner(
        tmp_path / "too-large",
        counts={"too-large:15b": MAX_MODEL_PARAMETERS + 1},
    )
    too_large.digests = {"too-large:15b": LARGE_DIGEST}
    oversized = too_large.list_models()["data"]["models"][0]
    assert oversized["eligible_small_model"] is False
    assert oversized["eligibility_reason"] == "parameter_count_exceeds_limit"
    rejected = too_large.select_model("too-large:15b", LARGE_DIGEST)
    assert rejected["error"]["code"] == "product_planning_model_too_large"
    assert not too_large.root.exists()
    assert all(path != "/api/generate" for path, _payload in too_large.requests)

    moe = StubPlanner(
        tmp_path / "moe",
        counts={"local:moe": 14_000_000_000},
        model_infos={
            "local:moe": {
                "general.architecture": "qwen3moe",
                "qwen3moe.expert_count": 128,
            }
        },
    )
    moe.digests = {"local:moe": LARGE_DIGEST}
    moe_model = moe.list_models()["data"]["models"][0]
    assert moe_model["eligible_small_model"] is False
    assert moe_model["eligibility_reason"] == "mixture_of_experts_not_allowed"
    assert (
        moe.select_model("local:moe", LARGE_DIGEST)["error"]["code"]
        == "product_planning_model_moe_not_allowed"
    )

    planner.generation_outputs.append(probe())
    selected = planner.select_model("large:7b", LARGE_DIGEST)
    assert selected["ok"] is True
    assert selected["data"]["model"]["parameter_count"] == 7_615_616_512
    selection = planner.root / "model_selection.json"
    assert stat_mode(selection) == 0o600
    assert stat_mode(planner.root) == 0o700
    persisted = selection.read_text(encoding="utf-8")
    assert '"prompt":' not in persisted
    assert '"response":' not in persisted


def test_generate_uses_native_json_schema_and_keeps_strict_nested_shapes(
    tmp_path: Path,
) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    select_small(planner)
    probe_payload = next(
        payload for path, payload in planner.requests if path == "/api/generate"
    )
    assert isinstance(probe_payload, dict)
    assert probe_payload["think"] is False
    assert FORMAL_MODEL_TIMEOUT_SECONDS == 180
    assert [
        timeout
        for path, timeout in planner.request_timeouts
        if path == "/api/generate"
    ] == [HTTP_TIMEOUT_SECONDS]
    assert probe_payload["format"] == {
        "type": "object",
        "properties": {
            "schema_version": {
                "type": "string",
                "enum": ["product_plan_probe.v1"],
            },
            "status": {"type": "string", "enum": ["ready"]},
            "role": {"type": "string", "enum": ["product_planner"]},
        },
        "required": ["schema_version", "status", "role"],
        "additionalProperties": False,
    }

    planner.generation_outputs.append(outline(clarification=True))
    started = planner.start("规划企业中台", catalog(with_capsule=False))
    assert started["data"]["status"] == "needs_clarification"
    generate_payloads = [
        payload for path, payload in planner.requests if path == "/api/generate"
    ]
    assert "clarification_status" in generate_payloads[-1]["prompt"]
    assert "exactly when questions is non-empty" in generate_payloads[-1]["prompt"]
    outline_schema = generate_payloads[-1]["format"]
    assert [
        timeout
        for path, timeout in planner.request_timeouts
        if path == "/api/generate"
    ] == [HTTP_TIMEOUT_SECONDS, FORMAL_MODEL_TIMEOUT_SECONDS]
    assert outline_schema["additionalProperties"] is False
    question_schema = outline_schema["properties"]["questions"]["items"]
    assert question_schema["additionalProperties"] is False
    assert (
        question_schema["properties"]["options"]["items"]["additionalProperties"]
        is False
    )


def test_outline_rule_codes_are_stable_and_valid_outline_is_unchanged(
    tmp_path: Path,
) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    select_small(planner)
    model = planner._selected_model(check_current=True)

    def invalid(rule_code: str) -> dict[str, object]:
        value = outline(clarification=True)
        requirement = value["requirements"][0]
        question = value["questions"][0]
        option = question["options"][0]
        if rule_code == "outline.shape_invalid":
            value["extra"] = True
        elif rule_code == "outline.schema_version_invalid":
            value["schema_version"] = "product_plan_outline.v2"
        elif rule_code == "outline.language_invalid":
            value["language"] = "fr"
        elif rule_code == "outline.questions_status_type_invalid":
            value["needs_clarification"] = "true"
        elif rule_code == "outline.product_name_invalid":
            value["product_name"] = " invalid "
        elif rule_code == "outline.requirements_count_invalid":
            value["requirements"] = []
        elif rule_code == "outline.requirement_shape_invalid":
            requirement["extra"] = True
        elif rule_code == "outline.reference_invalid":
            requirement["ref"] = "1-invalid"
        elif rule_code == "outline.duplicate_reference":
            value["requirements"].append(copy.deepcopy(requirement))
        elif rule_code == "outline.requirement_source_invalid":
            requirement["source"] = "invalid"
        elif rule_code == "outline.invalid_requirement_source":
            requirement["source"] = "planning_answer"
        elif rule_code == "outline.requirement_text_invalid":
            requirement["statement"] = " invalid "
        elif rule_code == "outline.questions_status_mismatch":
            value["needs_clarification"] = False
        elif rule_code == "outline.questions_count_invalid":
            value["questions"] = [copy.deepcopy(question) for _index in range(4)]
        elif rule_code == "outline.question_shape_invalid":
            question["extra"] = True
        elif rule_code == "outline.question_text_invalid":
            question["prompt"] = " invalid "
        elif rule_code == "outline.allow_custom_invalid":
            question["allow_custom"] = False
        elif rule_code == "outline.sensitive_question":
            question["prompt"] = "请输入密码。"
        elif rule_code == "outline.options_count_invalid":
            question["options"] = [option]
        elif rule_code == "outline.option_shape_invalid":
            option["extra"] = True
        elif rule_code == "outline.option_flags_invalid":
            option["forms_gap"] = "false"
        elif rule_code == "outline.recommended_option_order_invalid":
            option["recommended"] = False
        elif rule_code == "outline.option_text_invalid":
            option["label"] = " invalid "
        else:  # pragma: no cover - keeps the case table auditable
            raise AssertionError(rule_code)
        return value

    rule_codes = (
        "outline.shape_invalid",
        "outline.schema_version_invalid",
        "outline.language_invalid",
        "outline.questions_status_type_invalid",
        "outline.product_name_invalid",
        "outline.requirements_count_invalid",
        "outline.requirement_shape_invalid",
        "outline.reference_invalid",
        "outline.duplicate_reference",
        "outline.requirement_source_invalid",
        "outline.invalid_requirement_source",
        "outline.requirement_text_invalid",
        "outline.questions_status_mismatch",
        "outline.questions_count_invalid",
        "outline.question_shape_invalid",
        "outline.question_text_invalid",
        "outline.allow_custom_invalid",
        "outline.sensitive_question",
        "outline.options_count_invalid",
        "outline.option_shape_invalid",
        "outline.option_flags_invalid",
        "outline.recommended_option_order_invalid",
        "outline.option_text_invalid",
    )
    for rule_code in rule_codes:
        planner.generation_outputs.append(invalid(rule_code))
        with pytest.raises(ProductPlanningError) as captured:
            planner._outline("规划企业中台", [], model, None)
        assert captured.value.code == "product_plan_response_invalid"
        assert captured.value.rule_code == rule_code

    planner.generation_outputs.append(outline())
    validated, evidence = planner._outline("规划企业中台", [], model, None)
    assert validated == outline()
    assert len(evidence) == 1


def test_outline_rule_code_is_internal_and_requirement_coverage_is_labeled(
    tmp_path: Path,
) -> None:
    planner = StubPlanner(tmp_path / "public-error")
    select_small(planner)
    invalid_outline = outline(clarification=True)
    invalid_outline["product_name"] = "MODEL_PRIVATE_TEXT"
    invalid_outline["needs_clarification"] = False
    planner.generation_outputs.append(invalid_outline)
    failed = planner.start("规划企业中台", catalog(with_capsule=False))
    serialized = json.dumps(failed, ensure_ascii=False)
    assert failed["error"]["code"] == "product_plan_response_invalid"
    assert "rule_code" not in serialized
    assert "outline.questions_status_mismatch" not in serialized
    assert "MODEL_PRIVATE_TEXT" not in serialized
    stored = next(planner.root.glob("workspace_*/workspace.json")).read_text(
        encoding="utf-8"
    )
    assert "rule_code" not in stored
    assert "outline.questions_status_mismatch" not in stored
    assert "MODEL_PRIVATE_TEXT" not in stored
    assert '"prompt"' not in stored
    assert '"response"' not in stored

    valid = StubPlanner(tmp_path / "coverage")
    select_small(valid)
    queue_plan(valid)
    created = valid.start("规划企业中台", catalog())
    plan = copy.deepcopy(created["data"]["plan"])
    plan["requirements"].append(
        {
            "requirement_id": "requirement_ffffffffffffffffffff",
            "statement": "新增需求必须被工作项或缺口覆盖",
            "source": "product_goal",
            "source_digest": plan["goal_digest"],
        }
    )
    plan["canonical_digest"] = valid._plan_digest(plan)
    with pytest.raises(ProductPlanningError) as captured:
        valid._validate_plan(plan)
    assert captured.value.code == "product_plan_requirement_uncovered"
    assert captured.value.rule_code == "section.requirement_uncovered"


def test_section_rule_codes_are_stable_private_and_keep_valid_sections(
    tmp_path: Path,
) -> None:
    planner = StubPlanner(tmp_path / "direct")
    select_small(planner)
    model = planner._selected_model(check_current=True)
    requirements = outline()["requirements"]
    candidate_ref = "candidate_allowed"
    candidate = catalog()["capsules"][0]
    candidates = {candidate_ref: candidate}

    def invalid(rule_code: str) -> dict[str, object]:
        value = section("infrastructure")
        item = value["work_items"][0]
        if rule_code == "section.shape_invalid":
            value["extra"] = True
        elif rule_code == "section.schema_version_invalid":
            value["schema_version"] = "product_plan_section.v2"
        elif rule_code == "section.section_id_mismatch":
            value["section_id"] = "backend"
        elif rule_code == "section.item_count_invalid":
            value["work_items"] = []
        elif rule_code == "section.summary_invalid":
            value["summary"] = " invalid "
        elif rule_code == "section.work_item_shape_invalid":
            item["extra"] = True
        elif rule_code == "section.requirement_refs_invalid":
            item["requirement_refs"] = ["unknown_requirement"]
        elif rule_code == "section.delivery_wave_invalid":
            item["delivery_wave"] = 5
        elif rule_code == "section.work_item_text_invalid":
            item["acceptance_intent"] = " invalid "
        elif rule_code == "section.candidate_ref_unknown":
            item["candidate_ref"] = "candidate_unknown"
            item["gap_reason"] = ""
        elif rule_code == "section.candidate_gap_conflict":
            item["candidate_ref"] = candidate_ref
            item["gap_reason"] = "不能同时声称缺口。"
        elif rule_code == "section.gap_reason_invalid":
            item["gap_reason"] = " invalid "
        elif rule_code == "section.gap_reason_required":
            item["gap_reason"] = ""
        else:  # pragma: no cover - keeps the case table auditable
            raise AssertionError(rule_code)
        return value

    response_rule_codes = (
        "section.shape_invalid",
        "section.schema_version_invalid",
        "section.section_id_mismatch",
        "section.item_count_invalid",
        "section.summary_invalid",
        "section.work_item_shape_invalid",
        "section.requirement_refs_invalid",
        "section.delivery_wave_invalid",
        "section.work_item_text_invalid",
        "section.candidate_ref_unknown",
        "section.candidate_gap_conflict",
        "section.gap_reason_invalid",
        "section.gap_reason_required",
    )
    for rule_code in response_rule_codes:
        planner.generation_outputs.append(invalid(rule_code))
        with pytest.raises(ProductPlanningError) as captured:
            planner._section_call(
                model,
                "infrastructure",
                requirements,
                [],
                candidates,
                None,
            )
        assert captured.value.code == "product_plan_response_invalid"
        assert captured.value.rule_code == rule_code

    planner.generation_outputs.append(section("infrastructure", candidate_ref))
    valid, evidence = planner._section_call(
        model,
        "infrastructure",
        requirements,
        [],
        candidates,
        None,
    )
    section_payload = next(
        payload
        for path, payload in reversed(planner.requests)
        if path == "/api/generate"
    )
    assert "Do not emit work-item IDs, refs, dependencies" in section_payload["prompt"]
    work_item_schema = section_payload["format"]["properties"]["work_items"][
        "items"
    ]
    assert "ref" not in work_item_schema["properties"]
    assert "depends_on" not in work_item_schema["properties"]
    assert work_item_schema["properties"]["delivery_wave"]["enum"] == [1, 2, 3, 4]
    assert section_payload["format"]["properties"]["summary"] == {
        "type": "string",
        "minLength": 1,
        "maxLength": 500,
    }
    for key, minimum, maximum in (
        ("title", 1, 180),
        ("summary", 1, 800),
        ("acceptance_intent", 1, 500),
        ("gap_reason", 0, 500),
    ):
        assert work_item_schema["properties"][key] == {
            "type": "string",
            "minLength": minimum,
            "maxLength": maximum,
        }
        assert "pattern" not in work_item_schema["properties"][key]
    assert "must not have leading or trailing whitespace" in section_payload["prompt"]
    assert "Control characters are forbidden except tab and newline" in section_payload[
        "prompt"
    ]
    assert set(
        work_item_schema["properties"]["requirement_refs"]["items"]["enum"]
    ) == {item["ref"] for item in requirements}
    assert work_item_schema["properties"]["candidate_ref"]["enum"] == [
        "",
        candidate_ref,
    ]
    assert "capsule_id" not in section_payload["prompt"]
    assert "version_id" not in section_payload["prompt"]
    requirement_refs = {item["ref"] for item in requirements}
    assert planner._validate_checkpoint_section(
        valid,
        "infrastructure",
        requirement_refs,
        {candidate_ref},
    ) is None
    assert evidence["structured_response_digest"]

    minimum = section("infrastructure", candidate_ref)
    minimum["summary"] = "节"
    minimum_item = minimum["work_items"][0]
    for key in ("title", "summary", "acceptance_intent"):
        minimum_item[key] = "字"
    planner.generation_outputs.append(minimum)
    planner._section_call(
        model,
        "infrastructure",
        requirements,
        [],
        candidates,
        None,
    )

    maximum = section("infrastructure")
    maximum["summary"] = "节" * 500
    maximum_item = maximum["work_items"][0]
    maximum_item["title"] = "题" * 180
    maximum_item["summary"] = "述" * 800
    maximum_item["acceptance_intent"] = "验" * 500
    maximum_item["gap_reason"] = "缺" * 500
    planner.generation_outputs.append(maximum)
    planner._section_call(
        model,
        "infrastructure",
        requirements,
        [],
        candidates,
        None,
    )

    for key, invalid_text, rule_code in (
        ("title", " 标题", "section.work_item_text_invalid"),
        ("summary", "述" * 801, "section.work_item_text_invalid"),
        ("acceptance_intent", "验\u0000收", "section.work_item_text_invalid"),
        ("gap_reason", "缺" * 501, "section.gap_reason_invalid"),
    ):
        invalid_text_section = section("infrastructure")
        invalid_text_section["work_items"][0][key] = invalid_text
        planner.generation_outputs.append(invalid_text_section)
        with pytest.raises(ProductPlanningError) as captured:
            planner._section_call(
                model,
                "infrastructure",
                requirements,
                [],
                candidates,
                None,
            )
        assert captured.value.code == "product_plan_response_invalid"
        assert captured.value.rule_code == rule_code

    checkpoint_cases: list[tuple[str, dict[str, object]]] = []
    bad_shape = copy.deepcopy(valid)
    bad_shape["extra"] = True
    checkpoint_cases.append(("section.checkpoint_shape_invalid", bad_shape))
    unknown_candidate = copy.deepcopy(valid)
    unknown_candidate["work_items"][0]["candidate_ref"] = "candidate_unknown"
    unknown_candidate["work_items"][0]["gap_reason"] = ""
    checkpoint_cases.append(("section.candidate_ref_unknown", unknown_candidate))
    for rule_code, value in checkpoint_cases:
        with pytest.raises(ProductPlanningError) as captured:
            planner._validate_checkpoint_section(
                value,
                "infrastructure",
                requirement_refs,
                {candidate_ref},
            )
        assert captured.value.code == "product_workspace_corrupt"
        assert captured.value.rule_code == rule_code

    public = StubPlanner(tmp_path / "public")
    select_small(public)
    public.generation_outputs.append(outline())
    for section_id in SECTION_IDS:
        value = section(section_id)
        if section_id == "infrastructure":
            value["work_items"][0]["title"] = "SECTION_PRIVATE_TEXT"
            value["work_items"][0]["delivery_wave"] = 5
        public.generation_outputs.append(value)
    failed = public.start("规划企业中台", catalog(with_capsule=False))
    serialized = json.dumps(failed, ensure_ascii=False)
    assert failed["error"]["code"] == "product_plan_response_invalid"
    assert "rule_code" not in serialized
    assert "section.delivery_wave_invalid" not in serialized
    assert "SECTION_PRIVATE_TEXT" not in serialized
    stored = next(public.root.glob("workspace_*/workspace.json")).read_text(
        encoding="utf-8"
    )
    assert "section.delivery_wave_invalid" not in stored
    assert "SECTION_PRIVATE_TEXT" not in stored
    assert '"prompt"' not in stored
    assert '"response"' not in stored


def test_unproven_parameter_count_and_probe_extra_key_fail_closed(
    tmp_path: Path,
) -> None:
    planner = StubPlanner(
        tmp_path / "unknown",
        counts={"small:1.5b": None},
    )
    planner.digests = {"small:1.5b": SMALL_DIGEST}
    listed = planner.list_models()
    assert listed["data"]["models"][0]["eligibility_reason"] == "parameter_count_unproven"
    assert (
        planner.select_model("small:1.5b", SMALL_DIGEST)["error"]["code"]
        == "product_planning_model_too_large"
    )

    bad_probe = StubPlanner(tmp_path / "bad-probe")
    bad_probe.generation_outputs.append({**probe(), "extra": True})
    assert (
        bad_probe.select_model("small:1.5b", SMALL_DIGEST)["error"]["code"]
        == "product_planning_model_probe_failed"
    )
    assert not (bad_probe.root / "model_selection.json").exists()


def test_model_digest_is_rechecked_after_each_generation(tmp_path: Path) -> None:
    class RetaggingPlanner(StubPlanner):
        retag_after_generate = False

        def _request(
            self,
            path,
            payload=None,
            cancel_check=None,
            timeout_seconds=None,
        ):
            result = super()._request(
                path,
                payload,
                cancel_check,
                timeout_seconds,
            )
            if path == "/api/generate" and self.retag_after_generate:
                self.digests["small:1.5b"] = "d" * 64
            return result

    planner = RetaggingPlanner(tmp_path / "retagged")
    select_small(planner)
    planner.generation_outputs.append(outline())
    planner.retag_after_generate = True
    result = planner.start("规划企业中台", catalog(with_capsule=False))
    assert result["error"]["code"] == "product_planning_model_digest_changed"
    stored = next(planner.root.glob("workspace_*/workspace.json"))
    workspace = json.loads(stored.read_text(encoding="utf-8"))
    assert workspace["status"] == "failed"


def test_non_loopback_and_symlink_state_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(ProductPlanningError, match="ollama_loopback_required"):
        ProductPlanner(tmp_path / "state", "http://example.com:11434")
    with pytest.raises(ProductPlanningError, match="ollama_loopback_required"):
        ProductPlanner(tmp_path / "state", "http://localhost:11434")

    target = tmp_path / "target"
    target.mkdir()
    root = tmp_path / "linked"
    root.symlink_to(target, target_is_directory=True)
    planner = StubPlanner(root)
    planner.generation_outputs.append(probe())
    result = planner.select_model("small:1.5b", SMALL_DIGEST)
    assert result["error"]["code"] == "product_workspace_symlink_forbidden"
    assert list(target.iterdir()) == []

    target = tmp_path / "ancestor-target"
    target.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(target, target_is_directory=True)
    nested = StubPlanner(linked_parent / "product_workspaces")
    workspace = nested._new_workspace(
        "goal",
        {
            "name": "small:1.5b",
            "digest": SMALL_DIGEST,
            "parameter_count": 1_543_714_304,
            "parameter_size": "1.5b",
        },
    )
    with pytest.raises(ProductPlanningError, match="product_workspace_symlink_forbidden"):
        nested._save_workspace(workspace)
    assert list(target.iterdir()) == []


def test_http_deadline_and_cancel_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read1(self, _size):
            return b"x"

    class Opener:
        calls = 0
        timeouts = []

        def open(self, *_args, **kwargs):
            self.calls += 1
            self.timeouts.append(kwargs["timeout"])
            return Response()

    opener = Opener()
    monkeypatch.setattr(product_planner_module, "build_opener", lambda *_args: opener)
    monkeypatch.setattr(product_planner_module, "HTTP_TIMEOUT_SECONDS", 12.0)
    moments = iter((0.0, 13.0))
    monkeypatch.setattr(product_planner_module.time, "monotonic", lambda: next(moments))
    planner = ProductPlanner(tmp_path / "deadline")
    with pytest.raises(ProductPlanningError) as captured:
        planner._request("/api/tags")
    assert captured.value.code == "ollama_unavailable"
    assert captured.value.rule_code == "ollama.timeout"
    moments = iter((0.0, 13.0))
    assert planner.list_models()["error"]["code"] == "ollama_unavailable"
    assert opener.timeouts == [12.0, 12.0]

    monkeypatch.setattr(product_planner_module.time, "monotonic", lambda: 0.0)
    with pytest.raises(ProductPlanningError, match="product_plan_cancelled"):
        planner._request("/api/tags", cancel_check=lambda: True)
    assert opener.calls == 2


@pytest.mark.parametrize(
    ("failure_kind", "rule_code"),
    [
        ("timeout", "ollama.timeout"),
        ("connection", "ollama.connection"),
        ("http", "ollama.http"),
    ],
)
def test_ollama_transport_failures_share_one_public_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
    rule_code: str,
) -> None:
    class Opener:
        def open(self, *_args, **_kwargs):
            if failure_kind == "timeout":
                raise TimeoutError("PRIVATE_TIMEOUT")
            if failure_kind == "connection":
                raise product_planner_module.URLError(
                    ConnectionRefusedError("PRIVATE_CONNECTION")
                )
            raise product_planner_module.HTTPError(
                "http://127.0.0.1:11434/api/tags",
                503,
                "PRIVATE_HTTP",
                None,
                None,
            )

    monkeypatch.setattr(
        product_planner_module,
        "build_opener",
        lambda *_args: Opener(),
    )
    planner = ProductPlanner(tmp_path / failure_kind)
    with pytest.raises(ProductPlanningError) as captured:
        planner._request("/api/tags")
    assert captured.value.code == "ollama_unavailable"
    assert captured.value.rule_code == rule_code
    public = planner.list_models()
    assert public == {
        "ok": False,
        "error": {
            "code": "ollama_unavailable",
            "message_key": "ollama_unavailable",
        },
    }
    assert "PRIVATE_" not in json.dumps(public)


def test_real_plan_has_four_sections_twelve_items_and_exact_allowlist_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    select_small(planner)
    queue_plan(planner)
    result = planner.start(
        "构建一个面向中小企业的多租户中台 SaaS，包含登录、角色权限、客户管理、"
        "订阅计费、审计日志、PostgreSQL、备份和私有部署。",
        catalog(),
    )
    assert result["ok"] is True
    workspace = result["data"]
    plan = workspace["plan"]
    assert [item["section_id"] for item in plan["sections"]] == list(SECTION_IDS)
    work_items = [
        item for current in plan["sections"] for item in current["work_items"]
    ]
    assert len(work_items) == 12
    assert all(item["work_item_id"].startswith("work_item_") for item in work_items)
    assert all(
        set(item)
        == {
            "work_item_id",
            "title",
            "description",
            "requirement_ids",
            "depends_on",
            "acceptance_intent",
            "capsule_bindings",
            "gap_reason",
        }
        for item in work_items
    )
    assert all(item["requirement_ids"] for item in work_items)
    wave_one = [section["work_items"][0] for section in plan["sections"]]
    wave_two = [section["work_items"][1] for section in plan["sections"]]
    wave_three = [section["work_items"][2] for section in plan["sections"]]
    assert all(item["depends_on"] == [] for item in wave_one)
    assert all(
        item["depends_on"] == [prior["work_item_id"] for prior in wave_one]
        for item in wave_two
    )
    assert all(
        item["depends_on"] == [prior["work_item_id"] for prior in wave_two]
        for item in wave_three
    )
    assert sum(len(section["gaps"]) for section in plan["sections"]) == 8
    assert {
        (binding["capsule_id"], binding["version_id"])
        for item in work_items
        for binding in item["capsule_bindings"]
    } == {("capsule_formal", "version_exact")}
    assert all(
        binding["identity_status"] == "formal_exact_version"
        and binding["selection_status"] == "model_suggested"
        and binding["review_status"] == "pending"
        for item in work_items
        for binding in item["capsule_bindings"]
    )
    assert plan["candidate_generated"] is False
    assert plan["product_generated"] is False
    persisted_workspace = planner._workspace_by_token(workspace["plan_token"])
    assert len(plan["structured_response_digests"]) == 5
    assert all(
        call["call_type"] != "catalog_match"
        and not call["call_type"].startswith("catalog_match_")
        for call in persisted_workspace["model_calls"]
    )
    assert all(
        "ref" not in item and "depends_on" not in item
        for checkpoint in persisted_workspace["section_checkpoints"]
        for item in checkpoint["section"]["work_items"]
    )
    requirement_map = {
        draft["ref"]: formal["requirement_id"]
        for draft, formal in zip(
            persisted_workspace["outline"]["requirements"],
            plan["requirements"],
            strict=True,
        )
    }
    candidate_ref = persisted_workspace["section_checkpoints"][0]["candidate_refs"][0]
    candidate_map = {candidate_ref: catalog()["capsules"][0]}
    drafts = [
        checkpoint["section"]
        for checkpoint in persisted_workspace["section_checkpoints"]
    ]
    compiled_once, waves_once = planner._compile_section_drafts(
        plan["plan_id"], drafts, requirement_map, candidate_map
    )
    compiled_twice, waves_twice = planner._compile_section_drafts(
        plan["plan_id"], copy.deepcopy(drafts), requirement_map, candidate_map
    )
    assert compiled_once == compiled_twice == plan["sections"]
    assert waves_once == waves_twice == persisted_workspace["delivery_waves"]
    assert planner._plan_digest({"sections": compiled_once}) == planner._plan_digest(
        {"sections": compiled_twice}
    )
    assert persisted_workspace["outline_input_digest"] == planner._outline_input_digest(
        persisted_workspace
    )
    assert plan["structured_response_digests"][0] == persisted_workspace[
        "outline_response_digest"
    ]
    frontend_checkpoint = persisted_workspace["section_checkpoints"][0]
    with monkeypatch.context() as legacy:
        legacy.setattr(
            product_planner_module,
            "SECTION_DRAFT_SCHEMA_VERSION",
            "product_plan_section_draft.v1",
        )
        assert frontend_checkpoint["input_digest"] == planner._section_input_digest(
            persisted_workspace,
            persisted_workspace["outline"],
            "frontend",
            frontend_checkpoint["candidate_refs"],
        )
        planner._validate_section_checkpoints(persisted_workspace)
    with monkeypatch.context() as scoped:
        scoped.setattr(
            product_planner_module,
            "PLANNING_PROMPT_VERSION",
            "reweave_product_planning_prompt.v6",
        )
        assert persisted_workspace["outline_input_digest"] != planner._outline_input_digest(
            persisted_workspace
        )
        assert persisted_workspace["section_checkpoints"][0][
            "input_digest"
        ] != planner._section_input_digest(
            persisted_workspace,
            persisted_workspace["outline"],
            "frontend",
            persisted_workspace["section_checkpoints"][0]["candidate_refs"],
        )
    assert planner.generation_outputs == []
    assert all(
        request[0] != "/api/generate"
        or "html_text" not in json.dumps(request[1])
        and "css_text" not in json.dumps(request[1])
        and "source_relpath" not in json.dumps(request[1])
        for request in planner.requests
    )

    stored = next(planner.root.glob("workspace_*/workspace.json"))
    assert stat_mode(stored) == 0o600
    raw = stored.read_text(encoding="utf-8")
    assert "raw prompt" not in raw
    assert "raw response" not in raw
    assert "workspace_id" not in json.dumps(workspace)
    recovered = StubPlanner(planner.root, counts=planner.counts)
    recovered.digests = planner.digests
    restored = recovered.get(workspace["plan_token"])
    assert restored["data"]["plan"]["canonical_digest"] == plan["canonical_digest"]


def test_wave_compiler_skips_empty_waves_and_never_links_peers() -> None:
    sections = [
        {
            "section_id": "frontend",
            "work_items": [
                {"work_item_id": "W1", "depends_on": ["untrusted"]},
                {"work_item_id": "W2", "depends_on": ["untrusted"]},
                {"work_item_id": "W3", "depends_on": ["untrusted"]},
                {"work_item_id": "W4", "depends_on": ["untrusted"]},
                {"work_item_id": "W5", "depends_on": ["untrusted"]},
            ],
        }
    ]
    waves = {"W1": 1, "W2": 1, "W3": 3, "W4": 3, "W5": 4}
    ProductPlanner._compile_wave_dependencies(sections, waves)
    items = sections[0]["work_items"]
    assert [item["depends_on"] for item in items] == [
        [],
        [],
        ["W1", "W2"],
        ["W1", "W2"],
        ["W3", "W4"],
    ]
    ProductPlanner._assert_acyclic({item["work_item_id"]: item for item in items})


def test_revision_delivery_wave_is_recompiled_by_backend(tmp_path: Path) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    select_small(planner)
    queue_plan(planner)
    created = planner.start("规划企业中台", catalog())
    plan = created["data"]["plan"]
    workspace = planner._workspace_by_token(created["data"]["plan_token"])
    target = plan["sections"][0]["work_items"][1]
    proposed, waves = planner._apply_revision_operations(
        plan,
        [
            {
                "op": "update",
                "work_item_id": target["work_item_id"],
                "section_id": "frontend",
                "title": target["title"],
                "description": target["description"],
                "requirement_ids": target["requirement_ids"],
                "delivery_wave": 4,
                "acceptance_intent": target["acceptance_intent"],
            }
        ],
        workspace["delivery_waves"],
    )
    wave_three_ids = [
        section["work_items"][2]["work_item_id"]
        for section in proposed["sections"]
    ]
    proposed_target = next(
        item
        for section in proposed["sections"]
        for item in section["work_items"]
        if item["work_item_id"] == target["work_item_id"]
    )
    assert waves[target["work_item_id"]] == 4
    assert proposed_target["depends_on"] == wave_three_ids
    planner._validate_plan(proposed)


def test_questions_require_explicit_answer_and_do_not_preselect(
    tmp_path: Path,
) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    select_small(planner)
    planner.generation_outputs.append(outline(clarification=True))
    started = planner.start("规划一个多租户管理产品", catalog(with_capsule=False))
    assert started["data"]["status"] == "needs_clarification"
    question_set = started["data"]["question_set"]
    assert len(question_set["questions"]) == 1
    assert question_set["questions"][0]["options"][0]["recommended"] is True
    assert "selected" not in json.dumps(question_set)

    invalid = planner.answer(
        started["data"]["plan_token"],
        question_set["digest"],
        [],
        catalog(with_capsule=False),
    )
    assert invalid["error"]["code"] == "product_plan_answers_invalid"

    answered_outline = outline()
    answered_outline["requirements"][0]["source"] = "planning_answer"
    planner.generation_outputs.append(answered_outline)
    planner.generation_outputs.extend(section(section_id) for section_id in SECTION_IDS)
    answered = planner.answer(
        started["data"]["plan_token"],
        question_set["digest"],
        [
            {
                "question_id": question_set["questions"][0]["question_id"],
                "source": "option",
                "value": question_set["questions"][0]["options"][0]["option_id"],
            }
        ],
        catalog(with_capsule=False),
    )
    assert answered["ok"] is True
    assert answered["data"]["status"] == "plan_review"
    assert answered["data"]["plan"]["planning_answers"]
    assert answered["data"]["plan"]["requirements"][0]["source"] == "planning_answer"
    assert (
        answered["data"]["plan"]["requirements"][0]["source_digest"]
        != answered["data"]["plan"]["goal_digest"]
    )


def test_revision_explanation_uses_one_bound_call_and_legacy_evidence_restores(
    tmp_path: Path,
) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    select_small(planner)
    queue_plan(planner)
    created = planner.start("规划企业中台", catalog())
    token = created["data"]["plan_token"]
    plan = created["data"]["plan"]
    plan_bytes = json.dumps(
        plan,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    planner.generation_outputs.append(
        {"explanation": "基础设施缺口来自当前正式能力边界。"}
    )

    explained = planner.revise(
        token,
        revision_request(
            planner,
            token,
            plan,
            "解释基础设施缺口，不要修改计划。",
            selected_action="ask_plan",
            suggested_action="propose_revision",
        ),
        catalog(),
    )

    assert explained["ok"] is True
    assert explained["data"]["revision_result"] == {
        "kind": "explanation",
        "explanation": "基础设施缺口来自当前正式能力边界。",
        "plan_changed": False,
    }
    assert (
        json.dumps(
            explained["data"]["plan"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        == plan_bytes
    )
    call = planner._workspace_by_token(token)["model_calls"][-1]
    assert call["call_type"] == "plan_revision_explanation"
    assert call["base_plan_digest"] == plan["canonical_digest"]
    assert call["revision_request_digest"]
    assert call["model_name"] == "small:1.5b"
    assert call["model_digest"] == SMALL_DIGEST
    assert call["prompt_version"] == "product_plan_revision_explanation_prompt.v1"
    assert call["schema_version"] == "product_plan_revision_explanation.v1"
    assert "classified_intent" not in call
    assert "intent_response_digest" not in call
    assert "branch_outcome" not in call

    legacy_workspace = planner._workspace_by_token(token)
    legacy_intent_digest = "d" * 64
    common = {
        "input_bytes": call["input_bytes"],
        "output_bytes": call["output_bytes"],
        "duration_ms": call["duration_ms"],
        "base_plan_digest": call["base_plan_digest"],
        "revision_request_digest": call["revision_request_digest"],
        "model_name": call["model_name"],
        "model_digest": call["model_digest"],
    }
    legacy_workspace["model_calls"][-1:] = [
        {
            **common,
            "call_type": "plan_revision_intent",
            "structured_response_digest": legacy_intent_digest,
            "prompt_version": "product_plan_revision_intent_prompt.v1",
            "schema_version": "product_plan_revision_intent.v1",
        },
        {
            **common,
            "call_type": "plan_revision_explanation",
            "structured_response_digest": call["structured_response_digest"],
            "prompt_version": "product_plan_revision_explanation_prompt.v1",
            "schema_version": "product_plan_revision_explanation.v1",
            "classified_intent": "explanation",
            "intent_response_digest": legacy_intent_digest,
        },
    ]
    planner._validate_workspace(legacy_workspace)
    planner._save_workspace(legacy_workspace)
    restored = ProductPlanner(planner.root)._workspace_by_token(token)
    assert [call["call_type"] for call in restored["model_calls"][-2:]] == [
        "plan_revision_intent",
        "plan_revision_explanation",
    ]


@pytest.mark.parametrize(
    "output",
    [
        {
            "explanation": "REVISION_PRIVATE_TEXT",
            "questions": outline(clarification=True)["questions"],
            "operations": [],
        },
        {"explanation": "REVISION_PRIVATE_TEXT", "operations": []},
        {"explanation": "REVISION_PRIVATE_TEXT", "questions": []},
        {"operations": []},
        {"questions": outline(clarification=True)["questions"]},
        {"explanation": "REVISION_PRIVATE_TEXT", "kind": "explanation"},
        {"explanation": "REVISION_PRIVATE_TEXT", "intent": "explanation"},
        {"explanation": "REVISION_PRIVATE_TEXT", "outcome": "explanation"},
    ],
)
def test_revision_single_response_invalid_shapes_fail_closed_without_leaking(
    tmp_path: Path,
    output: dict[str, object],
) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    select_small(planner)
    queue_plan(planner)
    created = planner.start("规划企业中台", catalog())
    plan = created["data"]["plan"]
    calls_before = sum(path == "/api/generate" for path, _payload in planner.requests)
    planner.generation_outputs.append(copy.deepcopy(output))

    failed = planner.revise(
        created["data"]["plan_token"],
        revision_request(
            planner,
            created["data"]["plan_token"],
            plan,
            "REVISION_PRIVATE_TEXT",
            selected_action="propose_revision",
        ),
        catalog(),
    )

    assert failed["error"]["code"] == "product_plan_response_invalid"
    calls_after = sum(path == "/api/generate" for path, _payload in planner.requests)
    assert calls_after - calls_before == 2
    assert failed["data"]["plan"] == plan
    assert failed["data"]["plan_diff"] is None
    public = json.dumps(failed, ensure_ascii=False)
    stored = next(planner.root.glob("workspace_*/workspace.json")).read_text(
        encoding="utf-8"
    )
    assert "REVISION_PRIVATE_TEXT" not in public
    assert "REVISION_PRIVATE_TEXT" not in stored
    assert '"prompt"' not in stored
    assert '"response"' not in stored


def test_revision_is_pending_until_accept_and_reject_is_byte_stable(
    tmp_path: Path,
) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    select_small(planner)
    queue_plan(planner)
    created = planner.start("规划企业中台", catalog())
    token = created["data"]["plan_token"]
    plan = created["data"]["plan"]
    original_digest = plan["canonical_digest"]
    first_item = plan["sections"][0]["work_items"][0]
    queue_revision_update(
        planner,
        title="更新后的前端工作台",
        summary="调整可审阅的前端交付意图。",
        acceptance_intent="键盘和状态恢复均可验收。",
    )
    proposed = planner.revise(
        token,
        revision_request(
            planner,
            token,
            plan,
            "调整前端工作台",
            selected_action="propose_revision",
        ),
        catalog(),
    )
    assert proposed["data"]["status"] == "plan_diff_review"
    assert proposed["data"]["plan"]["canonical_digest"] == original_digest
    assert proposed["data"]["target_section_id"] == "frontend"
    assert proposed["data"]["plan_diff"]["schema_version"] == "product_plan_diff.v2"
    assert proposed["data"]["plan_diff"]["target_section_id"] == "frontend"
    assert proposed["data"]["plan_diff"]["updated"] == [first_item["work_item_id"]]
    revision_calls = planner._workspace_by_token(token)["model_calls"][-1:]
    assert [call["call_type"] for call in revision_calls] == ["plan_revision_proposal"]
    assert revision_calls[0]["prompt_version"] == "product_plan_revision_proposal_prompt.v2"
    assert revision_calls[0]["schema_version"] == "product_plan_revision_proposal.v3"
    proposed_digests = planner._workspace_by_token(token)["pending_diff"][
        "proposed_plan"
    ]["structured_response_digests"]
    assert proposed_digests[-1:] == [
        call["structured_response_digest"] for call in revision_calls
    ]
    changes = proposed["data"]["plan_diff"]["changes"]
    assert len(changes) == 1
    assert changes[0]["before"]["item"]["title"] == first_item["title"]
    assert changes[0]["after"]["item"]["title"] == "更新后的前端工作台"

    pending_workspace = planner._workspace_by_token(token)
    tampered = copy.deepcopy(pending_workspace["pending_diff"])
    tampered["public_diff"]["changes"][0]["after"]["item"]["title"] = "未审阅替换"
    with pytest.raises(ProductPlanningError, match="product_plan_diff_invalid"):
        planner._validate_pending_diff(pending_workspace["plan"], tampered)

    wrong_scope = copy.deepcopy(pending_workspace["pending_diff"])
    wrong_scope["target_section_id"] = "data"
    wrong_scope["public_diff"] = planner._plan_diff(
        pending_workspace["plan"],
        wrong_scope["proposed_plan"],
        "data",
    )
    with pytest.raises(ProductPlanningError) as scoped_error:
        planner._validate_pending_diff(pending_workspace["plan"], wrong_scope)
    assert scoped_error.value.code == "product_plan_diff_invalid"
    assert scoped_error.value.rule_code == "diff.target_section_mismatch"

    stale_accept = planner.revise(
        token,
        {
            "action": "accept_diff",
            "base_plan_digest": proposed["data"]["plan_diff"]["base_plan_digest"],
            "diff_digest": "0" * 64,
            "reviewed_plan": proposed["data"]["plan"],
            "reviewed_diff": proposed["data"]["plan_diff"],
        },
        catalog(),
    )
    assert stale_accept["error"]["code"] == "product_plan_diff_stale"
    second_request = planner.revise(
        token,
        {
            "action": "request",
            "message": "覆盖尚未审阅的修订",
            "reviewed_plan": proposed["data"]["plan"],
            "selected_action": "propose_revision",
            "target_section_id": "frontend",
            "suggestion_receipt": "suggestion_receipt_" + "0" * 48,
            "suggestion_digest": "0" * 64,
        },
        catalog(),
    )
    assert second_request["error"]["code"] == "product_plan_diff_pending"

    altered_review = copy.deepcopy(proposed["data"]["plan_diff"])
    altered_review["changes"][0]["after"]["item"]["title"] = "未审阅替换"
    mismatched_review = planner.revise(
        token,
        {
            "action": "accept_diff",
            "base_plan_digest": proposed["data"]["plan_diff"]["base_plan_digest"],
            "diff_digest": proposed["data"]["plan_diff"]["diff_digest"],
            "reviewed_plan": proposed["data"]["plan"],
            "reviewed_diff": altered_review,
        },
        catalog(),
    )
    assert mismatched_review["error"]["code"] == "product_plan_diff_stale"

    rejected = planner.revise(
        token,
        {
            "action": "reject_diff",
            "base_plan_digest": proposed["data"]["plan_diff"]["base_plan_digest"],
            "diff_digest": proposed["data"]["plan_diff"]["diff_digest"],
            "reviewed_plan": proposed["data"]["plan"],
            "reviewed_diff": proposed["data"]["plan_diff"],
        },
        catalog(),
    )
    assert rejected["data"]["plan"]["canonical_digest"] == original_digest

    queue_revision_update(
        planner,
        title="更新后的前端工作台",
        summary="调整可审阅的前端交付意图。",
        acceptance_intent="键盘和状态恢复均可验收。",
    )
    reproposed = planner.revise(
        token,
        revision_request(
            planner,
            token,
            rejected["data"]["plan"],
            "再次调整前端工作台",
            selected_action="propose_revision",
        ),
        catalog(),
    )
    accepted = planner.revise(
        token,
        {
            "action": "accept_diff",
            "base_plan_digest": reproposed["data"]["plan_diff"]["base_plan_digest"],
            "diff_digest": reproposed["data"]["plan_diff"]["diff_digest"],
            "reviewed_plan": reproposed["data"]["plan"],
            "reviewed_diff": reproposed["data"]["plan_diff"],
        },
        catalog(),
    )
    assert accepted["data"]["plan"]["plan_version"] == 2
    assert accepted["data"]["plan"]["parent_plan_digest"] == original_digest
    assert accepted["data"]["plan"]["canonical_digest"] != original_digest


def test_revision_question_set_v2_is_read_only_and_stale_on_answer(
    tmp_path: Path,
) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    select_small(planner)
    queue_plan(planner)
    created = planner.start("规划企业中台", catalog())
    token = created["data"]["plan_token"]
    question_set = seed_revision_question_set(
        planner,
        token,
        feedback="调整租户隔离",
    )
    workspace_path = next(planner.root.glob("workspace_*/workspace.json"))
    before = workspace_path.read_bytes()
    model_calls_before = len(planner._workspace_by_token(token)["model_calls"])
    restored = StubPlanner(planner.root)
    assert restored.get(token)["data"]["question_set"] == question_set
    result = restored.answer(
        token,
        question_set["digest"],
        [
            {
                "question_id": question_set["questions"][0]["question_id"],
                "source": "option",
                "value": question_set["questions"][0]["options"][0]["option_id"],
            }
        ],
        catalog(),
    )
    assert result["error"]["code"] == "product_plan_question_set_stale"
    assert workspace_path.read_bytes() == before
    assert len(restored._workspace_by_token(token)["model_calls"]) == model_calls_before


def test_revision_question_set_binds_and_restores_target_section(
    tmp_path: Path,
) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    select_small(planner)
    queue_plan(planner)
    created = planner.start("规划企业中台", catalog())
    token = created["data"]["plan_token"]
    question_set = seed_revision_question_set(
        planner,
        token,
        target_section_id="data",
        feedback="调整数据备份策略",
    )
    requested = planner.get(token)
    assert question_set["schema_version"] == "product_plan_question_set.v2"
    assert question_set["target_section_id"] == "data"
    assert requested["data"]["target_section_id"] == "data"
    same_questions_other_target = planner._question_set(
        planner._validate_questions(outline(clarification=True)["questions"]),
        purpose="revision",
        target_section_id="frontend",
    )
    assert same_questions_other_target["digest"] != question_set["digest"]

    restored = StubPlanner(planner.root)
    result = restored.answer(
        token,
        question_set["digest"],
        [
            {
                "question_id": question_set["questions"][0]["question_id"],
                "source": "option",
                "value": question_set["questions"][0]["options"][0]["option_id"],
            }
        ],
        catalog(),
    )
    assert result["error"]["code"] == "product_plan_question_set_stale"


def test_legacy_revision_question_set_is_readable_but_not_answerable(
    tmp_path: Path,
) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    select_small(planner)
    queue_plan(planner)
    created = planner.start("规划企业中台", catalog())
    token = created["data"]["plan_token"]
    question_set = seed_revision_question_set(
        planner,
        token,
        target_section_id="data",
        feedback="调整数据备份策略",
    )
    current = planner._workspace_by_token(token)
    legacy = copy.deepcopy(question_set)
    legacy["schema_version"] = "product_plan_question_set.v1"
    legacy.pop("target_section_id")
    legacy["digest"] = product_planner_module._digest(
        {key: value for key, value in legacy.items() if key != "digest"}
    )
    current["question_history"] = [legacy["digest"]]
    current["current_question_set"] = legacy
    with planner._lock:
        planner._save_workspace(current)
    workspace_path = next(planner.root.glob("workspace_*/workspace.json"))
    before = workspace_path.read_bytes()

    restored = StubPlanner(planner.root)
    assert restored.get(token)["data"]["question_set"] == legacy
    result = restored.answer(
        token,
        legacy["digest"],
        [
            {
                "question_id": legacy["questions"][0]["question_id"],
                "source": "option",
                "value": legacy["questions"][0]["options"][0]["option_id"],
            }
        ],
        catalog(),
    )
    assert result["error"]["code"] == "product_plan_question_set_stale"
    assert workspace_path.read_bytes() == before


def test_diff_accept_revalidates_current_capsule_eligibility(tmp_path: Path) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    select_small(planner)
    queue_plan(planner)
    created = planner.start("规划企业中台", catalog())
    queue_revision_update(
        planner,
        title="待接受的前端工作台",
        summary="接受前必须复核正式胶囊。",
        acceptance_intent="过期胶囊使修订失败关闭。",
    )
    proposed = planner.revise(
        created["data"]["plan_token"],
        revision_request(
            planner,
            created["data"]["plan_token"],
            created["data"]["plan"],
            "调整前端工作台",
            selected_action="propose_revision",
        ),
        catalog(),
    )
    diff = proposed["data"]["plan_diff"]
    rejected = planner.revise(
        created["data"]["plan_token"],
        {
            "action": "accept_diff",
            "base_plan_digest": diff["base_plan_digest"],
            "diff_digest": diff["diff_digest"],
            "reviewed_plan": proposed["data"]["plan"],
            "reviewed_diff": diff,
        },
        catalog(with_capsule=False),
    )
    assert rejected["error"]["code"] == "product_plan_capsule_stale"
    workspace = rejected["data"]["workspace"]
    assert workspace["plan"]["canonical_digest"] == created["data"]["plan"]["canonical_digest"]
    assert workspace["plan_diff"] is None
    assert workspace["status"] == "failed"


def test_revision_rejects_a_no_op_modification(tmp_path: Path) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    select_small(planner)
    queue_plan(planner)
    created = planner.start("规划企业中台", catalog())
    queue_revision_update(
        planner,
        title="已经审阅的前端工作台",
        summary="保持确定性计划展示。",
        acceptance_intent="键盘与状态恢复均通过。",
    )
    proposed = planner.revise(
        created["data"]["plan_token"],
        revision_request(
            planner,
            created["data"]["plan_token"],
            created["data"]["plan"],
            "更新前端工作台",
            selected_action="propose_revision",
        ),
        catalog(),
    )
    diff = proposed["data"]["plan_diff"]
    accepted = planner.revise(
        created["data"]["plan_token"],
        {
            "action": "accept_diff",
            "base_plan_digest": diff["base_plan_digest"],
            "diff_digest": diff["diff_digest"],
            "reviewed_plan": proposed["data"]["plan"],
            "reviewed_diff": diff,
        },
        catalog(),
    )
    item = accepted["data"]["plan"]["sections"][0]["work_items"][0]
    queue_revision_update(
        planner,
        title=item["title"],
        summary=item["description"],
        acceptance_intent=item["acceptance_intent"],
    )
    rule_codes: list[str | None] = []
    original_planning_error = planner._planning_error

    def observed_planning_error(workspace, exc):
        rule_codes.append(exc.rule_code)
        return original_planning_error(workspace, exc)

    planner._planning_error = observed_planning_error  # type: ignore[method-assign]
    result = planner.revise(
        created["data"]["plan_token"],
        revision_request(
            planner,
            created["data"]["plan_token"],
            accepted["data"]["plan"],
            "保持内容不变",
            selected_action="propose_revision",
        ),
        catalog(),
    )
    assert result["error"]["code"] == "product_plan_diff_invalid"
    assert rule_codes == ["diff.no_effect"]
    assert "diff.no_effect" not in json.dumps(result)
    stored = next(planner.root.glob("workspace_*/workspace.json")).read_text(
        encoding="utf-8"
    )
    assert "diff.no_effect" not in stored


def test_confirmation_revalidates_only_exact_bound_capsules(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    select_small(planner)
    queue_plan(planner)
    created = planner.start("规划企业中台", catalog())
    token = created["data"]["plan_token"]
    digest = created["data"]["plan"]["canonical_digest"]

    altered_review = copy.deepcopy(created["data"]["plan"])
    altered_review["sections"][0]["work_items"][0]["title"] = "未审阅替换"
    rejected_review = planner.confirm(token, digest, altered_review, catalog())
    assert rejected_review["error"]["code"] == "product_plan_confirmation_stale"

    stale = planner.confirm(
        token, digest, created["data"]["plan"], catalog(with_capsule=False)
    )
    assert stale["error"]["code"] == "product_plan_capsule_stale"
    assert stale["data"]["stale_work_items"]

    monkeypatch.setattr(
        product_planner_module,
        "_now",
        lambda: "2026-07-24T00:00:00Z",
    )
    compatibility_root = tmp_path / "compatibility_workspaces"
    shutil.copytree(planner.root, compatibility_root)
    request_count = len(planner.requests)
    confirmed = planner.confirm(token, digest, created["data"]["plan"], catalog())
    formal_capsule = catalog()["capsules"][0]
    compatibility = StubPlanner(compatibility_root).confirm(
        token,
        digest,
        created["data"]["plan"],
        catalog(),
        [
            {
                key: formal_capsule[key]
                for key in (
                    "capsule_id",
                    "version_id",
                    "canonical_hash",
                    "capability_key",
                    "capability_kind",
                )
            }
            | {"input_contract": {}, "output_contract": {}}
        ],
    )
    assert confirmed["ok"] is True
    assert compatibility["ok"] is True, compatibility
    assert json.dumps(
        confirmed["data"]["confirmation"],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ) == json.dumps(
        compatibility["data"]["confirmation"],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    assert len(planner.requests) == request_count
    receipt = confirmed["data"]["confirmation"]
    assert receipt["schema_version"] == "product_plan_confirmation.v1"
    assert "parameter_binding" not in receipt
    assert receipt["product_generated"] is False
    assert receipt["candidate_generated"] is False
    assert receipt["product_usage_written"] is False
    assert receipt["capsule_revalidation"]

    repeated = planner.confirm(token, digest, created["data"]["plan"], catalog())
    assert repeated["data"]["confirmation"] == receipt
    wrong_digest = planner.confirm(
        token, "0" * 64, created["data"]["plan"], catalog()
    )
    assert wrong_digest["error"]["code"] == "product_plan_confirmation_stale"

    stale_repeat = planner.confirm(
        token, digest, created["data"]["plan"], catalog(with_capsule=False)
    )
    assert stale_repeat["error"]["code"] == "product_plan_capsule_stale"


def test_parameter_offer_precedes_atomic_confirmation_and_cannot_be_rewritten(
    tmp_path: Path,
) -> None:
    root = tmp_path / "product_workspaces"
    planner = StubPlanner(root)
    select_small(planner)
    queue_plan(planner)
    created = planner.start("规划参数化报价", catalog())
    token = created["data"]["plan_token"]
    plan = copy.deepcopy(created["data"]["plan"])

    rows = []
    facts = []
    contracts = {
        "presentation": (
            {
                "schema": "data_contract.v1",
                "type": "object",
                "properties": {
                    "total": {"type": "integer", "minimum": 10, "maximum": 100}
                },
                "required": ["total"],
                "additional_properties": False,
            },
            {"schema": "no_output.v1"},
        ),
        "interaction": (
            {
                "schema": "data_contract.v1",
                "type": "object",
                "properties": {},
                "required": [],
                "additional_properties": False,
            },
            {
                "schema": "event_outputs.v1",
                "events": {
                    "calculate_requested": {
                        "schema": "data_contract.v1",
                        "type": "object",
                        "properties": {
                            "quantity": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 10,
                            }
                        },
                        "required": ["quantity"],
                        "additional_properties": False,
                    }
                },
            },
        ),
        "computation": (
            {
                "schema": "data_contract.v1",
                "type": "object",
                "properties": {
                    "quantity": {"type": "integer", "minimum": 1, "maximum": 10},
                    "unit_price": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100,
                    },
                },
                "required": ["quantity", "unit_price"],
                "additional_properties": False,
            },
            {
                "schema": "data_contract.v1",
                "type": "object",
                "properties": {
                    "total": {"type": "integer", "minimum": 10, "maximum": 100}
                },
                "required": ["total"],
                "additional_properties": False,
            },
        ),
    }
    for index, kind in enumerate(
        ("presentation", "interaction", "computation"),
        start=1,
    ):
        row = {
            "capsule_id": f"capsule_parameter_{kind}",
            "version_id": f"version_parameter_{kind}_1",
            "display_name": f"参数化 {kind}",
            "capability_key": "parameterized_quote",
            "role_key": kind,
            "variant_key": "default",
            "capability_kind": kind,
            "canonical_hash": str(index) * 64,
            "identity_status": "formal_exact_version",
        }
        rows.append(row)
        facts.append(
            {
                key: row[key]
                for key in (
                    "capsule_id",
                    "version_id",
                    "canonical_hash",
                    "capability_key",
                    "capability_kind",
                )
            }
            | {
                "input_contract": contracts[kind][0],
                "output_contract": contracts[kind][1],
            }
        )
    by_kind = {row["capability_kind"]: row for row in rows}
    chosen = ("presentation", "interaction", "computation", "presentation")
    for section, kind in zip(plan["sections"], chosen, strict=True):
        binding = section["work_items"][0]["capsule_bindings"][0]
        row = by_kind[kind]
        binding.update(
            {
                "capsule_id": row["capsule_id"],
                "version_id": row["version_id"],
                "display_name": row["display_name"],
                "capability_kind": row["capability_kind"],
                "canonical_hash": row["canonical_hash"],
            }
        )
    plan["canonical_digest"] = planner._plan_digest(plan)
    workspace = planner._workspace_by_token(token)
    workspace["plan"] = plan
    planner._save_workspace(workspace)
    formal_catalog = {"warehouse_revision": 8, "capsules": rows}

    required = planner.confirm(
        token,
        plan["canonical_digest"],
        plan,
        formal_catalog,
        facts,
    )
    assert required["error"]["code"] == "parameter_confirmation_required"
    offer = required["data"]["parameter_offer"]
    assert offer["plan_digest"] == plan["canonical_digest"]
    assert [row["input_field"] for row in offer["bindings"]] == ["unit_price"]
    assert planner.get(token)["data"]["status"] == "plan_review"
    assert planner.get(token)["data"]["confirmation"] is None

    request = {
        "schema_version": "parameterized_execution_confirmation.v1",
        "offer_digest": offer["offer_digest"],
        "values": [
            {
                "binding_id": offer["bindings"][0]["binding_id"],
                "value": 10,
            }
        ],
    }
    confirmed = planner.confirm(
        token,
        plan["canonical_digest"],
        plan,
        formal_catalog,
        facts,
        request,
    )
    assert confirmed["ok"] is True
    receipt = confirmed["data"]["confirmation"]
    assert receipt["schema_version"] == "product_plan_confirmation.v2"
    assert receipt["parameter_binding"]["bindings"][0]["value"] == 10
    assert receipt["receipt_digest"] == product_planner_module._digest(
        {key: value for key, value in receipt.items() if key != "receipt_digest"}
    )
    assert (
        planner.confirm(
            token,
            plan["canonical_digest"],
            plan,
            formal_catalog,
            facts,
            request,
        )["data"]["confirmation"]
        == receipt
    )
    recovery_root = tmp_path / "parameterized_recovery"
    shutil.copytree(root, recovery_root)
    recovery_planner = StubPlanner(recovery_root)
    interrupted = recovery_planner._workspace_by_token(token)
    interrupted["status"] = "plan_review"
    interrupted["confirmation"] = None
    recovery_planner._save_workspace(interrupted)
    recovered_snapshot = recovery_planner.confirm(
        token,
        plan["canonical_digest"],
        plan,
        formal_catalog,
        facts,
        request,
    )
    assert recovered_snapshot["ok"] is True
    assert recovered_snapshot["data"]["confirmation"] == receipt

    acceptance_confirmation = build_candidate_acceptance_confirmation(
        plan,
        receipt,
        [
            {
                "requirement_ids": [plan["requirements"][0]["requirement_id"]],
                "input": {"quantity": 3},
                "expected_output": {"total": 30},
            }
        ],
        contracts["interaction"][1]["events"]["calculate_requested"],
        contracts["computation"][1],
        "2026-07-24T00:00:00Z",
    )
    stored = planner.confirm_candidate_acceptance(
        token,
        acceptance_confirmation,
    )
    assert stored["ok"] is True
    restarted = StubPlanner(root)
    restored_acceptance = restarted.get_candidate_acceptance_confirmation(token)
    assert restored_acceptance["ok"] is True
    assert (
        restored_acceptance["data"]["acceptance_confirmation"]
        == acceptance_confirmation
    )
    tampered = copy.deepcopy(acceptance_confirmation)
    tampered["cases"][0]["expected_output"]["total"] = 31
    assert (
        restarted.confirm_candidate_acceptance(token, tampered)["error"]["code"]
        == "candidate_acceptance_confirmation_invalid"
    )
    changed = copy.deepcopy(request)
    changed["values"][0]["value"] = 11
    assert (
        planner.confirm(
            token,
            plan["canonical_digest"],
            plan,
            formal_catalog,
            facts,
            changed,
        )["error"]["code"]
        == "product_plan_confirmation_conflict"
    )
    restored = StubPlanner(root).get(token, formal_catalog, facts)
    assert restored["ok"] is True
    assert restored["data"]["confirmation"] == receipt
    tampered = copy.deepcopy(receipt)
    tampered_binding = tampered["parameter_binding"]
    tampered_binding["bindings"][0]["capsule_id"] = "capsule_outside_plan"
    tampered_binding["canonical_digest"] = product_planner_module._digest(
        {
            key: value
            for key, value in tampered_binding.items()
            if key != "canonical_digest"
        }
    )
    tampered["receipt_digest"] = product_planner_module._digest(
        {key: value for key, value in tampered.items() if key != "receipt_digest"}
    )
    with pytest.raises(
        ProductPlanningError,
        match="product_workspace_corrupt",
    ):
        planner._validate_stored_confirmation(tampered, plan)
    tampered_value = copy.deepcopy(receipt)
    value_binding = tampered_value["parameter_binding"]
    value_binding["bindings"][0]["value"] = 1_000
    value_binding["bindings"][0]["value_digest"] = product_planner_module._digest(
        1_000
    )
    value_binding["canonical_digest"] = product_planner_module._digest(
        {
            key: value
            for key, value in value_binding.items()
            if key != "canonical_digest"
        }
    )
    tampered_value["receipt_digest"] = product_planner_module._digest(
        {
            key: value
            for key, value in tampered_value.items()
            if key != "receipt_digest"
        }
    )
    with pytest.raises(
        ProductPlanningError,
        match="product_workspace_corrupt",
    ):
        planner._validate_stored_confirmation(tampered_value, plan, offer)


def test_workspace_restore_revalidates_only_relevant_exact_capsules(
    tmp_path: Path,
) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    select_small(planner)
    queue_plan(planner)
    created = planner.start("规划企业中台", catalog())
    token = created["data"]["plan_token"]
    digest = created["data"]["plan"]["canonical_digest"]

    unrelated_revision = catalog()
    unrelated_revision["warehouse_revision"] = 999
    restored = planner.get(token, unrelated_revision)
    assert restored["ok"] is True
    assert restored["data"]["status"] == "plan_review"

    confirmed = planner.confirm(token, digest, created["data"]["plan"], catalog())
    assert confirmed["data"]["status"] == "confirmed"
    restored_confirmed = planner.get(token, unrelated_revision)
    assert restored_confirmed["data"]["status"] == "confirmed"

    stale = planner.get(token, catalog(with_capsule=False))
    assert stale["error"]["code"] == "product_plan_capsule_stale"
    assert stale["data"]["stale_work_items"]
    assert stale["data"]["workspace"]["status"] == "failed"
    assert stale["data"]["workspace"]["confirmation"] is None
    persisted = planner.get(token)
    assert persisted["data"]["status"] == "failed"
    assert persisted["data"]["confirmation"] is None


def test_unknown_dependency_cycle_and_bad_workspace_are_isolated(tmp_path: Path) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    select_small(planner)
    queue_plan(planner)
    created = planner.start("规划企业中台", catalog())
    plan = created["data"]["plan"]
    broken = copy.deepcopy(plan)
    broken["sections"][0]["work_items"][0]["depends_on"] = ["work_item_unknown"]
    broken["canonical_digest"] = planner._plan_digest(broken)
    with pytest.raises(ProductPlanningError, match="product_plan_dependency_invalid"):
        planner._validate_plan(broken)

    cycle = copy.deepcopy(plan)
    first, second = cycle["sections"][0]["work_items"][:2]
    first["depends_on"] = [second["work_item_id"]]
    second["depends_on"] = [first["work_item_id"]]
    cycle["canonical_digest"] = planner._plan_digest(cycle)
    with pytest.raises(ProductPlanningError, match="product_plan_dependency_cycle"):
        planner._validate_plan(cycle)

    good = planner._new_workspace("另一个计划", planner._selected_model(check_current=False))
    planner._save_workspace(good)
    bad_file = next(
        path
        for path in planner.root.glob("workspace_*/workspace.json")
        if path.parent.name != good["workspace_id"]
    )
    bad_file.write_text("{bad-json", encoding="utf-8")
    summaries = planner.list_summaries()
    assert summaries["ok"] is True
    assert [row["plan_token"] for row in summaries["data"]["summaries"]] == [
        good["plan_token"]
    ]


def test_nested_workspace_schema_and_directory_identity_fail_closed(tmp_path: Path) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    select_small(planner)
    queue_plan(planner)
    created = planner.start("规划企业中台", catalog())
    stored = next(planner.root.glob("workspace_*/workspace.json"))
    original = json.loads(stored.read_text(encoding="utf-8"))

    nested_extra = copy.deepcopy(original)
    nested_extra["plan"]["path"] = "/private/should-not-project"
    nested_extra["plan"]["canonical_digest"] = planner._plan_digest(nested_extra["plan"])
    stored.write_text(json.dumps(nested_extra), encoding="utf-8")
    assert planner.get(created["data"]["plan_token"])["error"]["code"] == "product_plan_workspace_not_found"

    wrong_directory = copy.deepcopy(original)
    wrong_directory["workspace_id"] = "workspace_" + "f" * 32
    stored.write_text(json.dumps(wrong_directory), encoding="utf-8")
    assert planner.list_summaries()["data"]["summaries"] == []


def test_confirmation_snapshot_is_published_before_public_confirmed_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    select_small(planner)
    queue_plan(planner)
    created = planner.start("规划企业中台", catalog())
    token = created["data"]["plan_token"]
    digest = created["data"]["plan"]["canonical_digest"]
    original_save = planner._save_workspace

    def fail_confirmed(workspace):
        if workspace["status"] == "confirmed":
            raise ProductPlanningError("forced_workspace_failure")
        original_save(workspace)

    monkeypatch.setattr(planner, "_save_workspace", fail_confirmed)
    result = planner.confirm(token, digest, created["data"]["plan"], catalog())
    assert result["error"]["code"] == "forced_workspace_failure"
    monkeypatch.setattr(planner, "_save_workspace", original_save)
    restored = planner.get(token)
    assert restored["data"]["status"] == "plan_review"
    assert restored["data"]["confirmation"] is None
    retried = planner.confirm(token, digest, created["data"]["plan"], catalog())
    assert retried["ok"] is True
    assert retried["data"]["status"] == "confirmed"


def stat_mode(path: Path) -> int:
    return os.stat(path).st_mode & 0o777
