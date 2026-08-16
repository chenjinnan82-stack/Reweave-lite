from __future__ import annotations

import copy
import hashlib
import inspect
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import pimos_lite.reweave_product_planner as product_planner_module
from pimos_lite.reweave_capsule_store import canonicalize_capsule
from pimos_lite.reweave_plan_execution import (
    PlanExecutionError,
    build_candidate_acceptance_confirmation,
    canonical_digest,
    compile_multi_computation_plan_execution,
)
from pimos_lite.reweave_product_planner import (
    FORMAL_MODEL_TIMEOUT_SECONDS,
    HISTORICAL_PLANNING_PROMPT_VERSION,
    HTTP_TIMEOUT_SECONDS,
    LEGACY_LOCKED_BLUEPRINT_PROMPT_VERSION,
    LEGACY_LOCKED_BLUEPRINT_WORKSPACE_SCHEMA_VERSION,
    LEGACY_PLANNING_RULES_VERSION,
    MAX_MODEL_PARAMETERS,
    PLANNING_RULES_VERSION,
    ProductPlanner,
    ProductPlanningError,
    SECTION_PLANNING_RULES_VERSION,
    SECTION_IDS,
)
from tests.test_reweave_phase5_generation import _capsule_payload


SMALL_DIGEST = "a" * 64
LARGE_DIGEST = "b" * 64


class StubPlanner(ProductPlanner):
    def __init__(
        self,
        root: Path,
        *,
        counts: dict[str, int | None] | None = None,
        model_infos: dict[str, dict[str, object]] | None = None,
        experience_injection_enabled: bool | None = None,
    ) -> None:
        super().__init__(
            root,
            experience_injection_enabled=experience_injection_enabled,
        )
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


def gap_blueprint() -> dict[str, object]:
    requirement_by_section = {
        "frontend": "r_frontend",
        "backend": "r_backend",
        "data": "r_data",
        "infrastructure": "r_infra",
    }
    return {
        "schema_version": "product_plan_blueprint.v2",
        "sections": {
            section_id: {
                "applicability": "applicable",
                "summary": f"{section_id} 当前存在真实能力缺口。",
            }
            for section_id in SECTION_IDS
        },
        "selection": {"offer_ref": "", "assignments": {}},
        "gaps": [
            {
                "section_id": section_id,
                "requirement_refs": [requirement_by_section[section_id]],
                "title": f"{section_id} 能力缺口",
                "reason": "当前正式目录没有覆盖该用户可见能力。",
            }
            for section_id in SECTION_IDS
        ],
    }


def no_composition_selection() -> dict[str, str]:
    return {
        "schema_version": "product_composition_selection.v1",
        "capability_key": "",
    }


def single_quote_gap_blueprint() -> dict[str, object]:
    return {
        "schema_version": "product_plan_blueprint.v2",
        "sections": {
            section_id: {
                "applicability": (
                    "applicable"
                    if section_id == "backend"
                    else "not_applicable"
                ),
                "summary": (
                    "缺少一个可验证的报价规则计算。"
                    if section_id == "backend"
                    else "本产品不需要这一独立层。"
                ),
            }
            for section_id in SECTION_IDS
        },
        "selection": {"offer_ref": "", "assignments": {}},
        "gaps": [
            {
                "title": "报价规则计算",
                "reason": "当前正式目录无法把数量转换为完整报价输入。",
            }
        ],
    }


def time_outline() -> dict[str, object]:
    return {
        "schema_version": "product_plan_outline.v1",
        "product_name": "本地时间换算工具",
        "language": "zh",
        "requirements": [
            {
                "ref": "r_conversion",
                "statement": (
                    "输入整数小时，依次转换为分钟和秒，并只展示最终秒数。"
                ),
                "source": "goal",
            }
        ],
        "needs_clarification": False,
        "questions": [],
    }


def quote_outline() -> dict[str, object]:
    return {
        "schema_version": "product_plan_outline.v1",
        "product_name": "本地批量折扣报价工具",
        "language": "zh",
        "requirements": [
            {
                "ref": "r_quote",
                "statement": "输入数量，计算折扣单价与总价，并只展示最终总价。",
                "source": "goal",
            }
        ],
        "needs_clarification": False,
        "questions": [],
    }


def workflow_state_outline() -> dict[str, object]:
    return {
        "schema_version": "product_plan_outline.v1",
        "product_name": "本地事项分类工具",
        "language": "zh",
        "requirements": [
            {
                "ref": "r_input",
                "statement": "用户选择事项是否重要、是否紧急。",
                "source": "goal",
            },
            {
                "ref": "r_classify",
                "statement": "系统根据两个选择对事项进行分类。",
                "source": "goal",
            },
            {
                "ref": "r_rules",
                "statement": "系统使用已确认的四种分类规则。",
                "source": "goal",
            },
            {
                "ref": "r_result",
                "statement": "系统只展示最终分类结果。",
                "source": "goal",
            },
            {
                "ref": "r_local",
                "statement": "所有处理均在本机完成，不依赖网络服务。",
                "source": "goal",
            },
        ],
        "needs_clarification": False,
        "questions": [],
    }


def workflow_state_complete_catalog() -> dict[str, object]:
    value = finite_enum_gap_catalog()
    interaction = value["capsules"][0]
    presentation = value["capsules"][1]
    value["warehouse_revision"] = 73
    value["capsules"].insert(
        1,
        {
            "capsule_id": "capsule_workflow_state_classifier",
            "version_id": "version_workflow_state_classifier",
            "display_name": "工作流状态分类",
            "capability_key": "workflow_state_classification",
            "role_key": "priority_classifier",
            "variant_key": "default",
            "capability_kind": "computation",
            "canonical_hash": "c" * 64,
            "identity_status": "formal_exact_version",
            "input_contract": copy.deepcopy(
                interaction["output_contract"]["events"][
                    "classification_requested"
                ]
            ),
            "output_contract": copy.deepcopy(
                presentation["input_contract"]
            ),
            "error_contract": {
                "schema": "error_contract.v1",
                "errors": {},
            },
        },
    )
    return value


def queue_blueprint_time_plan(
    planner: StubPlanner,
    *,
    assignment_order: list[str] | None = None,
    capability_key: str = "time_unit_conversion",
    outline_value: dict[str, object] | None = None,
) -> None:
    outline_value = outline_value or time_outline()
    planner.generation_outputs.append(outline_value)
    original = planner._generate_json
    roles = assignment_order or [
        "hours_input",
        "hours_to_minutes",
        "minutes_to_seconds",
        "seconds_result",
    ]

    def generated(
        model,
        call_type,
        request_value,
        cancel_check=None,
        **kwargs,
    ):
        if call_type == "composition_selection":
            planner.generation_outputs.insert(
                0,
                {
                    "schema_version": "product_composition_selection.v1",
                    "capability_key": capability_key,
                },
            )
        elif call_type == "product_blueprint":
            offer = next(
                item
                for item in request_value["composition_offers"]
                if item["capability_key"] == capability_key
            )
            by_role = {
                item["role_key"]: item
                for item in offer["members"]
            }
            assignments = {}
            for role in roles:
                member = by_role[role]
                assignments[member["candidate_ref"]] = {
                    "section_id": (
                        "frontend"
                        if member["capability_kind"]
                        in {"interaction", "presentation"}
                        else "backend"
                    ),
                    "requirement_refs": [
                        item["ref"] for item in outline_value["requirements"]
                    ],
                    "title": role,
                    "summary": f"交付 {role} 正式能力。",
                    "acceptance_intent": f"验证 {role} 的正式行为。",
                }
            planner.generation_outputs.insert(
                0,
                {
                    "schema_version": "product_plan_blueprint.v2",
                    "sections": {
                        "frontend": {
                            "applicability": "applicable",
                            "summary": "输入与最终结果。",
                        },
                        "backend": {
                            "applicability": "applicable",
                            "summary": "两个确定性整数换算。",
                        },
                        "data": {
                            "applicability": "not_applicable",
                            "summary": "本产品不需要独立数据层。",
                        },
                        "infrastructure": {
                            "applicability": "not_applicable",
                            "summary": "本产品不需要独立基础设施层。",
                        },
                    },
                    "selection": {
                        "offer_ref": offer["offer_ref"],
                        "assignments": assignments,
                    },
                    "gaps": [],
                },
            )
        return original(
            model,
            call_type,
            request_value,
            cancel_check,
            **kwargs,
        )

    planner._generate_json = generated  # type: ignore[method-assign]


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


def multi_computation_catalog() -> dict[str, object]:
    empty_object = {
        "schema": "data_contract.v1",
        "type": "object",
        "properties": {},
        "required": [],
        "additional_properties": False,
    }
    empty_errors = {"schema": "error_contract.v1", "errors": {}}

    def integer_object(name: str, maximum: int) -> dict[str, object]:
        return {
            "schema": "data_contract.v1",
            "type": "object",
            "properties": {
                name: {"type": "integer", "minimum": 0, "maximum": maximum}
            },
            "required": [name],
            "additional_properties": False,
        }

    rows = [
        {
            "capsule_id": "capsule_hours_input",
            "version_id": "version_hours_input",
            "display_name": "小时输入",
            "capability_key": "time_unit_conversion",
            "role_key": "hours_input",
            "variant_key": "default",
            "capability_kind": "interaction",
            "canonical_hash": "1" * 64,
            "identity_status": "formal_exact_version",
            "input_contract": empty_object,
            "output_contract": {
                "schema": "event_outputs.v1",
                "events": {
                    "conversion_requested": integer_object("hours", 8760)
                },
            },
            "error_contract": empty_errors,
        },
        {
            "capsule_id": "capsule_hours_to_minutes",
            "version_id": "version_hours_to_minutes",
            "display_name": "小时转分钟",
            "capability_key": "time_unit_conversion",
            "role_key": "hours_to_minutes",
            "variant_key": "default",
            "capability_kind": "computation",
            "canonical_hash": "2" * 64,
            "identity_status": "formal_exact_version",
            "input_contract": integer_object("hours", 8760),
            "output_contract": integer_object("minutes", 525600),
            "error_contract": empty_errors,
        },
        {
            "capsule_id": "capsule_minutes_to_seconds",
            "version_id": "version_minutes_to_seconds",
            "display_name": "分钟转秒",
            "capability_key": "time_unit_conversion",
            "role_key": "minutes_to_seconds",
            "variant_key": "default",
            "capability_kind": "computation",
            "canonical_hash": "3" * 64,
            "identity_status": "formal_exact_version",
            "input_contract": integer_object("minutes", 525600),
            "output_contract": integer_object("seconds", 31536000),
            "error_contract": empty_errors,
        },
        {
            "capsule_id": "capsule_seconds_result",
            "version_id": "version_seconds_result",
            "display_name": "秒数结果",
            "capability_key": "time_unit_conversion",
            "role_key": "seconds_result",
            "variant_key": "default",
            "capability_kind": "presentation",
            "canonical_hash": "4" * 64,
            "identity_status": "formal_exact_version",
            "input_contract": integer_object("seconds", 31536000),
            "output_contract": {"schema": "no_output.v1"},
            "error_contract": empty_errors,
        },
    ]
    return {"warehouse_revision": 37, "capsules": rows}


def two_offer_catalog() -> dict[str, object]:
    value = copy.deepcopy(multi_computation_catalog())

    def integer_object(
        properties: dict[str, tuple[int, int]],
    ) -> dict[str, object]:
        return {
            "schema": "data_contract.v1",
            "type": "object",
            "properties": {
                name: {
                    "type": "integer",
                    "minimum": minimum,
                    "maximum": maximum,
                }
                for name, (minimum, maximum) in properties.items()
            },
            "required": list(properties),
            "additional_properties": False,
        }

    empty_object = integer_object({})
    empty_errors = {"schema": "error_contract.v1", "errors": {}}
    quantity = integer_object({"quantity": (1, 10)})
    priced_quantity = integer_object(
        {"quantity": (1, 10), "unit_price": (0, 1000)}
    )
    total = integer_object({"total": (0, 10000)})
    quote_rows = [
        {
            "capsule_id": "capsule_quote_input",
            "version_id": "version_quote_input",
            "display_name": "数量输入",
            "capability_key": "quote_calculation",
            "role_key": "parameterized_quote_input",
            "variant_key": "default",
            "capability_kind": "interaction",
            "canonical_hash": "5" * 64,
            "identity_status": "formal_exact_version",
            "input_contract": empty_object,
            "output_contract": {
                "schema": "event_outputs.v1",
                "events": {"quote_requested": quantity},
            },
            "error_contract": empty_errors,
        },
        {
            "capsule_id": "capsule_discount_policy",
            "version_id": "version_discount_policy",
            "display_name": "数量折扣策略",
            "capability_key": "quote_calculation",
            "role_key": "quantity_discount_policy",
            "variant_key": "default",
            "capability_kind": "computation",
            "canonical_hash": "6" * 64,
            "identity_status": "formal_exact_version",
            "input_contract": quantity,
            "output_contract": priced_quantity,
            "error_contract": empty_errors,
        },
        {
            "capsule_id": "capsule_quote_total",
            "version_id": "version_quote_total",
            "display_name": "总价计算",
            "capability_key": "quote_calculation",
            "role_key": "parameterized_quote_total",
            "variant_key": "default",
            "capability_kind": "computation",
            "canonical_hash": "7" * 64,
            "identity_status": "formal_exact_version",
            "input_contract": priced_quantity,
            "output_contract": total,
            "error_contract": empty_errors,
        },
        {
            "capsule_id": "capsule_quote_result",
            "version_id": "version_quote_result",
            "display_name": "报价结果",
            "capability_key": "quote_calculation",
            "role_key": "parameterized_quote_result",
            "variant_key": "default",
            "capability_kind": "presentation",
            "canonical_hash": "8" * 64,
            "identity_status": "formal_exact_version",
            "input_contract": total,
            "output_contract": {"schema": "no_output.v1"},
            "error_contract": empty_errors,
        },
    ]
    value["warehouse_revision"] = 42
    value["capsules"].extend(quote_rows)
    return value


def quote_gap_catalog() -> dict[str, object]:
    value = two_offer_catalog()
    value["warehouse_revision"] = 41
    value["capsules"] = [
        item
        for item in value["capsules"]
        if item["role_key"] != "quantity_discount_policy"
    ]
    for item in value["capsules"]:
        if item["capability_key"] == "quote_calculation":
            item["display_name"] = "参数化报价结果"
    return value


def finite_enum_gap_catalog(
    *,
    capability_key: str = "workflow_state_classification",
    display_name: str = "工作流状态分类",
    input_properties: dict[str, dict[str, object]] | None = None,
    result_field: str = "priority",
    result_enum: list[str] | None = None,
) -> dict[str, object]:
    input_properties = input_properties or {
        "important": {"type": "boolean"},
        "urgent": {"type": "boolean"},
    }
    result_enum = result_enum or [
        "delegate",
        "do_now",
        "drop",
        "schedule",
    ]
    lengths = [len(value.encode("utf-16-le")) // 2 for value in result_enum]
    input_contract = {
        "schema": "data_contract.v1",
        "type": "object",
        "properties": copy.deepcopy(input_properties),
        "required": sorted(input_properties),
        "additional_properties": False,
    }
    output_contract = {
        "schema": "data_contract.v1",
        "type": "object",
        "properties": {
            result_field: {
                "type": "string",
                "min_length": min(lengths),
                "max_length": max(lengths),
                "enum": list(result_enum),
            }
        },
        "required": [result_field],
        "additional_properties": False,
    }
    empty_object = {
        "schema": "data_contract.v1",
        "type": "object",
        "properties": {},
        "required": [],
        "additional_properties": False,
    }
    empty_errors = {"schema": "error_contract.v1", "errors": {}}
    return {
        "warehouse_revision": 67,
        "capsules": [
            {
                "capsule_id": f"capsule_{capability_key}_input",
                "version_id": f"version_{capability_key}_input",
                "display_name": display_name,
                "capability_key": capability_key,
                "role_key": "criteria_input",
                "variant_key": "default",
                "capability_kind": "interaction",
                "canonical_hash": "a" * 64,
                "identity_status": "formal_exact_version",
                "input_contract": empty_object,
                "output_contract": {
                    "schema": "event_outputs.v1",
                    "events": {"classification_requested": input_contract},
                },
                "error_contract": empty_errors,
            },
            {
                "capsule_id": f"capsule_{capability_key}_result",
                "version_id": f"version_{capability_key}_result",
                "display_name": display_name,
                "capability_key": capability_key,
                "role_key": "classification_result",
                "variant_key": "default",
                "capability_kind": "presentation",
                "canonical_hash": "b" * 64,
                "identity_status": "formal_exact_version",
                "input_contract": output_contract,
                "output_contract": {"schema": "no_output.v1"},
                "error_contract": empty_errors,
            },
        ],
    }


def revision_71_two_gap_catalog() -> dict[str, object]:
    value = finite_enum_gap_catalog()
    value["warehouse_revision"] = 71
    integer_input = {
        "schema": "data_contract.v1",
        "type": "object",
        "properties": {
            name: {"type": "integer", "minimum": 1, "maximum": 100}
            for name in ("height_cm", "length_cm", "width_cm")
        },
        "required": ["height_cm", "length_cm", "width_cm"],
        "additional_properties": False,
    }
    integer_output = {
        "schema": "data_contract.v1",
        "type": "object",
        "properties": {
            "volume_cm3": {
                "type": "integer",
                "minimum": 1,
                "maximum": 1_000_000,
            }
        },
        "required": ["volume_cm3"],
        "additional_properties": False,
    }
    empty_object = {
        "schema": "data_contract.v1",
        "type": "object",
        "properties": {},
        "required": [],
        "additional_properties": False,
    }
    empty_errors = {"schema": "error_contract.v1", "errors": {}}
    value["capsules"].extend(
        [
            {
                "capsule_id": "cap_857e0143c6d94a1fb99ee6e52412cf03",
                "version_id": "ver_08ec4b3684fa4f55bbda66e129ed9192",
                "display_name": "长方体体积计算",
                "capability_key": "rectangular_prism_volume",
                "role_key": "prism_dimensions_input",
                "variant_key": "default",
                "capability_kind": "interaction",
                "canonical_hash": (
                    "2e0c345b1c42ab67c232f10bba1432faa872531a89a1e2886fcc82f1e5122795"
                ),
                "identity_status": "formal_exact_version",
                "input_contract": empty_object,
                "output_contract": {
                    "schema": "event_outputs.v1",
                    "events": {"volume_requested": integer_input},
                },
                "error_contract": empty_errors,
            },
            {
                "capsule_id": "cap_a10e4acb4c6c42b7a265a44c9efab899",
                "version_id": "ver_cf57409b48ce432db7793937a0bf0a65",
                "display_name": "长方体体积计算",
                "capability_key": "rectangular_prism_volume",
                "role_key": "prism_volume_result",
                "variant_key": "default",
                "capability_kind": "presentation",
                "canonical_hash": (
                    "230fd04ded21956773ef78ef966e4308dcd4da447c0586608165bc27e4cea550"
                ),
                "identity_status": "formal_exact_version",
                "input_contract": integer_output,
                "output_contract": {"schema": "no_output.v1"},
                "error_contract": empty_errors,
            },
        ]
    )
    return value


def revision_73_one_gap_catalog() -> dict[str, object]:
    value = revision_71_two_gap_catalog()
    value["warehouse_revision"] = 73
    value["capsules"].append(
        copy.deepcopy(workflow_state_complete_catalog()["capsules"][1])
    )
    return value


def formal_revision_42_catalog() -> dict[str, object]:
    value = two_offer_catalog()
    identities = {
        "hours_input": (
            "cap_8fdd0f4fe61c4bf6942ad613db5de5b3",
            "ver_9bf950df07034d9ea752c2d2601f8356",
            "91957929a7370e60dc81e47294130c79291a6f1f7eda3a7c83332a76e857e98e",
        ),
        "hours_to_minutes": (
            "cap_a6e8b437ee484c4282b1e5a7b1b403fb",
            "ver_56f94ec68cd34443889ed17fd05ba7aa",
            "867b5a782a8b23c98ea1621bdcb51161115f7507c2ca250cccc8eb9022703ce2",
        ),
        "minutes_to_seconds": (
            "cap_5bcfd4781eb14e589fc59a665bbf8deb",
            "ver_21e67cbf423a4b7fbfe7151e240d5388",
            "1657cfea28c28cbec808dc4cec5fd398be77a2b2cee2c08f76e6780f737101d3",
        ),
        "seconds_result": (
            "cap_de8633de8caa48dd94635f494b2ca47d",
            "ver_2ae94891f4274f2b829a716e5230f415",
            "453041ead8fff042e8c82110462dfdc02e8e2abfa75dd4cfdf9fd44b3edf7803",
        ),
    }
    for row in value["capsules"]:
        if row["capability_key"] == "quote_calculation":
            row["display_name"] = "参数化报价结果"
            continue
        if row["capability_key"] != "time_unit_conversion":
            continue
        capsule_id, version_id, canonical_hash = identities[row["role_key"]]
        row.update(
            capsule_id=capsule_id,
            version_id=version_id,
            canonical_hash=canonical_hash,
            display_name="时间单位换算",
        )
    return value


def time_gap_catalog(missing_role: str) -> dict[str, object]:
    value = formal_revision_42_catalog()
    value["capsules"] = [
        row
        for row in value["capsules"]
        if row["role_key"] != missing_role
    ]
    return value


def time_gap_blueprint(
    *,
    title: str = "时间单位换算",
    reason: str = "当前正式目录缺少一段整数时间换算能力。",
) -> dict[str, object]:
    return {
        "schema_version": "product_plan_blueprint.v2",
        "sections": {
            section_id: {
                "applicability": (
                    "applicable"
                    if section_id == "backend"
                    else "not_applicable"
                ),
                "summary": (
                    "缺少一个可验证的整数时间换算。"
                    if section_id == "backend"
                    else "本产品不需要这一独立层。"
                ),
            }
            for section_id in SECTION_IDS
        },
        "selection": {"offer_ref": "", "assignments": {}},
        "gaps": [
            {
                "title": title,
                "reason": reason,
            }
        ],
    }


def start_time_gap_plan(
    planner: StubPlanner,
    missing_role: str,
) -> dict[str, object]:
    catalog = time_gap_catalog(missing_role)
    select_small(planner)
    planner.generation_outputs.extend(
        [time_outline(), no_composition_selection(), time_gap_blueprint()]
    )
    started = planner.start(
        "确定性测试夹具：时间换算能力准备",
        catalog,
    )
    question = started["data"]["question_set"]["questions"][0]
    option = next(item for item in question["options"] if item["forms_gap"])
    return planner.answer(
        started["data"]["plan_token"],
        started["data"]["question_set"]["digest"],
        [
            {
                "question_id": question["question_id"],
                "source": "option",
                "value": option["option_id"],
            }
        ],
        catalog,
    )


def start_quote_gap_plan(
    planner: StubPlanner,
    catalog_value: dict[str, object] | None = None,
) -> dict[str, object]:
    catalog = catalog_value or quote_gap_catalog()
    select_small(planner)
    planner.generation_outputs.extend(
        [quote_outline(), no_composition_selection(), single_quote_gap_blueprint()]
    )
    started = planner.start(
        "创建一个缺少报价策略的本地报价工具。",
        catalog,
    )
    question = started["data"]["question_set"]["questions"][0]
    option = next(item for item in question["options"] if item["forms_gap"])
    return planner.answer(
        started["data"]["plan_token"],
        started["data"]["question_set"]["digest"],
        [
            {
                "question_id": question["question_id"],
                "source": "option",
                "value": option["option_id"],
            }
        ],
        catalog,
    )


def use_legacy_workspace(planner: StubPlanner) -> None:
    original = planner._new_workspace

    def legacy(goal, model):
        workspace = original(goal, model)
        workspace["schema_version"] = (
            product_planner_module.LEGACY_WORKSPACE_SCHEMA_VERSION
        )
        workspace.pop("capability_gap_target_selection")
        workspace["section_checkpoints"] = []
        workspace.pop("composition_selection")
        workspace.pop("composition_selection_input_digest")
        workspace.pop("composition_selection_response_digest")
        workspace.pop("experience_query_digest")
        workspace.pop("experience_injection_enabled")
        workspace.pop("blueprint")
        workspace.pop("blueprint_input_digest")
        workspace.pop("blueprint_response_digest")
        return workspace

    planner._new_workspace = legacy  # type: ignore[method-assign]


def queue_multi_computation_plan(
    planner: StubPlanner,
    roles_by_section: dict[str, list[str]],
) -> None:
    use_legacy_workspace(planner)
    planner.generation_outputs.append(outline())
    original = planner._generate_json

    def generated(model, call_type, request_value, cancel_check=None):
        if call_type.startswith("section_"):
            section_id = request_value["section_id"]
            by_role = {
                item["role_key"]: item["candidate_ref"]
                for item in request_value["candidate_catalog"]
            }
            requirement_ref = {
                "frontend": "r_frontend",
                "backend": "r_backend",
                "data": "r_data",
                "infrastructure": "r_infra",
            }[section_id]
            planner.generation_outputs.insert(
                0,
                {
                    "schema_version": "product_plan_section_draft.v2",
                    "section_id": section_id,
                    "summary": f"{section_id} 时间换算交付",
                    "work_items": [
                        {
                            "title": role,
                            "summary": f"交付 {role} 正式能力。",
                            "requirement_refs": [requirement_ref],
                            "delivery_wave": 2,
                            "acceptance_intent": f"验证 {role} 的正式行为。",
                            "candidate_ref": by_role[role],
                            "gap_reason": "",
                        }
                        for role in roles_by_section[section_id]
                    ],
                },
            )
        return original(model, call_type, request_value, cancel_check)

    planner._generate_json = generated  # type: ignore[method-assign]


def select_small(planner: StubPlanner) -> None:
    planner.generation_outputs.append(probe())
    selected = planner.select_model("small:1.5b", SMALL_DIGEST)
    assert selected["ok"] is True


def queue_plan(planner: StubPlanner, *, with_capsule: bool = True) -> None:
    use_legacy_workspace(planner)
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


def test_workspace_reads_do_not_interrupt_another_live_planner(
    tmp_path: Path,
) -> None:
    root = tmp_path / "product_workspaces"
    planner = StubPlanner(root)
    select_small(planner)
    workspace = planner._new_workspace(
        "保持正在运行的工作区",
        planner._selected_model(check_current=False),
    )
    workspace["status"] = "planning"
    workspace["phase"] = "requirements_outline"
    planner._save_workspace(workspace)
    workspace_path = (
        planner._workspace_dir(workspace["workspace_id"]) / "workspace.json"
    )
    running_bytes = workspace_path.read_bytes()

    reader = ProductPlanner(root)
    state = reader.initial_state()
    assert state["ok"] is True
    assert workspace_path.read_bytes() == running_bytes
    assert planner._workspace_by_token(workspace["plan_token"])["status"] == "planning"

    assert reader.recover_orphaned_workspaces({workspace["plan_token"]}) == 0
    assert workspace_path.read_bytes() == running_bytes
    assert reader.recover_orphaned_workspaces(set()) == 1
    interrupted_bytes = workspace_path.read_bytes()
    assert interrupted_bytes != running_bytes
    assert reader._workspace_by_token(workspace["plan_token"])["status"] == "interrupted"
    assert reader.recover_orphaned_workspaces(set()) == 0
    assert workspace_path.read_bytes() == interrupted_bytes


def test_immutable_sidecar_publish_is_cross_process_create_only(
    tmp_path: Path,
) -> None:
    root = tmp_path / "product_workspaces"
    receipt = root / "receipts" / "receipt.json"
    gate = tmp_path / "gate"
    script = (
        "import json,sys,time\n"
        "from pathlib import Path\n"
        "from pimos_lite.reweave_product_planner import "
        "ProductPlanner,ProductPlanningError\n"
        "root,path,gate,ready,result=map(Path,sys.argv[1:6])\n"
        "value=json.loads(sys.argv[6])\n"
        "ready.write_text('ready',encoding='utf-8')\n"
        "while not gate.exists(): time.sleep(0.01)\n"
        "try:\n"
        " ProductPlanner(root)._write_immutable(path,value)\n"
        "except ProductPlanningError as exc:\n"
        " result.write_text(exc.code,encoding='utf-8')\n"
        "else:\n"
        " result.write_text('ok',encoding='utf-8')\n"
    )

    def race(path: Path, values: list[dict[str, object]]) -> list[str]:
        gate.unlink(missing_ok=True)
        processes = []
        results = []
        for index, value in enumerate(values):
            ready = tmp_path / f"{path.stem}-ready-{index}"
            result = tmp_path / f"{path.stem}-result-{index}"
            ready.unlink(missing_ok=True)
            result.unlink(missing_ok=True)
            results.append(result)
            processes.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        "-c",
                        script,
                        str(root),
                        str(path),
                        str(gate),
                        str(ready),
                        str(result),
                        json.dumps(value, sort_keys=True),
                    ],
                    cwd=Path(__file__).resolve().parents[1],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            )
        deadline = time.monotonic() + 10
        while not all(
            (tmp_path / f"{path.stem}-ready-{index}").is_file()
            for index in range(len(values))
        ):
            assert time.monotonic() < deadline
            time.sleep(0.01)
        gate.touch()
        for process in processes:
            _stdout, stderr = process.communicate(timeout=10)
            assert process.returncode == 0, stderr
        return [result.read_text(encoding="utf-8") for result in results]

    distinct = [{"winner": "first"}, {"winner": "second"}]
    assert sorted(race(receipt, distinct)) == [
        "ok",
        "product_plan_confirmation_conflict",
    ]
    assert json.loads(receipt.read_text(encoding="utf-8")) in distinct

    idempotent = root / "receipts" / "same.json"
    assert race(idempotent, [{"same": True}, {"same": True}]) == ["ok", "ok"]
    assert json.loads(idempotent.read_text(encoding="utf-8")) == {"same": True}


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
    if os.name == "posix":
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
    use_legacy_workspace(public)
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
            "LEGACY_PLANNING_PROMPT_VERSION",
            "reweave_product_planning_prompt.v8",
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
    section_prompts = [
        request[1]["prompt"]
        for request in planner.requests
        if request[0] == "/api/generate"
        and request[1]["prompt"].find('"section_id"') >= 0
    ]
    assert section_prompts
    assert all(
        "absence constraints" in prompt
        and "do not create a gap solely for such a constraint" in prompt
        and "Create a gap only when no supplied candidate covers a required user-visible "
        "behavior, data capability, or integration" in prompt
        for prompt in section_prompts
    )
    assert all(
        request[0] != "/api/generate"
        or "html_text" not in json.dumps(request[1])
        and "css_text" not in json.dumps(request[1])
        and "source_relpath" not in json.dumps(request[1])
        for request in planner.requests
    )

    stored = next(planner.root.glob("workspace_*/workspace.json"))
    if os.name == "posix":
        assert stat_mode(stored) == 0o600
    raw = stored.read_text(encoding="utf-8")
    assert "raw prompt" not in raw
    assert "raw response" not in raw
    assert "workspace_id" not in json.dumps(workspace)
    recovered = StubPlanner(planner.root, counts=planner.counts)
    recovered.digests = planner.digests
    restored = recovered.get(workspace["plan_token"])
    assert restored["data"]["plan"]["canonical_digest"] == plan["canonical_digest"]


