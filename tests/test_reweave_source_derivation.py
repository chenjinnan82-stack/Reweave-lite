from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from pimos_lite.reweave_source_derivation import (
    SOURCE_DERIVATION_PROMPT_V1,
    SOURCE_DERIVATION_PROMPT_VERSION,
    SOURCE_DERIVATION_REQUEST_V1,
    SOURCE_DERIVATION_REQUEST_VERSION,
    SourceDerivationError,
    _is_reparse_point,
    assemble_source_derived_standard_ui,
    append_source_derived_run_event,
    build_source_derived_authorization,
    build_source_derived_request,
    build_source_derived_standard_ui_proposal,
    get_source_derived_run,
    prepare_source_derived_run,
    read_source_derived_evidence,
    read_source_derived_ui_evidence,
    source_derived_project_graph_digest,
    source_derived_run_projection,
    validate_source_derived_response,
    validate_source_derived_standard_ui_proposal,
    write_source_derived_proposal,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE_GRAPH = ROOT / "scripts" / "analyze_reweave_source_graph.mjs"
NODE = shutil.which("node")


def test_standard_ui_proposal_is_closed_and_deterministic(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "panel.tsx").write_text(
        "export const Panel = () => null;\n",
        encoding="utf-8",
    )
    (source / "styles.css").write_text(
        ".panel { display: grid; }\n",
        encoding="utf-8",
    )
    evidence = read_source_derived_ui_evidence(
        source,
        ["styles.css", "panel.tsx"],
    )
    request = {
        "evidence_relpaths": ["panel.tsx", "styles.css"],
        "behavior_intent": "提交报修消息并展示紧急程度",
        "input_field": "message",
        "event_name": "classification_requested",
        "input_min_length": 1,
        "input_max_length": 1000,
        "result_field": "urgency",
        "result_enum": ["普通", "紧急"],
        "visible_text": {
            "input_label": "输入报修消息",
            "submit_label": "整理成工单",
            "result_label": "紧急程度",
        },
        "acceptance_cases": [
            {"input_text": "设备漏油", "expected_result": "紧急"}
        ],
    }
    proposal = build_source_derived_standard_ui_proposal(
        handoff_binding_digest="a" * 64,
        request=request,
        evidence=evidence,
        supervision_model={"name": "supervisor", "digest": "b" * 64},
        warehouse_revision=91,
        catalog_digest="c" * 64,
        prepared_at="2026-08-20T00:00:00Z",
    )
    assert validate_source_derived_standard_ui_proposal(proposal) == proposal
    first = assemble_source_derived_standard_ui(proposal)
    second = assemble_source_derived_standard_ui(copy.deepcopy(proposal))
    assert first == second
    assert set(first) == {
        "index.html",
        "interaction.js",
        "presentation.js",
        "styles.css",
    }
    assert "classification_requested" in first["interaction.js"]
    assert "普通" not in first["interaction.js"]
    assert "紧急" not in first["interaction.js"]
    for name in ("interaction.js", "presentation.js"):
        module = tmp_path / name.replace(".js", ".mjs")
        module.write_text(first[name], encoding="utf-8")
        checked = subprocess.run(
            ["node", "--check", str(module)],
            text=True,
            capture_output=True,
            check=False,
        )
        assert checked.returncode == 0, checked.stderr
    changed = copy.deepcopy(proposal)
    changed["request"]["input_max_length"] = 999
    with pytest.raises(
        SourceDerivationError,
        match="source_derived_ui_proposal_invalid",
    ):
        validate_source_derived_standard_ui_proposal(changed)


def test_source_derived_reparse_point_metadata_is_rejected() -> None:
    assert _is_reparse_point(
        SimpleNamespace(
            st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT
        )
    )
    assert not _is_reparse_point(SimpleNamespace(st_file_attributes=0))
    assert not _is_reparse_point(SimpleNamespace())


@pytest.mark.skipif(os.name != "nt", reason="Windows junction runtime only")
def test_source_derived_windows_junction_is_rejected(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    outside = tmp_path / "outside"
    source_root.mkdir()
    outside.mkdir()
    (outside / "outside.ts").write_text(
        "export const outside = true;\n",
        encoding="utf-8",
    )
    junction = source_root / "linked"
    created = subprocess.run(
        [
            "cmd.exe",
            "/d",
            "/c",
            "mklink",
            "/J",
            str(junction),
            str(outside),
        ],
        capture_output=True,
        check=False,
    )
    assert created.returncode == 0, (
        created.stdout.decode(errors="replace"),
        created.stderr.decode(errors="replace"),
    )
    try:
        with pytest.raises(
            SourceDerivationError,
            match="source_derivation_evidence_invalid",
        ):
            read_source_derived_evidence(
                source_root,
                "linked/outside.ts",
            )
        with pytest.raises(
            SourceDerivationError,
            match="source_derivation_evidence_invalid",
        ):
            read_source_derived_evidence(
                junction,
                "outside.ts",
            )
    finally:
        os.rmdir(junction)


def _error_contract() -> dict[str, object]:
    details = {
        "schema": "data_contract.v1",
        "type": "object",
        "properties": {},
        "required": [],
        "additional_properties": False,
    }
    return {
        "schema": "error_contract.v1",
        "errors": {
            "INPUT_CONTRACT_VIOLATION": {
                "field": None,
                "details": details,
            },
            "OUTPUT_CONTRACT_VIOLATION": {
                "field": None,
                "details": details,
            },
        },
    }


def _evidence(content: str, path: str = "src/utils/extractor.ts") -> dict[str, object]:
    encoded = content.encode("utf-8")
    return {
        "logical_path": path,
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "size_bytes": len(encoded),
        "content": content,
    }


def _authorization(evidence: list[dict[str, object]]) -> dict[str, object]:
    identities = [
        {key: item[key] for key in ("logical_path", "sha256", "size_bytes")}
        for item in evidence
    ]
    return build_source_derived_authorization(
        source_snapshot_sha256="1" * 64,
        project_graph_digest="2" * 64,
        evidence=identities,
        behavior_intent=(
            "沿用授权来源中的紧急度规则，将报修文本分类为紧急或普通。"
        ),
        input_contract={
            "schema": "data_contract.v1",
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "min_length": 1,
                    "max_length": 1000,
                }
            },
            "required": ["message"],
            "additional_properties": False,
        },
        output_contract={
            "schema": "data_contract.v1",
            "type": "object",
            "properties": {
                "urgency": {
                    "type": "string",
                    "min_length": 2,
                    "max_length": 2,
                    "enum": ["紧急", "普通"],
                }
            },
            "required": ["urgency"],
            "additional_properties": False,
        },
        error_contract=_error_contract(),
        result_field="urgency",
        acceptance_cases=[
            {
                "input": {"message": "升降平台无法升降，比较急"},
                "expected_output": {"urgency": "紧急"},
            },
            {
                "input": {"message": "叉车电瓶没电了"},
                "expected_output": {"urgency": "普通"},
            },
            {
                "input": {"message": "升降平台漏油，请尽快处理"},
                "expected_output": {"urgency": "紧急"},
            },
        ],
        source_proposal_model={"name": "source-model:test", "digest": "3" * 64},
        warehouse_revision=73,
        catalog_digest="4" * 64,
        authorized_at="2026-08-16T00:00:00Z",
    )


