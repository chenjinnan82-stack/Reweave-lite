from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "analyze_reweave_source_graph.mjs"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node is required")


def _module(path: str, source: str | bytes, *, sha256: str | None = None) -> dict[str, str]:
    raw = source.encode("utf-8") if isinstance(source, str) else source
    return {
        "path": path,
        "source_base64": base64.b64encode(raw).decode("ascii"),
        "sha256": sha256 or hashlib.sha256(raw).hexdigest(),
    }


def _request(
    mode: str,
    modules: dict[str, str | bytes],
    *,
    entry_modules: list[str] | None = None,
    target: dict[str, str] | None = None,
    parameter_domains: list[dict[str, object]] | None = None,
    module_snapshot: list[dict[str, str]] | None = None,
    symlinks: list[dict[str, str]] | None = None,
    isolate_entry_failures: bool = False,
) -> dict[str, object]:
    request: dict[str, object] = {
        "schema": "source_graph_request.v1",
        "mode": mode,
        "project_id": "source-graph-contract-test",
        "scope_snapshot_sha256": "1" * 64,
        "source_identity_sha256": "2" * 64,
        "entry_modules": entry_modules or [next(iter(modules))],
        "module_snapshot": module_snapshot
        or [_module(path, source) for path, source in modules.items()],
        "symlinks": symlinks or [],
    }
    if isolate_entry_failures:
        request["isolate_entry_failures"] = True
    if mode in {"prove", "capture"}:
        request["target"] = target
        request["parameter_domains"] = parameter_domains or []
    assert SCRIPT.is_file(), f"missing Stage D worker: {SCRIPT}"
    with tempfile.TemporaryDirectory(prefix="reweave-source-graph-test-") as temporary:
        temporary_root = Path(temporary).resolve()
        os.chmod(temporary_root, 0o700)
        marker = temporary_root / ".reweave-capture-job-v1"
        marker.write_text("reweave-capture-private-job.v1\n", encoding="utf-8")
        os.chmod(marker, 0o600)
        if mode == "capture":
            request["temporary_root"] = str(temporary_root)
        completed = subprocess.run(
            [NODE, "--max-old-space-size=512", str(SCRIPT)],
            input=json.dumps(request, ensure_ascii=False, separators=(",", ":")),
            capture_output=True,
            text=True,
            cwd=ROOT,
            timeout=45,
            check=False,
        )
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    result = json.loads(completed.stdout)
    assert result["schema"] == "source_graph.v1"
    return result


def _graph(modules: dict[str, str | bytes], **kwargs: object) -> dict[str, object]:
    result = _request("graph", modules, **kwargs)
    assert result["status"] == "ok", result
    return result


def _export(result: dict[str, object], module_path: str, public_name: str) -> dict[str, object]:
    module = next(
        item
        for item in result["modules"]  # type: ignore[index]
        if item["logical_path"] == module_path
    )
    exported = next(item for item in module["exports"] if item["public_name"] == public_name)
    bindings = {
        item["binding_id"]: item
        for graph_module in result["modules"]  # type: ignore[index]
        for item in graph_module["bindings"]
    }
    binding_id = exported["binding_id"]
    seen: set[str] = set()
    while True:
        assert binding_id not in seen, "alias cycle in a successful graph"
        seen.add(binding_id)
        binding = bindings[binding_id]
        if "parameters" in binding:
            return binding
        binding_id = binding["target_binding_id"]


def _prove(
    modules: dict[str, str | bytes],
    module_path: str,
    export_name: str,
    domains: list[dict[str, object]],
    *,
    entry_modules: list[str] | None = None,
) -> dict[str, object]:
    graph = _graph(modules, entry_modules=entry_modules or [module_path])
    target_binding = _export(graph, module_path, export_name)
    parameters = target_binding["parameters"]
    assert len(parameters) == len(domains)
    parameter_domains = [
        {"parameter_binding_id": parameter["binding_id"], "domain": domain}
        for parameter, domain in zip(parameters, domains, strict=True)
    ]
    result = _request(
        "prove",
        modules,
        entry_modules=entry_modules or [module_path],
        target={"module_relpath": module_path, "export_name": export_name},
        parameter_domains=parameter_domains,
    )
    if result["status"] == "ok":
        assert result["proof"]["target_binding_id"] == target_binding["binding_id"]
        expected_domains = []
        for item in parameter_domains:
            domain = item["domain"]
            normalized = dict(domain)
            if domain["kind"] == "boolean":
                normalized["values"] = sorted(set(domain["values"]))
            elif domain["kind"] == "enum":
                normalized["values"] = sorted(
                    set(domain["values"]), key=lambda value: value.encode("utf-8")
                )
            expected_domains.append(
                {
                    "parameter_binding_id": item["parameter_binding_id"],
                    "domain": normalized,
                }
            )
        assert result["proof"]["parameter_domains"] == expected_domains
    return result


