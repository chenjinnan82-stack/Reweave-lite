from __future__ import annotations

import copy
import json
import stat
from pathlib import Path

import pytest

from pimos_lite.reweave_experience import (
    ExperienceError,
    build_product_experience_model_cases,
    build_product_experience_query,
    build_project_experience_record,
    canonical_bytes,
    goal_tokens,
)
from pimos_lite.reweave_product_planner import ProductPlanningError
from tests.test_reweave_product_planner import (
    StubPlanner,
    multi_computation_catalog,
    queue_blueprint_time_plan,
    select_small,
)


def confirmed_time_workspace(
    root: Path,
    goal: str,
) -> tuple[StubPlanner, str, dict]:
    planner = StubPlanner(root)
    if not (root / "model_selection.json").is_file():
        select_small(planner)
    queue_blueprint_time_plan(planner)
    started = planner.start(goal, multi_computation_catalog())
    plan = started["data"]["plan"]
    confirmed = planner.confirm(
        started["data"]["plan_token"],
        plan["canonical_digest"],
        plan,
        multi_computation_catalog(),
    )
    assert confirmed["data"]["status"] == "confirmed"
    return planner, started["data"]["plan_token"], planner._workspace_by_token(
        started["data"]["plan_token"]
    )


def candidate(status: str = "review_ready") -> dict:
    value = {
        "status": status,
        "execution_digest": "d" * 64,
        "provenance": {"connection_digest": "e" * 64},
        "acceptance": {"status": "passed", "cases": []},
    }
    if status != "review_ready":
        value["acceptance"] = {
            "status": "failed",
            "cases": [
                {
                    "status": "failed",
                    "failure_code": "product_goal_mismatch",
                }
            ],
        }
    return value