def _proposal(source: str) -> dict[str, object]:
    return {
        "schema": "capability_source_proposal.v2",
        "entry": {
            "module_relpath": "capability.js",
            "export_name": "compute",
        },
        "files": [{"path": "capability.js", "content": source}],
        "witnesses": [
            {
                "input": {"message": "routine"},
                "expected_scalar_result": "普通",
            },
            {
                "input": {"message": "比较急"},
                "expected_scalar_result": "紧急",
            },
        ],
    }


def _source_graph(source: str, mode: str) -> dict[str, object]:
    assert NODE is not None
    encoded = source.encode("utf-8")
    module = {
        "path": "capability.js",
        "source_base64": base64.b64encode(encoded).decode("ascii"),
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }
    graph_request: dict[str, object] = {
        "schema": "source_graph_request.v2",
        "mode": "graph",
        "project_id": "source-derived-proposal-test",
        "scope_snapshot_sha256": "5" * 64,
        "source_identity_sha256": "6" * 64,
        "entry_modules": ["capability.js"],
        "module_snapshot": [module],
        "symlinks": [],
    }
    graph = subprocess.run(
        [NODE, "--max-old-space-size=256", str(SOURCE_GRAPH)],
        input=json.dumps(graph_request, ensure_ascii=False),
        text=True,
        capture_output=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=30,
        check=False,
    )
    assert graph.returncode == 0 and not graph.stderr
    result = json.loads(graph.stdout)
    assert result["status"] == "ok", result
    if mode == "graph":
        return result
    module_graph = result["modules"][0]
    exported = next(
        item
        for item in module_graph["exports"]
        if item["public_name"] == "compute"
    )
    by_binding = {
        item["binding_id"]: item for item in module_graph["bindings"]
    }
    binding = by_binding[exported["binding_id"]]
    prove_request = {
        **graph_request,
        "mode": "prove",
        "target": {
            "module_relpath": "capability.js",
            "export_name": "compute",
        },
        "parameter_domains": [
            {
                "parameter_binding_id": binding["parameters"][0][
                    "binding_id"
                ],
                "domain": {
                    "kind": "string",
                    "min_length": 1,
                    "max_length": 1000,
                },
            }
        ],
    }
    proved = subprocess.run(
        [NODE, "--max-old-space-size=256", str(SOURCE_GRAPH)],
        input=json.dumps(prove_request, ensure_ascii=False),
        text=True,
        capture_output=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=30,
        check=False,
    )
    assert proved.returncode == 0 and not proved.stderr
    return json.loads(proved.stdout)