def test_multi_computation_plan_requires_complete_roles_and_compiles_unique_chain(
    tmp_path: Path,
) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    select_small(planner)
    queue_multi_computation_plan(
        planner,
        {
            "frontend": ["hours_input"],
            "backend": ["hours_to_minutes"],
            "data": ["minutes_to_seconds"],
            "infrastructure": ["seconds_result"],
        },
    )

    result = planner.start("创建一个本地整数时间换算工具。", multi_computation_catalog())

    assert result["ok"] is True
    plan = result["data"]["plan"]
    assert plan["planning_rules_version"] == SECTION_PLANNING_RULES_VERSION
    items = [
        item
        for section_value in plan["sections"]
        for item in section_value["work_items"]
    ]
    by_capsule = {
        item["capsule_bindings"][0]["capsule_id"]: item
        for item in items
    }
    chain = [
        "capsule_hours_input",
        "capsule_hours_to_minutes",
        "capsule_minutes_to_seconds",
        "capsule_seconds_result",
    ]
    assert by_capsule[chain[0]]["depends_on"] == []
    for source, target in zip(chain[:-1], chain[1:], strict=True):
        assert by_capsule[target]["depends_on"] == [
            by_capsule[source]["work_item_id"]
        ]
    assert len(plan["structured_response_digests"]) == 5
    prompts = [
        request["prompt"]
        for path, request in planner.requests
        if path == "/api/generate"
        and type(request) is dict
        and '"section_id"' in request["prompt"]
    ]
    assert prompts
    assert all(
        key not in prompt
        for prompt in prompts
        for key in ("input_contract", "output_contract", "canonical_hash")
    )
    restored = planner.get(result["data"]["plan_token"], multi_computation_catalog())
    assert restored["ok"] is True
    assert restored["data"]["plan"] == plan


def test_product_blueprint_schema_selects_one_complete_composition_offer() -> None:
    request = {
        "requirements": [{"ref": "r_conversion"}],
        "composition_offers": [
            {
                "offer_ref": "offer_conversion",
                "capability_key": "conversion",
                "members": [
                    {
                        "candidate_ref": "candidate_a",
                        "display_name": "A",
                        "capability_key": "conversion",
                        "role_key": "input",
                        "variant_key": "default",
                        "capability_kind": "interaction",
                    },
                    {
                        "candidate_ref": "candidate_b",
                        "display_name": "B",
                        "capability_key": "conversion",
                        "role_key": "result",
                        "variant_key": "default",
                        "capability_kind": "presentation",
                    },
                ],
            },
        ],
    }
    schema = product_planner_module._structured_output_schema(
        "product_blueprint",
        request,
    )
    options = schema["properties"]["selection"]["oneOf"]
    assert len(options) == 2
    selected = options[0]
    assert selected["properties"]["offer_ref"]["enum"] == ["offer_conversion"]
    assignments = selected["properties"]["assignments"]
    assert set(assignments["properties"]) == {"candidate_a", "candidate_b"}
    assert assignments["additionalProperties"] is False
    assert assignments["required"] == ["candidate_a", "candidate_b"]
    assignment = assignments["properties"]["candidate_a"]
    assert set(assignment["properties"]) == {
        "section_id",
        "requirement_refs",
        "title",
        "summary",
        "acceptance_intent",
    }
    serialized = json.dumps(schema, sort_keys=True)
    for forbidden in (
        "capsule_id",
        "version_id",
        "canonical_hash",
        "depends_on",
        "delivery_wave",
        "input_contract",
        "output_contract",
    ):
        assert forbidden not in serialized
    with pytest.raises(ValueError, match="duplicate_json_key"):
        product_planner_module._strict_json(
            b'{"assignments":{"candidate_a":{},"candidate_a":{}}}'
        )


def test_composition_selection_is_example_free_and_resolves_exact_offer(
    tmp_path: Path,
) -> None:
    candidate_map = {
        f"candidate_{index:02d}": capsule
        for index, capsule in enumerate(two_offer_catalog()["capsules"])
    }
    planner = StubPlanner(tmp_path / "workspaces")
    offers = planner._composition_offers(candidate_map)
    assert {
        offer["capability_key"] for offer in offers
    } == {"time_unit_conversion", "quote_calculation"}
    request = {
        "composition_offers": list(reversed(offers)),
    }
    schema = product_planner_module._structured_output_schema(
        "composition_selection",
        request,
    )
    assert schema["properties"]["capability_key"]["enum"] == [
        "quote_calculation",
        "time_unit_conversion",
        "",
    ]
    assert "oneOf" not in json.dumps(schema, sort_keys=True)

    workspace = {
        "schema_version": (
            product_planner_module.PREVIOUS_REQUIREMENT_COVERAGE_WORKSPACE_SCHEMA_VERSION
        ),
        "goal_digest": "a" * 64,
        "answers": [],
        "model": {
            "name": "small:1.5b",
            "digest": SMALL_DIGEST,
            "parameter_count": 1_543_714_304,
            "parameter_size": "1.5b",
        },
        "outline_response_digest": "b" * 64,
    }
    assert planner._composition_selection_input_digest(
        workspace,
        time_outline(),
        offers,
    ) == planner._composition_selection_input_digest(
        workspace,
        time_outline(),
        list(reversed(offers)),
    )

    for capability_key in ("quote_calculation", "time_unit_conversion"):
        selection = {
            "schema_version": "product_composition_selection.v1",
            "capability_key": capability_key,
        }
        resolved = planner._resolve_composition_selection(selection, offers)
        assert resolved is not None
        assert resolved["capability_key"] == capability_key
        assert len(resolved["members"]) == 4
        assert {
            member["capability_key"] for member in resolved["members"]
        } == {capability_key}
    assert planner._resolve_composition_selection(
        no_composition_selection(),
        offers,
    ) is None
    with pytest.raises(
        ProductPlanningError,
        match="product_plan_composition_unknown",
    ):
        planner._resolve_composition_selection(
            {
                "schema_version": "product_composition_selection.v1",
                "capability_key": "missing_capability",
            },
            offers,
        )
    with pytest.raises(
        ProductPlanningError,
        match="product_plan_composition_selection_ambiguous",
    ):
        quote_offer = next(
            offer
            for offer in offers
            if offer["capability_key"] == "quote_calculation"
        )
        planner._resolve_composition_selection(
            {
                "schema_version": "product_composition_selection.v1",
                "capability_key": "quote_calculation",
            },
            [*offers, copy.deepcopy(quote_offer)],
        )

    planner.generation_outputs.append(
        {
            "schema_version": "product_composition_selection.v1",
            "capability_key": "quote_calculation",
        }
    )
    selection, _evidence = planner._composition_selection_call(
        workspace["model"],
        "创建报价工具",
        quote_outline(),
        [],
        list(reversed(offers)),
        None,
    )
    assert selection["capability_key"] == "quote_calculation"
    generate_request = next(
        payload
        for path, payload in reversed(planner.requests)
        if path == "/api/generate"
    )
    assert type(generate_request) is dict
    prompt = generate_request["prompt"]
    assert "schema_example" not in prompt
    assert "schema_examples" not in prompt
    assert "offer_ref" not in generate_request["format"]["properties"]


@pytest.mark.parametrize(
    ("capability_key", "outline_value", "roles"),
    [
        (
            "time_unit_conversion",
            time_outline(),
            [
                "hours_input",
                "hours_to_minutes",
                "minutes_to_seconds",
                "seconds_result",
            ],
        ),
        (
            "quote_calculation",
            quote_outline(),
            [
                "parameterized_quote_input",
                "quantity_discount_policy",
                "parameterized_quote_total",
                "parameterized_quote_result",
            ],
        ),
    ],
)
def test_composition_selection_locks_blueprint_to_one_complete_offer(
    tmp_path: Path,
    capability_key: str,
    outline_value: dict[str, object],
    roles: list[str],
) -> None:
    planner = StubPlanner(tmp_path / capability_key)
    select_small(planner)
    queue_blueprint_time_plan(
        planner,
        assignment_order=roles,
        capability_key=capability_key,
        outline_value=outline_value,
    )

    result = planner.start("构建一个本地工具。", two_offer_catalog())

    assert result["ok"] is True
    plan = result["data"]["plan"]
    items = {
        item["title"]: item
        for section in plan["sections"]
        for item in section["work_items"]
    }
    assert set(items) == set(roles)
    assert items[roles[0]]["depends_on"] == []
    for source, target in zip(roles[:-1], roles[1:], strict=True):
        assert items[target]["depends_on"] == [items[source]["work_item_id"]]
    calls = [
        payload
        for path, payload in planner.requests
        if path == "/api/generate"
    ]
    selection_request = next(
        payload
        for payload in calls
        if payload["format"]["properties"]["schema_version"]["enum"]
        == ["product_composition_selection.v1"]
    )
    selection_payload = json.loads(
        selection_request["prompt"].split("REQUEST_JSON:\n", 1)[1]
    )
    assert len(selection_payload["composition_offers"]) == 2
    assert "schema_example" not in selection_payload
    assert "schema_examples" not in selection_payload
    blueprint_request = next(
        payload
        for payload in calls
        if payload["format"]["properties"]["schema_version"]["enum"]
        == ["product_plan_blueprint.v2"]
    )
    blueprint_payload = json.loads(
        blueprint_request["prompt"].split("REQUEST_JSON:\n", 1)[1]
    )
    locked_prompt = blueprint_request["prompt"].split("REQUEST_JSON:\n", 1)[0]
    assert blueprint_payload["selection_locked"] is True
    assert [
        offer["capability_key"]
        for offer in blueprint_payload["composition_offers"]
    ] == [capability_key]
    assert "schema_example" not in blueprint_payload
    assert "schema_example" not in locked_prompt
    assert "schema_examples" not in locked_prompt
    assert "exactly one locked complete composition offer" in locked_prompt
    assert "include each supplied candidate_ref exactly once" in locked_prompt
    assert "add, remove, replace, or mix members" in locked_prompt
    assert "has an assignment or gap" in locked_prompt
    assert "section summaries do not count" in locked_prompt
    assert "at least one semantically relevant supplied member" in locked_prompt
    assert (
        "Section summaries do not count as requirement coverage"
        in blueprint_payload["rules"]["coverage"]
    )
    assert (
        "at least one semantically relevant assignment"
        in blueprint_payload["rules"]["coverage"]
    )
    for forbidden in (
        "报价",
        "折扣",
        "时间换算",
        "工作流",
        "important",
        "urgent",
        "priority",
        "capsule_id",
        "version_id",
        "canonical_hash",
        "input_contract",
        "output_contract",
    ):
        assert forbidden not in locked_prompt
    safe_keys = set().union(
        *(
            set(member)
            for offer in blueprint_payload["composition_offers"]
            for member in offer["members"]
        )
    )
    assert safe_keys == {
        "candidate_ref",
        "display_name",
        "capability_key",
        "role_key",
        "variant_key",
        "capability_kind",
    }
    assert len(
        blueprint_request["format"]["properties"]["selection"]["oneOf"]
    ) == 1
    assert blueprint_request["format"]["properties"]["gaps"]["maxItems"] == 0
    assignment_schema = blueprint_request["format"]["properties"]["selection"][
        "oneOf"
    ][0]["properties"]["assignments"]
    assert assignment_schema["required"] == [
        member["candidate_ref"]
        for member in blueprint_payload["composition_offers"][0]["members"]
    ]
    historical_schema = product_planner_module._structured_output_schema(
        "product_blueprint",
        blueprint_payload,
        prompt_version=(
            product_planner_module.PREVIOUS_GAP_PLANNING_PROMPT_VERSION
        ),
    )
    assert historical_schema["properties"]["gaps"]["maxItems"] == 64


def test_non_locked_blueprint_keeps_historical_schema_example_prompt(
    tmp_path: Path,
) -> None:
    planner = StubPlanner(tmp_path / "direct-blueprint")
    select_small(planner)
    candidate_map = {
        f"candidate_{index}": capsule
        for index, capsule in enumerate(
            planner._catalog(multi_computation_catalog())["capsules"]
        )
    }
    offers = planner._composition_offers(candidate_map)
    request = {
        "goal": "创建时间换算工具。",
        "requirements": time_outline()["requirements"],
        "prior_answers": [],
        "composition_offers": offers,
        "rules": {"selection": "Select one complete offer."},
        "schema_example": {"schema_version": "product_plan_blueprint.v2"},
    }
    planner.generation_outputs.append({})

    planner._generate_json(
        planner._selected_model(check_current=False),
        "product_blueprint",
        request,
        prompt_version=product_planner_module.DIRECT_BLUEPRINT_PROMPT_VERSION,
    )

    payload = next(
        payload
        for path, payload in reversed(planner.requests)
        if path == "/api/generate"
    )
    assert type(payload) is dict
    prompt = payload["prompt"].split("REQUEST_JSON:\n", 1)[0]
    assert "schema_example" in prompt
    assert "exactly one locked complete composition offer" not in prompt


def test_composition_offers_are_complete_group_scoped_and_order_invariant(
    tmp_path: Path,
) -> None:
    rows = multi_computation_catalog()["capsules"]
    second_group = []
    for row in rows:
        clone = copy.deepcopy(row)
        clone["capability_key"] = "distance_unit_conversion"
        clone["capsule_id"] = "distance_" + row["capsule_id"]
        clone["version_id"] = "distance_" + row["version_id"]
        clone["canonical_hash"] = {
            "hours_input": "5" * 64,
            "hours_to_minutes": "6" * 64,
            "minutes_to_seconds": "7" * 64,
            "seconds_result": "8" * 64,
        }[row["role_key"]]
        second_group.append(clone)
    candidate_map = {
        f"candidate_{index:02d}": row
        for index, row in enumerate([*rows, *second_group])
    }
    planner = ProductPlanner(tmp_path / "workspaces")
    offers = planner._composition_offers(candidate_map)
    reversed_offers = planner._composition_offers(
        dict(reversed(list(candidate_map.items())))
    )
    assert offers == reversed_offers
    assert len(offers) == 2
    assert {
        offer["capability_key"] for offer in offers
    } == {"time_unit_conversion", "distance_unit_conversion"}

    request = {
        "requirements": [{"ref": "r_conversion"}],
        "composition_offers": offers,
    }
    schema = product_planner_module._structured_output_schema(
        "product_blueprint",
        request,
    )
    reversed_schema = product_planner_module._structured_output_schema(
        "product_blueprint",
        {
            "requirements": list(reversed(request["requirements"])),
            "composition_offers": list(reversed(offers)),
        },
    )
    assert product_planner_module._digest(schema) == product_planner_module._digest(
        reversed_schema
    )
    workspace = {
        "goal_digest": "a" * 64,
        "answers": [],
        "model": {
            "name": "small:1.5b",
            "digest": SMALL_DIGEST,
            "parameter_count": 1_543_714_304,
            "parameter_size": "1.5b",
        },
        "outline_response_digest": "b" * 64,
    }
    assert planner._blueprint_input_digest(
        workspace,
        time_outline(),
        candidate_map,
        offers,
    ) == planner._blueprint_input_digest(
        workspace,
        time_outline(),
        dict(reversed(list(candidate_map.items()))),
        list(reversed(offers)),
    )
    branches = schema["properties"]["selection"]["oneOf"][:-1]
    required_sets = {
        branch["properties"]["offer_ref"]["enum"][0]: set(
            branch["properties"]["assignments"]["required"]
        )
        for branch in branches
    }
    assert all(len(refs) == 4 for refs in required_sets.values())
    assert not set.intersection(*required_sets.values())

    first, second = offers
    first_refs = {
        member["candidate_ref"] for member in first["members"]
    }
    second_ref = second["members"][0]["candidate_ref"]
    mixed_refs = sorted(first_refs)
    mixed_refs[-1] = second_ref
    assignment = {
        "section_id": "frontend",
        "requirement_refs": ["r_conversion"],
        "title": "转换",
        "summary": "使用完整正式能力组。",
        "acceptance_intent": "验证转换结果。",
    }
    mixed = {
        "schema_version": "product_plan_blueprint.v2",
        "sections": {
            section_id: {
                "applicability": (
                    "applicable" if section_id == "frontend" else "not_applicable"
                ),
                "summary": "转换能力。" if section_id == "frontend" else "不适用。",
            }
            for section_id in SECTION_IDS
        },
        "selection": {
            "offer_ref": first["offer_ref"],
            "assignments": {
                candidate_ref: copy.deepcopy(assignment)
                for candidate_ref in mixed_refs
            },
        },
        "gaps": [],
    }
    with pytest.raises(ProductPlanningError) as captured:
        planner._validate_blueprint(
            mixed,
            time_outline()["requirements"],
            set(candidate_map),
            required_sets,
        )
    assert captured.value.code == "product_plan_role_coverage_invalid"