def _capture(
    modules: dict[str, str | bytes],
    module_path: str,
    export_name: str,
    domains: list[dict[str, object]],
) -> dict[str, object]:
    graph = _graph(modules, entry_modules=[module_path])
    target_binding = _export(graph, module_path, export_name)
    parameters = target_binding["parameters"]
    assert len(parameters) == len(domains)
    result = _request(
        "capture",
        modules,
        entry_modules=[module_path],
        target={"module_relpath": module_path, "export_name": export_name},
        parameter_domains=[
            {"parameter_binding_id": parameter["binding_id"], "domain": domain}
            for parameter, domain in zip(parameters, domains, strict=True)
        ],
    )
    if result["status"] == "ok":
        assert result["proof"]["target_binding_id"] == target_binding["binding_id"]
    return result


def _integer(minimum: int, maximum: int) -> dict[str, object]:
    return {"kind": "integer", "intervals": [[minimum, maximum]]}


def _boolean(*values: bool) -> dict[str, object]:
    return {"kind": "boolean", "values": list(values)}


def _enum(*values: str) -> dict[str, object]:
    return {"kind": "enum", "values": list(values)}


def _assert_rejected(result: dict[str, object], *codes: str) -> None:
    assert result["status"] == "rejected", result
    assert result["error_code"] in codes, result
    assert "logical_path" in result


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _assert_integer_proof(
    result: dict[str, object], expected_intervals: list[list[int]]
) -> dict[str, object]:
    assert result["status"] == "ok", result
    proof = result["proof"]
    assert proof["result_domain"] == {
        "kind": "integer",
        "intervals": expected_intervals,
    }
    assert proof["parameter_domains"]
    assert proof["closure"]["module_paths"] == sorted(
        proof["closure"]["module_paths"], key=lambda path: path.encode("utf-8")
    )
    assert proof["closure"]["binding_ids"] == sorted(proof["closure"]["binding_ids"])
    assert len(proof["closure_sha256"]) == 64
    assert proof["target_binding_id"] in proof["closure"]["binding_ids"]
    return proof


def test_graph_uses_lexical_bindings_and_is_deterministic() -> None:
    modules = {
        "src/calc.js": """const rate = 2;
export function calculate(rate) {
  const doubled = rate * 2;
  return doubled;
}
"""
    }
    first = _graph(modules)
    second = _graph(modules)
    assert first == second
    binding = _export(first, "src/calc.js", "calculate")
    assert binding["kind"] == "function"
    assert len(binding["parameters"]) == 1
    assert binding["parameters"][0]["binding_id"] != next(
        item["binding_id"]
        for item in first["modules"][0]["bindings"]  # type: ignore[index]
        if item["kind"] == "module_const"
    )
    assert binding["reads"]
    expected_binding_id = _canonical_sha256(
        {
            "source_graph_version": "source_graph.v1",
            "logical_path": "src/calc.js",
            "binding_kind": "function",
            "start_byte": binding["start_byte"],
            "end_byte": binding["end_byte"],
            "declaration_sha256": binding["declaration_sha256"],
            "lexical_parent_binding_id": None,
        }
    )
    assert binding["binding_id"] == expected_binding_id


def test_graph_entry_isolation_deduplicates_failures_and_keeps_valid_entry() -> None:
    result = _request(
        "graph",
        {
            "good.js": "export function total(a, b) { return a * b; }\n",
            "bad.js": 'import value from "package"; export { value };\n',
        },
        entry_modules=["good.js", "bad.js", "bad.js"],
        isolate_entry_failures=True,
    )

    assert result["status"] == "ok"
    assert [item["logical_path"] for item in result["modules"]] == ["good.js"]
    assert result["rejection_summary"] == [{"code": "closure_unproven", "count": 1}]


def test_graph_entry_isolation_summarizes_direct_symlink_entry() -> None:
    result = _request(
        "graph",
        {
            "good.js": "export function total(a, b) { return a * b; }\n",
            "linked.js": "export function ignored(value) { return value; }\n",
        },
        entry_modules=["good.js", "linked.js"],
        symlinks=[{"path": "linked.js", "target": "good.js"}],
        isolate_entry_failures=True,
    )

    assert result["status"] == "ok"
    assert [item["logical_path"] for item in result["modules"]] == ["good.js"]
    assert result["rejection_summary"] == [
        {"code": "closure_symlink_forbidden", "count": 1}
    ]


def test_graph_entry_isolation_reuses_shared_dependency_rejection() -> None:
    result = _request(
        "graph",
        {
            "first.js": 'import { value } from "./bad.js"; export { value };\n',
            "second.js": 'import { value } from "./bad.js"; export { value };\n',
            "bad.js": 'import value from "package"; export { value };\n',
            "good.js": "export function total(a, b) { return a * b; }\n",
        },
        entry_modules=["first.js", "second.js", "good.js"],
        isolate_entry_failures=True,
    )

    assert result["status"] == "ok"
    assert [item["logical_path"] for item in result["modules"]] == ["good.js"]
    assert result["rejection_summary"] == [{"code": "closure_unproven", "count": 2}]


