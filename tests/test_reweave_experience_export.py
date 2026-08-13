from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "export_reweave_experience.py"
SPEC = importlib.util.spec_from_file_location("export_reweave_experience", SCRIPT)
assert SPEC and SPEC.loader
exporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exporter)


def canonical(value):
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def write_json(path: Path, value) -> str:
    raw = canonical(value)
    path.write_bytes(raw)
    return sha(raw)


def fixture_index(tmp_path: Path, reverse: bool = False) -> Path:
    plan = {
        "goal": "private customer goal that must never be exported",
        "catalog_digest": "1" * 64,
        "offer_digest": "2" * 64,
        "model": {
            "name": "qwen3:14b-q4_K_M",
            "digest": "3" * 64,
        },
        "selection": "offer_" + "4" * 24,
        "decision": "confirmed",
        "plan_digest": "5" * 64,
        "execution_digest": "6" * 64,
        "connection_digest": "7" * 64,
        "candidate_status": "review_ready",
        "delivery_status": "passed",
        "correction_count": 0,
    }
    validation = {
        "gap_digest": "8" * 64,
        "projection_digest": "9" * 64,
        "decision_digest": "a" * 64,
        "authorization_digest": "b" * 64,
        "source_proposal_digest": "c" * 64,
        "intake": "passed",
        "security": "passed",
        "runtime": "passed",
        "supervision": "approve",
        "admission": "review_required",
        "publication": "published",
        "candidate": "review_ready",
        "export": "passed",
        "visual": "passed",
        "rules": [
            {
                "name": "stage3_rules",
                "version": "stage3_rules.v1",
                "digest": "d" * 64,
            }
        ],
        "regression": [
            {
                "evidence_digest": "e" * 64,
                "rule_version": "validation_rules.v1",
            }
        ],
    }
    evidence = []
    for evidence_id, value in (("plan", plan), ("validation", validation)):
        filename = f"{evidence_id}.json"
        evidence.append(
            {
                "evidence_id": evidence_id,
                "path": filename,
                "project_scope_digest": "f" * 64,
                "sha256": write_json(tmp_path / filename, value),
            }
        )
    planning_fields = {
        "goal_safe_projection": {
            "evidence_id": "plan",
            "pointer": "/goal",
            "mode": "digest",
        },
        "frozen_catalog_digest": {
            "evidence_id": "plan",
            "pointer": "/catalog_digest",
            "mode": "value",
        },
        "composition_offer_digest": {
            "evidence_id": "plan",
            "pointer": "/offer_digest",
            "mode": "value",
        },
        "exact_model_name": {
            "evidence_id": "plan",
            "pointer": "/model/name",
            "mode": "value",
        },
        "exact_model_digest": {
            "evidence_id": "plan",
            "pointer": "/model/digest",
            "mode": "value",
        },
        "model_selection": {
            "evidence_id": "plan",
            "pointer": "/selection",
            "mode": "value",
        },
        "user_decision": {
            "evidence_id": "plan",
            "pointer": "/decision",
            "mode": "value",
        },
        "plan_digest": {
            "evidence_id": "plan",
            "pointer": "/plan_digest",
            "mode": "value",
        },
        "execution_digest": {
            "evidence_id": "plan",
            "pointer": "/execution_digest",
            "mode": "value",
        },
        "connection_digest": {
            "evidence_id": "plan",
            "pointer": "/connection_digest",
            "mode": "value",
        },
        "candidate_result": {
            "evidence_id": "plan",
            "pointer": "/candidate_status",
            "mode": "value",
        },
        "delivery_result": {
            "evidence_id": "plan",
            "pointer": "/delivery_status",
            "mode": "value",
        },
        "correction_count": {
            "evidence_id": "plan",
            "pointer": "/correction_count",
            "mode": "value",
        },
    }
    validation_fields = {
        field: {
            "evidence_id": "validation",
            "pointer": f"/{pointer}",
            "mode": "value",
        }
        for field, pointer in {
            "gap_digest": "gap_digest",
            "projection_digest": "projection_digest",
            "decision_digest": "decision_digest",
            "authorization_digest": "authorization_digest",
            "source_proposal_digest": "source_proposal_digest",
            "intake_result": "intake",
            "security_result": "security",
            "runtime_result": "runtime",
            "supervision_result": "supervision",
            "admission_result": "admission",
            "publication_result": "publication",
            "rule_version_identities": "rules",
            "candidate_result": "candidate",
            "export_result": "export",
            "visual_result": "visual",
            "regression_evidence": "regression",
        }.items()
    }
    records = [
        {
            "schema": "planning_experience.v1",
            "record_id": "planning",
            "project_scope_digest": "f" * 64,
            "fields": planning_fields,
        },
        {
            "schema": "validation_experience.v1",
            "record_id": "validation",
            "project_scope_digest": "f" * 64,
            "fields": validation_fields,
        },
    ]
    index = {
        "schema": "reweave_experience_evidence_index.v1",
        "project_scope_digest": "f" * 64,
        "evidence": list(reversed(evidence)) if reverse else evidence,
        "records": list(reversed(records)) if reverse else records,
    }
    path = tmp_path / ("index-reversed.json" if reverse else "index.json")
    write_json(path, index)
    return path