@pytest.mark.parametrize("missing_kind", ["presentation", "computation"])
def test_composition_offer_is_absent_without_a_mandatory_role(
    tmp_path: Path,
    missing_kind: str,
) -> None:
    rows = multi_computation_catalog()["capsules"]
    removed = False
    incomplete = []
    for row in rows:
        if row["capability_kind"] == missing_kind and (
            missing_kind == "computation" or not removed
        ):
            removed = True
            continue
        incomplete.append(row)
    candidate_map = {
        f"candidate_{index}": row for index, row in enumerate(incomplete)
    }
    planner = ProductPlanner(tmp_path / missing_kind)
    assert planner._composition_offers(candidate_map) == []


def test_product_plan_v2_blueprint_binds_each_role_once_and_derives_topology(
    tmp_path: Path,
) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    select_small(planner)
    calls_before = sum(path == "/api/generate" for path, _ in planner.requests)
    queue_blueprint_time_plan(planner)

    result = planner.start(
        "创建一个本地整数时间换算工具。",
        multi_computation_catalog(),
    )

    assert result["ok"] is True
    plan = result["data"]["plan"]
    assert plan["schema_version"] == "product_plan.v2"
    assert plan["planning_rules_version"] == PLANNING_RULES_VERSION
    assert plan["prompt_version"] == product_planner_module.PLANNING_PROMPT_VERSION
    assert sum(path == "/api/generate" for path, _ in planner.requests) - calls_before == 3
    workspace = planner._workspace_by_token(result["data"]["plan_token"])
    assert workspace["schema_version"] == "product_workspace.v12"
    assert "section_checkpoints" not in workspace
    assert workspace["composition_selection"] == {
        "schema_version": "product_composition_selection.v1",
        "capability_key": "time_unit_conversion",
    }
    assert workspace["blueprint"]["schema_version"] == "product_plan_blueprint.v2"
    assert [
        call["call_type"] for call in workspace["model_calls"]
    ] == ["requirements_outline", "composition_selection", "product_blueprint"]
    assert len(plan["structured_response_digests"]) == 3
    sections = {section["section_id"]: section for section in plan["sections"]}
    assert {item["title"] for item in sections["frontend"]["work_items"]} == {
        "hours_input",
        "seconds_result",
    }
    assert {item["title"] for item in sections["backend"]["work_items"]} == {
        "hours_to_minutes",
        "minutes_to_seconds",
    }
    for section_id in ("data", "infrastructure"):
        assert sections[section_id]["applicability"] == "not_applicable"
        assert sections[section_id]["work_items"] == []
        assert sections[section_id]["gaps"] == []
    items = {
        item["title"]: item
        for section in plan["sections"]
        for item in section["work_items"]
    }
    chain = [
        "hours_input",
        "hours_to_minutes",
        "minutes_to_seconds",
        "seconds_result",
    ]
    assert items[chain[0]]["depends_on"] == []
    for source, target in zip(chain[:-1], chain[1:], strict=True):
        assert items[target]["depends_on"] == [items[source]["work_item_id"]]
    assert workspace["delivery_waves"] == {
        items[role]["work_item_id"]: index
        for index, role in enumerate(chain, start=1)
    }
    pairs = [
        (
            binding["capsule_id"],
            binding["version_id"],
        )
        for section in plan["sections"]
        for item in section["work_items"]
        for binding in item["capsule_bindings"]
    ]
    assert len(pairs) == len(set(pairs)) == 4
    blueprint_request = next(
        payload
        for path, payload in planner.requests
        if path == "/api/generate"
        and payload["format"]["properties"].get("schema_version", {}).get("enum")
        == ["product_plan_blueprint.v2"]
    )
    for forbidden in ("capsule_id", "version_id", "canonical_hash", "input_contract"):
        assert forbidden not in blueprint_request["prompt"]
    restored = StubPlanner(planner.root, counts=planner.counts)
    restored.digests = planner.digests
    recovered = restored.get(
        result["data"]["plan_token"],
        multi_computation_catalog(),
    )
    assert recovered["ok"] is True
    assert recovered["data"]["plan"] == plan