def test_graph_without_isolation_preserves_global_entry_traversal() -> None:
    result = _request(
        "graph",
        {
            "a.js": 'import { value } from "./a_dep.js"; export { value };\n',
            "b.js": 'import { other } from "./Case.js"; export { other };\n',
            "a_dep.js": "export const value = ;\n",
            "case.js": "export const other = 1;\n",
        },
        entry_modules=["a.js", "b.js"],
    )

    assert result["status"] == "rejected"
    assert result["error_code"] == "import_path_spelling_mismatch"


def test_graph_without_isolation_preserves_entry_preflight_order() -> None:
    result = _request(
        "graph",
        {"linked.js": "export function ignored(value) { return value; }\n"},
        entry_modules=["linked.js", "../bad.js"],
        symlinks=[{"path": "linked.js", "target": "elsewhere.js"}],
    )

    assert result["status"] == "rejected"
    assert result["error_code"] == "closure_symlink_forbidden"


def test_graph_rejects_invalid_utf8_and_hash_mismatch() -> None:
    invalid = b"export function compute(x) { return x; }\n\xff"
    _assert_rejected(
        _request("graph", {"main.js": invalid}),
        "source_utf8_invalid",
    )
    source = b"export function compute(x) { return x; }"
    _assert_rejected(
        _request(
            "graph",
            {"main.js": source},
            module_snapshot=[_module("main.js", source, sha256="0" * 64)],
        ),
        "source_changed",
    )


def test_utf16_and_utf8_spans_cover_exact_emoji_crlf_declaration_bytes() -> None:
    source = "// 中文😀\r\nexport function 𝒜(x) {\r\n  return x + 1;\r\n}\r\n"
    graph = _graph({"unicode.js": source})
    binding = _export(graph, "unicode.js", "𝒜")
    raw = source.encode("utf-8")
    declaration = raw[binding["start_byte"] : binding["end_byte"]]
    assert hashlib.sha256(declaration).hexdigest() == binding["declaration_sha256"]
    assert declaration.decode("utf-8").startswith("export function 𝒜")
    assert binding["start_utf16"] == 9
    assert binding["end_utf16"] == 52
    assert binding["start_byte"] == 15
    assert binding["end_byte"] == 60
    assert (binding["line"], binding["column"]) == (2, 1)


def test_utf8_bom_remains_part_of_the_span_offset_map() -> None:
    source = b"\xef\xbb\xbfexport function f(x) { return x; }"
    graph = _graph({"bom.js": source})
    binding = _export(graph, "bom.js", "f")
    assert binding["start_utf16"] == 1
    assert binding["start_byte"] == 3
    assert source[binding["start_byte"] : binding["end_byte"]] == (
        b"export function f(x) { return x; }"
    )


@pytest.mark.parametrize(
    ("modules", "module_path", "export_name"),
    [
        ({"main.js": "export function calc(x) { return x + 1; }"}, "main.js", "calc"),
        ({"main.js": "export default function calc(x) { return x + 1; }"}, "main.js", "default"),
        (
            {
                "main.js": 'import { calc as local } from "./leaf.js"; export { local as total };',
                "leaf.js": "export function calc(x) { return x + 1; }",
            },
            "main.js",
            "total",
        ),
        (
            {
                "main.js": 'export { default as total } from "./leaf";',
                "leaf.mjs": "export default function calc(x) { return x + 1; }",
            },
            "main.js",
            "total",
        ),
    ],
)
def test_named_default_alias_reexport_and_extensionless_resolution(
    modules: dict[str, str], module_path: str, export_name: str
) -> None:
    result = _prove(modules, module_path, export_name, [_integer(0, 10)])
    assert result["status"] == "ok", result
    assert isinstance(result["proof"], dict)


def test_capture_bundle_is_deterministic_snapshot_only_and_tree_shaken() -> None:
    modules = {
        "src/main.js": (
            'import { addFee } from "./helper.js"; '
            "function unrelated() { fetch('/never'); } "
            "export function total(value) { return addFee(value); }"
        ),
        "src/helper.js": (
            "const FEE = 3; "
            "export function addFee(value) { return value + FEE; }"
        ),
        "not-in-closure.js": "export function secret() { return 99; }",
    }
    first = _capture(modules, "src/main.js", "total", [_integer(0, 100)])
    reordered = dict(reversed(list(modules.items())))
    second = _capture(reordered, "src/main.js", "total", [_integer(0, 100)])
    assert first["status"] == "ok", first
    assert second["status"] == "ok", second
    assert first["capture"] == second["capture"]

    capture = first["capture"]
    selected = base64.b64decode(capture["source_base64"], validate=True)
    assert hashlib.sha256(selected).hexdigest() == capture["selected_bundle_sha256"]
    assert len(selected) == capture["size_bytes"]
    assert capture["schema"] == "selected_bundle.v1"
    assert capture["bundle_contract_version"] == "reweave_capture_bundle.v1"
    assert capture["logical_path"] == "__reweave_capture__/selected.js"
    assert capture["esbuild_version"] == "0.28.1"
    assert len(capture["bundle_options_sha256"]) == 64
    assert capture["module_evaluation_paths"] == ["src/helper.js", "src/main.js"]
    assert capture["symbol_closure_paths"] == ["src/helper.js", "src/main.js"]
    assert capture["metafile_inputs"] == ["src/helper.js", "src/main.js"]
    decoded = selected.decode("utf-8")
    assert "__selected" in decoded
    assert "fetch" not in decoded
    assert "unrelated" not in decoded
    assert "not-in-closure" not in decoded
    assert "reweave-capture-" not in decoded
    assert str(ROOT) not in decoded