def output_records(paths: list[Path]) -> tuple[dict, dict]:
    planning = json.loads(
        next(path for path in paths if "planning_experience" in path.name).read_text()
    )
    validation = json.loads(
        next(path for path in paths if "validation_experience" in path.name).read_text()
    )
    return planning, validation


def label_value(
    *,
    task_id: str,
    scope: str,
    planning_sha: str,
    validation_sha: str,
    metrics: dict | None = None,
    model_digest: str = "3" * 64,
):
    all_metrics = {
        name: exporter.NOT_RECORDED
        for name in exporter.RATE_METRICS + exporter.AVERAGE_METRICS
    }
    all_metrics.update(metrics or {})
    body = {
        "schema": "reweave_experience_task_label.v1",
        "authority": exporter.AUTHORITY,
        "task_id": task_id,
        "project_scope_digest": scope,
        "planning_experience_sha256": planning_sha,
        "validation_experience_sha256": validation_sha,
        "fixed_model": {
            "name": "qwen3:14b-q4_K_M",
            "digest": model_digest,
        },
        "label_rule_version": exporter.LABEL_RULE_VERSION,
        "attribution_status": exporter.NOT_RECORDED,
        "metrics": all_metrics,
    }
    return {**body, "canonical_digest": sha(canonical(body))}


def benchmark_index(
    tmp_path: Path,
    experience_dir: Path,
    *,
    tasks: list[dict] | None = None,
) -> Path:
    planning = next(experience_dir.glob("*.planning_experience.v1.json"))
    validation = next(experience_dir.glob("*.validation_experience.v1.json"))
    planning_sha = sha(planning.read_bytes())
    validation_sha = sha(validation.read_bytes())
    if tasks is None:
        tasks = []
        for task_id, metrics in (
            (
                "task_a",
                {
                    "legal_offer_coverage_rate": True,
                    "correct_planning_rate": True,
                    "average_human_corrections": 0,
                },
            ),
            ("task_b", {}),
        ):
            label_name = f"{task_id}.label.json"
            label_sha = write_json(
                tmp_path / label_name,
                label_value(
                    task_id=task_id,
                    scope="f" * 64,
                    planning_sha=planning_sha,
                    validation_sha=validation_sha,
                    metrics=metrics,
                ),
            )
            tasks.append(
                {
                    "task_id": task_id,
                    "planning": {
                        "path": str(planning.relative_to(tmp_path)),
                        "sha256": planning_sha,
                    },
                    "validation": {
                        "path": str(validation.relative_to(tmp_path)),
                        "sha256": validation_sha,
                    },
                    "label": {"path": label_name, "sha256": label_sha},
                }
            )
    path = tmp_path / "benchmark.json"
    write_json(
        path,
        {
            "schema": "reweave_task_coverage_benchmark.v1",
            "fixed_model": {
                "name": "qwen3:14b-q4_K_M",
                "digest": "3" * 64,
            },
            "tasks": tasks,
        },
    )
    return path