def test_v12_freezes_query_before_calls_and_injects_only_selection(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state" / "product_workspaces"
    assert StubPlanner(root)._experience_injection_enabled is True
    catalog_value = multi_computation_catalog()
    historical = StubPlanner(root)
    select_small(historical)
    queue_blueprint_time_plan(historical)
    started = historical.start("创建本地时间换算工具。", catalog_value)
    historical_plan = started["data"]["plan"]
    historical.confirm(
        started["data"]["plan_token"],
        historical_plan["canonical_digest"],
        historical_plan,
        catalog_value,
    )
    historical.record_product_experience(
        started["data"]["plan_token"],
        catalog_value,
        "plan_confirmed",
    )

    control = StubPlanner(
        root,
        experience_injection_enabled=False,
    )
    queue_blueprint_time_plan(control)
    frozen_before_generate = {"value": False}
    original_freeze = control._freeze_product_experience_query

    def freeze(workspace):
        query = original_freeze(workspace)
        frozen_before_generate["value"] = True
        return query

    control._freeze_product_experience_query = freeze  # type: ignore[method-assign]
    original_generate = control._generate_json

    def generate(model, call_type, request_value, cancel_check=None, **kwargs):
        assert frozen_before_generate["value"] is True
        return original_generate(
            model,
            call_type,
            request_value,
            cancel_check,
            **kwargs,
        )

    control._generate_json = generate  # type: ignore[method-assign]
    control_result = control.start(
        "创建本地小时到秒的时间换算工具。",
        catalog_value,
    )
    assert control_result["ok"] is True
    control_workspace = control._workspace_by_token(
        control_result["data"]["plan_token"]
    )
    assert control_workspace["schema_version"] == "product_workspace.v12"
    assert control_workspace["experience_injection_enabled"] is False
    query_path = (
        control.root
        / control_workspace["workspace_id"]
        / "experience_query.json"
    )
    frozen_query_bytes = query_path.read_bytes()
    frozen_query = json.loads(frozen_query_bytes)
    assert frozen_query["cases"]
    assert control_workspace["experience_query_digest"] == frozen_query[
        "canonical_digest"
    ]
    if os.name == "posix":
        assert query_path.stat().st_mode & 0o777 == 0o600

    def selection_payload(planner: StubPlanner) -> dict[str, object]:
        return next(
            payload
            for path, payload in planner.requests
            if path == "/api/generate"
            and payload["format"]["properties"]["schema_version"]["enum"]
            == ["product_composition_selection.v1"]
        )

    control_payload = selection_payload(control)
    control_request = json.loads(
        control_payload["prompt"].split("\nREQUEST_JSON:\n", 1)[1]
    )
    assert control_request["experience_cases"] == []
    assert sum(
        '"experience_cases"' in payload["prompt"]
        for path, payload in control.requests
        if path == "/api/generate"
    ) == 1

    treatment = StubPlanner(
        root,
        experience_injection_enabled=True,
    )
    queue_blueprint_time_plan(treatment)
    treatment_result = treatment.start(
        "创建本地时间单位换算产品。",
        catalog_value,
    )
    assert treatment_result["ok"] is True
    treatment_workspace = treatment._workspace_by_token(
        treatment_result["data"]["plan_token"]
    )
    assert treatment_workspace["experience_injection_enabled"] is True
    treatment_payload = selection_payload(treatment)
    treatment_request = json.loads(
        treatment_payload["prompt"].split("\nREQUEST_JSON:\n", 1)[1]
    )
    assert treatment_request["experience_cases"]
    serialized = json.dumps(
        treatment_request["experience_cases"],
        ensure_ascii=False,
    )
    for forbidden in (
        "record_digest",
        "project_scope",
        "source_workspace",
        "exact_model",
        "capsule_id",
        "version_id",
        "canonical_hash",
    ):
        assert forbidden not in serialized

    cases = treatment_request["experience_cases"]
    offers = control_request["composition_offers"]
    common = {
        "goal": "same goal",
        "outline": time_outline(),
        "answers": [],
        "composition_offers": offers,
        "selection_locked": False,
        "prompt_version": product_planner_module.PLANNING_PROMPT_VERSION,
    }
    without_cases = control._composition_selection_request(
        experience_cases=[],
        **common,
    )
    with_cases = control._composition_selection_request(
        experience_cases=cases,
        **common,
    )
    assert {
        key: value
        for key, value in without_cases.items()
        if key != "experience_cases"
    } == {
        key: value
        for key, value in with_cases.items()
        if key != "experience_cases"
    }
    assert (
        control_payload["prompt"].split("REQUEST_JSON:", 1)[0]
        == treatment_payload["prompt"].split("REQUEST_JSON:", 1)[0]
    )

    extra = StubPlanner(root)
    queue_blueprint_time_plan(extra)
    extra_result = extra.start("创建时间长度转换产品。", catalog_value)
    extra_plan = extra_result["data"]["plan"]
    extra.confirm(
        extra_result["data"]["plan_token"],
        extra_plan["canonical_digest"],
        extra_plan,
        catalog_value,
    )
    extra.record_product_experience(
        extra_result["data"]["plan_token"],
        catalog_value,
        "plan_confirmed",
    )
    assert (
        control._freeze_product_experience_query(control_workspace)
        == frozen_query
    )
    assert query_path.read_bytes() == frozen_query_bytes


def test_v10_referenced_record_tamper_fails_before_generate(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state" / "product_workspaces"
    catalog_value = multi_computation_catalog()
    historical = StubPlanner(root)
    select_small(historical)
    queue_blueprint_time_plan(historical)
    started = historical.start("创建本地时间换算工具。", catalog_value)
    plan = started["data"]["plan"]
    historical.confirm(
        started["data"]["plan_token"],
        plan["canonical_digest"],
        plan,
        catalog_value,
    )
    record = historical.record_product_experience(
        started["data"]["plan_token"],
        catalog_value,
        "plan_confirmed",
    )
    assert record is not None

    planner = StubPlanner(root)
    model = planner._selected_model(check_current=False)
    workspace = planner._new_workspace(
        "创建本地小时换算工具。",
        model,
    )
    planner._save_workspace(workspace)
    query = planner._freeze_product_experience_query(workspace)
    assert query["cases"]
    workspace["status"] = "interrupted"
    planner._save_workspace(workspace)

    record_path = (
        root.parent
        / "product_experience"
        / "records"
        / record["source_workspace_id"]
        / "plan_confirmed.json"
    )
    tampered = json.loads(record_path.read_text(encoding="utf-8"))
    tampered["safe_case"]["members"][0]["display_name"] = "tampered"
    record_path.write_bytes(
        product_planner_module._canonical_bytes(tampered)
    )
    generate_before = sum(
        path == "/api/generate" for path, _payload in planner.requests
    )
    result = planner.start(
        workspace["goal"],
        catalog_value,
        resume_plan_token=workspace["plan_token"],
    )
    assert result["error"]["code"] == "project_experience_record_invalid"
    assert sum(
        path == "/api/generate" for path, _payload in planner.requests
    ) == generate_before


def test_v10_frozen_query_tamper_fails_before_generate(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state" / "product_workspaces"
    planner = StubPlanner(root)
    select_small(planner)
    workspace = planner._new_workspace(
        "创建本地时间换算工具。",
        planner._selected_model(check_current=False),
    )
    planner._save_workspace(workspace)
    planner._freeze_product_experience_query(workspace)
    workspace["status"] = "interrupted"
    planner._save_workspace(workspace)

    query_path = (
        root / workspace["workspace_id"] / "experience_query.json"
    )
    query = json.loads(query_path.read_text())
    query["query_goal_digest"] = "0" * 64
    query_path.write_bytes(product_planner_module._canonical_bytes(query))

    generate_before = sum(
        path == "/api/generate" for path, _payload in planner.requests
    )
    with pytest.raises(ProductPlanningError) as captured:
        planner._freeze_product_experience_query(workspace)
    assert str(captured.value) == "project_experience_query_invalid"
    assert sum(
        path == "/api/generate" for path, _payload in planner.requests
    ) == generate_before


@pytest.mark.parametrize(
    ("workspace_version", "rules_version", "prompt_version"),
    [
        (
            LEGACY_LOCKED_BLUEPRINT_WORKSPACE_SCHEMA_VERSION,
            product_planner_module.PREVIOUS_LOCKED_BLUEPRINT_PLANNING_RULES_VERSION,
            LEGACY_LOCKED_BLUEPRINT_PROMPT_VERSION,
        ),
        (
            product_planner_module.PREVIOUS_LOCKED_BLUEPRINT_WORKSPACE_SCHEMA_VERSION,
            product_planner_module.PREVIOUS_LOCKED_BLUEPRINT_PLANNING_RULES_VERSION,
            product_planner_module.PREVIOUS_LOCKED_BLUEPRINT_PROMPT_VERSION,
        ),
        (
            product_planner_module.PREVIOUS_GAP_WORKSPACE_SCHEMA_VERSION,
            product_planner_module.PREVIOUS_GAP_PLANNING_RULES_VERSION,
            product_planner_module.PREVIOUS_GAP_PLANNING_PROMPT_VERSION,
        ),
        (
            product_planner_module.PREVIOUS_TARGET_SELECTION_WORKSPACE_SCHEMA_VERSION,
            product_planner_module.PREVIOUS_TARGET_SELECTION_PLANNING_RULES_VERSION,
            product_planner_module.PREVIOUS_GAP_PLANNING_PROMPT_VERSION,
        ),
        (
            product_planner_module.PREVIOUS_REQUIREMENT_COVERAGE_WORKSPACE_SCHEMA_VERSION,
            product_planner_module.PREVIOUS_REQUIREMENT_COVERAGE_PLANNING_RULES_VERSION,
            product_planner_module.PREVIOUS_REQUIREMENT_COVERAGE_PROMPT_VERSION,
        ),
        (
            product_planner_module.PREVIOUS_EXPERIENCE_WORKSPACE_SCHEMA_VERSION,
            product_planner_module.PREVIOUS_EXPERIENCE_PLANNING_RULES_VERSION,
            product_planner_module.PLANNING_PROMPT_VERSION,
        ),
        (
            product_planner_module.PREVIOUS_NO_MATCH_WORKSPACE_SCHEMA_VERSION,
            product_planner_module.PREVIOUS_NO_MATCH_PLANNING_RULES_VERSION,
            product_planner_module.PLANNING_PROMPT_VERSION,
        ),
    ],
)
def test_historical_locked_blueprint_workspace_remains_recoverable(
    tmp_path: Path,
    workspace_version: str,
    rules_version: str,
    prompt_version: str,
) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    select_small(planner)
    queue_blueprint_time_plan(planner)
    catalog_value = multi_computation_catalog()
    started = planner.start(
        "创建一个本地整数时间换算工具。",
        catalog_value,
    )
    workspace = planner._workspace_by_token(started["data"]["plan_token"])
    normalized_catalog = planner._catalog(catalog_value)
    candidate_map = {}
    for index, capsule in enumerate(normalized_catalog["capsules"]):
        candidate_ref = "candidate_" + product_planner_module._digest(
            {
                "workspace_id": workspace["workspace_id"],
                "warehouse_revision": normalized_catalog["warehouse_revision"],
                "index": index,
                "capsule_id": capsule["capsule_id"],
                "version_id": capsule["version_id"],
                "canonical_hash": capsule["canonical_hash"],
            }
        )[:24]
        candidate_map[candidate_ref] = capsule
    offers = planner._composition_offers(candidate_map)

    workspace["schema_version"] = workspace_version
    if (
        workspace_version
        not in product_planner_module.EXPERIENCE_WORKSPACE_SCHEMA_VERSIONS
    ):
        workspace.pop("experience_query_digest")
        workspace.pop("experience_injection_enabled")
    if (
        workspace_version
        not in product_planner_module.TARGET_SELECTION_WORKSPACE_SCHEMA_VERSIONS
    ):
        workspace.pop("capability_gap_target_selection")
    workspace["outline_input_digest"] = planner._outline_input_digest(workspace)
    workspace["composition_selection_input_digest"] = (
        planner._composition_selection_input_digest(
            workspace,
            workspace["outline"],
            offers,
        )
    )
    selected_offer = planner._resolve_composition_selection(
        workspace["composition_selection"],
        offers,
    )
    workspace["blueprint_input_digest"] = (
        planner._selected_blueprint_input_digest(
            workspace,
            workspace["outline"],
            selected_offer,
        )
    )
    workspace["plan"]["planning_rules_version"] = rules_version
    workspace["plan"]["prompt_version"] = prompt_version
    workspace["plan"]["canonical_digest"] = planner._plan_digest(
        workspace["plan"]
    )
    planner._save_workspace(workspace)

    restored = StubPlanner(planner.root, counts=planner.counts)
    restored.digests = planner.digests
    recovered = restored.get(workspace["plan_token"], catalog_value)

    assert recovered["ok"] is True
    assert recovered["data"]["plan"]["prompt_version"] == prompt_version
    assert recovered["data"]["developer_evidence"]["prompt_version"] == prompt_version
    restored._validate_plan(recovered["data"]["plan"])


def test_pending_v10_gap_question_v3_remains_recoverable(
    tmp_path: Path,
) -> None:
    root = tmp_path / "product_workspaces"
    planner = StubPlanner(root)
    catalog = revision_71_two_gap_catalog()
    select_small(planner)
    planner.generation_outputs.extend(
        [quote_outline(), no_composition_selection()]
    )
    started = planner.start("创建本地分类工具。", catalog)
    workspace = planner._workspace_by_token(
        started["data"]["plan_token"]
    )
    normalized = planner._catalog(catalog)
    candidate_map = {
        "candidate_"
        + product_planner_module._digest(
            {
                "workspace_id": workspace["workspace_id"],
                "warehouse_revision": normalized["warehouse_revision"],
                "index": index,
                "capsule_id": capsule["capsule_id"],
                "version_id": capsule["version_id"],
                "canonical_hash": capsule["canonical_hash"],
            }
        )[:24]: capsule
        for index, capsule in enumerate(normalized["capsules"])
    }
    workspace["schema_version"] = (
        product_planner_module.PREVIOUS_EXPERIENCE_WORKSPACE_SCHEMA_VERSION
    )
    legacy_question = planner._capability_gap_target_question_set(
        planner._capability_gap_candidates(normalized),
        normalized,
    )
    workspace["question_history"] = [legacy_question["digest"]]
    workspace["current_question_set"] = legacy_question
    workspace["outline_input_digest"] = planner._outline_input_digest(
        workspace
    )
    workspace["composition_selection_input_digest"] = (
        planner._composition_selection_input_digest(
            workspace,
            workspace["outline"],
            planner._composition_offers(candidate_map),
        )
    )
    planner._save_workspace(workspace)

    restarted = StubPlanner(root)
    recovered = restarted.get(workspace["plan_token"], catalog)
    assert recovered["ok"] is True
    assert recovered["data"]["question_set"]["schema_version"] == (
        "product_plan_question_set.v3"
    )
    question = recovered["data"]["question_set"]["questions"][0]
    restarted.generation_outputs.append(single_quote_gap_blueprint())
    answered = restarted.answer(
        workspace["plan_token"],
        recovered["data"]["question_set"]["digest"],
        [
            {
                "question_id": question["question_id"],
                "source": "option",
                "value": question["options"][0]["option_id"],
            }
        ],
        catalog,
    )
    assert answered["ok"] is True
    assert restarted._workspace_by_token(workspace["plan_token"])[
        "capability_gap_target_selection"
    ]["schema_version"] == "product_capability_gap_target_selection.v1"


def test_product_workspace_v4_direct_blueprint_remains_recoverable(
    tmp_path: Path,
) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    select_small(planner)
    queue_blueprint_time_plan(planner)
    catalog_value = multi_computation_catalog()
    started = planner.start(
        "创建一个本地整数时间换算工具。",
        catalog_value,
    )
    workspace = planner._workspace_by_token(started["data"]["plan_token"])
    normalized_catalog = planner._catalog(catalog_value)
    candidate_map = {}
    for index, capsule in enumerate(normalized_catalog["capsules"]):
        candidate_ref = "candidate_" + product_planner_module._digest(
            {
                "workspace_id": workspace["workspace_id"],
                "warehouse_revision": normalized_catalog[
                    "warehouse_revision"
                ],
                "index": index,
                "capsule_id": capsule["capsule_id"],
                "version_id": capsule["version_id"],
                "canonical_hash": capsule["canonical_hash"],
            }
        )[:24]
        candidate_map[candidate_ref] = capsule
    offers = planner._composition_offers(candidate_map)

    workspace["schema_version"] = (
        product_planner_module.DIRECT_BLUEPRINT_WORKSPACE_SCHEMA_VERSION
    )
    workspace.pop("capability_gap_target_selection")
    workspace.pop("composition_selection")
    workspace.pop("composition_selection_input_digest")
    workspace.pop("composition_selection_response_digest")
    workspace.pop("experience_query_digest")
    workspace.pop("experience_injection_enabled")
    workspace["model_calls"] = [
        call
        for call in workspace["model_calls"]
        if call["call_type"] != "composition_selection"
    ]
    workspace["outline_input_digest"] = planner._outline_input_digest(
        workspace,
        product_planner_module.DIRECT_BLUEPRINT_PLANNING_RULES_VERSION,
        product_planner_module.DIRECT_BLUEPRINT_PROMPT_VERSION,
    )
    workspace["blueprint_input_digest"] = planner._blueprint_input_digest(
        workspace,
        workspace["outline"],
        candidate_map,
        offers,
    )
    workspace["plan"]["planning_rules_version"] = (
        product_planner_module.DIRECT_BLUEPRINT_PLANNING_RULES_VERSION
    )
    workspace["plan"]["prompt_version"] = (
        product_planner_module.DIRECT_BLUEPRINT_PROMPT_VERSION
    )
    workspace["plan"]["structured_response_digests"] = [
        workspace["outline_response_digest"],
        workspace["blueprint_response_digest"],
    ]
    workspace["plan"]["canonical_digest"] = planner._plan_digest(
        workspace["plan"]
    )
    planner._save_workspace(workspace)

    restored = StubPlanner(planner.root, counts=planner.counts)
    restored.digests = planner.digests
    recovered = restored.get(workspace["plan_token"], catalog_value)

    assert recovered["ok"] is True
    assert recovered["data"]["plan"]["planning_rules_version"] == (
        product_planner_module.DIRECT_BLUEPRINT_PLANNING_RULES_VERSION
    )
    assert recovered["data"]["plan"]["prompt_version"] == (
        product_planner_module.DIRECT_BLUEPRINT_PROMPT_VERSION
    )


def test_product_plan_v2_is_invariant_to_catalog_and_assignment_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plans = []
    for index, roles in enumerate(
        (
            [
                "hours_input",
                "hours_to_minutes",
                "minutes_to_seconds",
                "seconds_result",
            ],
            [
                "seconds_result",
                "minutes_to_seconds",
                "hours_to_minutes",
                "hours_input",
            ],
        )
    ):
        planner = StubPlanner(tmp_path / f"product_workspaces_{index}")
        select_small(planner)
        queue_blueprint_time_plan(planner, assignment_order=roles)
        identifiers = iter(range(1, 1_000))
        with monkeypatch.context() as scoped:
            scoped.setattr(
                product_planner_module.uuid,
                "uuid4",
                lambda: product_planner_module.uuid.UUID(
                    int=next(identifiers)
                ),
            )
            catalog_value = multi_computation_catalog()
            if index:
                catalog_value["capsules"] = list(
                    reversed(catalog_value["capsules"])
                )
            result = planner.start("创建一个本地整数时间换算工具。", catalog_value)
        assert result["ok"] is True
        plans.append(result["data"]["plan"])
    assert plans[0] == plans[1]
    assert planner._plan_digest(plans[0]) == planner._plan_digest(plans[1])


def test_locked_blueprint_requires_product_constraints_on_an_assignment(
    tmp_path: Path,
) -> None:
    outline_value = workflow_state_outline()
    requirements = outline_value["requirements"]
    candidate_refs = {
        "criteria_input": "candidate_input",
        "priority_classifier": "candidate_computation",
        "classification_result": "candidate_presentation",
    }
    offer_ref = "offer_workflow_state"

    def blueprint(
        refs: dict[str, str],
        *,
        cover_local_constraint: bool,
    ) -> dict[str, object]:
        computation_requirements = ["r_classify", "r_rules"]
        acceptance_intent = "验证四种分类规则。"
        if cover_local_constraint:
            computation_requirements.append("r_local")
            acceptance_intent = "验证四种分类规则并确认处理在本机完成。"
        return {
            "schema_version": "product_plan_blueprint.v2",
            "sections": {
                "frontend": {
                    "applicability": "applicable",
                    "summary": "接收用户条件并展示最终结果。",
                },
                "backend": {
                    "applicability": "applicable",
                    "summary": "执行确定性的事项分类。",
                },
                "data": {
                    "applicability": "not_applicable",
                    "summary": "所有处理在本机完成，不需要独立数据层。",
                },
                "infrastructure": {
                    "applicability": "not_applicable",
                    "summary": "所有处理在本机完成，不需要网络基础设施。",
                },
            },
            "selection": {
                "offer_ref": offer_ref,
                "assignments": {
                    refs["criteria_input"]: {
                        "section_id": "frontend",
                        "requirement_refs": ["r_input"],
                        "title": "criteria_input",
                        "summary": "接收事项条件。",
                        "acceptance_intent": "验证两个布尔条件。",
                    },
                    refs["priority_classifier"]: {
                        "section_id": "backend",
                        "requirement_refs": computation_requirements,
                        "title": "priority_classifier",
                        "summary": "执行事项分类。",
                        "acceptance_intent": acceptance_intent,
                    },
                    refs["classification_result"]: {
                        "section_id": "frontend",
                        "requirement_refs": ["r_result"],
                        "title": "classification_result",
                        "summary": "只展示最终分类。",
                        "acceptance_intent": "验证最终结果。",
                    },
                },
            },
            "gaps": [],
        }

    validator = ProductPlanner(tmp_path / "validator")
    summary_only = blueprint(
        candidate_refs,
        cover_local_constraint=False,
    )
    with pytest.raises(ProductPlanningError) as captured:
        validator._validate_blueprint(
            summary_only,
            requirements,
            set(candidate_refs.values()),
            {offer_ref: set(candidate_refs.values())},
        )
    assert captured.value.code == "product_plan_requirement_uncovered"
    assert captured.value.rule_code == "blueprint.requirement_uncovered"

    covered = blueprint(candidate_refs, cover_local_constraint=True)
    assert (
        validator._validate_blueprint(
            covered,
            requirements,
            set(candidate_refs.values()),
            {offer_ref: set(candidate_refs.values())},
        )
        == covered
    )

    planner = StubPlanner(tmp_path / "product_workspaces")
    select_small(planner)
    planner.generation_outputs.append(outline_value)
    original = planner._generate_json

    def generated(
        model,
        call_type,
        request_value,
        cancel_check=None,
        **kwargs,
    ):
        if call_type == "composition_selection":
            planner.generation_outputs.insert(
                0,
                {
                    "schema_version": "product_composition_selection.v1",
                    "capability_key": "workflow_state_classification",
                },
            )
        elif call_type == "product_blueprint":
            offer = request_value["composition_offers"][0]
            refs = {
                member["role_key"]: member["candidate_ref"]
                for member in offer["members"]
            }
            response = blueprint(refs, cover_local_constraint=True)
            response["selection"]["offer_ref"] = offer["offer_ref"]
            planner.generation_outputs.insert(0, response)
        return original(
            model,
            call_type,
            request_value,
            cancel_check,
            **kwargs,
        )

    planner._generate_json = generated  # type: ignore[method-assign]
    result = planner.start(
        "创建一个仅在本机运行的事项分类工具。",
        workflow_state_complete_catalog(),
    )

    assert result["ok"] is True
    plan = result["data"]["plan"]
    assert plan["schema_version"] == "product_plan.v2"
    assert plan["planning_rules_version"] == (
        "reweave_product_planning_rules.v12"
    )
    assert plan["prompt_version"] == "reweave_product_planning_prompt.v13"
    assert all(not section["gaps"] for section in plan["sections"])
    items = {
        item["title"]: item
        for section in plan["sections"]
        for item in section["work_items"]
    }
    chain = [
        "criteria_input",
        "priority_classifier",
        "classification_result",
    ]
    assert set(items) == set(chain)
    assert items[chain[0]]["depends_on"] == []
    assert items[chain[1]]["depends_on"] == [
        items[chain[0]]["work_item_id"]
    ]
    assert items[chain[2]]["depends_on"] == [
        items[chain[1]]["work_item_id"]
    ]
    local_requirement = next(
        item["requirement_id"]
        for item in plan["requirements"]
        if item["statement"] == "所有处理均在本机完成，不依赖网络服务。"
    )
    assert local_requirement in items["priority_classifier"][
        "requirement_ids"
    ]


def test_blueprint_fails_closed_on_unknown_duplicate_and_section_mismatch(
    tmp_path: Path,
) -> None:
    planner = ProductPlanner(tmp_path / "product_workspaces")
    requirements = time_outline()["requirements"]
    valid = {
        "schema_version": "product_plan_blueprint.v1",
        "sections": {
            "frontend": {
                "applicability": "applicable",
                "summary": "用户界面。",
            },
            "backend": {
                "applicability": "not_applicable",
                "summary": "不需要独立后端。",
            },
            "data": {
                "applicability": "not_applicable",
                "summary": "不需要独立数据层。",
            },
            "infrastructure": {
                "applicability": "not_applicable",
                "summary": "不需要独立基础设施层。",
            },
        },
        "assignments": {
            "candidate_a": {
                "section_id": "frontend",
                "requirement_refs": ["r_conversion"],
                "title": "转换界面",
                "summary": "提供用户可见转换。",
                "acceptance_intent": "验证最终结果。",
            }
        },
        "gaps": [],
    }
    unknown = copy.deepcopy(valid)
    unknown["assignments"]["candidate_unknown"] = unknown["assignments"].pop(
        "candidate_a"
    )
    with pytest.raises(ProductPlanningError) as captured:
        planner._validate_blueprint(unknown, requirements, {"candidate_a"})
    assert captured.value.code == "product_plan_candidate_unknown"

    mismatch = copy.deepcopy(valid)
    mismatch["sections"]["frontend"]["applicability"] = "not_applicable"
    with pytest.raises(ProductPlanningError) as captured:
        planner._validate_blueprint(mismatch, requirements, {"candidate_a"})
    assert captured.value.rule_code == "blueprint.applicability_mismatch"

    uncovered = copy.deepcopy(valid)
    uncovered["assignments"] = {}
    uncovered["sections"]["frontend"]["applicability"] = "not_applicable"
    with pytest.raises(ProductPlanningError) as captured:
        planner._validate_blueprint(uncovered, requirements, {"candidate_a"})
    assert captured.value.code == "product_plan_requirement_uncovered"

    duplicate = copy.deepcopy(multi_computation_catalog()["capsules"][0])
    candidate_map = {"candidate_a": duplicate, "candidate_b": duplicate}
    with pytest.raises(ProductPlanningError) as captured:
        planner._compile_blueprint_dependencies(
            [],
            candidate_map,
            ["candidate_a", "candidate_b"],
        )
    assert captured.value.code == "product_plan_binding_ambiguous"


@pytest.mark.parametrize(
    "missing_role",
    [
        "hours_input",
        "hours_to_minutes",
        "minutes_to_seconds",
        "seconds_result",
    ],
)
def test_product_plan_v2_rejects_an_incomplete_formal_role_group(
    tmp_path: Path,
    missing_role: str,
) -> None:
    planner = StubPlanner(tmp_path / missing_role)
    select_small(planner)
    queue_blueprint_time_plan(
        planner,
        assignment_order=[
            role
            for role in (
                "hours_input",
                "hours_to_minutes",
                "minutes_to_seconds",
                "seconds_result",
            )
            if role != missing_role
        ],
    )
    result = planner.start(
        "创建一个本地整数时间换算工具。",
        multi_computation_catalog(),
    )
    assert result["error"]["code"] == "product_plan_role_coverage_invalid"


def test_product_plan_v2_rejects_ambiguous_and_incompatible_contract_graphs(
    tmp_path: Path,
) -> None:
    value_contract = {
        "schema": "data_contract.v1",
        "type": "object",
        "properties": {
            "value": {"type": "integer", "minimum": 0, "maximum": 100}
        },
        "required": ["value"],
        "additional_properties": False,
    }
    ambiguous_catalog = multi_computation_catalog()
    for capsule in ambiguous_catalog["capsules"]:
        if capsule["capability_kind"] == "interaction":
            capsule["output_contract"] = {
                "schema": "event_outputs.v1",
                "events": {"conversion_requested": copy.deepcopy(value_contract)},
            }
        elif capsule["capability_kind"] == "computation":
            capsule["input_contract"] = copy.deepcopy(value_contract)
            capsule["output_contract"] = copy.deepcopy(value_contract)
        elif capsule["capability_kind"] == "presentation":
            capsule["input_contract"] = copy.deepcopy(value_contract)
    planner = ProductPlanner(tmp_path / "ambiguous")
    ambiguous_map = {
        f"candidate_{index}": capsule
        for index, capsule in enumerate(ambiguous_catalog["capsules"])
    }
    assert planner._composition_offers(ambiguous_map) == []

    incompatible_catalog = multi_computation_catalog()
    interaction = next(
        item
        for item in incompatible_catalog["capsules"]
        if item["capability_kind"] == "interaction"
    )
    interaction["output_contract"] = {
        "schema": "event_outputs.v1",
        "events": {"conversion_requested": copy.deepcopy(value_contract)},
    }
    incompatible_map = {
        f"candidate_{index}": capsule
        for index, capsule in enumerate(incompatible_catalog["capsules"])
    }
    assert planner._composition_offers(incompatible_map) == []


def test_product_plan_v2_supports_one_computation_and_real_gap_stops_execution(
    tmp_path: Path,
) -> None:
    single_catalog = multi_computation_catalog()
    single_catalog["capsules"] = [
        item
        for item in single_catalog["capsules"]
        if item["role_key"] != "minutes_to_seconds"
    ]
    computation = next(
        item
        for item in single_catalog["capsules"]
        if item["capability_kind"] == "computation"
    )
    presentation = next(
        item
        for item in single_catalog["capsules"]
        if item["capability_kind"] == "presentation"
    )
    computation["role_key"] = "hours_to_seconds"
    computation["output_contract"] = copy.deepcopy(
        presentation["input_contract"]
    )
    planner = StubPlanner(tmp_path / "single")
    select_small(planner)
    queue_blueprint_time_plan(
        planner,
        assignment_order=[
            "hours_input",
            "hours_to_seconds",
            "seconds_result",
        ],
    )
    result = planner.start("创建一个本地整数时间换算工具。", single_catalog)
    assert result["ok"] is True
    plan = result["data"]["plan"]
    workspace = planner._workspace_by_token(result["data"]["plan_token"])
    assert sorted(workspace["delivery_waves"].values()) == [1, 2, 3]
    assert sum(
        len(section["work_items"]) for section in plan["sections"]
    ) == 3

    gap_planner = StubPlanner(tmp_path / "gap")
    select_small(gap_planner)
    gap_planner.generation_outputs.extend(
        [outline(), no_composition_selection(), gap_blueprint()]
    )
    planned = gap_planner.start("规划企业中台", catalog(with_capsule=False))
    assert planned["ok"] is True
    gap_plan = planned["data"]["plan"]
    assert gap_plan["schema_version"] == "product_plan.v2"
    confirmed = gap_planner.confirm(
        planned["data"]["plan_token"],
        gap_plan["canonical_digest"],
        copy.deepcopy(gap_plan),
        catalog(with_capsule=False),
    )
    assert confirmed["ok"] is True
    with pytest.raises(PlanExecutionError, match="plan_execution_gap_present"):
        compile_multi_computation_plan_execution(
            gap_plan,
            confirmed["data"]["confirmation"],
            [],
        )


def test_deterministic_planner_plan_compiles_exact_multi_computation_connections(
    tmp_path: Path,
) -> None:
    source_catalog = multi_computation_catalog()
    capsules = []
    catalog_rows = []
    for row in source_catalog["capsules"]:
        payload = copy.deepcopy(_capsule_payload(row["capability_kind"]))
        for key in ("input_contract", "output_contract", "error_contract"):
            payload[key] = copy.deepcopy(row[key])
        canonical_hash = canonicalize_capsule(payload).sha256
        capsules.append(
            {
                **payload,
                "capsule_id": row["capsule_id"],
                "version_id": row["version_id"],
                "capability_key": row["capability_key"],
                "role_key": row["role_key"],
                "variant_key": row["variant_key"],
                "canonical_hash": canonical_hash,
            }
        )
        catalog_rows.append(
            {
                **row,
                "canonical_hash": canonical_hash,
            }
        )
    catalog_value = {
        "warehouse_revision": source_catalog["warehouse_revision"],
        "capsules": catalog_rows,
    }
    planner = StubPlanner(tmp_path / "product_workspaces")
    select_small(planner)
    queue_blueprint_time_plan(planner)
    planned = planner.start("创建一个本地整数时间换算工具。", catalog_value)
    assert planned["ok"] is True
    plan = planned["data"]["plan"]
    assert plan["schema_version"] == "product_plan.v2"
    confirmed = planner.confirm(
        planned["data"]["plan_token"],
        plan["canonical_digest"],
        copy.deepcopy(plan),
        catalog_value,
    )
    assert confirmed["ok"] is True
    confirmation = confirmed["data"]["confirmation"]
    assert confirmation["schema_version"] == "product_plan_confirmation.v1"

    execution = compile_multi_computation_plan_execution(
        plan,
        confirmation,
        capsules,
    )

    unit_to_work = {
        unit["execution_unit_id"]: unit["work_item_id"]
        for unit in execution["execution_units"]
    }
    connection_edges = {
        (
            unit_to_work[connection["source_execution_unit_id"]],
            unit_to_work[connection["target_execution_unit_id"]],
        )
        for connection in execution["connections"]
    }
    dependency_edges = {
        (dependency, item["work_item_id"])
        for section_value in plan["sections"]
        for item in section_value["work_items"]
        for dependency in item["depends_on"]
    }
    roles = {
        (capsule["capsule_id"], capsule["version_id"]): capsule["role_key"]
        for capsule in capsules
    }
    assert execution["schema_version"] == "plan_execution.v3"
    assert connection_edges == dependency_edges
    assert [
        (
            roles[
                (
                    connection["source_capsule_id"],
                    connection["source_version_id"],
                )
            ],
            roles[
                (
                    connection["target_capsule_id"],
                    connection["target_version_id"],
                )
            ],
        )
        for connection in execution["connections"]
    ] == [
        ("hours_input", "hours_to_minutes"),
        ("hours_to_minutes", "minutes_to_seconds"),
        ("minutes_to_seconds", "seconds_result"),
    ]
    assert len(execution["connections"]) == 3
    assert execution["connection_digest"] == canonical_digest(
        execution["connections"]
    )


@pytest.mark.parametrize(
    ("roles_by_section", "error_code"),
    [
        (
            {
                section_id: ["hours_to_minutes", "minutes_to_seconds"]
                for section_id in SECTION_IDS
            },
            "product_plan_role_coverage_invalid",
        ),
        (
            {
                "frontend": ["hours_input", "hours_to_minutes"],
                "backend": ["hours_to_minutes"],
                "data": ["minutes_to_seconds"],
                "infrastructure": ["seconds_result"],
            },
            "product_plan_binding_ambiguous",
        ),
    ],
)
def test_multi_computation_plan_fails_closed_on_missing_or_duplicate_roles(
    tmp_path: Path,
    roles_by_section: dict[str, list[str]],
    error_code: str,
) -> None:
    planner = StubPlanner(tmp_path / error_code)
    select_small(planner)
    queue_multi_computation_plan(planner, roles_by_section)

    result = planner.start("创建一个本地整数时间换算工具。", multi_computation_catalog())

    assert result["ok"] is False
    assert result["error"]["code"] == error_code
    assert result["data"]["status"] == "failed"
    assert result["data"]["plan"] is None


def test_multi_computation_plan_rejects_more_than_one_contract_order(
    tmp_path: Path,
) -> None:
    candidate_catalog = multi_computation_catalog()
    rows = candidate_catalog["capsules"]
    rows[2]["output_contract"] = copy.deepcopy(rows[1]["input_contract"])
    planner = StubPlanner(tmp_path / "ambiguous")
    select_small(planner)
    queue_multi_computation_plan(
        planner,
        {
            "frontend": ["hours_input"],
            "backend": ["hours_to_minutes"],
            "data": ["minutes_to_seconds"],
            "infrastructure": ["seconds_result"],
        },
    )

    result = planner.start("创建一个本地整数时间换算工具。", candidate_catalog)

    assert result["ok"] is False
    assert result["error"]["code"] == "product_plan_connection_order_ambiguous"
    assert result["data"]["status"] == "failed"


def test_legacy_planning_rules_workspace_remains_recoverable(tmp_path: Path) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    select_small(planner)
    queue_plan(planner)
    started = planner.start("构建一个正式本地产品。", catalog())
    assert started["ok"] is True
    workspace = planner._workspace_by_token(started["data"]["plan_token"])
    workspace["plan"]["planning_rules_version"] = LEGACY_PLANNING_RULES_VERSION
    workspace["plan"]["prompt_version"] = HISTORICAL_PLANNING_PROMPT_VERSION
    workspace["plan"]["canonical_digest"] = planner._plan_digest(workspace["plan"])
    workspace["outline_input_digest"] = planner._outline_input_digest(
        workspace,
        LEGACY_PLANNING_RULES_VERSION,
        HISTORICAL_PLANNING_PROMPT_VERSION,
    )
    for checkpoint in workspace["section_checkpoints"]:
        checkpoint["input_digest"] = planner._section_input_digest(
            workspace,
            workspace["outline"],
            checkpoint["section_id"],
            checkpoint["candidate_refs"],
            LEGACY_PLANNING_RULES_VERSION,
            HISTORICAL_PLANNING_PROMPT_VERSION,
        )
    planner._save_workspace(workspace)

    restored = planner.get(workspace["plan_token"], catalog())

    assert restored["ok"] is True
    assert (
        restored["data"]["developer_evidence"]["planning_rules_version"]
        == LEGACY_PLANNING_RULES_VERSION
    )
    assert (
        restored["data"]["developer_evidence"]["prompt_version"]
        == HISTORICAL_PLANNING_PROMPT_VERSION
    )


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
    planner.generation_outputs.extend(
        [no_composition_selection(), gap_blueprint()]
    )
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
    handoff = restarted.create_agent_handoff(
        token,
        acceptance_confirmation["canonical_digest"],
        "e" * 64,
    )
    assert handoff["ok"] is True
    handoff_token = handoff["data"]["handoff_token"]
    handoff_files = list(
        (root / workspace["workspace_id"] / "confirmed").glob(
            "agent_handoff_v1_*.json"
        )
    )
    assert len(handoff_files) == 1
    if os.name == "posix":
        assert handoff_files[0].stat().st_mode & 0o777 == 0o600
    assert handoff_token not in handoff_files[0].read_text(encoding="utf-8")
    handoff_status = restarted.get_agent_handoff_status(
        token,
        "e" * 64,
    )
    assert handoff_status["ok"] is True
    assert set(handoff_status["data"]) == {
        "schema_version",
        "status",
        "created_at",
        "revoked_at",
    }
    assert handoff_status["data"]["status"] == "active"
    assert "handoff_token" not in json.dumps(handoff_status)
    assert (
        restarted.create_agent_handoff(
            token,
            acceptance_confirmation["canonical_digest"],
            "e" * 64,
        )["error"]["code"]
        == "agent_handoff_already_active"
    )
    assert (
        restarted.get_agent_handoff_status(token, "f" * 64)["data"][
            "status"
        ]
        == "stale"
    )
    resolved_handoff = StubPlanner(root).resolve_agent_handoff(handoff_token)
    assert resolved_handoff["ok"] is True
    assert resolved_handoff["data"] == {
        "plan_token": token,
        "plan_digest": plan["canonical_digest"],
        "plan_confirmation_digest": receipt["receipt_digest"],
        "acceptance_confirmation_digest": acceptance_confirmation[
            "canonical_digest"
        ],
        "capsule_facts_digest": "e" * 64,
        "status": "active",
    }
    assert (
        restarted.resolve_agent_handoff("handoff_token_" + "0" * 48)[
            "error"
        ]["code"]
        == "agent_handoff_not_found"
    )
    revoked = restarted.revoke_agent_handoff(handoff_token)
    assert revoked["ok"] is True
    assert revoked["data"]["status"] == "revoked"
    assert (
        StubPlanner(root).resolve_agent_handoff(handoff_token)["error"]["code"]
        == "agent_handoff_revoked"
    )
    assert restarted.revoke_agent_handoff(handoff_token)["ok"] is True
    assert restarted.revoke_agent_handoff_for_plan(token)["data"] == {
        "status": "revoked",
        "revoked_at": revoked["data"]["revoked_at"],
    }
    start_file = tmp_path / "start-handoff-processes"
    script = (
        "import json,sys,time\n"
        "from pathlib import Path\n"
        "from pimos_lite.reweave_product_planner import ProductPlanner\n"
        "start=Path(sys.argv[5])\n"
        "while not start.exists(): time.sleep(0.001)\n"
        "print(json.dumps(ProductPlanner(Path(sys.argv[1])).create_agent_handoff("
        "sys.argv[2],sys.argv[3],sys.argv[4]),sort_keys=True))\n"
    )
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                script,
                str(root),
                token,
                acceptance_confirmation["canonical_digest"],
                "e" * 64,
                str(start_file),
            ],
            cwd=Path(__file__).resolve().parents[1],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _index in range(2)
    ]
    start_file.touch()
    concurrent = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=20)
        assert process.returncode == 0, stderr
        concurrent.append(json.loads(stdout))
    assert sum(result["ok"] is True for result in concurrent) == 1
    assert [
        result["error"]["code"]
        for result in concurrent
        if result["ok"] is False
    ] == ["agent_handoff_already_active"]
    lock_path = root / ".agent_handoff.lock"
    assert lock_path.read_bytes() in {b"", b"\0"}
    if os.name == "posix":
        assert lock_path.stat().st_mode & 0o777 == 0o600
    assert (
        StubPlanner(root).get_agent_handoff_status(token, "e" * 64)[
            "data"
        ]["status"]
        == "active"
    )
    assert restarted.revoke_agent_handoff_for_plan(token)["ok"] is True
    assert restarted.revoke_agent_handoff_for_plan(token)["data"][
        "status"
    ] == "revoked"

    active = restarted.create_agent_handoff(
        token,
        acceptance_confirmation["canonical_digest"],
        "e" * 64,
    )
    assert active["ok"] is True
    confirmed_dir = root / workspace["workspace_id"] / "confirmed"
    active_record = next(
        json.loads(path.read_text(encoding="utf-8"))
        for path in confirmed_dir.glob("agent_handoff_v1_*.json")
        if json.loads(path.read_text(encoding="utf-8"))["status"] == "active"
    )
    active_token = active["data"]["handoff_token"]
    conflicting = copy.deepcopy(active_record)
    conflicting_token = "handoff_token_" + "f" * 48
    conflicting["token_digest"] = hashlib.sha256(
        conflicting_token.encode("ascii")
    ).hexdigest()
    conflicting["canonical_digest"] = product_planner_module._digest(
        {
            key: value
            for key, value in conflicting.items()
            if key != "canonical_digest"
        }
    )
    conflict_path = restarted._agent_handoff_path(
        workspace,
        conflicting["token_digest"],
    )
    restarted._atomic_write(conflict_path, conflicting)
    assert restarted.get_agent_handoff_status(token)["data"]["status"] == "conflict"
    assert (
        restarted.resolve_agent_handoff(active_token)["error"]["code"]
        == "agent_handoff_conflict"
    )
    assert (
        restarted.resolve_agent_handoff(conflicting_token)["error"]["code"]
        == "agent_handoff_conflict"
    )
    assert (
        restarted.revoke_agent_handoff_for_plan(token)["error"]["code"]
        == "agent_handoff_conflict"
    )
    conflict_path.unlink()
    assert restarted.revoke_agent_handoff_for_plan(token)["ok"] is True

    corrupt_path = restarted._agent_handoff_path(workspace, "d" * 64)
    restarted._atomic_write(corrupt_path, {"bad": True})
    assert restarted.get_agent_handoff_status(token)["data"]["status"] == "conflict"
    assert (
        restarted.revoke_agent_handoff_for_plan(token)["error"]["code"]
        == "agent_handoff_conflict"
    )
    corrupt_path.unlink()
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