@pytest.mark.skipif(NODE is None, reason="Node is required")
def test_authorized_react_source_derives_one_proved_v5_computation() -> None:
    evidence_source = (
        'const urgentWords = ["急", "尽快", "马上", "严重", "危险", '
        '"漏油", "无法升降"];\n'
        "export function extract(message: string) {\n"
        "  return urgentWords.some((word) => message.includes(word)) "
        '? "紧急" : "普通";\n'
        "}\n"
    )
    evidence = [_evidence(evidence_source)]
    authorization = _authorization(evidence)
    request = build_source_derived_request(authorization, evidence)
    source = (
        "export function compute(arg0) {\n"
        '  return arg0.includes("急") || arg0.includes("尽快") ||\n'
        '    arg0.includes("马上") || arg0.includes("严重") ||\n'
        '    arg0.includes("危险") || arg0.includes("漏油") ||\n'
        '    arg0.includes("无法升降")\n'
        '    ? "紧急" : "普通";\n'
        "}\n"
    )

    normalized = validate_source_derived_response(
        _proposal(source),
        request,
        authorization,
        evidence,
    )
    proved = _source_graph(
        normalized["files"][0]["content"],
        "prove",
    )

    assert authorization["schema_version"] == (
        "source_derived_computation_authorization.v1"
    )
    assert request["schema_version"] == (
        SOURCE_DERIVATION_REQUEST_VERSION
    )
    assert request["formal_binding"]["prompt_version"] == (
        SOURCE_DERIVATION_PROMPT_VERSION
    )
    assert "Every return statement must return" in request["prompt"]
    assert "Never return an object" in request["prompt"]
    assert "computation_adapter.v5 performs that wrapping" in request["prompt"]
    assert authorization["evidence"][0] == {
        key: evidence[0][key]
        for key in ("logical_path", "sha256", "size_bytes")
    }
    assert "content" not in authorization["evidence"][0]
    assert "/Users/" not in json.dumps(request, ensure_ascii=False)
    assert proved["status"] == "ok", proved
    assert proved["proof"]["schema"] == "source_graph_proof.v3"
    assert proved["proof"]["result_domain"] == {
        "kind": "enum",
        "values": ["普通", "紧急"],
    }