def test_capture_reports_real_string_and_safe_integer_literals_for_sensitive_scanning() -> None:
    result = _capture(
        {
            "main.js": (
                'export function total(mode, value) { '
                'if (mode === "13800138000") return value * 2; '
                "return value; }"
            )
        },
        "main.js",
        "total",
        [_enum("safe", "13800138000"), _integer(0, 10)],
    )
    assert result["status"] == "ok", result
    assert result["capture"]["sensitivity_literals"] == ["13800138000", "2"]


@pytest.mark.parametrize(
    ("modules", "module_path", "export_name"),
    [
        (
            {"main.js": "export default function total(value) { return value + 1; }"},
            "main.js",
            "default",
        ),
        (
            {
                "main.js": 'export { total as quote } from "./leaf.js";',
                "leaf.js": "export function total(value) { return value + 1; }",
            },
            "main.js",
            "quote",
        ),
    ],
)
def test_capture_bundle_supports_default_and_static_reexport(
    modules: dict[str, str], module_path: str, export_name: str
) -> None:
    result = _capture(modules, module_path, export_name, [_integer(0, 10)])
    assert result["status"] == "ok", result
    selected = base64.b64decode(result["capture"]["source_base64"], validate=True)
    assert b"__selected" in selected


def test_capture_runs_dsl_and_top_level_proof_before_bundling() -> None:
    top_level_effect = {
        "main.js": "fetch('/before'); export function total(value) { return value; }"
    }
    _assert_rejected(
        _capture(top_level_effect, "main.js", "total", [_integer(0, 10)]),
        "top_level_side_effect",
    )

    unsupported_target = {
        "main.js": "export function total(value) { return value / 2; }"
    }
    _assert_rejected(
        _capture(unsupported_target, "main.js", "total", [_integer(0, 10)]),
        "unsupported_control_flow",
    )


def test_import_and_reexport_aliases_have_stable_binding_evidence() -> None:
    modules = {
        "main.js": 'import { calc as local } from "./leaf.js"; export { local as total };',
        "leaf.js": "export function calc(x) { return x + 1; }",
    }
    graph = _graph(modules)
    main = next(item for item in graph["modules"] if item["logical_path"] == "main.js")
    aliases = [item for item in main["bindings"] if item["kind"].endswith("_alias")]
    assert [item["kind"] for item in aliases] == ["import_alias", "export_alias"]
    assert all(len(item["target_binding_id"]) == 64 for item in aliases)
    assert all(len(item["export_token_sha256"]) == 64 for item in aliases)
    exported = next(item for item in main["exports"] if item["public_name"] == "total")
    assert exported["binding_id"] == aliases[-1]["binding_id"]
    assert aliases[-1]["target_binding_id"] == aliases[0]["binding_id"]
    assert aliases[-1]["reads"] == [aliases[0]["binding_id"]]


def test_import_alias_remains_the_lexical_edge_for_its_caller() -> None:
    modules = {
        "main.js": (
            'import { helper as local } from "./leaf.js"; '
            "export function total(value) { return local(value); }"
        ),
        "leaf.js": "export function helper(value) { return value + 1; }",
    }
    graph = _graph(modules)
    main = next(item for item in graph["modules"] if item["logical_path"] == "main.js")
    imported = next(item for item in main["bindings"] if item["kind"] == "import_alias")
    caller = next(
        item
        for item in main["bindings"]
        if item["kind"] == "function" and item["display_name"] == "total"
    )
    assert imported["binding_id"] in caller["calls"]
    assert imported["binding_id"] in caller["reads"]
    assert imported["binding_id"] in caller["captures"]
    assert imported["reads"] == [imported["target_binding_id"]]
    assert main["dynamic_dependencies"] == []


@pytest.mark.parametrize(
    "modules",
    [
        {
            "main.js": (
                'export { calc as total } from "./leaf.js"; '
                'export { calc as total } from "./leaf.js";'
            ),
            "leaf.js": "export function calc(value) { return value; }",
        },
        {
            "main.js": (
                'export { calc as total } from "./one.js"; '
                'export { calc as total } from "./two.js";'
            ),
            "one.js": "export function calc(value) { return value; }",
            "two.js": "export function calc(value) { return value + 1; }",
        },
        {
            "main.js": (
                "export function total(value) { return value; } "
                'export { calc as total } from "./leaf.js";'
            ),
            "leaf.js": "export function calc(value) { return value + 1; }",
        },
        {
            "main.js": (
                "export default function first(value) { return value; } "
                "export default function second(value) { return value + 1; }"
            ),
        },
        {
            "main.js": (
                "const first = (value) => value; export default first; "
                "export default function second(value) { return value + 1; }"
            ),
        },
    ],
)
def test_duplicate_or_ambiguous_reexport_name_is_rejected(
    modules: dict[str, str],
) -> None:
    _assert_rejected(_request("graph", modules), "closure_unproven")