def test_deterministic_strict_redacted_export(tmp_path):
    first = exporter.write_experience(fixture_index(tmp_path), tmp_path / "first")
    second = exporter.write_experience(
        fixture_index(tmp_path, reverse=True),
        tmp_path / "second",
    )
    assert [path.name for path in first] == [path.name for path in second]
    assert [path.read_bytes() for path in first] == [
        path.read_bytes() for path in second
    ]
    planning, validation = output_records(first)
    assert planning["authority"] == validation["authority"] == exporter.AUTHORITY
    assert planning["redaction_policy_version"] == exporter.REDACTION_POLICY_VERSION
    assert planning["derivation_rule_version"] == exporter.DERIVATION_RULE_VERSION
    assert planning["goal_safe_projection"] == {
        "canonical_value_sha256": sha(
            canonical("private customer goal that must never be exported")
        )
    }
    assert planning["failure_attribution"] == exporter.NOT_RECORDED
    assert validation["failure_attribution"] == exporter.NOT_RECORDED
    output = b"".join(path.read_bytes() for path in first)
    assert b"private customer goal" not in output
    assert b"prompt" not in output.lower()
    assert b"source_text" not in output.lower()
    assert str(tmp_path).encode() not in output
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in first)


@pytest.mark.parametrize(
    "unsafe",
    [
        "../outside.json",
        "/tmp/outside.json",
        "file:///tmp/outside.json",
        "C:/outside.json",
        "\\\\server\\share\\outside.json",
    ],
)
def test_evidence_path_escape_fails_closed(tmp_path, unsafe):
    index_path = fixture_index(tmp_path)
    index = json.loads(index_path.read_text())
    index["evidence"][0]["path"] = unsafe
    write_json(index_path, index)
    with pytest.raises(exporter.ExperienceExportError, match="unsafe_evidence_path"):
        exporter.derive_records(index_path)


def test_symlink_digest_scope_and_unknown_fields_fail_closed(tmp_path):
    index_path = fixture_index(tmp_path)
    linked = tmp_path / "linked.json"
    linked.symlink_to(tmp_path / "plan.json")
    index = json.loads(index_path.read_text())
    index["evidence"][0]["path"] = "linked.json"
    write_json(index_path, index)
    with pytest.raises(exporter.ExperienceExportError, match="unsafe_evidence_symlink"):
        exporter.derive_records(index_path)

    index_path = fixture_index(tmp_path)
    index = json.loads(index_path.read_text())
    index["evidence"][0]["sha256"] = "0" * 64
    write_json(index_path, index)
    with pytest.raises(exporter.ExperienceExportError, match="evidence_digest_mismatch"):
        exporter.derive_records(index_path)

    index_path = fixture_index(tmp_path)
    index = json.loads(index_path.read_text())
    index["evidence"][0]["project_scope_digest"] = "0" * 64
    write_json(index_path, index)
    with pytest.raises(exporter.ExperienceExportError, match="cross_project_evidence"):
        exporter.derive_records(index_path)

    index_path = fixture_index(tmp_path)
    index = json.loads(index_path.read_text())
    index["records"][0]["unexpected"] = True
    write_json(index_path, index)
    with pytest.raises(exporter.ExperienceExportError, match="invalid_record_spec"):
        exporter.derive_records(index_path)


def test_raw_prompt_source_and_bad_types_cannot_be_exported(tmp_path):
    index_path = fixture_index(tmp_path)
    index = json.loads(index_path.read_text())
    plan_path = tmp_path / "plan.json"
    plan = json.loads(plan_path.read_text())
    plan["prompt"] = "raw secret prompt"
    plan["source_text"] = "export function compute() {}"
    plan["bad_selection"] = {"prompt": plan["prompt"], "source_text": plan["source_text"]}
    plan_sha = write_json(plan_path, plan)
    next(item for item in index["evidence"] if item["evidence_id"] == "plan")[
        "sha256"
    ] = plan_sha
    index["records"][0]["fields"]["model_selection"] = {
        "evidence_id": "plan",
        "pointer": "/bad_selection",
        "mode": "value",
    }
    write_json(index_path, index)
    with pytest.raises(exporter.ExperienceExportError, match="invalid_model_selection"):
        exporter.write_experience(index_path, tmp_path / "blocked")
    assert not (tmp_path / "blocked").exists()

    index_path = fixture_index(tmp_path)
    index = json.loads(index_path.read_text())
    index["records"][0]["fields"]["goal_safe_projection"]["mode"] = "value"
    write_json(index_path, index)
    with pytest.raises(
        exporter.ExperienceExportError,
        match="invalid_field_projection_mode",
    ):
        exporter.derive_records(index_path)

    index_path = fixture_index(tmp_path)
    plan_path = tmp_path / "plan.json"
    plan = json.loads(plan_path.read_text())
    plan["decision"] = "anything_model_said"
    plan_sha = write_json(plan_path, plan)
    index = json.loads(index_path.read_text())
    next(item for item in index["evidence"] if item["evidence_id"] == "plan")[
        "sha256"
    ] = plan_sha
    write_json(index_path, index)
    with pytest.raises(exporter.ExperienceExportError, match="invalid_user_decision"):
        exporter.derive_records(index_path)