def test_source_derivation_is_order_stable_and_fails_closed() -> None:
    first = _evidence(
        'export const words = ["急"];\n',
        "src/rules.ts",
    )
    second = _evidence(
        "export function classify(value: string) { return value; }\n",
        "src/classify.ts",
    )
    authorization_a = _authorization([first, second])
    authorization_b = _authorization([second, first])
    request_a = build_source_derived_request(
        authorization_a,
        [first, second],
    )
    request_b = build_source_derived_request(
        authorization_b,
        [second, first],
    )

    assert authorization_a == authorization_b
    assert request_a == request_b

    changed = copy.deepcopy([first, second])
    changed[0]["content"] = 'export const words = ["危险"];\n'
    with pytest.raises(
        SourceDerivationError,
        match="source_derivation_evidence_invalid",
    ):
        build_source_derived_request(authorization_a, changed)

    tampered = copy.deepcopy(authorization_a)
    tampered["result_enum"] = ["其他", "紧急"]
    with pytest.raises(
        SourceDerivationError,
        match="source_derivation_authorization_invalid",
    ):
        build_source_derived_request(tampered, [first, second])

    secret = _evidence('const apiKey = "secret-value";\n')
    secret_authorization = _authorization([secret])
    with pytest.raises(
        SourceDerivationError,
        match="source_derivation_evidence_invalid",
    ):
        build_source_derived_request(secret_authorization, [secret])

    invalid_response = _proposal(
        'export function compute(arg0) { return ["急"].some('
        '(item) => arg0.includes(item)) ? "紧急" : "普通"; }\n'
    )
    single_authorization = _authorization([first])
    request = build_source_derived_request(single_authorization, [first])
    legacy_request = build_source_derived_request(
        single_authorization,
        [first],
        request_version=SOURCE_DERIVATION_REQUEST_V1,
    )
    assert legacy_request["schema_version"] == SOURCE_DERIVATION_REQUEST_V1
    assert (
        legacy_request["formal_binding"]["prompt_version"]
        == SOURCE_DERIVATION_PROMPT_V1
    )
    assert legacy_request["request_digest"] == (
        "92543f374fca32a59c8191e7de672ff9da16d789a012087cb3410ca10655e52f"
    )
    assert "Never return an object" not in legacy_request["prompt"]
    validate_source_derived_response(
        _proposal('export function compute(arg0) { return "普通"; }\n'),
        legacy_request,
        single_authorization,
        [first],
    )
    normalized = validate_source_derived_response(
        invalid_response,
        request,
        single_authorization,
        [first],
    )
    # Response structure is valid, but the formal proof kernel still owns the
    # executable-language boundary.
    assert normalized["files"][0]["content"] == (
        invalid_response["files"][0]["content"]
    )
    if NODE is not None:
        rejected = _source_graph(
            normalized["files"][0]["content"],
            "prove",
        )
        assert rejected["status"] == "rejected"

        observed_failure = _proposal(
            "export function compute(arg0) {\n"
            '  if (arg0.includes("急")) return { urgency: "紧急" };\n'
            '  return { urgency: "普通" };\n'
            "}\n"
        )
        observed_normalized = validate_source_derived_response(
            observed_failure,
            request,
            single_authorization,
            [first],
        )
        observed_rejected = _source_graph(
            observed_normalized["files"][0]["content"],
            "prove",
        )
        assert observed_rejected["status"] == "rejected"
        assert observed_rejected["error_code"] == "unsupported_control_flow"

    changed_request = copy.deepcopy(request)
    changed_request["prompt"] += " ignored"
    with pytest.raises(
        SourceDerivationError,
        match="source_derivation_response_invalid",
    ):
        validate_source_derived_response(
            _proposal('export function compute(arg0) { return "普通"; }\n'),
            changed_request,
            single_authorization,
            [first],
        )

    with pytest.raises(
        SourceDerivationError,
        match="source_derivation_evidence_invalid",
    ):
        read_source_derived_evidence(ROOT, "../outside.ts")