def test_extensionless_ambiguity_and_case_mismatch_fail_closed() -> None:
    ambiguous = {
        "main.js": 'export { calc } from "./leaf";',
        "leaf.js": "export function calc(x) { return x; }",
        "leaf.mjs": "export function calc(x) { return x; }",
    }
    _assert_rejected(_request("graph", ambiguous), "closure_unproven")
    wrong_case = {
        "main.js": 'export { calc } from "./Leaf.js";',
        "leaf.js": "export function calc(x) { return x; }",
    }
    _assert_rejected(_request("graph", wrong_case), "import_path_spelling_mismatch")


def test_cross_module_helper_and_const_are_proved() -> None:
    modules = {
        "main.js": 'import { addFee } from "./helper.js"; export function total(x) { return addFee(x); }',
        "helper.js": "const FEE = 3; export function addFee(x) { return x + FEE; }",
    }
    result = _prove(modules, "main.js", "total", [_integer(0, 100)])
    proof = _assert_integer_proof(result, [[3, 103]])
    assert proof["closure"]["module_paths"] == ["helper.js", "main.js"]


def test_reads_and_captures_follow_shadowed_lexical_symbols() -> None:
    source = """const rate = 2;
export function total(quantity) {
  const rate = quantity + 1;
  function apply(quantity) { return quantity * rate; }
  return apply(quantity);
}
"""
    graph = _graph({"main.js": source})
    outer = _export(graph, "main.js", "total")
    bindings = {
        item["binding_id"]: item
        for item in graph["modules"][0]["bindings"]  # type: ignore[index]
    }
    nested = next(
        item
        for item in bindings.values()
        if item["kind"] == "function"
        and item["lexical_parent_binding_id"] == outer["binding_id"]
    )
    local_rate = next(
        item
        for item in bindings.values()
        if item["kind"] == "local_const"
        and item["lexical_parent_binding_id"] == outer["binding_id"]
    )
    module_rate = next(item for item in bindings.values() if item["kind"] == "module_const")
    assert local_rate["binding_id"] in nested["captures"]
    assert module_rate["binding_id"] not in nested["captures"]
    assert nested["parameters"][0]["binding_id"] in nested["reads"]


def test_nested_helper_can_use_a_proved_immutable_capture() -> None:
    source = """export function total(quantity) {
  const rate = quantity + 1;
  function apply(value) { return value * rate; }
  return apply(quantity);
}
"""
    result = _prove({"main.js": source}, "main.js", "total", [_integer(0, 2)])
    _assert_integer_proof(result, [[0, 6]])


def test_same_module_helper_static_initializer_and_integer_operators_are_proved() -> None:
    source = """function scale(value) { return value * 2; }
const OFFSET = scale(2);
function adjust(value) { return scale(value) + OFFSET; }
export function total(value, discount) {
  const subtotal = adjust(value);
  let result = subtotal - discount;
  return +result;
}
"""
    result = _prove(
        {"main.js": source},
        "main.js",
        "total",
        [_integer(0, 100), _integer(0, 10)],
    )
    _assert_integer_proof(result, [[-6, 204]])


def test_local_const_temporal_dead_zone_fails_closed() -> None:
    source = """export function total(value) {
  const result = later + value;
  const later = 2;
  return result;
}
"""
    result = _prove({"main.js": source}, "main.js", "total", [_integer(0, 10)])
    assert result["status"] == "rejected", result


def test_top_level_const_bound_helper_temporal_dead_zone_fails_closed() -> None:
    rejected = _prove(
        {
            "main.js": (
                "const OFFSET = helper(1); "
                "const helper = (value) => value + 1; "
                "export function total(value) { return value + OFFSET; }"
            )
        },
        "main.js",
        "total",
        [_integer(0, 10)],
    )
    _assert_rejected(rejected, "top_level_initializer_unproven")

    accepted = _prove(
        {
            "main.js": (
                "const helper = (value) => value + 1; "
                "const OFFSET = helper(1); "
                "export function total(value) { return value + OFFSET; }"
            )
        },
        "main.js",
        "total",
        [_integer(0, 10)],
    )
    _assert_integer_proof(accepted, [[2, 12]])


def test_unrelated_dangerous_function_can_tree_shake_but_top_level_effect_cannot() -> None:
    safe = {
        "main.js": """function unrelated() { fetch('/never'); }
export function total(x) { return x + 1; }
"""
    }
    assert _prove(safe, "main.js", "total", [_integer(0, 10)])["status"] == "ok"

    unsafe = {
        "main.js": """function unrelated() { return 1; }
unrelated();
export function total(x) { return x + 1; }
"""
    }
    graph = _graph(unsafe)
    parameter = _export(graph, "main.js", "total")["parameters"][0]
    result = _request(
        "prove",
        unsafe,
        target={"module_relpath": "main.js", "export_name": "total"},
        parameter_domains=[
            {"parameter_binding_id": parameter["binding_id"], "domain": _integer(0, 10)}
        ],
    )
    _assert_rejected(result, "top_level_side_effect")