def test_capability_gap_projection_and_immutable_decision_chain(
    tmp_path: Path,
) -> None:
    root = tmp_path / "product_workspaces"
    planner = StubPlanner(root)
    created = start_quote_gap_plan(planner)

    assert created["ok"] is True
    assert created["data"]["status"] == "plan_review"
    gap = created["data"]["capability_gaps"][0]
    projection = gap["projection"]
    assert gap["status"] == "available"
    assert projection["capability_key"] == "quote_calculation"
    assert projection["slot"] == "before_existing_computation"
    assert projection["adapter_contract_version"] == "computation_adapter.v3"
    assert projection["result_field"] == "unit_price"
    assert projection["passthrough_fields"] == ["quantity"]
    assert set(projection["input_contract"]["properties"]) == {"quantity"}
    assert set(projection["output_contract"]["properties"]) == {
        "quantity",
        "unit_price",
    }

    request = {
        "plan_token": created["data"]["plan_token"],
        "plan_digest": created["data"]["plan"]["canonical_digest"],
        "projection_digest": projection["projection_digest"],
        "expected_previous_decision_digest": None,
        "decision": "authorize",
        "behavior_intent": "按数量计算折扣单价，并保留已验证的数量。",
        "reason": None,
        "acceptance_cases": [
            {
                "input": {"quantity": 1},
                "expected_output": {"quantity": 1, "unit_price": 100},
            },
            {
                "input": {"quantity": 5},
                "expected_output": {"quantity": 5, "unit_price": 80},
            },
        ],
    }
    authorized = planner.record_capability_gap_decision(
        *(request[key] for key in (
            "plan_token",
            "plan_digest",
            "projection_digest",
            "expected_previous_decision_digest",
            "decision",
            "behavior_intent",
            "reason",
            "acceptance_cases",
        )),
        quote_gap_catalog(),
    )
    assert authorized["ok"] is True
    current = authorized["data"]["capability_gaps"][0]["current_decision"]
    assert current["sequence"] == 1
    assert current["decision"] == "authorize"
    conflict = planner.record_capability_gap_decision(
        request["plan_token"],
        request["plan_digest"],
        request["projection_digest"],
        "f" * 64,
        "defer",
        None,
        None,
        [],
        quote_gap_catalog(),
    )
    assert conflict["error"]["code"] == "capability_gap_decision_conflict"
    invalid_reject = planner.record_capability_gap_decision(
        request["plan_token"],
        request["plan_digest"],
        request["projection_digest"],
        current["canonical_digest"],
        "reject",
        None,
        None,
        [],
        quote_gap_catalog(),
    )
    assert invalid_reject["error"]["code"] == "capability_gap_decision_invalid"

    repeated = planner.record_capability_gap_decision(
        *(request[key] for key in (
            "plan_token",
            "plan_digest",
            "projection_digest",
            "expected_previous_decision_digest",
            "decision",
            "behavior_intent",
            "reason",
            "acceptance_cases",
        )),
        quote_gap_catalog(),
    )
    assert repeated["ok"] is True
    assert len(
        repeated["data"]["capability_gaps"][0]["decision_history"]
    ) == 1

    deferred = planner.record_capability_gap_decision(
        request["plan_token"],
        request["plan_digest"],
        request["projection_digest"],
        current["canonical_digest"],
        "defer",
        None,
        "暂缓到下一次产品复核。",
        [],
        quote_gap_catalog(),
    )
    assert deferred["ok"] is True
    assert deferred["data"]["capability_gaps"][0]["current_decision"][
        "sequence"
    ] == 2

    restored = StubPlanner(root).get(
        request["plan_token"],
        quote_gap_catalog(),
    )
    assert restored["ok"] is True
    assert [
        row["decision"]
        for row in restored["data"]["capability_gaps"][0][
            "decision_history"
        ]
    ] == ["authorize", "defer"]


def test_capability_source_proposal_authorization_is_atomic_and_model_safe(
    tmp_path: Path,
) -> None:
    root = tmp_path / "product_workspaces"
    planner = StubPlanner(root)
    created = start_quote_gap_plan(planner)
    gap = created["data"]["capability_gaps"][0]
    projection = gap["projection"]
    decision_result = planner.record_capability_gap_decision(
        created["data"]["plan_token"],
        created["data"]["plan"]["canonical_digest"],
        projection["projection_digest"],
        None,
        "authorize",
        "按数量计算折扣单价，并保留已验证的数量。",
        None,
        [
            {
                "input": {"quantity": 1},
                "expected_output": {"quantity": 1, "unit_price": 100},
            },
            {
                "input": {"quantity": 5},
                "expected_output": {"quantity": 5, "unit_price": 80},
            },
        ],
        quote_gap_catalog(),
    )
    decision = decision_result["data"]["capability_gaps"][0][
        "current_decision"
    ]
    args = (
        created["data"]["plan_token"],
        created["data"]["plan"]["canonical_digest"],
        projection["projection_digest"],
        decision["canonical_digest"],
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _index: planner.prepare_capability_source_proposal(
                    *args,
                    quote_gap_catalog(),
                ),
                range(2),
            )
        )
    assert all(result["ok"] is True for result in results)
    views = [result["data"]["capability_gaps"][0] for result in results]
    assert (
        views[0]["source_proposal_authorization"]
        == views[1]["source_proposal_authorization"]
    )
    assert (
        views[0]["source_proposal_request"]
        == views[1]["source_proposal_request"]
    )

    workspace = planner._workspace_by_token(args[0])
    path = planner._capability_source_proposal_authorization_path(
        workspace,
        workspace["plan"],
    )
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["schema_version"] == (
        "capability_source_proposal_authorization.v1"
    )
    assert record["adapter_contract_version"] == "computation_adapter.v3"
    assert record["passthrough_fields"] == ["quantity"]
    assert len(record["acceptance_cases"]) == 2
    request = record["request"]
    assert request["schema_version"] == "capability_source_proposal_request.v1"
    assert request["formal_binding"]["authorization_digest"] == record[
        "authorization_digest"
    ]
    safe_text = json.dumps(
        request["model_safe_input"],
        ensure_ascii=False,
        sort_keys=True,
    )
    for forbidden in (
        "capsule_id",
        "version_id",
        "canonical_hash",
        "sqlite",
        "workspace_",
        "/Users/",
    ):
        assert forbidden not in safe_text
    assert record["capability_key"] not in safe_text

    allowed = {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "minItems",
        "maxItems",
        "enum",
    }

    def schema_keywords(value):
        if not isinstance(value, dict):
            return set()
        keys = set(value)
        children = []
        for key, item in value.items():
            if key == "properties":
                children.extend(item.values())
            elif key == "items":
                children.append(item)
        return keys | set().union(
            *(schema_keywords(item) for item in children),
            set(),
        )

    assert schema_keywords(request["format_schema"]) <= allowed
    valid_response = {
        "schema": "capability_source_proposal.v1",
        "entry": {
            "module_relpath": "capability.js",
            "export_name": "compute",
        },
        "files": [
            {
                "path": "capability.js",
                "content": (
                    "export function compute(quantity) { "
                    "return 105 - quantity * 5; }"
                ),
            }
        ],
    }
    assert (
        planner.validate_capability_source_proposal_response(valid_response)
        == valid_response
    )
    invalid_responses = [
        {**valid_response, "extra": True},
        {
            **valid_response,
            "entry": {
                "module_relpath": "wrong.js",
                "export_name": "compute",
            },
        },
        {
            **valid_response,
            "entry": {
                "module_relpath": "capability.js",
                "export_name": "other",
            },
        },
        {**valid_response, "files": []},
        {
            **valid_response,
            "files": [
                {"path": "capability.js", "content": ""},
            ],
        },
        {
            **valid_response,
            "files": [
                {
                    "path": "capability.js",
                    "content": "```js\nexport function compute() { return 1; }\n```",
                }
            ],
        },
        {
            **valid_response,
            "files": [
                {
                    "path": "capability.js",
                    "content": (
                        "export function compute() { return 1; }"
                        + " " * 4096
                    ),
                }
            ],
        },
    ]
    for invalid in invalid_responses:
        with pytest.raises(
            ProductPlanningError,
            match="capability_source_proposal_response_invalid",
        ):
            planner.validate_capability_source_proposal_response(invalid)

    reversed_catalog = quote_gap_catalog()
    reversed_catalog["capsules"].reverse()
    repeated = planner.prepare_capability_source_proposal(
        *args,
        reversed_catalog,
    )
    assert repeated["data"]["capability_gaps"][0][
        "source_proposal_request"
    ] == views[0]["source_proposal_request"]
    locked = planner.record_capability_gap_decision(
        args[0],
        args[1],
        args[2],
        decision["canonical_digest"],
        "defer",
        None,
        None,
        [],
        quote_gap_catalog(),
    )
    assert locked["error"]["code"] == "capability_gap_authorization_locked"

    restored = StubPlanner(root).get(args[0], quote_gap_catalog())
    assert restored["data"]["capability_gaps"][0][
        "source_proposal_authorization"
    ] == views[0]["source_proposal_authorization"]
    tampered = copy.deepcopy(record)
    tampered["request"]["stream"] = True
    path.write_text(json.dumps(tampered), encoding="utf-8")
    assert StubPlanner(root).get(args[0], quote_gap_catalog())["error"][
        "code"
    ] == "capability_source_proposal_authorization_invalid"


def test_capability_source_proposal_requires_current_authorization_and_supports_v2(
    tmp_path: Path,
) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    created = start_time_gap_plan(planner, "hours_to_minutes")
    gap = created["data"]["capability_gaps"][0]
    projection = gap["projection"]
    args = (
        created["data"]["plan_token"],
        created["data"]["plan"]["canonical_digest"],
        projection["projection_digest"],
    )
    missing = planner.prepare_capability_source_proposal(
        *args,
        "a" * 64,
        time_gap_catalog("hours_to_minutes"),
    )
    assert missing["error"]["code"] == (
        "capability_source_proposal_authorization_required"
    )
    deferred = planner.record_capability_gap_decision(
        *args,
        None,
        "defer",
        None,
        None,
        [],
        time_gap_catalog("hours_to_minutes"),
    )
    deferred_digest = deferred["data"]["capability_gaps"][0][
        "current_decision"
    ]["canonical_digest"]
    assert planner.prepare_capability_source_proposal(
        *args,
        deferred_digest,
        time_gap_catalog("hours_to_minutes"),
    )["error"]["code"] == (
        "capability_source_proposal_authorization_required"
    )
    authorized = planner.record_capability_gap_decision(
        *args,
        deferred_digest,
        "authorize",
        "将整数小时转换为分钟。",
        None,
        [
            {
                "input": {"hours": 1},
                "expected_output": {"minutes": 60},
            }
        ],
        time_gap_catalog("hours_to_minutes"),
    )
    decision = authorized["data"]["capability_gaps"][0]["current_decision"]
    prepared = planner.prepare_capability_source_proposal(
        *args,
        decision["canonical_digest"],
        time_gap_catalog("hours_to_minutes"),
    )
    assert prepared["ok"] is True
    workspace = planner._workspace_by_token(args[0])
    record = json.loads(
        planner._capability_source_proposal_authorization_path(
            workspace,
            workspace["plan"],
        ).read_text(encoding="utf-8")
    )
    assert record["adapter_contract_version"] == "computation_adapter.v2"
    assert record["passthrough_fields"] == []

    stale_catalog = time_gap_catalog("hours_to_minutes")
    stale_catalog["warehouse_revision"] = 43
    stale = planner.prepare_capability_source_proposal(
        *args,
        decision["canonical_digest"],
        stale_catalog,
    )
    assert stale["error"]["code"] == (
        "capability_source_proposal_authorization_stale"
    )


def test_capability_source_proposal_request_v2_projects_scalar_source_abi(
    tmp_path: Path,
) -> None:
    def authorize(
        planner: StubPlanner,
        created: dict[str, object],
        catalog: dict[str, object],
        behavior: str,
        acceptance_cases: list[dict[str, object]],
    ) -> dict[str, object]:
        gap = created["data"]["capability_gaps"][0]
        projection = gap["projection"]
        decided = planner.record_capability_gap_decision(
            created["data"]["plan_token"],
            created["data"]["plan"]["canonical_digest"],
            projection["projection_digest"],
            None,
            "authorize",
            behavior,
            None,
            acceptance_cases,
            catalog,
        )
        decision = decided["data"]["capability_gaps"][0][
            "current_decision"
        ]
        prepared = planner.prepare_capability_source_proposal(
            created["data"]["plan_token"],
            created["data"]["plan"]["canonical_digest"],
            projection["projection_digest"],
            decision["canonical_digest"],
            catalog,
        )
        assert prepared["ok"] is True
        workspace = planner._workspace_by_token(
            created["data"]["plan_token"]
        )
        return json.loads(
            planner._capability_source_proposal_authorization_path(
                workspace,
                workspace["plan"],
            ).read_text(encoding="utf-8")
        )

    time_planner = StubPlanner(tmp_path / "time")
    time_catalog = time_gap_catalog("hours_to_minutes")
    time_created = start_time_gap_plan(
        time_planner,
        "hours_to_minutes",
    )
    time_record = authorize(
        time_planner,
        time_created,
        time_catalog,
        "将整数小时转换为分钟。",
        [
            {
                "input": {"hours": 1},
                "expected_output": {"minutes": 60},
            }
        ],
    )
    assert time_record["request"]["schema_version"] == (
        "capability_source_proposal_request.v1"
    )
    assert time_record["request"]["formal_binding"]["prompt_version"] == (
        "capability_source_proposal_prompt.v1"
    )
    assert time_record["request"] == (
        ProductPlanner._build_capability_source_proposal_request(
            time_record
        )
    )

    time_request = (
        ProductPlanner._build_capability_source_proposal_request_v2(
            time_record
        )
    )
    assert time_request["schema_version"] == (
        "capability_source_proposal_request.v2"
    )
    assert time_request["formal_binding"]["authorization_digest"] == (
        time_record["authorization_digest"]
    )
    assert time_request["formal_binding"]["prompt_version"] == (
        "capability_source_proposal_prompt.v2"
    )
    assert time_request["formal_binding"][
        "supersedes_request_digest"
    ] == time_record["request"]["request_digest"]
    assert time_request["formal_binding"]["supersession_reason"] == (
        "source_abi_protocol_clarification"
    )
    time_safe = time_request["model_safe_input"]
    assert time_safe == {
        "source_function": {
            "schema_version": "capability_source_function_abi.v1",
            "module_relpath": "capability.js",
            "export_name": "compute",
            "parameters": [
                {
                    "position": 0,
                    "parameter_name": "arg0",
                    "input_field": "hours",
                    "contract": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 8760,
                    },
                }
            ],
            "return_contract": {
                "type": "integer",
                "minimum": 0,
                "maximum": 525600,
            },
        },
        "adapter_projection": {
            "contract_version": "computation_adapter.v2",
            "result_field": "minutes",
            "passthrough_fields": [],
        },
        "source_examples": [
            {"arguments": [1], "expected_scalar_result": 60}
        ],
    }
    assert time_request["formal_binding"]["source_abi_digest"] == (
        canonical_digest(time_safe["source_function"])
    )
    assert time_request["request_digest"] == canonical_digest(
        {
            key: value
            for key, value in time_request.items()
            if key != "request_digest"
        }
    )

    reversed_time_catalog = copy.deepcopy(time_catalog)
    reversed_time_catalog["capsules"].reverse()
    repeated = time_planner.prepare_capability_source_proposal(
        time_created["data"]["plan_token"],
        time_record["plan_digest"],
        time_record["projection_digest"],
        time_record["authorize_decision_digest"],
        reversed_time_catalog,
    )
    assert repeated["ok"] is True
    time_workspace = time_planner._workspace_by_token(
        time_created["data"]["plan_token"]
    )
    assert ProductPlanner._build_capability_source_proposal_request_v2(
        json.loads(
            time_planner._capability_source_proposal_authorization_path(
                time_workspace,
                time_workspace["plan"],
            ).read_text(encoding="utf-8")
        )
    ) == time_request

    reordered = copy.deepcopy(time_record)
    reordered["input_contract"]["properties"] = dict(
        reversed(list(reordered["input_contract"]["properties"].items()))
    )
    reordered["output_contract"]["properties"] = dict(
        reversed(list(reordered["output_contract"]["properties"].items()))
    )
    assert (
        ProductPlanner._build_capability_source_proposal_request_v2(
            reordered
        )
        == time_request
    )

    two_parameters = copy.deepcopy(time_record)
    two_parameters["input_contract"] = {
        "schema": "data_contract.v1",
        "type": "object",
        "properties": {
            "zeta": {"type": "integer", "minimum": 0, "maximum": 10},
            "alpha": {"type": "integer", "minimum": 0, "maximum": 10},
        },
        "required": ["alpha", "zeta"],
        "additional_properties": False,
    }
    two_parameters["acceptance_cases"] = [
        {
            "input": {"zeta": 2, "alpha": 1},
            "expected_output": {"minutes": 60},
        }
    ]
    resign_body = {
        key: value
        for key, value in two_parameters.items()
        if key not in {"authorization_digest", "request"}
    }
    two_parameters["authorization_digest"] = canonical_digest(resign_body)
    two_parameters["request"] = (
        ProductPlanner._build_capability_source_proposal_request(
            two_parameters
        )
    )
    two_parameter_request = (
        ProductPlanner._build_capability_source_proposal_request_v2(
            two_parameters
        )
    )
    assert [
        (row["parameter_name"], row["input_field"])
        for row in two_parameter_request["model_safe_input"][
            "source_function"
        ]["parameters"]
    ] == [("arg0", "alpha"), ("arg1", "zeta")]
    reversed_parameters = copy.deepcopy(two_parameters)
    reversed_parameters["input_contract"]["properties"] = dict(
        reversed(
            list(
                reversed_parameters["input_contract"][
                    "properties"
                ].items()
            )
        )
    )
    assert (
        ProductPlanner._build_capability_source_proposal_request_v2(
            reversed_parameters
        )
        == two_parameter_request
    )

    quote_planner = StubPlanner(tmp_path / "quote")
    quote_catalog = quote_gap_catalog()
    quote_record = authorize(
        quote_planner,
        start_quote_gap_plan(quote_planner),
        quote_catalog,
        "按数量计算折扣单价，并保留已验证的数量。",
        [
            {
                "input": {"quantity": 5},
                "expected_output": {"quantity": 5, "unit_price": 80},
            }
        ],
    )
    quote_request = (
        ProductPlanner._build_capability_source_proposal_request_v2(
            quote_record
        )
    )
    assert quote_request["model_safe_input"]["source_function"][
        "parameters"
    ] == [
        {
            "position": 0,
            "parameter_name": "arg0",
            "input_field": "quantity",
            "contract": {
                "type": "integer",
                "minimum": 1,
                "maximum": 10,
            },
        }
    ]
    assert quote_request["model_safe_input"]["adapter_projection"] == {
        "contract_version": "computation_adapter.v3",
        "result_field": "unit_price",
        "passthrough_fields": ["quantity"],
    }
    assert quote_request["model_safe_input"]["source_examples"] == [
        {"arguments": [5], "expected_scalar_result": 80}
    ]

    for request in (time_request, quote_request):
        safe_text = json.dumps(
            request["model_safe_input"],
            ensure_ascii=False,
            sort_keys=True,
        )
        for forbidden in (
            "expected_output",
            "output_contract",
            "capsule_id",
            "version_id",
            "canonical_hash",
            "capability_key",
            "workspace_",
            "/Users/",
        ):
            assert forbidden not in safe_text
        assert "Return one integer scalar" in request["prompt"]
        assert "Do not return an object, array, Promise" in request["prompt"]

    def resign(record: dict[str, object]) -> None:
        body = {
            key: value
            for key, value in record.items()
            if key not in {"authorization_digest", "request"}
        }
        record["authorization_digest"] = canonical_digest(body)
        record["request"] = (
            ProductPlanner._build_capability_source_proposal_request(
                record
            )
        )

    invalid_records = []
    changed = copy.deepcopy(quote_record)
    changed["result_field"] = "quantity"
    resign(changed)
    invalid_records.append(changed)
    changed = copy.deepcopy(quote_record)
    changed["passthrough_fields"] = []
    resign(changed)
    invalid_records.append(changed)
    changed = copy.deepcopy(quote_record)
    changed["acceptance_cases"][0]["expected_output"]["quantity"] = 4
    resign(changed)
    invalid_records.append(changed)
    changed = copy.deepcopy(time_record)
    changed["input_contract"]["properties"]["hours"]["maximum"] = 0
    resign(changed)
    invalid_records.append(changed)
    for invalid in invalid_records:
        with pytest.raises(
            ProductPlanningError,
            match="capability_source_proposal_request_invalid",
        ):
            ProductPlanner._build_capability_source_proposal_request_v2(
                invalid
            )


def test_capability_source_proposal_run_is_single_attempt_and_restart_safe(
    tmp_path: Path,
) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    catalog = time_gap_catalog("hours_to_minutes")
    created = start_time_gap_plan(planner, "hours_to_minutes")
    gap = created["data"]["capability_gaps"][0]
    decided = planner.record_capability_gap_decision(
        created["data"]["plan_token"],
        created["data"]["plan"]["canonical_digest"],
        gap["projection"]["projection_digest"],
        None,
        "authorize",
        "将整数小时转换为分钟。",
        None,
        [
            {
                "input": {"hours": 1},
                "expected_output": {"minutes": 60},
            }
        ],
        catalog,
    )
    decision = decided["data"]["capability_gaps"][0][
        "current_decision"
    ]
    prepared = planner.prepare_capability_source_proposal(
        created["data"]["plan_token"],
        created["data"]["plan"]["canonical_digest"],
        gap["projection"]["projection_digest"],
        decision["canonical_digest"],
        catalog,
    )
    authorization = prepared["data"]["capability_gaps"][0][
        "source_proposal_authorization"
    ]
    supervisor = {"name": "supervisor:7b", "digest": "c" * 64}
    run = planner.prepare_capability_source_proposal_run(
        created["data"]["plan_token"],
        created["data"]["plan"]["canonical_digest"],
        gap["projection"]["projection_digest"],
        authorization["authorization_digest"],
        supervisor,
        catalog,
    )
    assert run["created"] is True
    assert run["status"] == "pending"
    repeated = planner.prepare_capability_source_proposal_run(
        created["data"]["plan_token"],
        created["data"]["plan"]["canonical_digest"],
        gap["projection"]["projection_digest"],
        authorization["authorization_digest"],
        supervisor,
        copy.deepcopy(catalog),
    )
    assert repeated["created"] is False
    assert repeated["run_id"] == run["run_id"]

    generate_count = sum(
        1 for path, _payload in planner.requests if path == "/api/generate"
    )
    planner.generation_outputs.append(
        {
            "schema": "capability_source_proposal.v1",
            "entry": {
                "module_relpath": "capability.js",
                "export_name": "compute",
            },
            "files": [
                {
                    "path": "capability.js",
                    "content": (
                        "export function compute(arg0) "
                        "{ return arg0 * 60; }\n"
                    ),
                }
            ],
        }
    )
    generated = planner.run_capability_source_proposal_model(
        run["run_id"]
    )
    assert generated["proposal"]["entry"]["export_name"] == "compute"
    assert sum(
        1 for path, _payload in planner.requests if path == "/api/generate"
    ) == generate_count + 1
    source = planner.write_capability_source_proposal(
        run["run_id"],
        generated["proposal"]["files"][0]["content"],
    )
    assert source["source_relpath"] == "source/capability.js"

    for stage in (
        "source_proposal",
        "intake",
        "security",
        "runtime",
        "supervision",
        "admission",
    ):
        planner.append_capability_source_proposal_run_event(
            run["run_id"],
            status="running",
            stage=stage,
        )
    completed = planner.append_capability_source_proposal_run_event(
        run["run_id"],
        status="review_required",
        stage="admission",
        evidence={
            "review_id": "review_" + "d" * 32,
            "admission_digest": "e" * 64,
        },
    )
    assert completed["status"] == "review_required"
    restored = StubPlanner(planner.root).get_capability_source_proposal_run(
        run["run_id"]
    )
    assert restored == completed
    with pytest.raises(
        ProductPlanningError,
        match="capability_source_proposal_run_event_invalid",
    ):
        planner.append_capability_source_proposal_run_event(
            run["run_id"],
            status="running",
            stage="admission",
        )