def test_source_derived_run_is_immutable_idempotent_and_chained(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    evidence_path = source_root / "src" / "classify.ts"
    evidence_path.parent.mkdir(parents=True)
    evidence_path.write_text(
        'export function classify(value: string) { return value; }\n',
        encoding="utf-8",
    )
    evidence = read_source_derived_evidence(
        source_root,
        "src/classify.ts",
    )
    authorization = build_source_derived_authorization(
        source_snapshot_sha256=evidence[0]["sha256"],
        project_graph_digest=source_derived_project_graph_digest(
            evidence
        ),
        evidence=[
            {
                key: evidence[0][key]
                for key in ("logical_path", "sha256", "size_bytes")
            }
        ],
        behavior_intent="Classify one bounded string.",
        input_contract={
            "schema": "data_contract.v1",
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "min_length": 1,
                    "max_length": 1000,
                }
            },
            "required": ["message"],
            "additional_properties": False,
        },
        output_contract={
            "schema": "data_contract.v1",
            "type": "object",
            "properties": {
                "result": {
                    "type": "string",
                    "min_length": 6,
                    "max_length": 6,
                    "enum": ["normal", "urgent"],
                }
            },
            "required": ["result"],
            "additional_properties": False,
        },
        error_contract=_error_contract(),
        result_field="result",
        acceptance_cases=[
            {
                "input": {"message": "routine"},
                "expected_output": {"result": "normal"},
            },
            {
                "input": {"message": "urgent"},
                "expected_output": {"result": "urgent"},
            },
        ],
        source_proposal_model={"name": "source:test", "digest": "3" * 64},
        warehouse_revision=73,
        catalog_digest="4" * 64,
        authorized_at="2026-08-17T00:00:00Z",
    )
    request = build_source_derived_request(authorization, evidence)
    model = {
        "name": "source:test",
        "digest": "3" * 64,
        "parameter_count": 1_000_000,
        "parameter_size": "1M",
    }
    supervisor = {"name": "supervisor:test", "digest": "5" * 64}
    state = tmp_path / "state"
    first = prepare_source_derived_run(
        state,
        authorization,
        request,
        source_root_id="root_test",
        source_relpath="src/classify.ts",
        source_proposal_model=model,
        supervision_model=supervisor,
        created_at="2026-08-17T00:00:00Z",
    )
    repeated = prepare_source_derived_run(
        state,
        authorization,
        request,
        source_root_id="root_test",
        source_relpath="src/classify.ts",
        source_proposal_model=model,
        supervision_model=supervisor,
        created_at="2026-08-17T01:00:00Z",
    )
    assert first["created"] is True
    assert repeated["created"] is False
    assert repeated["run_id"] == first["run_id"]

    source = write_source_derived_proposal(
        state,
        first["run_id"],
        'export function compute(arg0) { return "normal"; }\n',
    )
    append_source_derived_run_event(
        state,
        first["run_id"],
        status="running",
        stage="source_proposal",
        created_at="2026-08-17T00:00:01Z",
    )
    append_source_derived_run_event(
        state,
        first["run_id"],
        status="running",
        stage="intake",
        evidence={
            **source,
            "model_response_digest": "6" * 64,
        },
        created_at="2026-08-17T00:00:02Z",
    )
    terminal = append_source_derived_run_event(
        state,
        first["run_id"],
        status="failed",
        stage="intake",
        error_code="manual_recovery_required",
        created_at="2026-08-17T00:00:03Z",
    )
    assert terminal["status"] == "failed"
    assert terminal["review_scope"] == "isolated"
    assert set(terminal) == {
        "schema_version",
        "run_id",
        "status",
        "stage",
        "attempt_count",
        "review_scope",
        "created_at",
        "updated_at",
        "error_code",
    }
    record = get_source_derived_run(state, first["run_id"])
    assert [event["sequence"] for event in record["events"]] == [1, 2, 3, 4]
    assert all(
        event["previous_event_digest"]
        == (
            None
            if index == 0
            else record["events"][index - 1]["canonical_digest"]
        )
        for index, event in enumerate(record["events"])
    )
    assert source_derived_run_projection(record) == terminal
    source_path = record["paths"]["source_file"]
    source_bytes = source_path.read_bytes()
    source_path.write_bytes(b"tampered")
    if os.name == "posix":
        source_path.chmod(0o600)
    with pytest.raises(
        SourceDerivationError,
        match="source_derivation_source_conflict",
    ):
        get_source_derived_run(state, first["run_id"])
    source_path.write_bytes(source_bytes)
    if os.name == "posix":
        source_path.chmod(0o600)
    assert not list(source_path.parent.glob(".*.tmp"))
    with pytest.raises(
        SourceDerivationError,
        match="source_derivation_run_event_invalid",
    ):
        append_source_derived_run_event(
            state,
            first["run_id"],
            status="running",
            stage="security",
            created_at="2026-08-17T00:00:04Z",
        )

    link = source_root / "src" / "linked.ts"
    try:
        link.symlink_to(evidence_path)
    except (OSError, NotImplementedError):
        return
    with pytest.raises(
        SourceDerivationError,
        match="source_derivation_evidence_invalid",
    ):
        read_source_derived_evidence(source_root, "src/linked.ts")

    for name, content in (
        ("wrong.txt", b"export const value = 1;\n"),
        ("secret.ts", b'const token = "secret-value";\n'),
        ("large.ts", b"x" * (128 * 1024 + 1)),
    ):
        candidate = source_root / "src" / name
        candidate.write_bytes(content)
        with pytest.raises(
            SourceDerivationError,
            match="source_derivation_evidence_invalid",
        ):
            read_source_derived_evidence(source_root, f"src/{name}")