def test_if_ternary_switch_boolean_enum_and_math_whitelist() -> None:
    source = """export function price(value, enabled, tier) {
  const magnitude = value < 0 ? Math.abs(value) : Math.max(value, 1);
  if (!enabled && tier === "low") return Math.min(magnitude, 5);
  switch (tier) {
    case "high": return magnitude + 2;
    default: return magnitude;
  }
}
"""
    result = _prove(
        {"main.js": source},
        "main.js",
        "price",
        [_integer(-10, 10), _boolean(False, True), _enum("low", "high")],
    )
    _assert_integer_proof(result, [[1, 12]])


def test_branch_refinement_keeps_a_nonconvex_union() -> None:
    source = """export function f(value) {
  if (value < 0) return -value;
  return value + 10;
}
"""
    result = _prove({"main.js": source}, "main.js", "f", [_integer(-2, 2)])
    _assert_integer_proof(result, [[1, 2], [10, 12]])


def test_remainder_uses_nonzero_javascript_integer_domain() -> None:
    source = "export function remainder(value, divisor) { return value % divisor; }"
    passed = _prove(
        {"main.js": source},
        "main.js",
        "remainder",
        [_integer(-10, 10), _integer(2, 5)],
    )
    _assert_integer_proof(passed, [[-4, 4]])
    rejected = _prove(
        {"main.js": source},
        "main.js",
        "remainder",
        [_integer(-10, 10), _integer(-1, 1)],
    )
    _assert_rejected(rejected, "interval_unproven")


def test_mutable_capture_is_rejected() -> None:
    source = "let rate = 2; export function total(x) { return x * rate; }"
    result = _prove({"main.js": source}, "main.js", "total", [_integer(0, 10)])
    _assert_rejected(result, "mutable_capture")


@pytest.mark.parametrize(
    ("source", "codes"),
    [
        ("export function f(x) { return f(x); }", ("closure_unproven",)),
        ("export function f(x) { while (x > 0) x = x - 1; return x; }", ("unsupported_control_flow",)),
        ("export function f(x, g) { return g(x); }", ("dynamic_dependency",)),
        ("export function f(x) { return document.body ? x : 0; }", ("unsupported_control_flow",)),
        ("export function f(x) { fetch('/x'); return x; }", ("unsupported_control_flow",)),
        ("export function f(x) { localStorage.setItem('x', '1'); return x; }", ("unsupported_control_flow",)),
        ("export function f(x) { const Math = {abs(v) { return v; }}; return Math.abs(x); }", ("unsupported_control_flow",)),
    ],
)
def test_recursion_loop_dynamic_dom_network_storage_and_math_shadow_fail_closed(
    source: str, codes: tuple[str, ...]
) -> None:
    parameter_count = source[source.index("(") + 1 : source.index(")")].count(",") + 1
    result = _prove(
        {"main.js": source},
        "main.js",
        "f",
        [_integer(0, 10)] * parameter_count,
    )
    _assert_rejected(result, *codes)


def test_dynamic_import_is_a_dynamic_dependency() -> None:
    source = "export function f(x) { import('./leaf.js'); return x; }"
    result = _prove(
        {"main.js": source, "leaf.js": "export const value = 1;"},
        "main.js",
        "f",
        [_integer(0, 10)],
    )
    _assert_rejected(result, "dynamic_dependency")


def test_unreachable_dangerous_code_in_selected_function_is_rejected() -> None:
    source = "export function f(x) { return x; fetch('/hidden-secret'); }"
    result = _prove({"main.js": source}, "main.js", "f", [_integer(0, 10)])
    _assert_rejected(result, "unsupported_control_flow")
    serialized = json.dumps(result, ensure_ascii=False)
    assert "hidden-secret" not in serialized
    assert "source_base64" not in serialized
    assert "stack" not in result


@pytest.mark.parametrize(
    "helper_body",
    [
        "fetch('/hidden'); return value;",
        "return helper(value);",
    ],
)
def test_unreachable_transitive_helper_is_still_audited(helper_body: str) -> None:
    modules = {
        "main.js": (
            'import { helper } from "./helper.js"; '
            "export function f(value) { return value; return helper(value); }"
        ),
        "helper.js": f"export function helper(value) {{ {helper_body} }}",
    }
    result = _prove(modules, "main.js", "f", [_integer(0, 10)])
    _assert_rejected(result, "unsupported_control_flow", "closure_unproven")


def test_enum_input_cannot_be_the_final_computation_output() -> None:
    result = _prove(
        {"main.js": "export function f(kind) { return kind; }"},
        "main.js",
        "f",
        [_enum("public", "customer@example.com")],
    )
    _assert_rejected(result, "interval_unproven")
    assert "customer@example.com" not in json.dumps(result)


def test_cross_module_top_level_side_effect_is_rejected() -> None:
    modules = {
        "main.js": 'import { helper } from "./helper.js"; export function f(x) { return helper(x); }',
        "helper.js": "const ready = fetch('/secret'); export function helper(x) { return x + 1; }",
    }
    result = _prove(modules, "main.js", "f", [_integer(0, 10)])
    _assert_rejected(result, "top_level_side_effect")
    assert "/secret" not in json.dumps(result)