def test_failure_attribution_and_regression_require_explicit_evidence(tmp_path):
    index_path = fixture_index(tmp_path)
    plan_path = tmp_path / "plan.json"
    plan = json.loads(plan_path.read_text())
    plan["failure"] = "model_failed"
    plan_sha = write_json(plan_path, plan)
    index = json.loads(index_path.read_text())
    next(item for item in index["evidence"] if item["evidence_id"] == "plan")[
        "sha256"
    ] = plan_sha
    index["records"][0]["fields"]["failure_attribution"] = {
        "evidence_id": "plan",
        "pointer": "/failure",
        "mode": "value",
    }
    write_json(index_path, index)
    with pytest.raises(
        exporter.ExperienceExportError,
        match="invalid_failure_attribution",
    ):
        exporter.derive_records(index_path)

    index_path = fixture_index(tmp_path)
    validation_path = tmp_path / "validation.json"
    validation = json.loads(validation_path.read_text())
    validation["regression"] = [{"evidence_digest": "e" * 64}]
    validation_sha = write_json(validation_path, validation)
    index = json.loads(index_path.read_text())
    next(item for item in index["evidence"] if item["evidence_id"] == "validation")[
        "sha256"
    ] = validation_sha
    write_json(index_path, index)
    with pytest.raises(
        exporter.ExperienceExportError,
        match="invalid_regression_evidence",
    ):
        exporter.derive_records(index_path)


def test_output_conflict_symlink_and_mid_write_leave_no_partial_files(
    tmp_path, monkeypatch
):
    index_path = fixture_index(tmp_path)
    conflict = tmp_path / "conflict"
    conflict.mkdir()
    existing = conflict / "keep.txt"
    existing.write_text("keep")
    with pytest.raises(
        exporter.ExperienceExportError,
        match="output_directory_not_empty",
    ):
        exporter.write_experience(index_path, conflict)
    assert existing.read_text() == "keep"

    symlink = tmp_path / "output-link"
    target = tmp_path / "output-target"
    target.mkdir()
    symlink.symlink_to(target, target_is_directory=True)
    with pytest.raises(
        exporter.ExperienceExportError,
        match="output_directory_unsafe",
    ):
        exporter.write_experience(index_path, symlink)
    assert not list(target.iterdir())

    original = exporter._write_temp_file
    calls = 0

    def fail_second(path, data):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("sentinel write failure")
        original(path, data)

    monkeypatch.setattr(exporter, "_write_temp_file", fail_second)
    interrupted = tmp_path / "interrupted"
    with pytest.raises(exporter.ExperienceExportError, match="output_write_failed"):
        exporter.write_experience(index_path, interrupted)
    assert not interrupted.exists() or not list(interrupted.iterdir())


def test_task_labels_are_required_and_missing_metrics_do_not_shrink_denominator(
    tmp_path,
):
    exporter.write_experience(fixture_index(tmp_path), tmp_path / "experience")
    benchmark = benchmark_index(tmp_path, tmp_path / "experience")
    scorecard = exporter.build_scorecard(benchmark)
    metric = scorecard["metrics"]["correct_planning_rate"]
    assert metric == {
        "recorded_count": 1,
        "missing_count": 1,
        "numerator": 1,
        "denominator": 2,
        "rate": exporter.NOT_RECORDED,
    }
    missing = scorecard["metrics"]["correct_rejection_rate"]
    assert missing == {
        "recorded_count": 0,
        "missing_count": 2,
        "numerator": 0,
        "denominator": 2,
        "rate": exporter.NOT_RECORDED,
    }
    average = scorecard["metrics"]["average_human_corrections"]
    assert average == {
        "recorded_count": 1,
        "missing_count": 1,
        "sum": 0,
        "count": 2,
        "average": exporter.NOT_RECORDED,
    }
    assert scorecard["task_distribution_breadth"] == "INSUFFICIENT"
    assert scorecard["claims"] == {
        "model_qualification": False,
        "architecture_pass": False,
        "task_distribution_sufficient": False,
    }

    raw = json.loads(benchmark.read_text())
    raw["tasks"][0].pop("label")
    write_json(benchmark, raw)
    with pytest.raises(exporter.ExperienceExportError, match="invalid_benchmark_task"):
        exporter.build_scorecard(benchmark)