def test_project_experience_milestones_are_redacted_immutable_and_recoverable(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state" / "product_workspaces"
    planner, token, workspace = confirmed_time_workspace(
        root,
        "创建本地整数时间换算工具，输入小时并显示最终秒数。",
    )
    catalog = multi_computation_catalog()
    plan_record = planner.record_product_experience(
        token,
        catalog,
        "plan_confirmed",
    )
    terminal_record = planner.record_product_experience(
        token,
        catalog,
        "candidate_terminal",
        candidate=candidate(),
    )
    export_record = planner.record_product_experience(
        token,
        catalog,
        "export_terminal",
        candidate=candidate(),
        export_status="saved",
    )

    assert plan_record and terminal_record and export_record
    assert export_record["safe_case"]["delivery_result"] == "passed"
    experience_root = root.parent / "product_experience"
    record_dir = experience_root / "records" / workspace["workspace_id"]
    assert sorted(path.name for path in record_dir.iterdir()) == [
        "candidate_terminal.json",
        "export_terminal.json",
        "plan_confirmed.json",
    ]
    assert stat.S_IMODE(experience_root.stat().st_mode) == 0o700
    assert all(
        stat.S_IMODE(path.stat().st_mode) == 0o600
        for path in record_dir.iterdir()
    )
    raw = b"".join(path.read_bytes() for path in record_dir.iterdir())
    assert workspace["goal"].encode() not in raw
    for forbidden in (b"/Users/", b"REQUEST_JSON", b"prompt", b"source code"):
        assert forbidden not in raw

    restarted = StubPlanner(root)
    assert (
        restarted.record_product_experience(
            token,
            catalog,
            "export_terminal",
            candidate=candidate(),
            export_status="already_saved",
        )
        == export_record
    )
    with pytest.raises(
        ProductPlanningError,
        match="project_experience_record_conflict",
    ):
        changed = candidate()
        changed["execution_digest"] = "f" * 64
        restarted.record_product_experience(
            token,
            catalog,
            "candidate_terminal",
            candidate=changed,
        )


def test_retrieval_uses_latest_milestone_and_is_order_deterministic(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state" / "product_workspaces"
    planner, token, _workspace = confirmed_time_workspace(
        root,
        "创建本地时间换算工具，将小时换算为秒数。",
    )
    catalog = multi_computation_catalog()
    planner.record_product_experience(token, catalog, "plan_confirmed")
    planner.record_product_experience(
        token,
        catalog,
        "export_terminal",
        candidate=candidate(),
        export_status="saved",
    )
    for goal in (
        "创建本地秒数换算工具。",
        "创建小时分钟换算应用。",
        "创建时间单位换算产品。",
    ):
        historical, historical_token, _ = confirmed_time_workspace(root, goal)
        historical.record_product_experience(
            historical_token,
            catalog,
            "plan_confirmed",
        )

    query_planner = StubPlanner(root)
    queue_blueprint_time_plan(query_planner)
    started = query_planner.start(
        "创建本地时间换算工具，将小时换算为秒数。",
        catalog,
    )
    query = query_planner.retrieve_product_experience(
        started["data"]["plan_token"]
    )
    assert len(query["cases"]) == 3
    assert query["cases"][0]["milestone"] == "export_terminal"
    assert "换算" not in json.dumps(query, ensure_ascii=False)
    model_cases = build_product_experience_model_cases(query)
    assert [item["rank"] for item in model_cases] == [1, 2, 3]
    assert set(model_cases[0]) == {
        "rank",
        "capability_key",
        "members",
        "outcome",
    }
    assert set(model_cases[0]["members"][0]) == {
        "display_name",
        "role_key",
        "variant_key",
        "capability_kind",
    }
    serialized_cases = json.dumps(model_cases, ensure_ascii=False)
    for forbidden in (
        "record_digest",
        "project_scope",
        "source_workspace",
        "exact_model",
        "canonical_hash",
        "capsule_id",
        "version_id",
    ):
        assert forbidden not in serialized_cases

    scope = query_planner._project_experience_scope()
    records = query_planner._project_experience_records(
        scope["canonical_digest"]
    )
    workspace = query_planner._workspace_by_token(
        started["data"]["plan_token"]
    )
    reversed_query = build_product_experience_query(
        workspace=workspace,
        project_scope_digest=scope["canonical_digest"],
        records_with_workspaces=list(reversed(records)),
    )
    assert reversed_query == query

    different_model = copy.deepcopy(workspace)
    different_model["model"]["digest"] = "f" * 64
    isolated = build_product_experience_query(
        workspace=different_model,
        project_scope_digest=scope["canonical_digest"],
        records_with_workspaces=records,
    )
    assert isolated["cases"] == []
    unrelated = copy.deepcopy(workspace)
    unrelated["goal"] = "猫咪音乐播放器"
    unrelated["goal_digest"] = "9" * 64
    zero_match = build_product_experience_query(
        workspace=unrelated,
        project_scope_digest=scope["canonical_digest"],
        records_with_workspaces=records,
    )
    assert zero_match["cases"] == []

    other_root = tmp_path / "other-state" / "product_workspaces"
    other, other_token, _ = confirmed_time_workspace(
        other_root,
        "创建本地时间换算工具，将小时换算为秒数。",
    )
    assert other.retrieve_product_experience(other_token)["cases"] == []
    assert (
        other._project_experience_scope()["canonical_digest"]
        != scope["canonical_digest"]
    )


def test_unattributed_failure_is_not_recorded_and_tampering_fails_closed(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state" / "product_workspaces"
    planner, token, workspace = confirmed_time_workspace(
        root,
        "创建本地时间换算工具。",
    )
    assert (
        planner.record_product_experience(
            token,
            multi_computation_catalog(),
            "candidate_terminal",
            candidate={
                "status": "acceptance_failed",
                "acceptance": {"status": "failed", "cases": []},
            },
        )
        is None
    )
    assert not (
        root.parent
        / "product_experience"
        / "records"
        / workspace["workspace_id"]
        / "candidate_terminal.json"
    ).exists()

    planner.record_product_experience(
        token,
        multi_computation_catalog(),
        "plan_confirmed",
    )
    path = (
        root.parent
        / "product_experience"
        / "records"
        / workspace["workspace_id"]
        / "plan_confirmed.json"
    )
    row = json.loads(path.read_text())
    row["safe_case"]["members"][0]["display_name"] = "tampered"
    path.write_bytes(canonical_bytes(row))
    with pytest.raises(
        ProductPlanningError,
        match="project_experience_record_invalid",
    ):
        planner.retrieve_product_experience(token)


def test_attributed_candidate_failure_is_recorded(tmp_path: Path) -> None:
    root = tmp_path / "state" / "product_workspaces"
    planner, token, _workspace = confirmed_time_workspace(
        root,
        "创建本地时间换算工具。",
    )
    record = planner.record_product_experience(
        token,
        multi_computation_catalog(),
        "candidate_terminal",
        candidate=candidate("acceptance_failed"),
    )
    assert record
    assert record["safe_case"]["candidate_result"] == "failed"
    assert record["safe_case"]["failure_attribution"]["code"] == (
        "product_goal_mismatch"
    )


def test_english_goal_retrieval_ranks_related_case_first(tmp_path: Path) -> None:
    root = tmp_path / "state" / "product_workspaces"
    catalog = multi_computation_catalog()
    related, related_token, _ = confirmed_time_workspace(
        root,
        "Build an offline hour conversion utility.",
    )
    related_record = related.record_product_experience(
        related_token,
        catalog,
        "plan_confirmed",
    )
    other, other_token, _ = confirmed_time_workspace(
        root,
        "Build an offline duration utility.",
    )
    other.record_product_experience(other_token, catalog, "plan_confirmed")
    query_planner, query_token, _ = confirmed_time_workspace(
        root,
        "Build an offline hour conversion calculator.",
    )
    query = query_planner.retrieve_product_experience(query_token)
    assert query["cases"][0]["record_digest"] == related_record["record_digest"]


@pytest.mark.parametrize("tamper", ["scope", "directory"])
def test_project_experience_scope_tampering_fails_closed(
    tmp_path: Path,
    tamper: str,
) -> None:
    root = tmp_path / tamper / "product_workspaces"
    planner, token, _workspace = confirmed_time_workspace(
        root,
        "创建本地时间换算工具。",
    )
    planner.record_product_experience(
        token,
        multi_computation_catalog(),
        "plan_confirmed",
    )
    experience_root = root.parent / "product_experience"
    if tamper == "scope":
        path = experience_root / "project_scope.json"
        row = json.loads(path.read_text())
        row["scope_id"] = "project_scope_tampered"
        path.write_bytes(canonical_bytes(row))
    else:
        extra = experience_root / "unexpected.json"
        extra.write_text("{}\n")
        extra.chmod(0o600)
    with pytest.raises(
        ProductPlanningError,
        match="project_experience_scope_invalid",
    ):
        planner.retrieve_product_experience(token)


def test_goal_tokenization_supports_nfkc_latin_and_cjk_bigrams() -> None:
    assert goal_tokens("ＦＯＯ workflow 分类工具") == goal_tokens(
        "foo workflow 分类工具"
    )
    assert "分类" in goal_tokens("工作流状态分类")


def test_project_record_rejects_unattributed_failure_in_pure_builder(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state" / "product_workspaces"
    _planner, _token, workspace = confirmed_time_workspace(
        root,
        "创建时间换算工具。",
    )
    with pytest.raises(
        ExperienceError,
        match="project_experience_failure_unattributed",
    ):
        build_project_experience_record(
            workspace=workspace,
            catalog=multi_computation_catalog(),
            project_scope_digest="a" * 64,
            milestone="candidate_terminal",
            candidate={
                "status": "acceptance_failed",
                "acceptance": {"status": "failed", "cases": []},
            },
        )