def test_graph_records_unknown_calls_and_nonwhitelisted_top_level_execution() -> None:
    source = "const ready = service.start(); if (true) {} export function f(x) { return obj.m(x); }"
    graph = _graph({"main.js": source})
    module = graph["modules"][0]
    assert {item["kind"] for item in module["dynamic_dependencies"]} == {
        "unknown_member_call",
        "unknown_read",
    }
    assert [item["kind"] for item in module["top_level_execution"]] == [
        "VariableStatement",
        "IfStatement",
    ]


def test_graph_records_unknown_top_level_initializer_as_execution() -> None:
    source = "const rate = ambientRate; export function total(value) { return value; }"
    graph = _graph({"main.js": source})
    module = graph["modules"][0]
    assert {item["kind"] for item in module["dynamic_dependencies"]} == {
        "unknown_read"
    }
    assert [item["kind"] for item in module["top_level_execution"]] == [
        "VariableStatement"
    ]


@pytest.mark.parametrize(
    "initializer",
    [
        "{}",
        "class {}",
        "1 / 2",
        "1 % 0",
        "9007199254740991 + 1",
        "true + 1",
        "true && 1",
    ],
)
def test_graph_records_unsupported_top_level_initializers_as_execution(
    initializer: str,
) -> None:
    source = (
        f"const unsupported = {initializer}; "
        "export function total(value) { return value; }"
    )
    graph = _graph({"main.js": source})
    assert [item["kind"] for item in graph["modules"][0]["top_level_execution"]] == [
        "VariableStatement"
    ]


def test_graph_does_not_flag_fixed_functions_or_static_scalar_constants() -> None:
    source = (
        "const INTEGER = -2; const FLAG = !false; const KIND = 'standard'; "
        "const helper = (value) => value + INTEGER; "
        "export function total(value) { return helper(value); }"
    )
    graph = _graph({"main.js": source})
    assert graph["modules"][0]["top_level_execution"] == []


def test_entry_modules_exclude_unreferenced_snapshot_modules() -> None:
    modules = {
        "main.js": "export function f(x) { return x + 1; }",
        "private/secret.js": "export const customerName = 'not-returned';",
    }
    graph = _graph(modules, entry_modules=["main.js"])
    assert [item["logical_path"] for item in graph["modules"]] == ["main.js"]
    assert "customerName" not in json.dumps(graph)


def test_unicode_normalization_path_conflict_and_near_match_fail_closed() -> None:
    composed = "caf\u00e9.js"
    decomposed = "cafe\u0301.js"
    conflict = _request(
        "graph",
        {
            composed: "export function f(x) { return x; }",
            decomposed: "export function g(x) { return x; }",
        },
        entry_modules=[composed],
    )
    _assert_rejected(conflict, "source_path_normalization_conflict")

    near_match = _request(
        "graph",
        {
            "main.js": f'export {{ f }} from "./{decomposed}";',
            composed: "export function f(x) { return x; }",
        },
        entry_modules=["main.js"],
    )
    _assert_rejected(near_match, "import_path_spelling_mismatch")


def test_closure_import_through_symlink_is_rejected() -> None:
    modules = {
        "main.js": 'import { helper } from "./leaf.js"; export function f(x) { return helper(x); }',
        "leaf.js": "export function helper(x) { return x + 1; }",
    }
    graph = _request(
        "graph",
        modules,
        symlinks=[{"path": "leaf.js"}],
    )
    _assert_rejected(graph, "closure_symlink_forbidden")


def test_unrelated_symlink_does_not_block_a_proved_closure() -> None:
    modules = {"main.js": "export function f(x) { return x + 1; }"}
    graph = _request(
        "graph",
        modules,
        symlinks=[{"path": "unrelated.js"}],
    )
    assert graph["status"] == "ok", graph


@pytest.mark.parametrize(
    "source",
    [
        'import { helper } from "package"; export function f(x) { return helper(x); }',
        'import { helper } from "https://example.invalid/x.js"; export function f(x) { return helper(x); }',
        'import { helper } from "./leaf.js?raw"; export function f(x) { return helper(x); }',
        'import { helper } from "./leaf.js#part"; export function f(x) { return helper(x); }',
        'import { helper } from "./leaf/index.js"; export function f(x) { return helper(x); }',
        'import "./leaf.js"; export function f(x) { return x; }',
        'import * as leaf from "./leaf.js"; export function f(x) { return leaf.helper(x); }',
        'export * from "./leaf.js";',
        'const leaf = require("./leaf.js"); export function f(x) { return leaf.helper(x); }',
    ],
)
def test_unsupported_resolver_forms_fail_closed_without_source_leak(source: str) -> None:
    modules = {
        "main.js": source,
        "leaf.js": "export function helper(x) { return x + 1; }",
        "leaf/index.js": "export function helper(x) { return x + 1; }",
    }
    result = _request("graph", modules)
    _assert_rejected(result, "closure_unproven")
    serialized = json.dumps(result, ensure_ascii=False)
    assert source not in serialized
    assert str(ROOT) not in serialized