def test_scorecard_is_order_invariant_and_written_0600(tmp_path):
    exporter.write_experience(fixture_index(tmp_path), tmp_path / "experience")
    benchmark = benchmark_index(tmp_path, tmp_path / "experience")
    original = exporter.build_scorecard(benchmark)
    value = json.loads(benchmark.read_text())
    value["tasks"] = list(reversed(value["tasks"]))
    reversed_path = tmp_path / "benchmark-reversed.json"
    write_json(reversed_path, value)
    assert canonical(original) == canonical(exporter.build_scorecard(reversed_path))
    output = exporter.write_scorecard(benchmark, tmp_path / "scorecard")
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert output.read_bytes() == canonical(original)


def test_experience_label_model_and_project_tampering_fail_closed(tmp_path):
    outputs = exporter.write_experience(
        fixture_index(tmp_path),
        tmp_path / "experience",
    )
    benchmark = benchmark_index(tmp_path, tmp_path / "experience")
    benchmark_value = json.loads(benchmark.read_text())

    planning = next(path for path in outputs if "planning_experience" in path.name)
    planning_value = json.loads(planning.read_text())
    planning_value["canonical_digest"] = "0" * 64
    planning.write_bytes(canonical(planning_value))
    benchmark_value["tasks"][0]["planning"]["sha256"] = sha(planning.read_bytes())
    write_json(benchmark, benchmark_value)
    with pytest.raises(exporter.ExperienceExportError, match="invalid_experience_record"):
        exporter.build_scorecard(benchmark)

    outputs = exporter.write_experience(
        fixture_index(tmp_path),
        tmp_path / "experience-fresh",
    )
    benchmark = benchmark_index(tmp_path, tmp_path / "experience-fresh")
    value = json.loads(benchmark.read_text())
    label_path = tmp_path / value["tasks"][0]["label"]["path"]
    label = json.loads(label_path.read_text())
    label["canonical_digest"] = "0" * 64
    label_path.write_bytes(canonical(label))
    value["tasks"][0]["label"]["sha256"] = sha(label_path.read_bytes())
    write_json(benchmark, value)
    with pytest.raises(exporter.ExperienceExportError, match="invalid_task_label"):
        exporter.build_scorecard(benchmark)

    outputs = exporter.write_experience(
        fixture_index(tmp_path),
        tmp_path / "experience-model",
    )
    benchmark = benchmark_index(tmp_path, tmp_path / "experience-model")
    value = json.loads(benchmark.read_text())
    value["fixed_model"]["digest"] = "0" * 64
    write_json(benchmark, value)
    with pytest.raises(
        exporter.ExperienceExportError,
        match="cross_project_or_model_benchmark_task",
    ):
        exporter.build_scorecard(benchmark)


def test_duplicate_json_keys_are_rejected(tmp_path):
    evidence = tmp_path / "evidence.json"
    evidence.write_text('{"value":1,"value":2}', encoding="utf-8")
    index = {
        "schema": "reweave_experience_evidence_index.v1",
        "project_scope_digest": "f" * 64,
        "evidence": [
            {
                "evidence_id": "duplicate",
                "path": "evidence.json",
                "project_scope_digest": "f" * 64,
                "sha256": sha(evidence.read_bytes()),
            }
        ],
        "records": [
            {
                "schema": "planning_experience.v1",
                "record_id": "planning",
                "project_scope_digest": "f" * 64,
                "fields": {},
            }
        ],
    }
    index_path = tmp_path / "index.json"
    write_json(index_path, index)
    with pytest.raises(exporter.ExperienceExportError, match="duplicate_json_key"):
        exporter.derive_records(index_path)