@pytest.mark.parametrize(
    "acceptance_cases",
    [
        [],
        [
            {
                "input": {},
                "expected_output": {"quantity": 1, "unit_price": 100},
            }
        ],
        [
            {
                "input": {"quantity": 11},
                "expected_output": {"quantity": 11, "unit_price": 50},
            }
        ],
        [
            {
                "input": {"quantity": 5, "extra": 1},
                "expected_output": {"quantity": 5, "unit_price": 80},
            }
        ],
        [
            {
                "input": {"quantity": 5},
                "expected_output": {"quantity": 4, "unit_price": 80},
            }
        ],
    ],
)
def test_capability_gap_authorization_rejects_invalid_acceptance_cases(
    tmp_path: Path,
    acceptance_cases: list[dict[str, object]],
) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    created = start_quote_gap_plan(planner)
    projection = created["data"]["capability_gaps"][0]["projection"]
    result = planner.record_capability_gap_decision(
        created["data"]["plan_token"],
        created["data"]["plan"]["canonical_digest"],
        projection["projection_digest"],
        None,
        "authorize",
        "按数量计算单价。",
        None,
        acceptance_cases,
        quote_gap_catalog(),
    )
    assert result["ok"] is False
    assert result["error"]["code"] in {
        "capability_gap_acceptance_invalid",
        "capability_gap_decision_invalid",
    }


def test_capability_gap_projection_is_deterministic_and_fails_closed() -> None:
    catalog_value = quote_gap_catalog()
    planner = StubPlanner(Path("/private/tmp/reweave-gap-probe"))
    normalized = planner._catalog(catalog_value)
    plan = {
        "plan_id": "plan_" + "a" * 24,
        "plan_version": 1,
        "canonical_digest": "b" * 64,
        "sections": [
            {
                "section_id": "backend",
                "gaps": [
                    {
                        "gap_id": "gap_" + "c" * 20,
                        "title": "缺少报价规则",
                        "reason": "正式能力不完整。",
                        "requirement_ids": ["requirement_" + "d" * 20],
                    }
                ],
            }
        ],
    }
    first, first_status = planner._capability_gap_projection(plan, normalized)
    reversed_catalog = planner._catalog(
        {
            "warehouse_revision": catalog_value["warehouse_revision"],
            "capsules": list(reversed(catalog_value["capsules"])),
        }
    )
    second, second_status = planner._capability_gap_projection(
        plan,
        reversed_catalog,
    )
    assert first_status == second_status == "available"
    assert first == second

    complete = planner._catalog(two_offer_catalog())
    assert planner._capability_gap_projection(plan, complete) == (
        None,
        "capability_gap_boundary_unavailable",
    )

    ambiguous = copy.deepcopy(catalog_value)
    duplicates = []
    for row in catalog_value["capsules"]:
        if row["capability_key"] != "quote_calculation":
            continue
        duplicate = copy.deepcopy(row)
        duplicate["capsule_id"] += "_other"
        duplicate["version_id"] += "_other"
        duplicate["canonical_hash"] = (
            "9" if row["capability_kind"] == "interaction" else "8"
        ) * 64
        duplicate["capability_key"] = "other_quote"
        duplicate["display_name"] = "另一个报价组"
        duplicates.append(duplicate)
    ambiguous["capsules"].extend(duplicates)
    assert planner._capability_gap_projection(
        plan,
        planner._catalog(ambiguous),
    ) == (None, "capability_gap_boundary_ambiguous")

    zero_computation = quote_gap_catalog()
    zero_computation["capsules"] = [
        row
        for row in zero_computation["capsules"]
        if row["role_key"] != "parameterized_quote_total"
    ]
    zero_projection, zero_status = planner._capability_gap_projection(
        plan,
        planner._catalog(zero_computation),
    )
    assert zero_status == "available"
    assert zero_projection["slot"] == "only_computation"
    assert (
        zero_projection["adapter_contract_version"]
        == "computation_adapter.v2"
    )

    multiple_gaps = copy.deepcopy(plan)
    multiple_gaps["sections"].append(
        {
            "section_id": "data",
            "gaps": [
                {
                    "gap_id": "gap_" + "e" * 20,
                    "title": "第二个缺口",
                    "reason": "不允许多个缺口。",
                    "requirement_ids": ["requirement_" + "f" * 20],
                }
            ],
        }
    )
    assert planner._capability_gap_projection(
        multiple_gaps,
        normalized,
    ) == (None, "capability_gap_plan_count_unsupported")


def test_finite_enum_gap_projection_v2_is_generic_and_deterministic(
    tmp_path: Path,
) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    plan = {
        "plan_id": "plan_" + "a" * 24,
        "plan_version": 1,
        "canonical_digest": "b" * 64,
        "sections": [
            {
                "section_id": "backend",
                "gaps": [
                    {
                        "gap_id": "gap_" + "c" * 20,
                        "title": "唯一状态分类缺口",
                        "reason": "正式目录只有输入与展示。",
                        "requirement_ids": ["requirement_" + "d" * 20],
                    }
                ],
            }
        ],
    }
    catalog_a = finite_enum_gap_catalog()
    first, status = planner._capability_gap_projection(
        plan,
        planner._catalog(catalog_a),
    )
    reversed_projection, reversed_status = (
        planner._capability_gap_projection(
            plan,
            planner._catalog(
                {
                    "warehouse_revision": catalog_a["warehouse_revision"],
                    "capsules": list(reversed(catalog_a["capsules"])),
                }
            ),
        )
    )
    assert status == reversed_status == "available"
    assert first == reversed_projection
    assert first["schema_version"] == "capability_gap_projection.v2"
    assert first["slot"] == "only_computation"
    assert first["adapter_contract_version"] == "computation_adapter.v4"
    assert first["capture_mapping_schema"] == "computation_capture_mapping.v4"
    assert first["proof_schema"] == "source_graph_proof.v2"
    assert first["result_field"] == "priority"
    assert first["result_enum"] == [
        "delegate",
        "do_now",
        "drop",
        "schedule",
    ]
    assert first["passthrough_fields"] == []

    catalog_b = finite_enum_gap_catalog(
        capability_key="access_readiness",
        display_name="访问就绪状态",
        input_properties={
            "enabled": {"type": "boolean"},
            "verified": {"type": "boolean"},
        },
        result_field="access_state",
        result_enum=["blocked", "limited", "ready"],
    )
    second, second_status = planner._capability_gap_projection(
        plan,
        planner._catalog(catalog_b),
    )
    assert second_status == "available"
    assert second["capability_key"] == "access_readiness"
    assert second["result_field"] == "access_state"
    assert second["result_enum"] == ["blocked", "limited", "ready"]

    ambiguous = {
        "warehouse_revision": 67,
        "capsules": [*catalog_a["capsules"], *catalog_b["capsules"]],
    }
    assert planner._capability_gap_projection(
        plan,
        planner._catalog(ambiguous),
    ) == (None, "capability_gap_boundary_ambiguous")


def test_finite_enum_gap_adapter_rejects_open_or_noncanonical_contracts() -> None:
    catalog_value = finite_enum_gap_catalog()
    input_contract = catalog_value["capsules"][0]["output_contract"]["events"][
        "classification_requested"
    ]
    output_contract = catalog_value["capsules"][1]["input_contract"]
    assert ProductPlanner._finite_enum_gap_adapter(
        input_contract,
        output_contract,
    )["result_enum"] == ["delegate", "do_now", "drop", "schedule"]

    invalid_fields = [
        {"type": "string", "min_length": 0, "max_length": 32},
        {"type": "string", "min_length": 4, "max_length": 8, "enum": []},
        {
            "type": "string",
            "min_length": 4,
            "max_length": 8,
            "enum": ["drop", "drop"],
        },
        {
            "type": "string",
            "min_length": 4,
            "max_length": 8,
            "enum": ["schedule", "drop"],
        },
        {
            "type": "string",
            "min_length": 3,
            "max_length": 3,
            "enum": [f"v{index:02d}" for index in range(33)],
        },
        {
            "type": "array",
            "items": {"type": "boolean"},
            "min_items": 1,
            "max_items": 1,
        },
        {
            "type": "object",
            "properties": {},
            "required": [],
            "additional_properties": False,
        },
    ]
    for invalid_field in invalid_fields:
        invalid_output = copy.deepcopy(output_contract)
        invalid_output["properties"]["priority"] = invalid_field
        assert (
            ProductPlanner._finite_enum_gap_adapter(
                input_contract,
                invalid_output,
            )
            is None
        )


def test_finite_enum_gap_positions_are_unique_and_complete_chain_has_no_gap() -> None:
    planner = StubPlanner(Path("/private/tmp/reweave-enum-gap-positions"))
    base = finite_enum_gap_catalog()
    interaction = base["capsules"][0]
    presentation = base["capsules"][1]
    event_contract = interaction["output_contract"]["events"][
        "classification_requested"
    ]
    enum_contract = presentation["input_contract"]
    empty_errors = {"schema": "error_contract.v1", "errors": {}}

    before = copy.deepcopy(base)
    before["capsules"].append(
        {
            "capsule_id": "capsule_existing_after_classifier",
            "version_id": "version_existing_after_classifier",
            "display_name": "工作流状态分类",
            "capability_key": "workflow_state_classification",
            "role_key": "existing_after_classifier",
            "variant_key": "default",
            "capability_kind": "computation",
            "canonical_hash": "c" * 64,
            "identity_status": "formal_exact_version",
            "input_contract": copy.deepcopy(enum_contract),
            "output_contract": copy.deepcopy(enum_contract),
            "error_contract": empty_errors,
        }
    )
    before_candidate = planner._capability_gap_candidates(
        planner._catalog(before)
    )[0]
    assert before_candidate["slot"] == "before_existing_computation"
    assert before_candidate["adapter_contract_version"] == (
        "computation_adapter.v4"
    )

    boolean_output = {
        "schema": "data_contract.v1",
        "type": "object",
        "properties": {"eligible": {"type": "boolean"}},
        "required": ["eligible"],
        "additional_properties": False,
    }
    after = copy.deepcopy(base)
    after["capsules"].append(
        {
            "capsule_id": "capsule_existing_boolean",
            "version_id": "version_existing_boolean",
            "display_name": "工作流状态分类",
            "capability_key": "workflow_state_classification",
            "role_key": "existing_boolean_filter",
            "variant_key": "default",
            "capability_kind": "computation",
            "canonical_hash": "d" * 64,
            "identity_status": "formal_exact_version",
            "input_contract": copy.deepcopy(event_contract),
            "output_contract": boolean_output,
            "error_contract": empty_errors,
        }
    )
    after_candidate = planner._capability_gap_candidates(
        planner._catalog(after)
    )[0]
    assert after_candidate["slot"] == "after_existing_computation"
    assert after_candidate["adapter_contract_version"] == (
        "computation_adapter.v4"
    )

    complete = copy.deepcopy(base)
    complete["capsules"].append(
        {
            "capsule_id": "capsule_complete_classifier",
            "version_id": "version_complete_classifier",
            "display_name": "工作流状态分类",
            "capability_key": "workflow_state_classification",
            "role_key": "complete_classifier",
            "variant_key": "default",
            "capability_kind": "computation",
            "canonical_hash": "e" * 64,
            "identity_status": "formal_exact_version",
            "input_contract": copy.deepcopy(event_contract),
            "output_contract": copy.deepcopy(enum_contract),
            "error_contract": empty_errors,
        }
    )
    assert planner._capability_gap_candidates(planner._catalog(complete)) == []


def test_finite_enum_gap_prepares_v2_authorization_and_v4_request(
    tmp_path: Path,
) -> None:
    root = tmp_path / "product_workspaces"
    planner = StubPlanner(root)
    created = start_quote_gap_plan(planner, finite_enum_gap_catalog())
    gap = created["data"]["capability_gaps"][0]
    projection = gap["projection"]
    assert projection["schema_version"] == "capability_gap_projection.v2"
    plan = created["data"]["plan"]
    token = created["data"]["plan_token"]
    cases = [
        {
            "input": {"important": True, "urgent": True},
            "expected_output": {"priority": "do_now"},
        },
        {
            "input": {"important": False, "urgent": False},
            "expected_output": {"priority": "drop"},
        },
    ]
    authorized = planner.record_capability_gap_decision(
        token,
        plan["canonical_digest"],
        projection["projection_digest"],
        None,
        "authorize",
        "根据两个布尔条件返回有限状态。",
        None,
        cases,
        finite_enum_gap_catalog(),
    )
    assert authorized["ok"] is True
    decision = authorized["data"]["capability_gaps"][0]["current_decision"]
    assert decision["decision"] == "authorize"
    workspace = planner._workspace_by_token(token)
    projection_path = planner._capability_gap_projection_v2_path(
        workspace,
        plan,
    )
    assert projection_path.is_file()

    prepared = planner.prepare_capability_source_proposal(
        token,
        plan["canonical_digest"],
        projection["projection_digest"],
        decision["canonical_digest"],
        finite_enum_gap_catalog(),
    )
    assert prepared["ok"] is True
    assert not planner._capability_source_proposal_authorization_path(
        workspace,
        plan,
    ).exists()
    authorization_path = (
        planner._capability_source_proposal_authorization_v2_path(
            workspace,
            plan,
        )
    )
    authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
    assert authorization["schema_version"] == (
        "capability_source_proposal_authorization.v2"
    )
    assert authorization["capture_mapping_schema"] == (
        "computation_capture_mapping.v4"
    )
    assert authorization["proof_schema"] == "source_graph_proof.v2"
    assert authorization["result_enum"] == [
        "delegate",
        "do_now",
        "drop",
        "schedule",
    ]
    request = authorization["request"]
    assert request["schema_version"] == "capability_source_proposal_request.v4"
    assert request["formal_binding"]["prompt_version"] == (
        "capability_source_proposal_prompt.v4"
    )
    assert request["formal_binding"]["output_protocol_version"] == (
        "capability_source_proposal.v2"
    )
    assert request["model_safe_input"]["source_function"][
        "schema_version"
    ] == "capability_source_function_abi.v2"
    assert set(request["model_safe_input"]) == {
        "source_function",
        "adapter_projection",
        "user_acceptance_examples",
        "witness_requirements",
    }
    for key, value in (
        ("proof_schema", "source_graph_proof.v1"),
        ("capture_mapping_schema", "computation_capture_mapping.v3"),
        ("result_enum", ["do_now", "delegate", "drop", "schedule"]),
    ):
        tampered = copy.deepcopy(authorization)
        tampered[key] = value
        with pytest.raises(
            ProductPlanningError,
            match="capability_source_proposal_authorization_invalid",
        ):
            planner._validate_capability_source_proposal_authorization(
                workspace,
                tampered,
                planner._read_capability_gap_projection(workspace),
                decision,
            )
    tampered_request = copy.deepcopy(authorization)
    tampered_request["request"]["request_digest"] = "0" * 64
    with pytest.raises(
        ProductPlanningError,
        match="capability_source_proposal_authorization_invalid",
    ):
        planner._validate_capability_source_proposal_authorization(
            workspace,
            tampered_request,
            planner._read_capability_gap_projection(workspace),
            decision,
        )
    legacy = copy.deepcopy(authorization)
    legacy["request"] = (
        planner._build_capability_source_proposal_request_v3(legacy)
    )
    assert planner._validate_capability_source_proposal_authorization(
        workspace,
        legacy,
        planner._read_capability_gap_projection(workspace),
        decision,
    ) == legacy
    assert planner._runtime_capability_source_proposal_request(
        legacy
    ) == legacy["request"]

    restored = StubPlanner(root).get(token, finite_enum_gap_catalog())
    restored_gap = restored["data"]["capability_gaps"][0]
    assert restored_gap["current_decision"] == decision
    assert restored_gap["source_proposal_authorization"][
        "authorization_digest"
    ] == authorization["authorization_digest"]
    assert restored_gap["source_proposal_request"]["prompt_version"] == (
        "capability_source_proposal_prompt.v4"
    )


def test_bounded_string_gap_prepares_v3_authorization_and_v5_request(
    tmp_path: Path,
) -> None:
    catalog = finite_enum_gap_catalog(
        capability_key="message_classification",
        display_name="消息分类",
        input_properties={
            "message": {
                "type": "string",
                "min_length": 1,
                "max_length": 1000,
            }
        },
        result_field="classification",
        result_enum=["normal", "urgent"],
    )
    planner = StubPlanner(tmp_path / "product_workspaces")
    created = start_quote_gap_plan(planner, catalog)
    projection = created["data"]["capability_gaps"][0]["projection"]
    assert projection["schema_version"] == "capability_gap_projection.v3"
    assert projection["adapter_contract_version"] == "computation_adapter.v5"
    assert projection["proof_schema"] == "source_graph_proof.v3"
    assert projection["result_enum"] == ["normal", "urgent"]
    plan = created["data"]["plan"]
    token = created["data"]["plan_token"]
    workspace = planner._workspace_by_token(token)
    stored_projection = planner._read_capability_gap_projection(workspace)
    assert stored_projection["capture_mapping_schema"] == (
        "computation_capture_mapping.v5"
    )
    authorized = planner.record_capability_gap_decision(
        token,
        plan["canonical_digest"],
        projection["projection_digest"],
        None,
        "authorize",
        "根据有界字符串返回有限分类。",
        None,
        [
            {
                "input": {"message": "routine task"},
                "expected_output": {"classification": "normal"},
            },
            {
                "input": {"message": "urgent task"},
                "expected_output": {"classification": "urgent"},
            },
        ],
        catalog,
    )
    assert authorized["ok"] is True
    decision = authorized["data"]["capability_gaps"][0]["current_decision"]
    prepared = planner.prepare_capability_source_proposal(
        token,
        plan["canonical_digest"],
        projection["projection_digest"],
        decision["canonical_digest"],
        catalog,
    )
    assert prepared["ok"] is True
    workspace = planner._workspace_by_token(token)
    assert workspace["schema_version"] == "product_workspace.v12"
    authorization = planner._read_capability_source_proposal_authorization(
        workspace,
        planner._read_capability_gap_projection(workspace),
        decision,
    )
    assert authorization["schema_version"] == (
        "capability_source_proposal_authorization.v3"
    )
    request = authorization["request"]
    assert request["schema_version"] == "capability_source_proposal_request.v5"
    assert request["formal_binding"]["prompt_version"] == (
        "capability_source_proposal_prompt.v5"
    )
    assert request["model_safe_input"]["source_function"]["schema_version"] == (
        "capability_source_function_abi.v3"
    )
    assert "arg0.includes(\"fixed non-empty literal\")" in request["prompt"]
    for forbidden in ("capsule_id", "version_id", "canonical_hash", "source_path"):
        assert forbidden not in json.dumps(request, sort_keys=True)

    response = {
        "schema": "capability_source_proposal.v2",
        "entry": {
            "module_relpath": "capability.js",
            "export_name": "compute",
        },
        "files": [
            {
                "path": "capability.js",
                "content": (
                    "export function compute(arg0) { "
                    "return arg0.includes('urgent') ? 'urgent' : 'normal'; }"
                ),
            }
        ],
        "witnesses": [
            {
                "input": {"message": "urgent task"},
                "expected_scalar_result": "urgent",
            },
            {
                "input": {"message": "routine task"},
                "expected_scalar_result": "normal",
            },
        ],
    }
    normalized = planner.validate_capability_source_proposal_response(
        response,
        request,
    )
    assert [
        item["expected_scalar_result"] for item in normalized["witnesses"]
    ] == ["normal", "urgent"]
    too_long = copy.deepcopy(response)
    too_long["witnesses"][0]["input"]["message"] = "x" * 1001
    with pytest.raises(
        ProductPlanningError,
        match="capability_source_proposal_response_invalid",
    ):
        planner.validate_capability_source_proposal_response(too_long, request)


def test_finite_enum_source_proposal_v2_requires_complete_ordered_witnesses(
    tmp_path: Path,
) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    created = start_quote_gap_plan(planner, finite_enum_gap_catalog())
    plan = created["data"]["plan"]
    token = created["data"]["plan_token"]
    projection = created["data"]["capability_gaps"][0]["projection"]
    authorized = planner.record_capability_gap_decision(
        token,
        plan["canonical_digest"],
        projection["projection_digest"],
        None,
        "authorize",
        "根据两个布尔条件返回有限状态。",
        None,
        [
            {
                "input": {"important": True, "urgent": True},
                "expected_output": {"priority": "do_now"},
            }
        ],
        finite_enum_gap_catalog(),
    )
    decision = authorized["data"]["capability_gaps"][0]["current_decision"]
    planner.prepare_capability_source_proposal(
        token,
        plan["canonical_digest"],
        projection["projection_digest"],
        decision["canonical_digest"],
        finite_enum_gap_catalog(),
    )
    workspace = planner._workspace_by_token(token)
    authorization = planner._read_capability_source_proposal_authorization(
        workspace,
        planner._read_capability_gap_projection(workspace),
        decision,
    )
    request = planner._build_capability_source_proposal_request_v3(
        authorization
    )
    serialized_request = json.dumps(
        request,
        ensure_ascii=False,
        sort_keys=True,
    )
    for forbidden in (
        "capsule_id",
        "version_id",
        "canonical_hash",
        "source_path",
        "source_code",
    ):
        assert forbidden not in serialized_request
    for forbidden_keyword in (
        '"const"',
        '"pattern"',
        '"minLength"',
        '"maxLength"',
        '"oneOf"',
        '"anyOf"',
        '"allOf"',
    ):
        assert forbidden_keyword not in json.dumps(
            request["format_schema"],
            sort_keys=True,
        )
    reordered_authorization = copy.deepcopy(authorization)
    reordered_authorization["input_contract"]["properties"] = dict(
        reversed(
            list(
                reordered_authorization["input_contract"][
                    "properties"
                ].items()
            )
        )
    )
    assert planner._build_capability_source_proposal_request_v3(
        reordered_authorization
    ) == request
    assert planner._build_capability_source_proposal_request_v4(
        reordered_authorization
    ) == planner._build_capability_source_proposal_request_v4(
        authorization
    )
    response = {
        "schema": "capability_source_proposal.v2",
        "entry": {
            "module_relpath": "capability.js",
            "export_name": "compute",
        },
        "files": [
            {
                "path": "capability.js",
                "content": (
                    "export function compute(arg0, arg1) { "
                    "return arg0 ? (arg1 ? 'do_now' : 'schedule') "
                    ": (arg1 ? 'delegate' : 'drop'); }"
                ),
            }
        ],
        "witnesses": [
            {
                "input": {"important": False, "urgent": True},
                "expected_scalar_result": "delegate",
            },
            {
                "input": {"important": True, "urgent": True},
                "expected_scalar_result": "do_now",
            },
            {
                "input": {"important": False, "urgent": False},
                "expected_scalar_result": "drop",
            },
            {
                "input": {"important": True, "urgent": False},
                "expected_scalar_result": "schedule",
            },
        ],
    }
    assert planner.validate_capability_source_proposal_response(
        response,
        request,
    ) == response
    invalid_values = []
    missing = copy.deepcopy(response)
    missing["witnesses"].pop()
    invalid_values.append(missing)
    duplicate = copy.deepcopy(response)
    duplicate["witnesses"][1]["input"] = copy.deepcopy(
        duplicate["witnesses"][0]["input"]
    )
    invalid_values.append(duplicate)
    reordered = copy.deepcopy(response)
    reordered["witnesses"][0], reordered["witnesses"][1] = (
        reordered["witnesses"][1],
        reordered["witnesses"][0],
    )
    invalid_values.append(reordered)
    extra = copy.deepcopy(response)
    extra["witnesses"][0]["input"]["extra"] = True
    invalid_values.append(extra)
    wrong_type = copy.deepcopy(response)
    wrong_type["witnesses"][0]["input"]["important"] = 1
    invalid_values.append(wrong_type)
    outside_enum = copy.deepcopy(response)
    outside_enum["witnesses"][0]["expected_scalar_result"] = "unknown"
    invalid_values.append(outside_enum)
    for invalid in invalid_values:
        with pytest.raises(
            ProductPlanningError,
            match="capability_source_proposal_response_invalid",
        ):
            planner.validate_capability_source_proposal_response(
                invalid,
                request,
            )

    request_v4 = planner._build_capability_source_proposal_request_v4(
        authorization
    )
    assert request_v4["schema_version"] == (
        "capability_source_proposal_request.v4"
    )
    assert request_v4["formal_binding"]["prompt_version"] == (
        "capability_source_proposal_prompt.v4"
    )
    assert "expected_scalar_results" in request_v4[
        "model_safe_input"
    ]["witness_requirements"]
    assert "ordered_expected_scalar_results" not in request_v4[
        "model_safe_input"
    ]["witness_requirements"]
    assert "witness array order has no meaning" in request_v4["prompt"]

    model_order = copy.deepcopy(response)
    model_order["witnesses"] = [
        response["witnesses"][1],
        response["witnesses"][3],
        response["witnesses"][0],
        response["witnesses"][2],
    ]
    original_model_order = copy.deepcopy(model_order)
    normalized = planner.validate_capability_source_proposal_response(
        model_order,
        request_v4,
    )
    assert model_order == original_model_order
    assert normalized == response

    duplicate_result = copy.deepcopy(model_order)
    duplicate_result["witnesses"][1]["expected_scalar_result"] = "do_now"
    with pytest.raises(
        ProductPlanningError,
        match="capability_source_proposal_response_invalid",
    ):
        planner.validate_capability_source_proposal_response(
            duplicate_result,
            request_v4,
        )