def test_safe_integer_overflow_and_enum_limit_fail_closed() -> None:
    overflow = _prove(
        {"main.js": "export function f(x) { return x + 1; }"},
        "main.js",
        "f",
        [_integer(9_007_199_254_740_991, 9_007_199_254_740_991)],
    )
    _assert_rejected(overflow, "interval_unproven")

    enum_source = 'export function f(kind) { return kind === "v0" ? 1 : 2; }'
    accepted = _prove(
        {"main.js": enum_source},
        "main.js",
        "f",
        [_enum(*(f"v{index}" for index in range(32)))],
    )
    assert accepted["status"] == "ok", accepted
    too_many = _prove(
        {"main.js": enum_source},
        "main.js",
        "f",
        [_enum(*(f"v{index}" for index in range(33)))],
    )
    _assert_rejected(too_many, "interval_unproven")


@pytest.mark.parametrize(
    "domain",
    [
        {"kind": "integer", "intervals": []},
        {"kind": "boolean", "values": []},
        {"kind": "enum", "values": []},
    ],
)
def test_empty_external_parameter_domain_is_rejected(domain: dict[str, object]) -> None:
    result = _prove(
        {"main.js": "export function f(value) { return 1; }"},
        "main.js",
        "f",
        [domain],
    )
    _assert_rejected(result, "interval_unproven")


def test_more_than_sixteen_disjoint_integer_segments_are_rejected() -> None:
    branches = "\n".join(
        f"  if (value === {index}) return {index * 2};" for index in range(16)
    )
    source = f"export function f(value) {{\n{branches}\n  return 32;\n}}"
    result = _prove({"main.js": source}, "main.js", "f", [_integer(0, 16)])
    _assert_rejected(result, "interval_unproven")


def test_sixteen_disjoint_integer_segments_are_preserved_exactly() -> None:
    branches = "\n".join(
        f"  if (value === {index}) return {index * 2};" for index in range(15)
    )
    source = f"export function f(value) {{\n{branches}\n  return 30;\n}}"
    result = _prove({"main.js": source}, "main.js", "f", [_integer(0, 15)])
    _assert_integer_proof(result, [[index * 2, index * 2] for index in range(16)])


def _flat_closure(module_count: int, *, padded_size: int | None = None) -> dict[str, str]:
    imports = "\n".join(
        f'import {{ helper{index} }} from "./helper{index}.js";'
        for index in range(1, module_count)
    )
    additions = " + ".join(f"helper{index}()" for index in range(1, module_count))
    main = f"{imports}\nexport function compute(value) {{ return value{(' + ' + additions) if additions else ''}; }}\n"
    modules = {"main.js": main}
    for index in range(1, module_count):
        modules[f"helper{index}.js"] = f"export function helper{index}() {{ return {index}; }}\n"
    if padded_size is not None:
        for path, source in tuple(modules.items()):
            encoded = source.encode("utf-8")
            assert len(encoded) + 3 <= padded_size
            modules[path] = source + "//" + "x" * (padded_size - len(encoded) - 2)
            assert len(modules[path].encode("utf-8")) == padded_size
    return modules


def _deep_closure(import_depth: int) -> dict[str, str]:
    modules: dict[str, str] = {}
    for depth in range(import_depth + 1):
        name = "main.js" if depth == 0 else f"helper{depth}.js"
        export_name = "compute" if depth == 0 else f"helper{depth}"
        if depth == import_depth:
            modules[name] = f"export function {export_name}(value) {{ return value; }}"
        else:
            next_name = f"helper{depth + 1}"
            modules[name] = (
                f'import {{ {next_name} }} from "./{next_name}.js"; '
                f"export function {export_name}(value) {{ return {next_name}(value); }}"
            )
    return modules


def test_module_count_and_import_depth_limits_are_exact() -> None:
    accepted_modules = _flat_closure(32)
    assert _prove(
        accepted_modules, "main.js", "compute", [_integer(0, 1)]
    )["status"] == "ok"
    _assert_rejected(
        _prove(_flat_closure(33), "main.js", "compute", [_integer(0, 1)]),
        "closure_unproven",
    )

    accepted_depth = _deep_closure(8)
    assert _prove(
        accepted_depth, "main.js", "compute", [_integer(0, 1)]
    )["status"] == "ok"
    _assert_rejected(
        _prove(_deep_closure(9), "main.js", "compute", [_integer(0, 1)]),
        "closure_unproven",
    )


def test_closure_source_byte_limit_is_four_mibibytes() -> None:
    one_mib = 1024 * 1024
    accepted = _flat_closure(4, padded_size=one_mib)
    assert sum(len(source.encode("utf-8")) for source in accepted.values()) == 4 * one_mib
    assert _prove(accepted, "main.js", "compute", [_integer(0, 1)])["status"] == "ok"

    rejected = _flat_closure(5, padded_size=850_000)
    assert sum(len(source.encode("utf-8")) for source in rejected.values()) > 4 * one_mib
    _assert_rejected(
        _prove(rejected, "main.js", "compute", [_integer(0, 1)]),
        "closure_unproven",
    )