def test_finite_enum_source_proposal_requires_input_enumeration_review(
    tmp_path: Path,
) -> None:
    catalog = finite_enum_gap_catalog(
        input_properties={
            "mode": {
                "type": "string",
                "min_length": 3,
                "max_length": 4,
                "enum": ["auto", "off"],
            }
        }
    )
    planner = StubPlanner(tmp_path / "product_workspaces")
    created = start_quote_gap_plan(planner, catalog)
    plan = created["data"]["plan"]
    projection = created["data"]["capability_gaps"][0]["projection"]
    authorized = planner.record_capability_gap_decision(
        created["data"]["plan_token"],
        plan["canonical_digest"],
        projection["projection_digest"],
        None,
        "authorize",
        "根据有限模式返回有限状态。",
        None,
        [
            {
                "input": {"mode": "auto"},
                "expected_output": {"priority": "do_now"},
            }
        ],
        catalog,
    )
    decision = authorized["data"]["capability_gaps"][0]["current_decision"]
    prepared = planner.prepare_capability_source_proposal(
        created["data"]["plan_token"],
        plan["canonical_digest"],
        projection["projection_digest"],
        decision["canonical_digest"],
        catalog,
    )
    assert prepared["error"]["code"] == (
        "capability_source_proposal_input_enumeration_review_required"
    )
    workspace = planner._workspace_by_token(created["data"]["plan_token"])
    assert planner._capability_source_proposal_authorization_paths(
        workspace
    ) == []


@pytest.mark.parametrize(
    "cases",
    [
        [
            {
                "input": {"important": True},
                "expected_output": {"priority": "do_now"},
            }
        ],
        [
            {
                "input": {
                    "important": True,
                    "urgent": True,
                    "extra": False,
                },
                "expected_output": {"priority": "do_now"},
            }
        ],
        [
            {
                "input": {"important": 1, "urgent": True},
                "expected_output": {"priority": "do_now"},
            }
        ],
        [
            {
                "input": {"important": True, "urgent": True},
                "expected_output": {"priority": "unknown"},
            }
        ],
        [
            {
                "input": {"important": True, "urgent": True},
                "expected_output": {"priority": "do_now"},
            },
            {
                "input": {"important": True, "urgent": True},
                "expected_output": {"priority": "do_now"},
            },
        ],
    ],
)
def test_finite_enum_gap_acceptance_rejects_invalid_or_duplicate_cases(
    tmp_path: Path,
    cases: list[dict[str, object]],
) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    created = start_quote_gap_plan(planner, finite_enum_gap_catalog())
    projection = created["data"]["capability_gaps"][0]["projection"]
    result = planner.record_capability_gap_decision(
        created["data"]["plan_token"],
        created["data"]["plan"]["canonical_digest"],
        projection["projection_digest"],
        None,
        "authorize",
        "根据两个布尔条件返回有限状态。",
        None,
        cases,
        finite_enum_gap_catalog(),
    )
    assert result["error"]["code"] == "capability_gap_acceptance_invalid"


def test_finite_enum_gap_lock_v2_is_safe_and_model_only_describes_it(
    tmp_path: Path,
) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    captured: dict[str, object] = {}
    original = planner._generate_json

    def generated(model, call_type, request_value, cancel_check=None, **kwargs):
        if call_type == "product_blueprint":
            captured["request"] = copy.deepcopy(request_value)
        return original(
            model,
            call_type,
            request_value,
            cancel_check,
            **kwargs,
        )

    planner._generate_json = generated
    created = start_quote_gap_plan(planner, finite_enum_gap_catalog())
    assert created["ok"] is True
    request = captured["request"]
    lock = request["capability_gap_lock"]
    assert lock["schema_version"] == "product_capability_gap_blueprint_lock.v2"
    assert lock["adapter_contract_version"] == "computation_adapter.v4"
    assert lock["input_fields"] == [
        {"name": "important", "type": "boolean"},
        {"name": "urgent", "type": "boolean"},
    ]
    assert lock["output_fields"] == [
        {
            "name": "priority",
            "type": "string",
            "min_length": 4,
            "max_length": 8,
            "enum": ["delegate", "do_now", "drop", "schedule"],
        }
    ]
    serialized = json.dumps(lock, ensure_ascii=False, sort_keys=True)
    for forbidden in (
        "capsule_id",
        "version_id",
        "canonical_hash",
        "input_contract",
        "output_contract",
        "source",
    ):
        assert forbidden not in serialized
    schema = product_planner_module._structured_output_schema(
        "product_blueprint",
        request,
    )
    assert schema["properties"]["gaps"]["minItems"] == 1
    assert schema["properties"]["gaps"]["maxItems"] == 1


def test_multiple_deterministic_gaps_require_one_safe_user_selection(
    tmp_path: Path,
) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    catalog = revision_71_two_gap_catalog()
    normalized = planner._catalog(catalog)
    reversed_normalized = planner._catalog(
        {
            "warehouse_revision": 71,
            "capsules": list(reversed(catalog["capsules"])),
        }
    )
    candidates = planner._capability_gap_candidates(normalized)
    reversed_candidates = planner._capability_gap_candidates(
        reversed_normalized
    )
    assert [
        candidate["capability_key"] for candidate in candidates
    ] == [
        "rectangular_prism_volume",
        "workflow_state_classification",
    ]
    select_small(planner)
    planner.generation_outputs.extend(
        [quote_outline(), no_composition_selection()]
    )
    started = planner.start(
        "创建一个本地工作流状态分类工具。",
        catalog,
    )
    assert started["ok"] is True
    assert started["data"]["status"] == "needs_clarification"
    question_set = started["data"]["question_set"]
    workspace = planner._workspace_by_token(
        started["data"]["plan_token"]
    )
    assert workspace["schema_version"] == "product_workspace.v12"
    assert question_set["schema_version"] == "product_plan_question_set.v4"
    reversed_question_set = planner._capability_gap_target_question_set(
        reversed_candidates,
        reversed_normalized,
        question_set["target_context_digest"],
    )
    assert json.dumps(
        question_set,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode() == json.dumps(
        reversed_question_set,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    question = question_set["questions"][0]
    assert question["allow_custom"] is False
    assert [option["label"] for option in question["options"]] == [
        "工作流状态分类",
        "长方体体积计算",
        "以上都不是",
    ]
    serialized = json.dumps(question_set, ensure_ascii=False)
    for forbidden in (
        "capability_key",
        "capsule_id",
        "version_id",
        "canonical_hash",
        "computation_adapter",
        "source_graph",
        "offer_ref",
    ):
        assert forbidden not in serialized
    workflow_option = next(
        option
        for option in question["options"]
        if option["label"] == "工作流状态分类"
    )
    workflow_answers = [
        {
            "question_id": question["question_id"],
            "source": "option",
            "value": workflow_option["option_id"],
        }
    ]
    structured = planner._answers(question_set, workflow_answers)
    first_selection = planner._capability_gap_target_selection(
        workspace,
        question_set,
        structured,
        normalized,
    )
    second_selection = planner._capability_gap_target_selection(
        workspace,
        reversed_question_set,
        structured,
        reversed_normalized,
    )
    assert first_selection == second_selection
    no_match_answers = planner._answers(
        question_set,
        [
            {
                "question_id": question["question_id"],
                "source": "option",
                "value": question["options"][-1]["option_id"],
            }
        ],
    )
    no_match_selection = planner._capability_gap_target_selection(
        workspace,
        question_set,
        no_match_answers,
        normalized,
    )
    assert no_match_selection == planner._capability_gap_target_selection(
        workspace,
        reversed_question_set,
        no_match_answers,
        reversed_normalized,
    )
    assert no_match_selection["outcome"] == "no_match"
    assert no_match_selection["candidate_digest"] is None
    prism_option = next(
        option
        for option in question["options"]
        if option["label"] == "长方体体积计算"
    )
    prism_selection = planner._capability_gap_target_selection(
        workspace,
        question_set,
        planner._answers(
            question_set,
            [
                {
                    "question_id": question["question_id"],
                    "source": "option",
                    "value": prism_option["option_id"],
                }
            ],
        ),
        normalized,
    )
    assert planner._selected_capability_gap_candidate(
        prism_selection,
        normalized,
    )["capability_key"] == "rectangular_prism_volume"
    assert started["data"]["question_set"] == question_set
    assert [call["call_type"] for call in workspace["model_calls"]] == [
        "requirements_outline",
        "composition_selection",
    ]

    captured: dict[str, object] = {}
    original = planner._generate_json

    def generated(model, call_type, request_value, cancel_check=None, **kwargs):
        if call_type == "product_blueprint":
            captured["request"] = copy.deepcopy(request_value)
        return original(
            model,
            call_type,
            request_value,
            cancel_check,
            **kwargs,
        )

    planner._generate_json = generated
    planner.generation_outputs.append(single_quote_gap_blueprint())
    answered = planner.answer(
        workspace["plan_token"],
        question_set["digest"],
        workflow_answers,
        catalog,
    )
    assert answered["ok"] is True
    assert answered["data"]["status"] == "plan_review"
    projection = answered["data"]["capability_gaps"][0][
        "projection"
    ]
    assert projection["schema_version"] == "capability_gap_projection.v2"
    assert projection["capability_key"] == (
        "workflow_state_classification"
    )
    assert projection["slot"] == "only_computation"
    assert projection["adapter_contract_version"] == (
        "computation_adapter.v4"
    )
    assert projection["result_enum"] == [
        "delegate",
        "do_now",
        "drop",
        "schedule",
    ]
    lock = captured["request"]["capability_gap_lock"]
    assert lock["capability_key"] == "workflow_state_classification"
    plan = answered["data"]["plan"]
    reversed_projection, reversed_status = (
        planner._capability_gap_projection(
            plan,
            reversed_normalized,
            first_selection["candidate_digest"],
        )
    )
    assert reversed_status == "available"
    stored_projection = planner._read_capability_gap_projection(
        planner._workspace_by_token(workspace["plan_token"])
    )
    assert reversed_projection == stored_projection
    assert [call["call_type"] for call in planner._workspace_by_token(
        workspace["plan_token"]
    )["model_calls"]] == [
        "requirements_outline",
        "composition_selection",
        "product_blueprint",
    ]

    rejector = StubPlanner(tmp_path / "reject-all")
    select_small(rejector)
    rejector.generation_outputs.extend(
        [quote_outline(), no_composition_selection()]
    )
    rejected_start = rejector.start(
        "创建另一个不属于这些候选的本地工具。",
        catalog,
    )
    rejected_question_set = rejected_start["data"]["question_set"]
    rejected_question = rejected_question_set["questions"][0]
    rejected = rejector.answer(
        rejected_start["data"]["plan_token"],
        rejected_question_set["digest"],
        [
            {
                "question_id": rejected_question["question_id"],
                "source": "option",
                "value": rejected_question["options"][-1]["option_id"],
            }
        ],
        catalog,
    )
    assert rejected["error"]["code"] == (
        "product_plan_capability_gap_target_unmatched"
    )
    assert [
        call["call_type"]
        for call in rejector._workspace_by_token(
            rejected_start["data"]["plan_token"]
        )["model_calls"]
    ] == ["requirements_outline", "composition_selection"]


def test_gap_target_selection_fails_closed_on_invalid_answer_or_drift(
    tmp_path: Path,
) -> None:
    catalog = revision_71_two_gap_catalog()
    for source, value in (
        ("custom", "请替我选择"),
        ("option", "option_unknown"),
    ):
        planner = StubPlanner(tmp_path / source)
        select_small(planner)
        planner.generation_outputs.extend(
            [quote_outline(), no_composition_selection()]
        )
        started = planner.start("创建本地分类工具。", catalog)
        question_set = started["data"]["question_set"]
        result = planner.answer(
            started["data"]["plan_token"],
            question_set["digest"],
            [
                {
                    "question_id": question_set["questions"][0][
                        "question_id"
                    ],
                    "source": source,
                    "value": value,
                }
            ],
            catalog,
        )
        assert result["error"]["code"] == "product_plan_answers_invalid"

    planner = StubPlanner(tmp_path / "stale")
    select_small(planner)
    planner.generation_outputs.extend(
        [quote_outline(), no_composition_selection()]
    )
    started = planner.start("创建本地分类工具。", catalog)
    question_set = started["data"]["question_set"]
    changed = copy.deepcopy(catalog)
    changed["warehouse_revision"] = 72
    option = question_set["questions"][0]["options"][0]
    stale = planner.answer(
        started["data"]["plan_token"],
        question_set["digest"],
        [
            {
                "question_id": question_set["questions"][0][
                    "question_id"
                ],
                "source": "option",
                "value": option["option_id"],
            }
        ],
        changed,
    )
    assert stale["error"]["code"] == (
        "product_plan_capability_gap_target_stale"
    )

    workspace = planner._workspace_by_token(
        started["data"]["plan_token"]
    )
    target_context_drift = copy.deepcopy(question_set)
    target_context_drift["target_context_digest"] = "f" * 64
    target_context_drift["digest"] = product_planner_module._digest(
        {
            key: value
            for key, value in target_context_drift.items()
            if key != "digest"
        }
    )
    with pytest.raises(ProductPlanningError) as captured:
        planner._capability_gap_target_selection(
            workspace,
            target_context_drift,
            planner._answers(
                question_set,
                [
                    {
                        "question_id": question_set["questions"][0][
                            "question_id"
                        ],
                        "source": "option",
                        "value": option["option_id"],
                    }
                ],
            ),
            planner._catalog(catalog),
        )
    assert captured.value.code == (
        "product_plan_capability_gap_target_stale"
    )

    planner = StubPlanner(tmp_path / "duplicate")
    select_small(planner)
    planner.generation_outputs.extend(
        [quote_outline(), no_composition_selection()]
    )
    started = planner.start("创建本地分类工具。", catalog)
    question_set = started["data"]["question_set"]
    answer = {
        "question_id": question_set["questions"][0]["question_id"],
        "source": "option",
        "value": question_set["questions"][0]["options"][0]["option_id"],
    }
    duplicate = planner.answer(
        started["data"]["plan_token"],
        question_set["digest"],
        [answer, answer],
        catalog,
    )
    assert duplicate["error"]["code"] == "product_plan_answers_invalid"

    planner = StubPlanner(tmp_path / "candidate-drift")
    select_small(planner)
    planner.generation_outputs.extend(
        [quote_outline(), no_composition_selection()]
    )
    started = planner.start("创建本地分类工具。", catalog)
    question_set = started["data"]["question_set"]
    candidate_drift = copy.deepcopy(catalog)
    candidate_drift["capsules"][0]["canonical_hash"] = "f" * 64
    drifted = planner.answer(
        started["data"]["plan_token"],
        question_set["digest"],
        [
            {
                "question_id": question_set["questions"][0][
                    "question_id"
                ],
                "source": "option",
                "value": question_set["questions"][0]["options"][0][
                    "option_id"
                ],
            }
        ],
        candidate_drift,
    )
    assert drifted["error"]["code"] == (
        "product_plan_capability_gap_target_stale"
    )

    too_many = copy.deepcopy(catalog)
    third = finite_enum_gap_catalog(
        capability_key="third_gap",
        display_name="第三个业务能力",
        result_field="state",
        result_enum=["no", "yes"],
    )
    fourth = finite_enum_gap_catalog(
        capability_key="fourth_gap",
        display_name="第四个业务能力",
        result_field="state",
        result_enum=["no", "yes"],
    )
    too_many["capsules"].extend(third["capsules"])
    too_many["capsules"].extend(fourth["capsules"])
    planner = StubPlanner(tmp_path / "too-many")
    select_small(planner)
    planner.generation_outputs.extend(
        [quote_outline(), no_composition_selection()]
    )
    failed = planner.start("创建一个当前尚缺失的本地工具。", too_many)
    assert failed["error"]["code"] == (
        "product_plan_capability_gap_target_ambiguous"
    )


def test_single_unrelated_gap_can_be_rejected_before_blueprint(
    tmp_path: Path,
) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    catalog = revision_73_one_gap_catalog()
    select_small(planner)
    planner.generation_outputs.extend(
        [
            {
                "schema_version": "product_plan_outline.v1",
                "product_name": "本地报修消息紧急度分类器",
                "language": "zh",
                "requirements": [
                    {
                        "ref": "r_workorder",
                        "statement": "输入报修文本并分类为紧急或普通。",
                        "source": "goal",
                    }
                ],
                "needs_clarification": False,
                "questions": [],
            },
            no_composition_selection(),
        ]
    )
    started = planner.start(
        "创建一个本地报修消息紧急度分类器。",
        catalog,
    )
    assert started["ok"] is True
    assert started["data"]["status"] == "needs_clarification"
    question_set = started["data"]["question_set"]
    assert question_set["schema_version"] == "product_plan_question_set.v4"
    question = question_set["questions"][0]
    assert [option["label"] for option in question["options"]] == [
        "长方体体积计算",
        "以上都不是",
    ]
    assert [option["forms_gap"] for option in question["options"]] == [
        True,
        False,
    ]
    no_match = question["options"][-1]
    stopped = planner.answer(
        started["data"]["plan_token"],
        question_set["digest"],
        [
            {
                "question_id": question["question_id"],
                "source": "option",
                "value": no_match["option_id"],
            }
        ],
        catalog,
    )
    assert stopped["error"]["code"] == (
        "product_plan_capability_gap_target_unmatched"
    )
    assert stopped["data"]["status"] == "failed"
    assert stopped["data"]["plan"] is None
    assert stopped["data"]["capability_gaps"] == []
    workspace = planner._workspace_by_token(
        started["data"]["plan_token"]
    )
    assert workspace["failure_code"] == (
        "product_plan_capability_gap_target_unmatched"
    )
    assert workspace["capability_gap_target_selection"]["outcome"] == (
        "no_match"
    )
    assert workspace["capability_gap_target_selection"][
        "candidate_digest"
    ] is None
    assert workspace["blueprint"] is None
    assert [call["call_type"] for call in workspace["model_calls"]] == [
        "requirements_outline",
        "composition_selection",
    ]
    assert not list(
        (tmp_path / "product_workspaces").rglob(
            "capability_gap_projection*.json"
        )
    )
    assert not list(
        (tmp_path / "product_workspaces").rglob("agent_handoff_v1_*.json")
    )
    workspace_path = (
        planner.root / workspace["workspace_id"] / "workspace.json"
    )
    terminal_bytes = workspace_path.read_bytes()
    request_count = len(planner.requests)

    resumed = planner.start(
        "创建一个本地报修消息紧急度分类器。",
        catalog,
        resume_plan_token=workspace["plan_token"],
    )
    assert resumed["error"]["code"] == "product_plan_no_match_terminal"
    assert len(planner.requests) == request_count
    assert workspace_path.read_bytes() == terminal_bytes

    for _ in range(2):
        abandoned = planner.abandon(workspace["plan_token"])
        assert abandoned["ok"] is True
        assert abandoned["data"]["status"] == "failed"
        assert workspace_path.read_bytes() == terminal_bytes

    restarted = StubPlanner(tmp_path / "product_workspaces")
    restored = restarted.get(workspace["plan_token"], catalog)
    assert restored["ok"] is True
    assert restored["data"]["status"] == "failed"
    assert restored["data"]["developer_evidence"]["failure_code"] == (
        "product_plan_capability_gap_target_unmatched"
    )
    summaries = restarted.list_summaries()["data"]["summaries"]
    assert any(
        row["plan_token"] == workspace["plan_token"]
        and row["status"] == "failed"
        for row in summaries
    )
    assert workspace_path.read_bytes() == terminal_bytes


def test_unique_gap_requires_confirmation_then_model_only_describes_it(
    tmp_path: Path,
) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    captured: dict[str, object] = {}
    original = planner._generate_json

    def generated(model, call_type, request_value, cancel_check=None, **kwargs):
        if call_type == "product_blueprint":
            captured["request"] = copy.deepcopy(request_value)
        return original(
            model,
            call_type,
            request_value,
            cancel_check,
            **kwargs,
        )

    planner._generate_json = generated
    created = start_time_gap_plan(planner, "hours_to_minutes")

    assert created["ok"] is True
    request = captured["request"]
    lock = request["capability_gap_lock"]
    assert request["selection_locked"] is True
    assert request["composition_offers"] == []
    assert "schema_example" not in request
    assert lock["capability_key"] == "time_unit_conversion"
    assert lock["slot"] == "before_existing_computation"
    assert lock["adapter_contract_version"] == "computation_adapter.v2"
    assert lock["input_fields"] == [
        {"name": "hours", "type": "integer", "minimum": 0, "maximum": 8760}
    ]
    assert lock["output_fields"] == [
        {
            "name": "minutes",
            "type": "integer",
            "minimum": 0,
            "maximum": 525600,
        }
    ]
    assert [item["role_key"] for item in lock["existing_members"]] == [
        "hours_input",
        "minutes_to_seconds",
        "seconds_result",
    ]
    serialized = json.dumps(request, sort_keys=True)
    for forbidden in (
        "capsule_id",
        "version_id",
        "canonical_hash",
        "input_contract",
        "output_contract",
    ):
        assert forbidden not in serialized

    schema = product_planner_module._structured_output_schema(
        "product_blueprint",
        request,
    )
    assert schema["properties"]["gaps"]["minItems"] == 1
    assert schema["properties"]["gaps"]["maxItems"] == 1
    assert set(schema["properties"]["gaps"]["items"]["properties"]) == {
        "title",
        "reason",
    }
    assert schema["properties"]["sections"]["properties"]["backend"][
        "properties"
    ]["applicability"]["enum"] == ["applicable"]
    plan = created["data"]["plan"]
    gaps = [gap for section in plan["sections"] for gap in section["gaps"]]
    assert len(gaps) == 1
    assert gaps[0]["requirement_ids"] == [
        plan["requirements"][0]["requirement_id"]
    ]
    workspace = planner._workspace_by_token(created["data"]["plan_token"])
    assert workspace["schema_version"] == "product_workspace.v12"
    assert workspace["blueprint_input_digest"] == (
        planner._selected_blueprint_input_digest(
            workspace,
            workspace["outline"],
            None,
            lock,
        )
    )
    changed_lock = copy.deepcopy(lock)
    changed_lock["output_fields"][0]["maximum"] += 1
    assert workspace["blueprint_input_digest"] != (
        planner._selected_blueprint_input_digest(
            workspace,
            workspace["outline"],
            None,
            changed_lock,
        )
    )
    assert workspace["plan"]["planning_rules_version"] == (
        "reweave_product_planning_rules.v12"
    )
    assert workspace["plan"]["prompt_version"] == (
        "reweave_product_planning_prompt.v13"
    )

    invalid = time_gap_blueprint()
    invalid["gaps"].append(
        {"title": "第二个缺口", "reason": "模型不得拆分锁定缺口。"}
    )
    with pytest.raises(ProductPlanningError) as captured_error:
        planner._expand_locked_gap_blueprint(
            invalid,
            time_outline()["requirements"],
        )
    assert captured_error.value.rule_code == "blueprint.locked_gap_invalid"


@pytest.mark.parametrize(
    (
        "missing_role",
        "slot",
        "result_field",
        "upstream_role",
        "downstream_role",
        "acceptance_cases",
    ),
    [
        (
            "hours_to_minutes",
            "before_existing_computation",
            "minutes",
            "hours_input",
            "minutes_to_seconds",
            [
                {"input": {"hours": 1}, "expected_output": {"minutes": 60}},
                {"input": {"hours": 2}, "expected_output": {"minutes": 120}},
                {
                    "input": {"hours": 24},
                    "expected_output": {"minutes": 1440},
                },
            ],
        ),
        (
            "minutes_to_seconds",
            "after_existing_computation",
            "seconds",
            "hours_to_minutes",
            "seconds_result",
            [
                {
                    "input": {"minutes": 60},
                    "expected_output": {"seconds": 3600},
                },
                {
                    "input": {"minutes": 120},
                    "expected_output": {"seconds": 7200},
                },
                {
                    "input": {"minutes": 1440},
                    "expected_output": {"seconds": 86400},
                },
            ],
        ),
    ],
)
def test_time_conversion_gap_uses_generic_integer_projection(
    tmp_path: Path,
    missing_role: str,
    slot: str,
    result_field: str,
    upstream_role: str,
    downstream_role: str,
    acceptance_cases: list[dict[str, object]],
) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    catalog_value = time_gap_catalog(missing_role)
    created = start_time_gap_plan(planner, missing_role)
    assert created["ok"] is True
    gap = created["data"]["capability_gaps"][0]
    projection = gap["projection"]
    normalized = planner._catalog(catalog_value)
    formal_projection, formal_status = (
        planner._capability_gap_projection(
            created["data"]["plan"],
            normalized,
        )
    )
    assert gap["status"] == "available"
    assert formal_status == "available"
    assert projection["projection_digest"] == (
        formal_projection["projection_digest"]
    )
    assert projection["capability_key"] == "time_unit_conversion"
    assert projection["slot"] == slot
    assert projection["adapter_contract_version"] == "computation_adapter.v2"
    assert formal_projection["capture_mapping_schema"] == (
        "computation_capture_mapping.v2"
    )
    assert projection["result_field"] == result_field
    assert projection["passthrough_fields"] == []
    assert formal_projection["upstream"]["role_key"] == upstream_role
    assert formal_projection["downstream"]["role_key"] == downstream_role

    reversed_projection, reversed_status = (
        planner._capability_gap_projection(
            created["data"]["plan"],
            planner._catalog(
                {
                    "warehouse_revision": catalog_value[
                        "warehouse_revision"
                    ],
                    "capsules": list(reversed(catalog_value["capsules"])),
                }
            ),
        )
    )
    assert reversed_status == "available"
    assert json.dumps(
        formal_projection,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8") == json.dumps(
        reversed_projection,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    changed_text = copy.deepcopy(created["data"]["plan"])
    changed_text["canonical_digest"] = "f" * 64
    changed_text["sections"][1]["gaps"][0]["title"] = "不同建议标题"
    changed_text["sections"][1]["gaps"][0]["reason"] = "不同建议原因"
    changed_projection, changed_status = planner._capability_gap_projection(
        changed_text,
        normalized,
    )
    assert changed_status == "available"
    semantic_keys = {
        "capability_key",
        "capability_kind",
        "slot",
        "input_contract",
        "output_contract",
        "adapter_contract_version",
        "capture_mapping_schema",
        "result_field",
        "passthrough_fields",
        "upstream",
        "downstream",
        "existing_members",
        "warehouse_revision",
        "catalog_digest",
        "projection_source",
    }
    assert {
        key: formal_projection[key] for key in semantic_keys
    } == {
        key: changed_projection[key] for key in semantic_keys
    }
    assert formal_projection["projection_digest"] != (
        changed_projection["projection_digest"]
    )

    authorized = planner.record_capability_gap_decision(
        created["data"]["plan_token"],
        created["data"]["plan"]["canonical_digest"],
        projection["projection_digest"],
        None,
        "authorize",
        (
            "将整数小时转换为分钟。"
            if missing_role == "hours_to_minutes"
            else "将整数分钟转换为秒。"
        ),
        None,
        acceptance_cases,
        catalog_value,
    )
    assert authorized["ok"] is True
    assert authorized["data"]["capability_gaps"][0]["current_decision"][
        "acceptance_cases"
    ] == acceptance_cases


def test_time_conversion_gap_is_not_name_special_cased_and_fails_closed() -> None:
    planner = StubPlanner(Path("/private/tmp/reweave-time-gap-generic-probe"))
    plan = {
        "plan_id": "plan_" + "a" * 24,
        "plan_version": 1,
        "canonical_digest": "b" * 64,
        "sections": [
            {
                "section_id": "backend",
                "gaps": [
                    {
                        "gap_id": "gap_" + "c" * 20,
                        "title": "通用整数能力",
                        "reason": "确定性目录存在一个缺口。",
                        "requirement_ids": ["requirement_" + "d" * 20],
                    }
                ],
            }
        ],
    }
    complete = planner._catalog(formal_revision_42_catalog())
    assert planner._capability_gap_projection(plan, complete) == (
        None,
        "capability_gap_boundary_unavailable",
    )

    ambiguous = formal_revision_42_catalog()
    ambiguous["capsules"] = [
        row
        for row in ambiguous["capsules"]
        if row["role_key"]
        not in {"hours_to_minutes", "quantity_discount_policy"}
    ]
    assert planner._capability_gap_projection(
        plan,
        planner._catalog(ambiguous),
    ) == (None, "capability_gap_boundary_ambiguous")

    source = inspect.getsource(
        ProductPlanner._capability_gap_candidates
    ) + inspect.getsource(
        ProductPlanner._integer_gap_adapter
    ) + inspect.getsource(
        ProductPlanner._capability_gap_blueprint_lock
    ) + inspect.getsource(
        ProductPlanner._expand_locked_gap_blueprint
    )
    for forbidden in (
        "quote_calculation",
        "time_unit_conversion",
        "quantity",
        "unit_price",
        "hours",
        "minutes",
        "seconds",
    ):
        assert forbidden not in source


def test_capability_gap_decision_rejects_catalog_drift_and_tampering(
    tmp_path: Path,
) -> None:
    planner = StubPlanner(tmp_path / "product_workspaces")
    created = start_quote_gap_plan(planner)
    gap = created["data"]["capability_gaps"][0]
    stale_catalog = quote_gap_catalog()
    stale_catalog["warehouse_revision"] = 42
    stale = planner.record_capability_gap_decision(
        created["data"]["plan_token"],
        created["data"]["plan"]["canonical_digest"],
        gap["projection"]["projection_digest"],
        None,
        "defer",
        None,
        None,
        [],
        stale_catalog,
    )
    assert stale["error"]["code"] == "capability_gap_projection_stale"

    workspace = planner._workspace_by_token(created["data"]["plan_token"])
    projection_path = planner._capability_gap_projection_path(
        workspace,
        workspace["plan"],
    )
    tampered = json.loads(projection_path.read_text(encoding="utf-8"))
    tampered["result_field"] = "total"
    projection_path.write_text(json.dumps(tampered), encoding="utf-8")
    restored = planner.get(
        created["data"]["plan_token"],
        quote_gap_catalog(),
    )
    assert restored["ok"] is False
    assert restored["error"]["code"] == "capability_gap_projection_invalid"


def test_capability_gap_rejects_two_legal_positions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    normalized = StubPlanner(
        Path("/private/tmp/reweave-gap-two-position-probe")
    )._catalog(quote_gap_catalog())
    monkeypatch.setattr(
        product_planner_module,
        "contracts_compatible",
        lambda _source, _target: True,
    )
    monkeypatch.setattr(
        ProductPlanner,
        "_integer_gap_adapter",
        staticmethod(
            lambda _input, _output: {
                "adapter_contract_version": "computation_adapter.v3",
                "capture_mapping_schema": "computation_capture_mapping.v3",
                "result_field": "result",
                "passthrough_fields": ["quantity"],
            }
        ),
    )

    assert ProductPlanner._capability_gap_candidates(normalized) == []


def test_capability_replan_handoff_locks_one_offer_and_is_idempotent(
    tmp_path: Path,
) -> None:
    empty = {
        "schema": "data_contract.v1",
        "type": "object",
        "properties": {},
        "required": [],
        "additional_properties": False,
    }
    years = {
        "schema": "data_contract.v1",
        "type": "object",
        "properties": {
            "years": {"type": "integer", "minimum": 0, "maximum": 100}
        },
        "required": ["years"],
        "additional_properties": False,
    }
    months = {
        "schema": "data_contract.v1",
        "type": "object",
        "properties": {
            "months": {"type": "integer", "minimum": 0, "maximum": 1200}
        },
        "required": ["months"],
        "additional_properties": False,
    }
    errors = {"schema": "error_contract.v1", "errors": {}}
    year_rows = [
        {
            "capsule_id": "capsule_year_input",
            "version_id": "version_year_input",
            "display_name": "年数换算为月数",
            "capability_key": "year_month_conversion",
            "role_key": "years_input",
            "variant_key": "default",
            "capability_kind": "interaction",
            "canonical_hash": "a" * 64,
            "identity_status": "formal_exact_version",
            "input_contract": empty,
            "output_contract": {
                "schema": "event_outputs.v1",
                "events": {"conversion_requested": years},
            },
            "error_contract": errors,
        },
        {
            "capsule_id": "capsule_year_compute",
            "version_id": "version_year_compute",
            "display_name": "年数换算为月数",
            "capability_key": "year_month_conversion",
            "role_key": "years_to_months",
            "variant_key": "default",
            "capability_kind": "computation",
            "canonical_hash": "b" * 64,
            "identity_status": "formal_exact_version",
            "input_contract": years,
            "output_contract": months,
            "error_contract": errors,
        },
        {
            "capsule_id": "capsule_month_result",
            "version_id": "version_month_result",
            "display_name": "年数换算为月数",
            "capability_key": "year_month_conversion",
            "role_key": "months_result",
            "variant_key": "default",
            "capability_kind": "presentation",
            "canonical_hash": "c" * 64,
            "identity_status": "formal_exact_version",
            "input_contract": months,
            "output_contract": {"schema": "no_output.v1"},
            "error_contract": errors,
        },
    ]
    base = two_offer_catalog()
    gap_catalog = {
        "warehouse_revision": 55,
        "capsules": [*base["capsules"], year_rows[0], year_rows[2]],
    }
    goal = "输入整数年数，转换为月数，并只展示最终月数。"
    outline_value = {
        "schema_version": "product_plan_outline.v1",
        "product_name": "年数换算工具",
        "language": "zh",
        "requirements": [
            {"ref": "r_years", "statement": goal, "source": "goal"}
        ],
        "needs_clarification": False,
        "questions": [],
    }
    planner = StubPlanner(tmp_path / "product_workspaces")
    select_small(planner)
    planner.generation_outputs.extend(
        [outline_value, no_composition_selection(), time_gap_blueprint()]
    )
    created = planner.start(goal, gap_catalog)
    question_set = created["data"]["question_set"]
    question = question_set["questions"][0]
    candidate_option = next(
        option for option in question["options"] if option["forms_gap"]
    )
    created = planner.answer(
        created["data"]["plan_token"],
        question_set["digest"],
        [
            {
                "question_id": question["question_id"],
                "source": "option",
                "value": candidate_option["option_id"],
            }
        ],
        gap_catalog,
    )
    gap = created["data"]["capability_gaps"][0]
    projection = gap["projection"]
    decided = planner.record_capability_gap_decision(
        created["data"]["plan_token"],
        created["data"]["plan"]["canonical_digest"],
        projection["projection_digest"],
        None,
        "authorize",
        "将整数年数转换为月数。",
        None,
        [
            {"input": {"years": 1}, "expected_output": {"months": 12}},
            {"input": {"years": 2}, "expected_output": {"months": 24}},
            {"input": {"years": 100}, "expected_output": {"months": 1200}},
        ],
        gap_catalog,
    )
    decision = decided["data"]["capability_gaps"][0]["current_decision"]
    prepared = planner.prepare_capability_source_proposal(
        created["data"]["plan_token"],
        created["data"]["plan"]["canonical_digest"],
        projection["projection_digest"],
        decision["canonical_digest"],
        gap_catalog,
    )
    assert prepared["ok"] is True
    source = planner._workspace_by_token(created["data"]["plan_token"])
    stored_projection = planner._read_capability_gap_projection(source)
    authorization = planner._read_capability_source_proposal_authorization(
        source,
        stored_projection,
        planner._capability_gap_decisions(source, stored_projection)[-1],
    )
    full_catalog = {
        "warehouse_revision": 57,
        "capsules": [*base["capsules"], *copy.deepcopy(year_rows)],
    }
    published = next(
        row
        for row in full_catalog["capsules"]
        if row["role_key"] == "years_to_months"
    )
    published["error_contract"] = authorization["error_contract"]
    global_map = {
        f"candidate_{index}": row
        for index, row in enumerate(
            planner._catalog(full_catalog)["capsules"]
        )
    }
    global_offers = planner._composition_offers(global_map)
    assert len(global_offers) == 3
    locked_offer = next(
        offer
        for offer in global_offers
        if offer["capability_key"] == "year_month_conversion"
    )
    for invalid_key in ("", "time_unit_conversion"):
        planner.generation_outputs.append(
            {
                "schema_version": "product_composition_selection.v1",
                "capability_key": invalid_key,
            }
        )
        invalid, _evidence = planner._composition_selection_call(
            planner._selected_model(check_current=False),
            goal,
            outline_value,
            [],
            [locked_offer],
            None,
            selection_locked=True,
        )
        if invalid_key:
            with pytest.raises(
                ProductPlanningError,
                match="product_plan_composition_unknown",
            ):
                planner._resolve_composition_selection(
                    invalid,
                    [locked_offer],
                )
        else:
            assert planner._resolve_composition_selection(
                invalid,
                [locked_offer],
            ) is None

    captured: list[dict[str, object]] = []
    planner.generation_outputs.append(outline_value)
    original = planner._generate_json

    def generated(model, call_type, request_value, cancel_check=None, **kwargs):
        if call_type == "composition_selection":
            captured.append(copy.deepcopy(request_value))
            offer = request_value["composition_offers"][0]
            planner.generation_outputs.insert(
                0,
                {
                    "schema_version": "product_composition_selection.v1",
                    "capability_key": offer["capability_key"],
                },
            )
        elif call_type == "product_blueprint":
            offer = request_value["composition_offers"][0]
            assignments = {
                member["candidate_ref"]: {
                    "section_id": (
                        "frontend"
                        if member["capability_kind"]
                        in {"interaction", "presentation"}
                        else "backend"
                    ),
                    "requirement_refs": ["r_years"],
                    "title": member["role_key"],
                    "summary": "使用锁定的正式能力。",
                    "acceptance_intent": "验证确定性串联。",
                }
                for member in offer["members"]
            }
            planner.generation_outputs.insert(
                0,
                {
                    "schema_version": "product_plan_blueprint.v2",
                    "sections": {
                        "frontend": {
                            "applicability": "applicable",
                            "summary": "输入与结果。",
                        },
                        "backend": {
                            "applicability": "applicable",
                            "summary": "年数转换。",
                        },
                        "data": {
                            "applicability": "not_applicable",
                            "summary": "无需数据层。",
                        },
                        "infrastructure": {
                            "applicability": "not_applicable",
                            "summary": "无需基础设施层。",
                        },
                    },
                    "selection": {
                        "offer_ref": offer["offer_ref"],
                        "assignments": assignments,
                    },
                    "gaps": [],
                },
            )
        return original(
            model,
            call_type,
            request_value,
            cancel_check,
            **kwargs,
        )

    planner._generate_json = generated  # type: ignore[method-assign]
    binding = {
        "admission_review_id": "review_year",
        "admission_digest": "d" * 64,
        "publication_review_id": "review_year",
        "published_capsule": planner._gap_capsule_identity(published),
        "authorization_revision": 55,
        "admission_revision_before": 55,
        "admission_revision_after": 56,
        "publication_revision": 57,
    }
    result = planner.start_capability_replan(
        created["data"]["plan_token"],
        created["data"]["plan"]["canonical_digest"],
        projection["projection_digest"],
        binding,
        full_catalog,
    )
    assert result["ok"] is True
    successor = result["data"]
    assert successor["status"] == "plan_review"
    assert successor["confirmation"] is None
    assert [
        call["call_type"]
        for call in successor["developer_evidence"]["model_calls"]
    ] == [
        "requirements_outline",
        "composition_selection",
        "product_blueprint",
    ]
    assert len(captured) == 1
    assert captured[0]["selection_locked"] is True
    assert len(captured[0]["composition_offers"]) == 1
    assert captured[0]["composition_offers"][0]["capability_key"] == (
        "year_month_conversion"
    )
    schema = product_planner_module._structured_output_schema(
        "composition_selection",
        captured[0],
    )
    assert schema["properties"]["capability_key"]["enum"] == [
        "year_month_conversion"
    ]
    items = {
        item["title"]: item
        for section in successor["plan"]["sections"]
        for item in section["work_items"]
    }
    assert set(items) == {"years_input", "years_to_months", "months_result"}
    assert items["years_input"]["depends_on"] == []
    assert items["years_to_months"]["depends_on"] == [
        items["years_input"]["work_item_id"]
    ]
    assert items["months_result"]["depends_on"] == [
        items["years_to_months"]["work_item_id"]
    ]
    assert successor["capability_replan"]["acceptance_suggestions"] == (
        decision["acceptance_cases"]
    )

    request_count = len(planner.requests)
    reversed_catalog = copy.deepcopy(full_catalog)
    reversed_catalog["capsules"].reverse()
    repeated = planner.start_capability_replan(
        created["data"]["plan_token"],
        created["data"]["plan"]["canonical_digest"],
        projection["projection_digest"],
        None,
        reversed_catalog,
    )
    assert repeated["ok"] is True
    assert repeated["data"]["plan_token"] == successor["plan_token"]
    assert len(planner.requests) == request_count
    with ThreadPoolExecutor(max_workers=20) as executor:
        concurrent = list(
            executor.map(
                lambda _index: planner.start_capability_replan(
                    created["data"]["plan_token"],
                    created["data"]["plan"]["canonical_digest"],
                    projection["projection_digest"],
                    None,
                    full_catalog,
                ),
                range(20),
            )
        )
    assert {
        row["data"]["plan_token"] for row in concurrent if row["ok"] is True
    } == {successor["plan_token"]}
    assert len(planner.requests) == request_count
    stale_catalog = copy.deepcopy(full_catalog)
    stale_catalog["warehouse_revision"] = 58
    stale = planner.start_capability_replan(
        created["data"]["plan_token"],
        created["data"]["plan"]["canonical_digest"],
        projection["projection_digest"],
        None,
        stale_catalog,
    )
    assert stale["error"]["code"] == "capability_replan_handoff_stale"
    assert len(list(planner.root.glob("workspace_*/workspace.json"))) == 2

    successor_workspace = planner._workspace_by_token(successor["plan_token"])
    successor_path = (
        planner.root
        / successor_workspace["workspace_id"]
        / "workspace.json"
    )
    successor_bytes = successor_path.read_bytes()
    successor_path.unlink()
    planner.generation_outputs.append(outline_value)
    missing = planner.start_capability_replan(
        created["data"]["plan_token"],
        created["data"]["plan"]["canonical_digest"],
        projection["projection_digest"],
        None,
        full_catalog,
    )
    assert missing["ok"] is True
    assert missing["data"]["plan_token"] == successor["plan_token"]
    assert missing["data"]["status"] == "plan_review"
    assert successor_path.exists()
    assert len(list(planner.root.glob("workspace_*/workspace.json"))) == 2
    assert len(
        list(
            planner._capability_replan_handoffs_dir().glob(
                "handoff_*.json"
            )
        )
    ) == 1

    handoff_path = planner._capability_replan_handoff_path(
        created["data"]["plan"]["canonical_digest"]
    )
    handoff_v2 = planner._read_json(handoff_path)
    assert handoff_v2["schema_version"] == "capability_replan_handoff.v2"
    pristine = planner._successor_workspace_from_binding(
        handoff_v2["successor_workspace_binding"]
    )
    assert handoff_v2["successor_workspace_digest"] == (
        product_planner_module._digest(pristine)
    )
    planner._atomic_write(successor_path, pristine)
    assert planner.recover_orphaned_workspaces(set()) == 1
    planner.generation_outputs.append(outline_value)
    resumed_after_restart = planner.start_capability_replan(
        created["data"]["plan_token"],
        created["data"]["plan"]["canonical_digest"],
        projection["projection_digest"],
        None,
        full_catalog,
    )
    assert resumed_after_restart["ok"] is True
    assert resumed_after_restart["data"]["plan_token"] == (
        successor["plan_token"]
    )
    assert resumed_after_restart["data"]["status"] == "plan_review"

    legacy = {
        key: copy.deepcopy(value)
        for key, value in handoff_v2.items()
        if key
        not in {
            "source_goal_answers_digest",
            "successor_workspace_binding",
            "successor_workspace_digest",
            "handoff_digest",
        }
    }
    legacy["schema_version"] = "capability_replan_handoff.v1"
    legacy["handoff_digest"] = product_planner_module._digest(legacy)
    planner._atomic_write(handoff_path, legacy)
    legacy_result = planner.start_capability_replan(
        created["data"]["plan_token"],
        created["data"]["plan"]["canonical_digest"],
        projection["projection_digest"],
        None,
        full_catalog,
    )
    assert legacy_result["ok"] is True
    assert legacy_result["data"]["plan_token"] == successor["plan_token"]
    assert legacy_result["data"]["capability_replan"]["schema_version"] == (
        "capability_replan_handoff.v1"
    )
    planner._atomic_write(handoff_path, handoff_v2)

    different_request = planner.start_capability_replan(
        created["data"]["plan_token"],
        "f" * 64,
        projection["projection_digest"],
        None,
        full_catalog,
    )
    assert different_request["error"]["code"] == (
        "capability_replan_handoff_conflict"
    )

    for field in (
        "target_offer_digest",
        "successor_workspace_digest",
        "source_goal_answers_digest",
    ):
        handoff = copy.deepcopy(handoff_v2)
        handoff[field] = "0" * 64
        planner._atomic_write(handoff_path, handoff)
        tampered = planner.start_capability_replan(
            created["data"]["plan_token"],
            created["data"]["plan"]["canonical_digest"],
            projection["projection_digest"],
            None,
            full_catalog,
        )
        assert tampered["error"]["code"] == (
            "capability_replan_handoff_conflict"
        )
        planner._atomic_write(handoff_path, handoff_v2)

    recovered_workspace = planner._workspace_by_token(
        successor["plan_token"]
    )
    drifted_workspace = copy.deepcopy(recovered_workspace)
    drifted_workspace["goal"] = "被篡改的后继目标"
    drifted_workspace["goal_digest"] = product_planner_module._digest(
        drifted_workspace["goal"]
    )
    planner._atomic_write(successor_path, drifted_workspace)
    drifted = planner.start_capability_replan(
        created["data"]["plan_token"],
        created["data"]["plan"]["canonical_digest"],
        projection["projection_digest"],
        None,
        full_catalog,
    )
    assert drifted["error"]["code"] == "capability_replan_handoff_conflict"
    successor_path.write_bytes(successor_bytes)
