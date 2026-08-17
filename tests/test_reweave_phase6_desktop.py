from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import pytest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "reweave_phase6_quote"
SNAKE_JS_REPOSITORY = "https://github.com/MasiaAntoine/snake-js"
SNAKE_JS_COMMIT = "894e7dc8549b0aa347ecbe985704a3c32fbbc767"
SNAKE_JS_SNAPSHOT = "26ac34b1bc41102c9846d7899dca5d3ce5b4709ab988899cc30ab1fb800e1e5d"
SNAKE_JS_PLAN_ID = (
    "weave_dd8dc1dc965daa0085d897e4f481815e7e465cf6d770652893e27591a030b54f"
)
SNAKE_JS_PATCH_SHA256 = (
    "ae85f9bd49ec8a0d5f25f70fa8dccc07809319dbfcdd1e80874f2f4fb891d76f"
)
TARGET_VALIDATION_STEPS = [
    "target_snapshot_match",
    "target_path_and_resource_boundaries",
    "capsule_usage_scope",
    "module_native_composition",
    "target_output_collision",
    "target_snapshot_unchanged",
]
TARGET_EVIDENCE_CHECKS = [
    "target_snapshot_bound",
    "target_paths_and_resources",
    "capsule_usage_scope",
    "module_native_composition",
    "output_paths_collision_free",
    "target_snapshot_unchanged",
]


def _canonical_sha256(value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _tree_state(root: Path, *, exclude_git: bool = False) -> dict[str, object]:
    if not root.exists():
        return {"exists": False, "entry_count": 0, "sha256": _canonical_sha256([])}
    rows: list[dict[str, object]] = []
    mtimes = [{"path": ".", "mtime_ns": root.lstat().st_mtime_ns}]
    for path in sorted(root.rglob("*")):
        relpath = path.relative_to(root)
        if exclude_git and relpath.parts and relpath.parts[0] == ".git":
            continue
        info = path.lstat()
        mtimes.append({"path": relpath.as_posix(), "mtime_ns": info.st_mtime_ns})
        row: dict[str, object] = {
            "path": relpath.as_posix(),
            "mode": stat.S_IMODE(info.st_mode),
        }
        if path.is_symlink():
            row.update({"kind": "symlink", "target": os.readlink(path)})
        elif path.is_file():
            content = path.read_bytes()
            row.update(
                {
                    "kind": "file",
                    "size_bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            )
        elif path.is_dir():
            row["kind"] = "directory"
        else:
            row["kind"] = "other"
        rows.append(row)
    return {
        "exists": True,
        "root_mode": stat.S_IMODE(root.lstat().st_mode),
        "entry_count": len(rows),
        "sha256": _canonical_sha256(rows),
        "mtime_sha256": _canonical_sha256(mtimes),
    }


def _git_target_state(target: Path) -> dict[str, object]:
    environment = dict(os.environ)
    environment["GIT_OPTIONAL_LOCKS"] = "0"

    def git(*args: str) -> bytes:
        return subprocess.run(
            ["git", "-C", str(target), *args],
            check=True,
            capture_output=True,
            env=environment,
        ).stdout

    status = git("status", "--porcelain=v1", "-z", "--untracked-files=all")
    return {
        "head": git("rev-parse", "HEAD").decode("ascii").strip(),
        "status_clean": status == b"",
        "status_sha256": hashlib.sha256(status).hexdigest(),
    }


def _usage_state(store) -> dict[str, object]:
    with store.read_connection() as connection:
        rows = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM product_capsule_usage ORDER BY usage_id"
            )
        ]
    return {"count": len(rows), "sha256": _canonical_sha256(rows)}


def _contains_bytes(root: Path, needle: bytes) -> bool:
    if not root.exists():
        return False
    for path in root.rglob("*"):
        if path.is_file() and not path.is_symlink():
            try:
                if needle in path.read_bytes():
                    return True
            except OSError:
                continue
    return False


def test_simple_mode_scans_multiply_without_creating_candidate(
    tmp_path: Path, monkeypatch
) -> None:
    if shutil.which("node") is None:
        pytest.skip("Node is required for JavaScript computation scanning")
    if sys.platform.startswith("linux") and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        pytest.skip("A desktop GUI session is required")
    pytest.importorskip("PySide6.QtWebEngineCore")
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWebEngineCore import QWebEngineProfile

    source = tmp_path / "source"
    state = tmp_path / "state"
    source.mkdir()
    (source / "multiply.js").write_text(
        "export function Multiply(x, y) { return x * y; }\n",
        encoding="utf-8",
    )
    (source / "classify.js").write_text(
        'export function Classify(question) {\n'
        '  return question.includes("urgent") ? "urgent" : "normal";\n'
        "}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("REWEAVE_STATE_DIR", str(state))

    def source_snapshot() -> list[tuple[str, int, int, str]]:
        rows: list[tuple[str, int, int, str]] = []
        for path in sorted(source.rglob("*")):
            info = path.lstat()
            digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""
            rows.append(
                (
                    path.relative_to(source).as_posix(),
                    stat.S_IMODE(info.st_mode),
                    info.st_mtime_ns,
                    digest,
                )
            )
        return rows

    source_before = source_snapshot()
    from pimos_lite import desktop_reweave_static as desktop
    from pimos_lite.reweave_app_service import ReweaveAppService

    service = ReweaveAppService()
    root = service._capsule_intake.bind_source_root(
        source, root_kind="single_project"
    )
    registered = service.register_javascript_computation_source(
        {
            "source_root_id": root["root_id"],
            "project_relpath": ".",
            "display_name": "Multiply source",
        }
    )
    assert registered.get("ok") is True, registered
    captured_mapping_requests: list[dict[str, object]] = []

    def capture_mapping_request(payload: dict[str, object]) -> dict[str, object]:
        captured_mapping_requests.append(payload)
        return {"ok": False, "error": {"code": "capture_request_observed"}}

    monkeypatch.setattr(
        service, "start_create_computation_adapter", capture_mapping_request
    )

    original_get_initial_state = service.get_initial_state

    def initial_state_with_disabled_rows() -> dict[str, object]:
        initial = original_get_initial_state()
        management = initial["capsuleIngestionV1"]
        management["projects"] = list(management["projects"]) + [
            {
                "project_id": "pending-project",
                "source_type": "static_web",
                "project_state": "pending_confirmation",
                "project_relpath": "pending",
                "display_name": "Pending source",
            },
            {
                "project_id": "missing-project",
                "source_type": "static_web",
                "project_state": "source_missing",
                "project_relpath": "missing",
                "display_name": "Missing source",
            },
            {
                "project_id": "unknown-state-project",
                "source_type": "static_web",
                "project_state": "mystery",
                "project_relpath": "unknown-state",
                "display_name": "Unknown state source",
            },
            {
                "project_id": "unknown-type-project",
                "source_type": "mystery",
                "project_state": "ready",
                "project_relpath": "unknown-type",
                "display_name": "Unknown type source",
            },
        ]
        return initial

    monkeypatch.setattr(service, "get_initial_state", initial_state_with_disabled_rows)

    QApplication = desktop.import_qt_webengine()[0]
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    profile = QWebEngineProfile.defaultProfile()
    profile.setCachePath(str(tmp_path / "qweb-cache"))
    profile.setPersistentStoragePath(str(tmp_path / "qweb-storage"))
    window = None

    def pump(seconds: float = 0.03) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.005)

    try:
        with patch.object(desktop, "ReweaveAppService", return_value=service):
            window, _bridge = desktop.create_reweave_window()
            page = window.centralWidget().page()
            window.show()

            def js(expression: str, timeout: float = 15) -> object:
                result: list[object] = []
                page.runJavaScript(expression, result.append)
                deadline = time.monotonic() + timeout
                while not result and time.monotonic() < deadline:
                    pump()
                if not result:
                    raise TimeoutError("javascript_callback_timeout")
                return result[0]

            def wait_js(expression: str, timeout: float, label: str) -> object:
                deadline = time.monotonic() + timeout
                last: object = None
                while time.monotonic() < deadline:
                    last = js(expression)
                    if last:
                        return last
                    pump(0.08)
                raise TimeoutError(f"{label}:{last!r}")

            wait_js(
                "document.readyState === 'complete' && !!window.reweaveBridge",
                30,
                "desktop_bridge",
            )
            if js("document.documentElement.lang !== 'zh-CN'"):
                js("document.getElementById('btn-lang').click(); true")
            js("document.getElementById('btn-capsule-warehouse').click(); true")
            wait_js(
                "!document.getElementById('screen-capsule-warehouse').classList.contains('hidden') && "
                "!document.getElementById('btn-open-capsule-ingestion').classList.contains('hidden')",
                10,
                "empty warehouse management entry",
            )
            js(
                "document.getElementById('btn-open-capsule-ingestion').focus(); "
                "document.getElementById('btn-open-capsule-ingestion').click(); true"
            )
            wait_js(
                "document.getElementById('warehouse-projects').textContent.includes('Multiply source')",
                30,
                "project_row",
            )
            root_id = str(root["root_id"])
            root_selection = json.loads(
                str(
                    js(
                        """JSON.stringify((() => {
                          const controls = Array.from(document.querySelectorAll(
                            '#warehouse-projects select[data-source-root-selector="session"]'
                          ));
                          const html = document.getElementById('warehouse-projects').outerHTML;
                          return {
                            count: controls.length,
                            values: controls.map(item => item.value),
                            labels: controls.map(item => item.options[1]?.textContent || ''),
                            registration_disabled: document.querySelector(
                              '#warehouse-projects [data-action="register-javascript-computation-source"]'
                            )?.disabled ?? false,
                            html
                          };
                        })())"""
                    )
                )
            )
            assert root_selection["count"] == 2
            assert root_selection["values"] == ["", ""]
            assert all(
                re.fullmatch(r"source · [0-9a-f]{6}", label)
                for label in root_selection["labels"]
            )
            assert root_selection["registration_disabled"] is True
            assert str(source) not in root_selection["html"]
            assert root_id not in root_selection["html"]
            assert (
                js(
                    """(() => {
                      const controls = Array.from(document.querySelectorAll(
                        '#warehouse-projects select[data-source-root-selector="session"]'
                      ));
                      controls[0].value = '0';
                      controls[0].dispatchEvent(new Event('change', {bubbles:true}));
                      return controls.every(item => item.value === '0') &&
                        !document.querySelector(
                          '#warehouse-projects [data-action="register-javascript-computation-source"]'
                        ).disabled;
                    })()"""
                )
                is True
            )
            assert js(
                "(() => { const block = Array.from(document.querySelectorAll("
                "'#warehouse-projects .warehouse-project-config')).find(item => "
                "item.textContent.includes('Multiply source')); "
                "const button = block && block.querySelector('[data-specimen-project-id]'); "
                "button.click(); return "
                "!document.getElementById('capsule-ingestion-specimen').classList.contains('is-empty') && "
                "document.getElementById('ingestion-specimen-name').textContent.includes('Multiply source') && "
                "document.getElementById('ingestion-specimen-presentation').textContent === '—'; })()"
            )
            before_click = json.loads(
                str(
                    js(
                        """JSON.stringify((() => {
                          const block = Array.from(document.querySelectorAll('#warehouse-projects .warehouse-project-config'))
                            .find(item => item.textContent.includes('Multiply source'));
                          const button = block?.querySelector('[data-action="scan-javascript-computations"]');
                          const statusId = button?.getAttribute('aria-describedby')?.split(' ').pop();
                          return {
                            developer_mode: document.getElementById('warehouse-developer-mode').checked,
                            popover_developer: document.getElementById('capsule-warehouse-popover').classList.contains('developer-mode'),
                            button_text: button?.textContent || '',
                            disabled: button?.disabled ?? true,
                            status: statusId ? document.getElementById(statusId)?.textContent || '' : '',
                            help: document.getElementById('javascript-computation-scan-help')?.textContent || '',
                            described_by_help: (button?.getAttribute('aria-describedby') || '').split(' ').includes('javascript-computation-scan-help'),
                            clicked: button ? (button.click(), true) : false
                          };
                        })())"""
                    )
                )
            )
            assert before_click == {
                "developer_mode": False,
                "popover_developer": False,
                "button_text": "查找可复用的计算功能",
                "disabled": False,
                "status": "已准备好，可以只读查找计算功能。",
                "help": "只读检查这个项目中的 JavaScript 函数。不会运行、修改或构建来源项目，也不会立即发布胶囊。",
                "described_by_help": True,
                "clicked": True,
            }
            disabled_rows = json.loads(
                str(
                    js(
                        """JSON.stringify((() => {
                          function row(name) {
                            const block = Array.from(document.querySelectorAll('#warehouse-projects .warehouse-project-config'))
                              .find(item => item.textContent.includes(name));
                            const button = block?.querySelector('[data-action="scan-javascript-computations"]');
                            const statusId = button?.getAttribute('aria-describedby')?.split(' ').pop();
                            return {
                              disabled: button?.disabled ?? false,
                              status: statusId ? document.getElementById(statusId)?.textContent || '' : '',
                              source_label: block?.querySelector('.warehouse-row > span')?.textContent || ''
                            };
                          }
                          return {
                            pending: row('Pending source'),
                            missing: row('Missing source'),
                            unknown_state: row('Unknown state source'),
                            unknown_type: row('Unknown type source')
                          };
                        })())"""
                    )
                )
            )
            assert disabled_rows == {
                "pending": {
                    "disabled": True,
                    "status": "项目尚未确认，请先确认来源项目。",
                    "source_label": "Pending source · 静态网页来源",
                },
                "missing": {
                    "disabled": True,
                    "status": "来源目录当前不可访问，请重新选择原目录。",
                    "source_label": "Missing source · 静态网页来源",
                },
                "unknown_state": {
                    "disabled": True,
                    "status": "项目状态未知，请刷新项目列表后重试。",
                    "source_label": "Unknown state source · 静态网页来源",
                },
                "unknown_type": {
                    "disabled": True,
                    "status": "来源类型无法识别，请重新发现或登记该项目。",
                    "source_label": "Unknown type source · 未知来源类型",
                },
            }
            wait_js(
                "Array.from(document.querySelectorAll('#warehouse-projects details summary')).some(item => item.textContent.includes('Multiply'))",
                60,
                "multiply_offer",
            )
            offer = json.loads(
                str(
                    js(
                        """JSON.stringify((() => {
                          const block = Array.from(document.querySelectorAll('#warehouse-projects .warehouse-project-config'))
                            .find(item => item.textContent.includes('Multiply source'));
                          const details = Array.from(block?.querySelectorAll('details') || [])
                            .find(item => item.querySelector('summary')?.textContent.includes('Multiply'));
                          if (details) details.open = true;
                          return {
                            found: block?.textContent.includes('找到 2 个可进一步验证的计算功能。') || false,
                            input_1: details?.textContent.includes('输入 1（源码参数：x）') || false,
                            input_2: details?.textContent.includes('输入 2（源码参数：y）') || false,
                            input_help: details?.textContent.includes('这是该输入在新产品中的名称。例如 quantity 可以表示数量。') || false,
                            result_help: details?.textContent.includes('这是计算结果在新产品中的名称。例如 total 可以表示总价。') || false
                          };
                        })())"""
                    )
                )
            )
            assert offer == {
                "found": True,
                "input_1": True,
                "input_2": True,
                "input_help": True,
                "result_help": True,
            }
            wait_js(
                "Array.from(document.querySelectorAll('#warehouse-projects details summary'))"
                ".some(item => item.textContent.includes('Classify'))",
                60,
                "classify_offer",
            )
            witnesses = [
                ("half package urgent", "urgent"),
                ("regular task", "normal"),
            ]
            configured = json.loads(
                str(
                    js(
                        """JSON.stringify((() => {
                  const details = Array.from(document.querySelectorAll(
                    '#warehouse-projects details'
                  )).find(item => item.querySelector('summary')?.textContent.includes('Classify'));
                  if (!details) return {ok:false, reason:'details'};
                  details.open = true;
                  const inputRow = Array.from(details.querySelectorAll('.warehouse-actions'))
                    .find(item => item.textContent.includes('源码参数：question'));
                  const resultRow = Array.from(details.querySelectorAll('.warehouse-actions'))
                    .find(item => item.textContent.includes('输出字段'));
                  const kind = inputRow?.querySelector('select');
                  const numbers = inputRow?.querySelectorAll('input[type="number"]');
                  const field = inputRow?.querySelector('input[type="text"]');
                  const resultField = resultRow?.querySelector('input[type="text"]');
                  const resultEnum = Array.from(resultRow?.querySelectorAll('textarea') || [])
                    .find(item => item.parentElement?.textContent.includes('输出枚举'));
                  if (!kind || !numbers || numbers.length !== 2 || !field ||
                      !resultField || !resultEnum) return {
                        ok:false,
                        reason:'controls',
                        numbers:numbers?.length || 0,
                        input_row:!!inputRow,
                        result_row:!!resultRow,
                        kind:!!kind,
                        field:!!field,
                        result_field:!!resultField,
                        result_enum:!!resultEnum
                      };
                  kind.value = 'string';
                  kind.dispatchEvent(new Event('change', {bubbles:true}));
                  field.value = 'question';
                  numbers[0].value = '1';
                  numbers[1].value = '500';
                  resultField.value = 'knowledge_category';
                  resultEnum.value = 'urgent\\nnormal';
                  resultEnum.dispatchEvent(new Event('input', {bubbles:true}));
                  const witnesses = Array.from(details.querySelectorAll('label'))
                    .filter(item => item.textContent.includes('的验收输入'))
                    .map(item => item.querySelector('input[type="text"]'))
                    .filter(Boolean);
                  if (witnesses.length !== 2) return {
                    ok:false, reason:'witnesses', count:witnesses.length
                  };
                  witnesses[0].value = 'half package urgent';
                  witnesses[1].value = 'regular task';
                  details.querySelector('input[type="checkbox"]').checked = true;
                  details.querySelector(
                    '[data-action="create-javascript-computation-capture"]'
                  ).click();
                  return {ok:true};
                })())"""
                    )
                )
            )
            assert configured == {"ok": True}
            deadline = time.monotonic() + 10
            while not captured_mapping_requests and time.monotonic() < deadline:
                pump()
            assert len(captured_mapping_requests) == 1
            mapping_request = captured_mapping_requests[0]
            assert mapping_request == {
                "schema": "computation_capture_mapping.v5",
                "project_id": str(registered["data"]["project_id"]),
                "offer_id": mapping_request["offer_id"],
                "review_id": None,
                "arguments": [
                    {
                        "parameter_binding_id": mapping_request["arguments"][0][
                            "parameter_binding_id"
                        ],
                        "input_field": "question",
                        "kind": "string",
                        "min_length": 1,
                        "max_length": 500,
                    }
                ],
                "result_field": "knowledge_category",
                "result_enum": ["urgent", "normal"],
                "proof_schema": "source_graph_proof.v3",
                "examples": [
                    {
                        "input": {"question": input_text},
                        "expected": {"knowledge_category": expected},
                    }
                    for input_text, expected in witnesses
                ],
            }
            assert re.fullmatch(
                r"[0-9a-f]{64}",
                str(mapping_request["arguments"][0]["parameter_binding_id"]),
            )
            with service._capsule_store.read_connection() as connection:
                counts = tuple(
                    connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    for table in (
                        "review_items",
                        "capsules",
                        "capsule_versions",
                        "product_capsule_usage",
                    )
                )
            assert counts == (0, 0, 0, 0)
            assert source_snapshot() == source_before
            failed_model_run_id = "run_" + ("f" * 32)
            original_get_intake_run = service.get_intake_run

            def failed_model_listing(_payload=None):
                return {
                    "ok": True,
                    "run_id": failed_model_run_id,
                    "status": "failed",
                }

            def intake_run_with_failed_model(payload=None):
                if (payload == {"run_id": failed_model_run_id}):
                    return {
                        "ok": True,
                        "data": {
                            "run_id": failed_model_run_id,
                            "status": "failed",
                            "error_code": "list_supervision_models_failed",
                        },
                    }
                return original_get_intake_run(payload)

            monkeypatch.setattr(
                service, "list_supervision_models", failed_model_listing
            )
            monkeypatch.setattr(
                service, "get_intake_run", intake_run_with_failed_model
            )
            with service._capsule_store.transaction() as connection:
                connection.execute(
                    "UPDATE source_roots SET status = 'source_missing' "
                    "WHERE root_id = ?",
                    (root_id,),
                )
                service._capsule_store.bump_revision(connection)
            js("document.getElementById('btn-supervision-model-refresh').click(); true")
            pump(0.2)
            wait_js(
                "Array.from(document.querySelectorAll("
                "'#warehouse-projects select[data-source-root-selector=\"session\"]'))"
                ".every(item => item.value === '') && "
                "document.getElementById('warehouse-runs').textContent.includes("
                f"'{failed_model_run_id} · failed') && "
                "document.getElementById('capsule-warehouse-status').textContent.includes("
                "'未改用其他来源')",
                30,
                "missing source root fails closed",
            )
            assert js(
                "document.querySelector("
                "'#warehouse-projects [data-action=\"register-javascript-computation-source\"]'"
                ").disabled"
            )
    finally:
        if window is not None:
            window.close()
            window.deleteLater()
            pump()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            app.processEvents()
        service.close()


def test_static_web_target_review_ui_never_writes_or_calls_confirm_service(
    tmp_path: Path, monkeypatch
) -> None:
    if sys.platform.startswith("linux") and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        pytest.skip("A desktop GUI session is required")
    pytest.importorskip("PySide6.QtWebEngineCore")
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWebEngineCore import QWebEngineProfile

    target = tmp_path / "target-site"
    target.mkdir()
    (target / "index.html").write_text(
        "<!doctype html><html><body><h1>Existing target</h1></body></html>\n",
        encoding="utf-8",
    )

    def target_tree() -> dict[str, tuple[bytes, int]]:
        return {
            path.relative_to(target).as_posix(): (
                path.read_bytes(),
                path.stat().st_mtime_ns,
            )
            for path in target.rglob("*")
            if path.is_file()
        }

    target_before = target_tree()
    snapshot = "a" * 64
    plan_id = "static_web_plan_test"
    profile_data = {
        "schema_version": "static_web_target_profile.v1",
        "target_kind": "static_web",
        "entry_path": "index.html",
        "snapshot_sha256": snapshot,
        "files": [
            {
                "path": "index.html",
                "kind": "text",
                "size_bytes": 72,
                "sha256": "b" * 64,
            }
        ],
        "resources": [],
        "javascript": {
            "schema_version": "source_graph.v1",
            "entry_modules": [],
            "reachable_module_count": 0,
            "graph_sha256": None,
        },
        "checks": [{"name": "stable_snapshot", "passed": True}],
        "permissions": {
            "target_read": True,
            "target_write": False,
            "apply": False,
            "commit": False,
            "store_write": False,
            "network_access": False,
            "model_call": False,
        },
        "source_unchanged": True,
    }
    patch_data = {
        "schema_version": "static_web_target_patch.v1",
        "status": "ready_for_review",
        "plan_id": plan_id,
        "strategy": "static_web_iframe_embed.v1",
        "target": {
            "entry_path": "index.html",
            "snapshot_sha256": snapshot,
            "profile": profile_data,
        },
        "authorization": {
            "mode": "review_patch_only",
            "target_snapshot_sha256": snapshot,
            "usage_scope": {"kind": "general"},
            "usage_scope_match": True,
            "target_project_write": False,
            "apply": False,
            "commit": False,
        },
        "weave_plan": {
            "schema_version": "static_web_weave_plan.v1",
            "plan_id": plan_id,
            "adapter_version": "static_web_iframe_embed.v1",
            "task": "Add quote card",
            "capsules": [
                {
                    "capsule_id": "capsule_presentation",
                    "version_id": "version_presentation_1",
                    "canonical_hash": "d" * 64,
                    "capability_key": "quote",
                    "role_key": "presentation",
                    "variant_key": "default",
                    "capability_kind": "presentation",
                    "usage_scope": {"kind": "general"},
                }
            ],
            "failure_policy": "stop_without_target_write",
            "affected_files": [{"path": "index.html", "operation": "modify"}],
            "validation_steps": [
                "target_snapshot_match",
                "target_path_and_resource_boundaries",
                "capsule_usage_scope",
                "module_native_composition",
                "target_output_collision",
                "target_snapshot_unchanged",
            ],
        },
        "composer": {
            "composer_version": "module_native_formal_product.v1",
            "connections": [],
            "provenance": {},
            "output_mapping": [],
        },
        "changes": [
            {
                "path": "index.html",
                "operation": "modify",
                "origin": "static_web_iframe_embed.v1",
                "before_sha256": "b" * 64,
                "after_sha256": "c" * 64,
                "size_bytes": 96,
                "content_encoding": "utf-8",
                "after_content": "never render this field",
                "diff": "@@ -1 +1 @@\n-Existing target\n+Existing target with capsule\n",
            }
        ],
        "text_unified_diff": "@@ -1 +1 @@\n-Existing target\n+Existing target with capsule\n",
        "evidence": {
            "schema_version": "static_web_target_patch_evidence.v1",
            "status": "passed",
            "checks": [{"name": "target_snapshot_unchanged", "passed": True}],
            "target_project_write": False,
            "product_store_write": False,
            "usage_registration_write": False,
        },
    }

    class Service:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []
            self.analysis_attempts = 0

        def get_initial_state(self) -> dict[str, object]:
            return {
                "skipWelcome": True,
                "sourceBoxes": [],
                "warehouseCapsules": [
                    {
                        "id": "capsule_presentation",
                        "capsule_id": "capsule_presentation",
                        "version_id": "version_presentation_1",
                        "name": "Quote card",
                        "type": "presentation",
                        "role": "presentation",
                        "status": "active",
                        "formal_version": True,
                        "generation_eligible": True,
                        "tags": ["quote"],
                        "preview": "A reusable quote card.",
                    }
                ],
                "history": [],
            }

        def analyze_static_web_target(
            self, payload: dict[str, object]
        ) -> dict[str, object]:
            assert payload == {
                "target_path": str(target),
                "entry_relpath": "index.html",
            }
            self.calls.append(("analyze_static_web_target", payload))
            self.analysis_attempts += 1
            if self.analysis_attempts == 1:
                return {
                    "ok": True,
                    "data": {**profile_data, "target_path": str(target)},
                }
            return {"ok": True, "data": profile_data}

        def generate_static_web_patch(
            self, payload: dict[str, object]
        ) -> dict[str, object]:
            assert payload == {
                "target_path": str(target),
                "entry_relpath": "index.html",
                "task": "Add quote card",
                "capsule_ids": ["capsule_presentation"],
                "selection_mode": "manual",
                "authorization": {
                    "mode": "review_patch_only",
                    "target_snapshot_sha256": snapshot,
                },
            }
            self.calls.append(("generate_static_web_patch", payload))
            return {"ok": True, "data": patch_data}

        def close(self) -> None:
            return None

    class FixedDirectoryDialog:
        @staticmethod
        def getExistingDirectory(*_args, **_kwargs) -> str:
            return str(target)

    from pimos_lite import desktop_reweave_static as desktop

    service = Service()
    qt_parts = desktop.import_qt_webengine()
    QApplication = qt_parts[0]
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    profile = QWebEngineProfile.defaultProfile()
    profile.setCachePath(str(tmp_path / "qweb-cache"))
    profile.setPersistentStoragePath(str(tmp_path / "qweb-storage"))
    window = None

    def pump(seconds: float = 0.03) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.005)

    try:
        with (
            patch.object(
                desktop,
                "import_qt_webengine",
                return_value=(*qt_parts[:5], FixedDirectoryDialog),
            ),
            patch.object(desktop, "ReweaveAppService", return_value=service),
        ):
            window, _bridge = desktop.create_reweave_window()
            page = window.centralWidget().page()
            window.show()

            def js(expression: str, timeout: float = 10.0) -> object:
                result: list[object] = []
                page.runJavaScript(expression, result.append)
                deadline = time.monotonic() + timeout
                while not result and time.monotonic() < deadline:
                    pump()
                if not result:
                    raise TimeoutError("javascript_callback_timeout")
                return result[0]

            def wait_js(expression: str, timeout: float, label: str) -> object:
                deadline = time.monotonic() + timeout
                last: object = None
                while time.monotonic() < deadline:
                    last = js(expression)
                    if last:
                        return last
                    pump(0.08)
                raise TimeoutError(f"{label}:{last!r}")

            screenshot_root = os.environ.get("REWEAVE_GATE23_SCREENSHOT_DIR", "").strip()

            def capture(name: str, width: int = 1440, height: int = 900) -> None:
                window.resize(width, height)
                pump(0.25)
                if not screenshot_root:
                    return
                destination = Path(screenshot_root)
                destination.mkdir(parents=True, exist_ok=True)
                assert window.grab().save(str(destination / f"{name}.png"))

            wait_js(
                "document.readyState === 'complete' && !!window.reweaveBridge && "
                "!document.getElementById('screen-main').classList.contains('hidden')",
                30,
                "desktop_bridge",
            )
            capture("gate3-01-compat-tools")
            js(
                "document.querySelectorAll('.screen').forEach(function(node){"
                "node.classList.add('hidden');});"
                "document.getElementById('screen-welcome').classList.remove('hidden'); true"
            )
            capture("gate3-02-welcome")
            js(
                "document.getElementById('screen-welcome').classList.add('hidden');"
                "document.getElementById('screen-cleaning').classList.remove('hidden');"
                "document.getElementById('cleaning-steps').innerHTML="
                "'<li class=\"done\">读取本地来源边界</li><li class=\"active\">建立只读索引</li>';"
                "document.getElementById('progress-bar').style.width='62%'; true"
            )
            capture("gate3-03-cleaning")
            js(
                "document.getElementById('screen-cleaning').classList.add('hidden');"
                "document.getElementById('screen-main').classList.remove('hidden'); true"
            )
            js("document.getElementById('task-input').value='Keep standalone task'; true")
            assert js(
                "!document.getElementById('btn-compat-target-nav').classList.contains('hidden')"
            )
            js("document.getElementById('btn-compat-target-nav').click(); true")
            wait_js(
                "!document.getElementById('screen-target').classList.contains('hidden')",
                10,
                "target_screen",
            )
            assert js(
                "(() => {"
                "const bar=document.querySelector('#screen-target > .product-plan-bar');"
                "const brand=bar.querySelector('.product-plan-brand').getBoundingClientRect();"
                "const delivery=bar.querySelector('.product-delivery-switch').getBoundingClientRect();"
                "const tools=bar.querySelector('.product-plan-tools').getBoundingClientRect();"
                "const rect=bar.getBoundingClientRect();"
                "const background=getComputedStyle(bar).backgroundColor;"
                "return Math.round(rect.height)===72 && Math.round(brand.left)===24 && "
                "brand.right<delivery.left && delivery.right<tools.left && "
                "background.includes('242, 245, 243') && "
                "bar.scrollWidth===bar.clientWidth;"
                "})()"
            )
            capture("gate3-04-target-select")
            capture("gate3-05-target-select-1100", 1100, 720)
            wait_js(
                "(() => {"
                "const bar=document.querySelector('#screen-target > .product-plan-bar');"
                "const brand=bar.querySelector('.product-plan-brand').getBoundingClientRect();"
                "const rect=bar.getBoundingClientRect();"
                "return Math.round(rect.height)===72 && Math.round(brand.left)===18 && "
                "bar.scrollWidth===bar.clientWidth && "
                "document.documentElement.scrollWidth===window.innerWidth;"
                "})()",
                3,
                "target_shell_1100",
            )
            window.resize(1440, 900)
            pump(0.15)
            js("document.getElementById('btn-select-target').click(); true")
            wait_js(
                "document.getElementById('target-selected-name').textContent.includes('target-site')",
                10,
                "target_selection",
            )
            js("document.getElementById('btn-analyze-target').click(); true")
            wait_js(
                "(() => {"
                "const node=document.getElementById('target-analysis-status');"
                "const text=node&&node.textContent||'';"
                "return node.classList.contains('is-error') && "
                "!!node.querySelector('.target-status-reason') && "
                "!!node.querySelector('.target-status-recovery') && "
                "!text.includes('frontend_contract_rejected') && "
                "(text.includes('前端契约') || text.includes('frontend contract'));"
                "})()",
                10,
                "malformed_profile_rejected",
            )
            capture("gate3-06-target-rejected")
            assert str(target) not in str(js("document.body.textContent"))
            js("document.getElementById('btn-analyze-target').click(); true")
            wait_js(
                "!document.getElementById('target-profile-summary').classList.contains('hidden')",
                10,
                "target_profile",
            )
            wait_js(
                "document.getElementById('screen-target').getAttribute('data-target-stage') === 'compose'",
                10,
                "target_stage_compose",
            )
            wait_js(
                "!!document.querySelector('#target-capsule-cards input[type=checkbox]')",
                10,
                "target_capsule",
            )
            capture("gate3-07-target-compose")
            js(
                "(() => {"
                "const checkbox=document.querySelector('#target-capsule-cards input[type=checkbox]');"
                "checkbox.click();"
                "const task=document.getElementById('target-task');"
                "task.value='Add quote card';"
                "task.dispatchEvent(new Event('input',{bubbles:true}));"
                "return true;})()"
            )
            wait_js(
                "!document.getElementById('btn-generate-target-patch').disabled",
                10,
                "generate_enabled",
            )
            js(
                "(() => {"
                "document.getElementById('btn-generate-target-patch').click();"
                "const task=document.getElementById('target-task');"
                "task.value='Changed while response is pending';"
                "task.dispatchEvent(new Event('input',{bubbles:true}));"
                "return true;})()"
            )
            deadline = time.monotonic() + 10
            while len(service.calls) < 3 and time.monotonic() < deadline:
                pump(0.08)
            assert len(service.calls) == 3
            pump(0.2)
            assert js(
                "document.getElementById('target-review').hasAttribute('hidden')"
            )
            js(
                "(() => {"
                "const task=document.getElementById('target-task');"
                "task.value='Add quote card';"
                "task.dispatchEvent(new Event('input',{bubbles:true}));"
                "document.getElementById('btn-generate-target-patch').click();"
                "return true;})()"
            )
            wait_js(
                "document.getElementById('screen-target').getAttribute('data-target-stage') === 'review' && "
                "!document.getElementById('target-review').hasAttribute('hidden') && "
                "document.getElementById('target-file-diffs').textContent.includes('Existing target') && "
                "document.getElementById('target-evidence-summary').textContent.trim().length > 0",
                10,
                "patch_review",
            )
            capture("gate3-08-target-review")
            assert "never render this field" not in str(
                js("document.getElementById('target-review').textContent")
            )
            assert str(target) not in str(js("document.body.textContent"))
            js("document.getElementById('target-developer-mode').click(); true")
            assert js(
                "document.getElementById('screen-target').classList.contains('developer-mode')"
            )
            capture("gate3-09-target-review-evidence")
            calls_before_confirm = len(service.calls)
            js("document.getElementById('btn-confirm-target-patch').click(); true")
            wait_js(
                "document.getElementById('screen-target').getAttribute('data-target-stage') === 'confirmed' && "
                "document.getElementById('target-confirmation-receipt').textContent.trim().length > 0",
                10,
                "confirmation_receipt",
            )
            capture("gate3-10-target-confirmed")
            js("document.getElementById('btn-target-lang').click(); true")
            capture("gate3-11-target-confirmed-en")
            js("document.getElementById('btn-target-lang').click(); true")
            pump(0.2)
            assert len(service.calls) == calls_before_confirm == 4
            assert [name for name, _payload in service.calls] == [
                "analyze_static_web_target",
                "analyze_static_web_target",
                "generate_static_web_patch",
                "generate_static_web_patch",
            ]
            js("document.getElementById('btn-target-back').click(); true")
            wait_js(
                "!document.getElementById('screen-product-plan').classList.contains('hidden')",
                10,
                "product_screen",
            )
            assert js("document.getElementById('task-input').value") == (
                "Keep standalone task"
            )
            assert target_tree() == target_before
    finally:
        if window is not None:
            window.close()
            window.deleteLater()
            pump()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            app.processEvents()


def test_capsule_warehouse_read_only_scene_with_real_service(
    tmp_path: Path, monkeypatch
) -> None:
    if sys.platform.startswith("linux") and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        pytest.skip("A desktop GUI session is required")
    pytest.importorskip("PySide6.QtWebEngineCore")

    if os.environ.get("REWEAVE_WAREHOUSE_SCENE_CHILD") != "1":
        child_env = os.environ.copy()
        child_env["REWEAVE_WAREHOUSE_SCENE_CHILD"] = "1"
        child_env.pop("PYTEST_ADDOPTS", None)
        child = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                "-q",
                (
                    "tests/test_reweave_phase6_desktop.py::"
                    "test_capsule_warehouse_read_only_scene_with_real_service"
                ),
            ],
            cwd=ROOT,
            env=child_env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert child.returncode == 0, child.stdout + child.stderr
        return

    from PySide6.QtCore import QCoreApplication, QEvent, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWebEngineCore import QWebEngineProfile

    from pimos_lite import desktop_reweave_static as desktop
    from pimos_lite.reweave_app_service import ReweaveAppService
    from pimos_lite.reweave_capsule_store import CapsuleWarehouseStore
    from tests.test_reweave_phase5_generation import _capsule_payload, _seed_capsule

    sources_root = tmp_path / "readonly-sources"
    sources_root.mkdir()
    state_dir = tmp_path / "state"
    monkeypatch.setenv("REWEAVE_STATE_DIR", str(state_dir))
    store = CapsuleWarehouseStore(state_dir / "capsule_warehouse.sqlite3")
    store.initialize()

    absolute_canary = str(sources_root.resolve())
    after_content_canary = "WAREHOUSE_AFTER_CONTENT_MUST_NOT_RENDER"
    snippet_code_canary = "WAREHOUSE_SPECULATIVE_SNIPPET_MUST_NOT_RENDER"
    helper_code_canary = "WAREHOUSE_HELPER_MODULE_MUST_NOT_RENDER"
    missing_version_capsule_id = ""
    missing_version_version_id = ""
    missing_identity_capsule_id = ""
    projection_variants: dict[str, str] = {}

    class ObservedService(ReweaveAppService):
        def get_initial_state(self) -> dict[str, object]:
            result = super().get_initial_state()
            capsules = result.get("warehouseCapsules")
            if isinstance(capsules, list):
                for capsule in capsules:
                    if not isinstance(capsule, dict):
                        continue
                    capsule_id = str(capsule.get("capsule_id") or "")
                    capsule["snippet"] = {
                        "kind": "verified_core_code",
                        "verified": True,
                        "validation_status": "passed",
                        "preview": snippet_code_canary,
                        "language": "js",
                    }
                    if capsule_id == missing_version_capsule_id:
                        capsule["source_id"] = "formal-source-without-exact-version"
                        capsule["source"] = "Versionless formal source"
                    elif capsule_id == missing_identity_capsule_id:
                        capsule["source"] = "Display-only source"
            return result

        def get_capsule_detail(
            self, payload: dict[str, object] | None = None
        ) -> dict[str, object]:
            result = super().get_capsule_detail(payload)
            detail = result.get("data") if isinstance(result, dict) else None
            if isinstance(detail, dict):
                detail["after_content"] = after_content_canary
                versions = detail.get("versions")
                if isinstance(versions, list):
                    for version in versions:
                        if not isinstance(version, dict):
                            continue
                        validation = version.get("validation_result_json")
                        if isinstance(validation, dict):
                            validation["absolute_path_canary"] = absolute_canary
                requested_id = str((payload or {}).get("capsule_id") or "")
                if requested_id == missing_version_capsule_id and isinstance(versions, list):
                    wrong_version = dict(versions[0]) if versions else {}
                    wrong_version_id = missing_version_version_id + "-other"
                    wrong_version["version_id"] = wrong_version_id
                    detail["versions"] = [wrong_version]
                    detail["sources"] = [
                        {
                            "version_id": wrong_version_id,
                            "project_id": "untrusted-other-version",
                            "source_identity": "project:untrusted-other-version",
                            "source_kind": "project",
                            "source_relpath": "index.html",
                            "relationship": "exact",
                        }
                    ]
            return result

        def get_capsule_core_code_projection(
            self, payload: dict[str, object] | None = None
        ) -> dict[str, object]:
            result = super().get_capsule_core_code_projection(payload)
            projection = result.get("data") if isinstance(result, dict) else None
            capsule_id = str((payload or {}).get("capsule_id") or "")
            variant = projection_variants.get(capsule_id)
            if not isinstance(projection, dict) or not variant:
                return result
            core_code = projection.get("core_code")
            if variant == "wrong_schema":
                projection["schema_version"] = "capsule_core_code_projection.invalid"
            elif variant == "wrong_version":
                projection["version_id"] = str(projection.get("version_id") or "") + "-other"
            elif variant == "wrong_project":
                projection["project_id"] = "project-other"
                projection["source_identity"] = "project:project-other"
            elif variant == "absolute_path" and isinstance(core_code, dict):
                core_code["logical_path"] = absolute_canary + "/entry.js"
            elif variant == "helper_module" and isinstance(core_code, dict):
                core_code["logical_path"] = "helper.js"
                core_code["content"] = helper_code_canary
                core_code["sha256"] = hashlib.sha256(
                    helper_code_canary.encode("utf-8")
                ).hexdigest()
            return result

    service = ObservedService(capsule_store=store)
    project_rows: list[tuple[Path, str, str]] = []
    deterministic_source_ids = [
        "00000000-0000-4000-8000-000000000001",
        "00000000-0000-4000-8000-000000000101",
        "00000000-0000-4000-8000-000000000002",
        "00000000-0000-4000-8000-000000000102",
        "00000000-0000-4000-8000-000000000003",
        "00000000-0000-4000-8000-000000000103",
    ]
    with patch(
        "pimos_lite.reweave_capsule_intake._uuid",
        side_effect=deterministic_source_ids,
    ):
        for slug, display_name in (
            ("source-a", "Readonly source A"),
            ("source-b", "Readonly source B"),
            ("source-c", "Readonly source C"),
        ):
            source = sources_root / slug
            source.mkdir()
            (source / "index.html").write_text(
                f'<main data-capsule-root="{slug}"></main>\n', encoding="utf-8"
            )
            root = service._capsule_intake.bind_source_root(
                source, root_kind="single_project"
            )
            discovered = service._capsule_intake.discover_projects(str(root["root_id"]))
            project = service._capsule_intake.confirm_project(
                str(discovered[0]["project_id"])
            )
            project_id = str(project["project_id"])
            with store.transaction() as connection:
                connection.execute(
                    "UPDATE projects SET display_name = ? WHERE project_id = ?",
                    (display_name, project_id),
                )
                store.bump_revision(connection)
            project_rows.append((source, display_name, project_id))

    capsule_rows: list[tuple[str, str, int]] = []
    successful_payload = _capsule_payload("presentation")
    successful_payload["javascript_modules"].append(  # type: ignore[union-attr]
        {
            "path": "helper.js",
            "source": f'export const helperCanary = "{helper_code_canary}";\n',
        }
    )
    successful_entry_content = str(
        successful_payload["javascript_modules"][0]["source"]  # type: ignore[index]
    )
    for project_index, kind, suffix, capability_key in (
        (0, "presentation", "alpha_presentation", "alpha_presentation"),
        (0, "interaction", "alpha_interaction", "alpha_interaction"),
        (1, "presentation", "beta_presentation", "beta_presentation"),
        (1, "computation", "beta_computation", "beta_computation"),
        (2, "interaction", "gamma_interaction", "gamma_interaction"),
        (2, "computation", "gamma_computation", "gamma_computation"),
    ):
        payload = None
        if suffix == "alpha_presentation":
            payload = successful_payload
        elif kind == "computation":
            payload = _capsule_payload(kind)
            payload["input_contract"]["properties"]["unit_price"] = {  # type: ignore[index]
                "type": "integer",
                "minimum": 1,
            }
        capsule_id, version_id = _seed_capsule(
            store,
            kind,
            capability_key=capability_key,
            suffix=suffix,
            payload=payload,
        )
        capsule_rows.append((capsule_id, version_id, project_index))
    projection_variants.update(
        {
            capsule_rows[1][0]: "wrong_schema",
            capsule_rows[2][0]: "wrong_version",
            capsule_rows[3][0]: "wrong_project",
            capsule_rows[4][0]: "absolute_path",
            capsule_rows[5][0]: "helper_module",
        }
    )
    missing_version_capsule_id, missing_version_version_id = _seed_capsule(
        store,
        "presentation",
        capability_key="missing_version_capability",
        suffix="missing_version",
    )
    missing_identity_capsule_id, _missing_identity_version_id = _seed_capsule(
        store,
        "interaction",
        capability_key="missing_identity_capability",
        suffix="missing_identity",
    )

    with store.transaction() as connection:
        for index, (_capsule_id, version_id, project_index) in enumerate(capsule_rows):
            source, _display_name, project_id = project_rows[project_index]
            source_hash = hashlib.sha256((source / "index.html").read_bytes()).hexdigest()
            canonical_hash = str(
                connection.execute(
                    "SELECT canonical_hash FROM capsule_versions WHERE version_id = ?",
                    (version_id,),
                ).fetchone()[0]
            )
            connection.execute(
                "INSERT INTO capsule_sources "
                "(source_link_id, version_id, project_id, source_identity, source_kind, "
                "source_relpath, source_hash, candidate_canonical_hash, relationship, read_at) "
                "VALUES (?, ?, ?, ?, 'project', 'index.html', ?, ?, 'exact', ?)",
                (
                    f"warehouse-scene-source-{index}",
                    version_id,
                    project_id,
                    f"project:{project_id}",
                    source_hash,
                    canonical_hash,
                    "2026-07-19T00:00:00Z",
                ),
            )
        store.bump_revision(connection)

    initial_state = service.get_initial_state()
    assert len(initial_state["warehouseCapsules"]) == 8
    assert len(initial_state["capsuleIngestionV1"]["projects"]) == 3

    untouched_target = tmp_path / "untouched-user-target"
    untouched_target.mkdir()
    (untouched_target / "sentinel.txt").write_text(
        "core-code projection must not touch this target\n", encoding="utf-8"
    )

    def warehouse_table_state() -> dict[str, object]:
        tables = (
            "capsules",
            "capsule_versions",
            "capsule_sources",
            "product_capsule_usage",
        )
        with store.read_connection() as connection:
            rows = [
                {
                    "table": table,
                    "rows": [
                        dict(row)
                        for row in connection.execute(
                            f"SELECT * FROM {table} ORDER BY rowid"
                        )
                    ],
                }
                for table in tables
            ]
        return {"tables": list(tables), "sha256": _canonical_sha256(rows)}

    qt_parts = desktop.import_qt_webengine()
    QApplication = qt_parts[0]
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    profile = QWebEngineProfile.defaultProfile()
    profile.setCachePath(str(tmp_path / "qweb-cache"))
    profile.setPersistentStoragePath(str(tmp_path / "qweb-storage"))
    window = None

    def pump(seconds: float = 0.03) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.005)

    try:
        with patch.object(desktop, "ReweaveAppService", return_value=service):
            window, bridge = desktop.create_reweave_window()
            view = window.centralWidget()
            page = view.page()
            window.show()

            def js(expression: str, timeout: float = 15) -> object:
                result: list[object] = []
                page.runJavaScript(expression, result.append)
                deadline = time.monotonic() + timeout
                while not result and time.monotonic() < deadline:
                    pump()
                if not result:
                    raise TimeoutError("javascript_callback_timeout")
                return result[0]

            def wait_js(expression: str, timeout: float, label: str) -> object:
                deadline = time.monotonic() + timeout
                last: object = None
                while time.monotonic() < deadline:
                    last = js(expression)
                    if last:
                        return last
                    pump(0.08)
                raise TimeoutError(f"{label}:{last!r}")

            def warehouse_state() -> dict[str, object]:
                return json.loads(
                    str(js("JSON.stringify(window.ReweavePrototype.getState().warehouse)"))
                )

            screenshot_root = os.environ.get("REWEAVE_GATE2_SCREENSHOT_DIR", "").strip()

            def capture(name: str, width: int = 1440, height: int = 900) -> None:
                if not screenshot_root:
                    return
                destination = Path(screenshot_root)
                destination.mkdir(parents=True, exist_ok=True)
                window.resize(width, height)
                pump(0.25)
                assert window.grab().save(str(destination / f"{name}.png"))

            wait_js(
                "document.readyState === 'complete' && !!window.reweaveBridge && "
                "!document.getElementById('screen-product-plan').classList.contains('hidden')",
                30,
                "default product screen",
            )
            js("document.getElementById('btn-product-plan-back').click(); true")
            wait_js(
                "!document.getElementById('screen-main').classList.contains('hidden')",
                10,
                "compatibility tools",
            )
            bridge_calls: list[str] = []
            projection_bridge_payloads: list[dict[str, object]] = []
            original_phase4_call = bridge._phase4_call

            def observe_phase4_call(method_name: str, payload_json: str = "") -> str:
                bridge_calls.append(method_name)
                if method_name == "get_capsule_core_code_projection":
                    parsed_payload = json.loads(payload_json)
                    assert isinstance(parsed_payload, dict)
                    projection_bridge_payloads.append(parsed_payload)
                return original_phase4_call(method_name, payload_json)

            bridge._phase4_call = observe_phase4_call

            source_before = _tree_state(sources_root)
            target_before = _tree_state(untouched_target)
            revision_before = store.current_revision()
            tables_before = warehouse_table_state()
            usage_before = _usage_state(store)
            products_before = _tree_state(state_dir / "products")

            js(
                "document.getElementById('btn-capsule-warehouse').focus(); "
                "document.getElementById('btn-capsule-warehouse').click(); true"
            )
            wait_js(
                "window.ReweavePrototype.getState().warehouse.source_group_count === 5 && "
                "!window.ReweavePrototype.getState().warehouse.source_relations_loading && "
                "document.querySelectorAll('#warehouse-scene-world [data-project-key]').length === 5",
                30,
                "source project overview",
            )
            assert warehouse_state()["view"] == "overview"
            assert "canvas" not in warehouse_state()
            assert projection_bridge_payloads == []
            assert js("document.getElementById('warehouse-scene-links') === null")
            assert js("document.querySelectorAll('#warehouse-scene-nodes [data-project-key]').length") == 3
            assert js("document.querySelectorAll('#warehouse-unresolved-nodes [data-project-key]').length") == 2
            assert js("!document.getElementById('warehouse-unresolved-shelf').classList.contains('hidden')")
            assert js(
                "getComputedStyle(document.getElementById('warehouse-scene-canvas')).overflowY === 'visible' && "
                "document.querySelectorAll('.warehouse-source-toggle').length === 3 && "
                "document.querySelectorAll('.warehouse-source-accordion.is-open').length === 0 && "
                "document.querySelectorAll('.warehouse-capsule-rack-grid:not([hidden])').length === 0"
            )
            overview_keys = json.loads(
                str(
                    js(
                        "JSON.stringify(Array.from(document.querySelectorAll("
                        "'#warehouse-scene-world [data-project-key]')).map(function (node) { "
                        "return node.dataset.projectKey; }))"
                    )
                )
            )
            assert len(overview_keys) == len(set(overview_keys)) == 5
            overview_text = str(js("document.getElementById('warehouse-scene-world').textContent"))
            for expected_label in (
                "Readonly source A",
                "Readonly source B",
                "Readonly source C",
                "Missing Version Capability",
                "Missing Identity Capability",
            ):
                assert expected_label in overview_text
            capture("dev-fixture-01-source-accordion")
            capture("dev-fixture-02-source-accordion-1100", 1100, 720)
            window.resize(1440, 900)
            pump(0.15)

            window.activateWindow()
            view.setFocus()
            pump()
            key_target = view.focusProxy() or view
            assert js(
                "(() => { const node = Array.from(document.querySelectorAll("
                "'#warehouse-scene-nodes [data-project-key]')).find(function (item) { "
                "return item.textContent.includes('Readonly source A'); }); "
                "node.focus(); return document.activeElement === node; })()"
            )
            QTest.keyClick(key_target, Qt.Key.Key_Return)
            wait_js(
                "window.ReweavePrototype.getState().warehouse.view === 'project' && "
                "document.querySelectorAll('.warehouse-source-accordion.is-open').length === 1 && "
                "document.querySelectorAll('.warehouse-capsule-rack-grid:not([hidden]) "
                "[data-capsule-id]').length === 2",
                10,
                "project capsule rack",
            )
            formal_project_state = warehouse_state()
            assert formal_project_state["project_id"] == project_rows[0][2]
            assert projection_bridge_payloads == []
            assert js(
                "document.querySelector('.warehouse-source-toggle.is-open').textContent.includes("
                + json.dumps("Readonly source A")
                + ") && "
                "document.querySelectorAll('.warehouse-capsule-rack-grid:not([hidden]) "
                ".warehouse-capability-lane').length === 3"
            )
            capture("dev-fixture-03-independent-capsule-rack")

            selected_id = capsule_rows[0][0]
            assert js(
                "(() => { const node = document.querySelector('#warehouse-scene-nodes "
                "[data-capsule-id=" + json.dumps(selected_id) + "]'); "
                "node.focus(); return document.activeElement === node; })()"
            )
            assert js(
                "(() => { const node = document.querySelector('#warehouse-scene-nodes "
                "[data-capsule-id=" + json.dumps(selected_id) + "]'); "
                "const unit = node.closest('.warehouse-capsule-unit'); "
                "return node.getAttribute('aria-expanded') === 'false' && "
                "unit.querySelector('.warehouse-capsule-contract').hidden && "
                "unit.querySelector('.warehouse-source-slot').dataset.evidenceThread === 'verified' && "
                "!!unit.querySelector('.warehouse-source-path'); })()"
            )
            js(
                "document.querySelector('#warehouse-scene-nodes [data-capsule-id="
                + json.dumps(selected_id)
                + "]').click(); true"
            )
            wait_js(
                "window.ReweavePrototype.getState().warehouse.view === 'project' && "
                "window.ReweavePrototype.getState().warehouse.capsule_id === "
                + json.dumps(selected_id),
                10,
                "formal capsule contract",
            )
            contract_dom = json.loads(
                str(
                    js(
                        "JSON.stringify((() => { const node = document.querySelector("
                        "'#warehouse-scene-nodes [data-capsule-id="
                        + json.dumps(selected_id)
                        + "]'); const unit = node && node.closest('.warehouse-capsule-unit'); "
                        "const panel = unit && unit.querySelector('.warehouse-capsule-contract'); "
                        "return { unit_open: !!unit && unit.classList.contains('is-open'), "
                        "panel_hidden: !panel || panel.hidden, panel_text: panel ? panel.textContent : '' }; })())"
                    )
                )
            )
            assert contract_dom["unit_open"] is True
            assert contract_dom["panel_hidden"] is False
            assert projection_bridge_payloads == []
            assert "render" in contract_dom["panel_text"]
            assert "total" in contract_dom["panel_text"]
            assert "unit_price=10" not in contract_dom["panel_text"]
            capture("dev-fixture-04-formal-contract")
            js(
                "(() => { const unit = document.querySelector('#warehouse-scene-world [data-capsule-id="
                + json.dumps(selected_id)
                + "]').closest('.warehouse-capsule-unit'); "
                "const path = unit.querySelector('.warehouse-source-path'); "
                "path.focus(); path.click(); return true; })()"
            )
            wait_js(
                "window.ReweavePrototype.getState().warehouse.view === 'code' && "
                "window.ReweavePrototype.getState().warehouse.verified_core_code === true",
                10,
                "verified capsule code page",
            )
            simple_state = warehouse_state()
            assert simple_state["capsule_id"] == selected_id
            assert simple_state["verified_core_code"] is True
            assert projection_bridge_payloads == [
                {
                    "capsule_id": selected_id,
                    "version_id": capsule_rows[0][1],
                    "project_id": project_rows[0][2],
                }
            ]
            assert js(
                "!document.getElementById('warehouse-core-code').classList.contains('hidden') && "
                "document.getElementById('warehouse-core-code-empty').classList.contains('hidden') && "
                "document.getElementById('warehouse-core-code').textContent === "
                + json.dumps(successful_entry_content) + " && "
                "!document.body.textContent.includes(" + json.dumps(snippet_code_canary) + ") && "
                "!document.body.textContent.includes(" + json.dumps(helper_code_canary) + ")"
            )
            capture("dev-fixture-05-code")

            js("document.getElementById('warehouse-code-developer-mode').click(); true")
            developer_state = warehouse_state()
            assert developer_state["capsule_id"] == simple_state["capsule_id"]
            assert developer_state["developer_mode"] is True
            assert js(
                "!document.getElementById('warehouse-developer-details').classList.contains('hidden') && "
                "!document.getElementById('btn-open-capsule-ingestion').classList.contains('hidden')"
            )
            assert selected_id in str(js("document.getElementById('warehouse-developer-evidence').textContent"))
            formal_evidence = json.loads(
                str(js("document.getElementById('warehouse-developer-evidence').textContent"))
            )
            assert formal_evidence["source"]["project_id"] == project_rows[0][2]
            assert (
                formal_evidence["source"]["source_identity_status"]
                == "formal_exact_version_source"
            )
            assert len(formal_evidence["source"]["relationships"]) == 1
            assert formal_evidence["capsule"]["version_id"] == capsule_rows[0][1]
            assert formal_evidence["core_code_projection"]["schema_version"] == (
                "capsule_core_code_projection.v1"
            )
            assert formal_evidence["core_code_projection"]["logical_path"] == (
                "presentation.js"
            )
            assert re.fullmatch(
                r"[0-9a-f]{64}", formal_evidence["core_code_projection"]["sha256"]
            )
            assert "content" not in formal_evidence["core_code_projection"]
            assert js(
                "!document.documentElement.outerHTML.includes(" + json.dumps(absolute_canary) + ") && "
                "!document.body.textContent.includes(" + json.dumps(after_content_canary) + ") && "
                "!document.body.textContent.includes(" + json.dumps(snippet_code_canary) + ") && "
                "!document.body.textContent.includes(" + json.dumps(helper_code_canary) + ")"
            )
            capture("dev-fixture-06-code-evidence")

            js("document.getElementById('btn-warehouse-code-zoom-in').click(); true")
            assert warehouse_state()["code_scale"] > 1
            js("document.getElementById('btn-warehouse-scene-back').click(); true")
            wait_js(
                "window.ReweavePrototype.getState().warehouse.view === 'project'",
                10,
                "return to project",
            )
            wait_js(
                "document.activeElement && document.activeElement.dataset.nodeKey === "
                + json.dumps("path:" + selected_id)
                + " && !document.querySelector('#warehouse-scene-world [data-capsule-id="
                + json.dumps(selected_id)
                + "]').closest('.warehouse-capsule-unit')"
                ".querySelector('.warehouse-capsule-contract').hidden",
                10,
                "contract and path focus restored",
            )

            js("document.getElementById('btn-warehouse-scene-back').click(); true")
            wait_js(
                "window.ReweavePrototype.getState().warehouse.view === 'overview'",
                10,
                "return to overview",
            )
            restored_keys = json.loads(
                str(
                    js(
                        "JSON.stringify(Array.from(document.querySelectorAll("
                        "'#warehouse-scene-world [data-project-key]')).map(function (node) { "
                        "return node.dataset.projectKey; }))"
                    )
                )
            )
            assert restored_keys == overview_keys
            no_result_before = warehouse_state()
            no_result_nodes = js(
                "JSON.stringify(Array.from(document.querySelectorAll("
                "'#warehouse-scene-world [data-node-key]')).map(function (node) { "
                "return node.dataset.nodeKey; }))"
            )
            js(
                "(() => { const input = document.getElementById('warehouse-scene-query'); "
                "input.value = 'definitely-no-formal-source'; "
                "input.dispatchEvent(new Event('input', {bubbles:true})); "
                "input.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', bubbles:true})); "
                "return true; })()"
            )
            assert warehouse_state()["search_match_count"] == 0
            assert warehouse_state()["view"] == no_result_before["view"]
            assert js(
                "JSON.stringify(Array.from(document.querySelectorAll("
                "'#warehouse-scene-world [data-node-key]')).map(function (node) { "
                "return node.dataset.nodeKey; }))"
            ) == no_result_nodes
            assert js(
                "document.getElementById('warehouse-search-status').textContent.includes("
                + json.dumps("当前来源项目和焦点保持不变")
                + ")"
            )
            capture("dev-fixture-07-search-no-result")
            js(
                "(() => { const input = document.getElementById('warehouse-scene-query'); "
                "input.value = ''; input.dispatchEvent(new Event('input', {bubbles:true})); return true; })()"
            )
            js(
                "(() => { const input = document.getElementById('warehouse-scene-query'); "
                "input.value = 'Readonly source B'; input.dispatchEvent(new Event('input', {bubbles:true})); "
                "input.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', bubbles:true})); return true; })()"
            )
            wait_js(
                "document.activeElement && document.activeElement.dataset.projectKey",
                10,
                "project search focus",
            )
            js(
                "(() => { const input = document.getElementById('warehouse-scene-query'); "
                "input.value = ''; input.dispatchEvent(new Event('input', {bubbles:true})); return true; })()"
            )

            js(
                "(() => { const input = document.getElementById('warehouse-scene-query'); "
                "input.value = 'Beta Computation'; input.dispatchEvent(new Event('input', {bubbles:true})); "
                "input.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', bubbles:true})); return true; })()"
            )
            wait_js(
                "window.ReweavePrototype.getState().warehouse.view === 'project' && "
                "document.activeElement && document.activeElement.dataset.capsuleId",
                10,
                "capsule search focus",
            )
            js(
                "(() => { const input = document.getElementById('warehouse-scene-query'); "
                "input.value = ''; input.dispatchEvent(new Event('input', {bubbles:true})); return true; })()"
            )
            assert warehouse_state()["view"] == "overview"

            def assert_failed_projection(
                project_label: str,
                capsule_row: tuple[str, str, int],
                variant: str,
            ) -> None:
                capsule_id, version_id, project_index = capsule_row
                before_calls = len(projection_bridge_payloads)
                assert projection_variants[capsule_id] == variant
                assert js(
                    "(() => { const node = Array.from(document.querySelectorAll("
                    "'#warehouse-scene-nodes [data-project-key]')).find(function (item) { "
                    "return item.textContent.includes(" + json.dumps(project_label) + "); }); "
                    "node.click(); return true; })()"
                )
                wait_js(
                    "window.ReweavePrototype.getState().warehouse.view === 'project' && "
                    "window.ReweavePrototype.getState().warehouse.project_id === "
                    + json.dumps(project_rows[project_index][2]),
                    10,
                    variant + " project",
                )
                assert js(
                    "(() => { const node = document.querySelector('#warehouse-scene-nodes "
                    "[data-capsule-id=" + json.dumps(capsule_id) + "]'); "
                    "node.click(); return true; })()"
                )
                wait_js(
                    "window.ReweavePrototype.getState().warehouse.view === 'project' && "
                    "window.ReweavePrototype.getState().warehouse.capsule_id === "
                    + json.dumps(capsule_id),
                    10,
                    variant + " contract",
                )
                assert len(projection_bridge_payloads) == before_calls
                contract_text = str(
                    js(
                        "document.querySelector('#warehouse-scene-world [data-capsule-id="
                        + json.dumps(capsule_id)
                        + "]').closest('.warehouse-capsule-unit')"
                        ".querySelector('.warehouse-capsule-contract').textContent"
                    )
                )
                if "interaction" in capsule_id:
                    assert "mount" in contract_text
                    assert "calculate_requested(quantity)" in contract_text
                elif "computation" in capsule_id:
                    assert "compute" in contract_text
                    assert "quantity" in contract_text
                    assert "unit_price" in contract_text
                    assert "total" in contract_text
                else:
                    assert "render" in contract_text
                    assert "total" in contract_text
                assert "unit_price=10" not in contract_text
                assert "10 元" not in contract_text
                assert js(
                    "(() => { const unit = document.querySelector('#warehouse-scene-world [data-capsule-id="
                    + json.dumps(capsule_id)
                    + "]').closest('.warehouse-capsule-unit'); "
                    "const path = unit.querySelector('.warehouse-source-path'); "
                    "path.focus(); path.click(); return true; })()"
                )
                wait_js(
                    "window.ReweavePrototype.getState().warehouse.view === 'code' && "
                    "window.ReweavePrototype.getState().warehouse.capsule_id === "
                    + json.dumps(capsule_id),
                    10,
                    variant + " code page",
                )
                deadline = time.monotonic() + 10
                while (
                    len(projection_bridge_payloads) != before_calls + 1
                    and time.monotonic() < deadline
                ):
                    pump(0.03)
                assert len(projection_bridge_payloads) == before_calls + 1
                pump(0.15)
                failed_state = warehouse_state()
                assert failed_state["verified_core_code"] is False
                assert js(
                    "document.getElementById('warehouse-evidence-validation').textContent === "
                    + json.dumps("证据不可用")
                    + " && document.getElementById('warehouse-code-proof').classList.contains('is-error')"
                )
                assert projection_bridge_payloads[-1] == {
                    "capsule_id": capsule_id,
                    "version_id": version_id,
                    "project_id": project_rows[project_index][2],
                }
                assert js(
                    "document.getElementById('warehouse-core-code').classList.contains('hidden') && "
                    "!document.getElementById('warehouse-core-code-empty').classList.contains('hidden') && "
                    "document.getElementById('warehouse-core-code').textContent === '' && "
                    "!document.documentElement.outerHTML.includes(" + json.dumps(absolute_canary) + ") && "
                    "!document.body.textContent.includes(" + json.dumps(helper_code_canary) + ") && "
                    "!document.body.textContent.includes(" + json.dumps(after_content_canary) + ") && "
                    "!document.body.textContent.includes(" + json.dumps(snippet_code_canary) + ")"
                )
                failed_evidence = json.loads(
                    str(js("document.getElementById('warehouse-developer-evidence').textContent"))
                )
                assert failed_evidence["capsule"]["capsule_id"] == capsule_id
                assert failed_evidence["capsule"]["version_id"] == version_id
                assert failed_evidence["source"]["project_id"] == project_rows[project_index][2]
                assert failed_evidence["core_code_projection"] is None
                js("document.getElementById('btn-warehouse-scene-back').click(); true")
                wait_js(
                    "window.ReweavePrototype.getState().warehouse.view === 'project'",
                    10,
                    "return from " + variant + " code",
                )
                js("document.getElementById('btn-warehouse-scene-back').click(); true")
                wait_js(
                    "window.ReweavePrototype.getState().warehouse.view === 'overview'",
                    10,
                    "return from " + variant + " project",
                )

            for failed_row, variant in zip(
                capsule_rows[1:],
                (
                    "wrong_schema",
                    "wrong_version",
                    "wrong_project",
                    "absolute_path",
                    "helper_module",
                ),
                strict=True,
            ):
                assert_failed_projection(
                    project_rows[failed_row[2]][1], failed_row, variant
                )

            fallback_projection_calls = len(projection_bridge_payloads)
            assert js(
                "(() => { const entry = Array.from(document.querySelectorAll("
                "'#warehouse-unresolved-nodes .warehouse-unresolved-entry')).find(function (item) { "
                "return item.textContent.includes('Missing Version Capability'); }); "
                "const capsule = entry && entry.querySelector('[data-capsule-id]'); "
                "capsule.focus(); capsule.click(); return !!capsule; })()"
            )
            wait_js(
                "window.ReweavePrototype.getState().warehouse.view === 'project' && "
                "window.ReweavePrototype.getState().warehouse.project_key === "
                + json.dumps("unresolved:" + missing_version_capsule_id),
                10,
                "missing exact version contract",
            )
            missing_version_group_state = warehouse_state()
            assert missing_version_group_state["project_id"] is None
            assert js(
                "(() => { const unit = document.querySelector('#warehouse-scene-world [data-capsule-id="
                + json.dumps(missing_version_capsule_id)
                + "]').closest('.warehouse-capsule-unit'); return "
                "unit.textContent.includes('缺少当前精确版本的项目来源关系') && "
                "unit.querySelector('.warehouse-source-path') === null && "
                "unit.querySelector('.warehouse-source-slot').dataset.evidenceThread === 'error' && "
                "!unit.querySelector('.warehouse-capsule-contract').hidden; })()"
            )
            assert warehouse_state()["capsule_id"] == missing_version_capsule_id
            assert warehouse_state()["verified_core_code"] is False
            assert len(projection_bridge_payloads) == fallback_projection_calls
            js("document.getElementById('btn-warehouse-scene-back').click(); true")
            wait_js(
                "window.ReweavePrototype.getState().warehouse.view === 'overview'",
                10,
                "return from missing exact version contract",
            )

            assert js(
                "(() => { const entry = Array.from(document.querySelectorAll("
                "'#warehouse-unresolved-nodes .warehouse-unresolved-entry')).find(function (item) { "
                "return item.textContent.includes('Missing Identity Capability'); }); "
                "const capsule = entry && entry.querySelector('[data-capsule-id]'); "
                "capsule.focus(); capsule.click(); return !!capsule; })()"
            )
            wait_js(
                "window.ReweavePrototype.getState().warehouse.view === 'project' && "
                "window.ReweavePrototype.getState().warehouse.project_key === "
                + json.dumps("unresolved:" + missing_identity_capsule_id),
                10,
                "missing formal source identity contract",
            )
            missing_identity_group_state = warehouse_state()
            assert missing_identity_group_state["project_id"] is None
            assert js(
                "(() => { const unit = document.querySelector('#warehouse-scene-world [data-capsule-id="
                + json.dumps(missing_identity_capsule_id)
                + "]').closest('.warehouse-capsule-unit'); return "
                "unit.textContent.includes('缺少当前精确版本的项目来源关系') && "
                "unit.querySelector('.warehouse-source-path') === null && "
                "!unit.querySelector('.warehouse-capsule-contract').hidden; })()"
            )
            assert warehouse_state()["verified_core_code"] is False
            assert len(projection_bridge_payloads) == fallback_projection_calls
            js("document.getElementById('btn-warehouse-scene-back').click(); true")
            wait_js(
                "window.ReweavePrototype.getState().warehouse.view === 'overview'",
                10,
                "return from missing formal source identity contract",
            )

            assert js("document.getElementById('btn-warehouse-zoom-in') === null")
            assert js("document.getElementById('btn-warehouse-zoom-reset') === null")
            js("document.getElementById('btn-warehouse-scene-back').click(); true")
            wait_js(
                "!document.getElementById('screen-main').classList.contains('hidden') && "
                "document.activeElement === document.getElementById('btn-capsule-warehouse')",
                10,
                "main entry focus restored",
            )

            assert bridge_calls == ["get_capsule_detail"] * 8 + [
                "get_capsule_core_code_projection"
            ] * 6
            assert _tree_state(sources_root) == source_before
            assert _tree_state(untouched_target) == target_before
            assert store.current_revision() == revision_before
            assert warehouse_table_state() == tables_before
            assert _usage_state(store) == usage_before
            assert _tree_state(state_dir / "products") == products_before
            js("document.getElementById('btn-capsule-warehouse').click(); true")
            wait_js(
                "window.ReweavePrototype.getState().warehouse.view === 'overview' && "
                "!document.getElementById('screen-capsule-warehouse').classList.contains('hidden')",
                10,
                "source rack before intake",
            )
            js(
                "(() => { const rack = document.getElementById('warehouse-scene-canvas'); "
                "rack.scrollTop = rack.scrollHeight; "
                "window.scrollTo(0, document.documentElement.scrollHeight); return true; })()"
            )
            capture("dev-fixture-08-insufficient-source-shelf")
            js(
                "document.getElementById('btn-open-capsule-ingestion').focus(); "
                "document.getElementById('btn-open-capsule-ingestion').click(); true"
            )
            wait_js(
                "!document.getElementById('screen-capsule-ingestion').classList.contains('hidden') && "
                "document.querySelector('[data-ingestion-panel=\"source\"]').classList.contains('is-active') && "
                "document.getElementById('screen-capsule-ingestion').scrollTop === 0 && "
                "window.scrollY === 0",
                10,
                "source intake",
            )
            assert js(
                "document.getElementById('capsule-ingestion-specimen').classList.contains('is-empty') && "
                "document.getElementById('ingestion-tab-source').getAttribute('aria-selected') === 'true' && "
                "!document.getElementById('ingestion-panel-source').hidden"
            )
            QTest.keyClick(key_target, Qt.Key.Key_Right)
            wait_js(
                "document.getElementById('ingestion-tab-supervision').getAttribute('aria-selected') === 'true' && "
                "!document.getElementById('ingestion-panel-supervision').hidden && "
                "document.getElementById('ingestion-panel-source').hidden",
                10,
                "intake tab arrow navigation",
            )
            for station in ("supervision", "review", "formal", "source"):
                js(
                    "document.querySelector('[data-ingestion-station="
                    + json.dumps(station)
                    + "]').click(); true"
                )
                wait_js(
                    "document.querySelectorAll('[data-ingestion-panel].is-active').length === 1 && "
                    "document.querySelector('[data-ingestion-panel="
                    + json.dumps(station)
                    + "]').classList.contains('is-active') && "
                    "document.querySelector('[data-ingestion-station="
                    + json.dumps(station)
                    + "]').getAttribute('aria-selected') === 'true' && "
                    "!document.querySelector('[data-ingestion-panel="
                    + json.dumps(station)
                    + "]').hidden && "
                    "document.activeElement.dataset.ingestionStation === "
                    + json.dumps(station),
                    10,
                    station + " intake station",
                )
            js(
                "document.querySelector('[data-ingestion-station=\"formal\"]').click();"
                "document.querySelector('#warehouse-capability-groups details').open=true;"
                "document.querySelector('.warehouse-capsule-seal.is-management').click();true"
            )
            wait_js(
                "document.querySelector('.warehouse-capsule-seal.is-management')"
                ".getAttribute('aria-expanded') === 'true' && "
                "document.querySelector('.ingestion-formal-detail').dataset.loaded === 'true' && "
                "!document.querySelector('.ingestion-formal-detail').hidden",
                10,
                "formal capability read-only detail",
            )
            assert js(
                "document.querySelector('.ingestion-formal-detail').textContent.includes('入口') && "
                "!document.querySelector('.ingestion-formal-detail').textContent.includes('unit_price=10')"
            )
            js("document.querySelector('[data-ingestion-station=\"source\"]').click();true")
            pump(1)
            capture("dev-fixture-09-source-intake")
            js("document.getElementById('btn-ingestion-back').click(); true")
            wait_js(
                "!document.getElementById('screen-capsule-warehouse').classList.contains('hidden') && "
                "window.ReweavePrototype.getState().warehouse.view === 'overview' && "
                "document.activeElement === document.getElementById('btn-open-capsule-ingestion')",
                10,
                "return from empty-specimen intake",
            )
            assert js(
                "(() => { const node = Array.from(document.querySelectorAll("
                "'#warehouse-scene-nodes [data-project-key]')).find(item => "
                "item.textContent.includes('Readonly source A')); node.click(); return true; })()"
            )
            wait_js(
                "window.ReweavePrototype.getState().warehouse.view === 'project'",
                10,
                "specimen source project",
            )
            js(
                "document.querySelector('#warehouse-scene-nodes [data-capsule-id="
                + json.dumps(selected_id)
                + "]').click(); true"
            )
            wait_js(
                "window.ReweavePrototype.getState().warehouse.view === 'project' && "
                "window.ReweavePrototype.getState().warehouse.capsule_id === "
                + json.dumps(selected_id),
                10,
                "specimen capsule contract",
            )
            js(
                "(() => { const unit = document.querySelector('#warehouse-scene-world [data-capsule-id="
                + json.dumps(selected_id)
                + "]').closest('.warehouse-capsule-unit'); "
                "unit.querySelector('.warehouse-source-path').click(); return true; })()"
            )
            wait_js(
                "window.ReweavePrototype.getState().warehouse.view === 'code' && "
                "window.ReweavePrototype.getState().warehouse.verified_core_code === true",
                10,
                "specimen capsule code",
            )
            js(
                "document.getElementById('btn-open-capsule-ingestion').focus(); "
                "document.getElementById('btn-open-capsule-ingestion').click(); true"
            )
            wait_js(
                "!document.getElementById('capsule-ingestion-specimen').classList.contains('is-empty') && "
                "document.getElementById('ingestion-specimen-name').textContent.includes('Readonly source A') && "
                "document.getElementById('ingestion-specimen-presentation').textContent === '1'",
                10,
                "source specimen carried from code",
            )
            for station in ("supervision", "review", "formal", "source"):
                js(
                    "document.querySelector('[data-ingestion-station="
                    + json.dumps(station)
                    + "]').click(); true"
                )
                assert js(
                    "document.getElementById('ingestion-specimen-name').textContent.includes("
                    + json.dumps("Readonly source A")
                    + ")"
                )
            capture("dev-fixture-10-source-context-intake")
            js("document.getElementById('btn-ingestion-back').click(); true")
            wait_js(
                "window.ReweavePrototype.getState().warehouse.view === 'code' && "
                "document.activeElement === document.getElementById('btn-open-capsule-ingestion')",
                10,
                "return from source specimen intake",
            )
            assert _tree_state(sources_root) == source_before
            assert _tree_state(untouched_target) == target_before
            assert store.current_revision() == revision_before
            assert warehouse_table_state() == tables_before
            assert _usage_state(store) == usage_before
            assert _tree_state(state_dir / "products") == products_before

            full_initial_state = service.get_initial_state

            def single_source_initial_state() -> dict[str, object]:
                result = full_initial_state()
                allowed = {capsule_rows[0][0], capsule_rows[1][0]}
                result["warehouseCapsules"] = [
                    capsule
                    for capsule in result["warehouseCapsules"]
                    if capsule.get("capsule_id") in allowed
                ]
                return result

            service.get_initial_state = single_source_initial_state
            js(
                "document.getElementById('btn-open-capsule-ingestion').click();"
                "document.getElementById('btn-supervision-model-refresh').click(); true"
            )
            wait_js(
                "window.ReweavePrototype.getState().warehouse.source_group_count === 1",
                10,
                "single source refresh",
            )
            js("document.getElementById('btn-ingestion-back').click(); true")
            wait_js(
                "window.ReweavePrototype.getState().warehouse.view === 'code'",
                10,
                "return to code after single source refresh",
            )
            for expected_view in ("project", "overview"):
                js("document.getElementById('btn-warehouse-scene-back').click(); true")
                wait_js(
                    "window.ReweavePrototype.getState().warehouse.view === "
                    + json.dumps(expected_view),
                    10,
                    "return through " + expected_view,
                )
            js("document.getElementById('btn-warehouse-scene-back').click(); true")
            wait_js(
                "!document.getElementById('screen-main').classList.contains('hidden')",
                10,
                "leave single source warehouse",
            )
            js("document.getElementById('btn-capsule-warehouse').click(); true")
            wait_js(
                "window.ReweavePrototype.getState().warehouse.view === 'project' && "
                "document.querySelectorAll('.warehouse-source-accordion.is-open').length === 1",
                10,
                "single source auto expanded",
            )
            capture("dev-fixture-11-single-source-auto-expanded")
            js("document.querySelector('.warehouse-source-toggle.is-open').click(); true")
            wait_js(
                "window.ReweavePrototype.getState().warehouse.view === 'overview'",
                10,
                "single source user collapse",
            )
            js("document.getElementById('btn-warehouse-lang').click(); true")
            assert warehouse_state()["view"] == "overview"
            assert js(
                "document.querySelectorAll('.warehouse-source-accordion.is-open').length === 0"
            )
            assert _tree_state(sources_root) == source_before
            assert _tree_state(untouched_target) == target_before
            assert store.current_revision() == revision_before
            assert warehouse_table_state() == tables_before
            assert _usage_state(store) == usage_before
            assert _tree_state(state_dir / "products") == products_before
    finally:
        if window is not None:
            window.close()
            window.deleteLater()
            pump()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            app.processEvents()


def _run_product_capability_gap_qweb_case(
    tmp_path: Path,
    monkeypatch,
    *,
    time_fixture: bool,
    enum_fixture: bool = False,
    replan_fixture: bool = False,
    multi_field_replan: bool = False,
    start_error_code: str | None = None,
    preauthorized: bool = False,
) -> None:
    pytest.importorskip("PySide6.QtWebEngineCore")
    if sys.platform.startswith("linux") and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        pytest.skip("A desktop GUI session is required")

    import copy

    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWebEngineCore import QWebEngineProfile

    from pimos_lite import desktop_reweave_static as desktop
    from pimos_lite.reweave_app_service import ReweaveAppService
    from pimos_lite.reweave_capsule_store import CapsuleWarehouseStore
    from tests.test_reweave_phase5_generation import _NoLegacyEngine

    plan_token = "plan_token_" + "7" * 48
    plan_digest = "8" * 64
    projection_digest = "9" * 64
    if enum_fixture:
        screenshot_prefix = "capability-gap-finite-enum"
        product_name = "确定性测试夹具：有限枚举能力准备"
        goal = "DETERMINISTIC_TEST_FIXTURE_NOT_FORMAL_WAREHOUSE_STATE"
        summary = "缺少一个确定性的有限枚举状态分类。"
        gap_title = "有限状态分类"
        gap_reason = "正式测试目录只有输入与展示能力。"
        capability_key = "workflow_state_classification"
        capability_group_display_name = "工作流状态分类"
        input_properties = {
            "important": {"type": "boolean"},
            "urgent": {"type": "boolean"},
        }
        output_properties = {
            "priority": {
                "type": "string",
                "min_length": 4,
                "max_length": 8,
                "enum": ["delegate", "do_now", "drop", "schedule"],
            }
        }
        adapter_contract_version = "computation_adapter.v4"
        result_field = "priority"
        passthrough_fields = []
        warehouse_revision = 67
        published_role_order = []
    elif multi_field_replan:
        replan_fixture = True
        screenshot_prefix = "candidate-acceptance-formal-scalars"
        product_name = "正式标量验收夹具"
        goal = "DETERMINISTIC_TEST_FIXTURE_NOT_FORMAL_WAREHOUSE_STATE"
        summary = "验证计划页正式标量验收值。"
        gap_title = "正式标量验收"
        gap_reason = "测试计划页对正式标量契约的精确提交。"
        capability_key = "rectangle_area_calculation"
        capability_group_display_name = "矩形面积计算"
        input_properties = {
            "count": {
                "type": "integer",
                "minimum": 1,
                "maximum": 3,
                "enum": [1, 2, 3],
            },
            "enabled": {"type": "boolean"},
            "label": {
                "type": "string",
                "min_length": 0,
                "max_length": 8,
                "enum": ["", "  keep  "],
            },
            "price": {
                "type": "decimal",
                "minimum": "0",
                "maximum": "999999999999999999.99",
                "max_scale": 2,
            },
        }
        output_properties = {
            "amount": {
                "type": "decimal",
                "minimum": "0",
                "maximum": "999999999999999999.99",
                "max_scale": 2,
            },
            "approved": {"type": "boolean"},
            "note": {"type": "string", "min_length": 0, "max_length": 8},
            "rank": {
                "type": "integer",
                "minimum": 1,
                "maximum": 3,
                "enum": [1, 2, 3],
            },
        }
        adapter_contract_version = "computation_adapter.v2"
        result_field = "amount"
        passthrough_fields = []
        warehouse_revision = 63
        published_role_order = [
            "rectangle_dimensions_input",
            "rectangle_area",
            "rectangle_area_result",
        ]
    elif replan_fixture:
        screenshot_prefix = "capability-gap-year-replan"
        product_name = "年数换算能力准备"
        goal = "创建一个本地年数换算工具。"
        summary = "缺少一个确定性的整数年数换算。"
        gap_title = "年数转换为月数"
        gap_reason = "正式能力原先无法把年数转换为月数。"
        capability_key = "year_month_conversion"
        capability_group_display_name = "年数换算为月数"
        input_properties = {
            "years": {"type": "integer", "minimum": 0, "maximum": 100}
        }
        output_properties = {
            "months": {"type": "integer", "minimum": 0, "maximum": 1200}
        }
        adapter_contract_version = "computation_adapter.v2"
        result_field = "months"
        passthrough_fields = []
        warehouse_revision = 55
        published_role_order = [
            "years_input",
            "years_to_months",
            "months_result",
        ]
    elif time_fixture:
        screenshot_prefix = "capability-gap-time"
        product_name = "确定性测试夹具：时间换算能力准备"
        goal = "确定性测试夹具：补齐整数小时到分钟的换算能力。"
        summary = "缺少一个确定性的整数时间换算。"
        gap_title = "小时转换为分钟"
        gap_reason = "正式能力无法把小时转换为分钟。"
        capability_key = "time_unit_conversion"
        capability_group_display_name = "时间单位换算"
        input_properties = {
            "hours": {"type": "integer", "minimum": 0, "maximum": 8760}
        }
        output_properties = {
            "minutes": {
                "type": "integer",
                "minimum": 0,
                "maximum": 525600,
            }
        }
        adapter_contract_version = "computation_adapter.v2"
        result_field = "minutes"
        passthrough_fields = []
        warehouse_revision = 42
        published_role_order = [
            "hours_input",
            "hours_to_minutes",
            "minutes_to_seconds",
            "seconds_result",
        ]
    else:
        screenshot_prefix = "capability-gap"
        product_name = "报价规则能力准备"
        goal = "创建一个缺少报价规则的本地报价工具。"
        summary = "缺少一个确定性的报价规则计算。"
        gap_title = "报价规则计算"
        gap_reason = "正式能力无法把数量转换为完整报价输入。"
        capability_key = "quote_calculation"
        capability_group_display_name = "参数化报价结果"
        input_properties = {
            "quantity": {"type": "integer", "minimum": 1, "maximum": 10}
        }
        output_properties = {
            "quantity": {"type": "integer", "minimum": 1, "maximum": 10},
            "unit_price": {
                "type": "integer",
                "minimum": 0,
                "maximum": 1000,
            },
        }
        adapter_contract_version = "computation_adapter.v3"
        result_field = "unit_price"
        passthrough_fields = ["quantity"]
        warehouse_revision = 41
        published_role_order = [
            "parameterized_quote_input",
            "quantity_discount_policy",
            "parameterized_quote_total",
            "parameterized_quote_result",
        ]
    gap_id = "gap_" + "a" * 20
    plan = {
        "schema_version": "product_plan.v2",
        "product_name": product_name,
        "canonical_digest": plan_digest,
        "sections": [
            {
                "section_id": "frontend",
                "applicability": "not_applicable",
                "summary": "沿用现有输入与展示能力。",
                "work_items": [],
                "gaps": [],
            },
            {
                "section_id": "backend",
                "applicability": "applicable",
                "summary": summary,
                    "work_items": [],
                    "gaps": [
                        {
                            "gap_id": gap_id,
                        "title": gap_title,
                        "reason": gap_reason,
                        "requirement_ids": ["requirement_" + "b" * 20],
                    }
                ],
            },
            {
                "section_id": "data",
                "applicability": "not_applicable",
                "summary": "不需要独立数据层。",
                "work_items": [],
                "gaps": [],
            },
            {
                "section_id": "infrastructure",
                "applicability": "not_applicable",
                "summary": "不需要独立基础设施层。",
                "work_items": [],
                "gaps": [],
            },
        ],
    }
    projection = {
        "projection_digest": projection_digest,
        "capability_key": capability_key,
        "capability_group_display_name": capability_group_display_name,
        "capability_kind": "computation",
        "slot": "before_existing_computation",
        "input_contract": {
            "schema": "data_contract.v1",
            "type": "object",
            "properties": input_properties,
            "required": list(input_properties),
            "additional_properties": False,
        },
        "output_contract": {
            "schema": "data_contract.v1",
            "type": "object",
            "properties": output_properties,
            "required": list(output_properties),
            "additional_properties": False,
        },
        "adapter_contract_version": adapter_contract_version,
        "result_field": result_field,
        "passthrough_fields": passthrough_fields,
        "warehouse_revision": warehouse_revision,
        "catalog_digest": "c" * 64,
    }
    if enum_fixture:
        projection.update(
            schema_version="capability_gap_projection.v2",
            proof_schema="source_graph_proof.v2",
            result_enum=["delegate", "do_now", "drop", "schedule"],
        )

    class Planner:
        def __init__(self) -> None:
            self.decisions: list[dict[str, object]] = []
            self.ambiguous = False
            self.stale = False
            self.authorization: dict[str, object] | None = None
            self.prepare_calls = 0
            self.replan_calls = 0
            self.replan_status = "available"
            self.successor_token = "plan_token_" + "6" * 48
            self.source_run: dict[str, object] | None = None
            self.review_outcome: dict[str, object] | None = None

        def _workspace(self) -> dict[str, object]:
            current = copy.deepcopy(self.decisions[-1]) if self.decisions else None
            return {
                "plan_token": plan_token,
                "goal": goal,
                "status": "plan_review",
                "question_set": None,
                "plan": copy.deepcopy(plan),
                "plan_diff": None,
                "confirmation": None,
                "capability_gaps": [
                    {
                        **copy.deepcopy(plan["sections"][1]["gaps"][0]),
                        "status": (
                            "capability_gap_boundary_ambiguous"
                            if self.ambiguous
                            else (
                                "capability_gap_projection_stale"
                                if self.stale or replan_fixture
                                else "available"
                            )
                        ),
                        "projection": (
                            None if self.ambiguous else copy.deepcopy(projection)
                        ),
                        "decision_history": copy.deepcopy(self.decisions),
                        "current_decision": current,
                        "source_proposal_authorization": copy.deepcopy(
                            self.authorization
                        ),
                        "source_proposal_request": (
                            {
                                "request_digest": "e" * 64,
                                "prompt_version": (
                                    "capability_source_proposal_prompt.v4"
                                    if enum_fixture
                                    else "capability_source_proposal_prompt.v1"
                                ),
                                "output_protocol_version": (
                                    "capability_source_proposal.v2"
                                    if enum_fixture
                                    else "capability_source_proposal.v1"
                                ),
                                "status": "waiting_model_authorization",
                            }
                            if self.authorization is not None
                            else None
                        ),
                        "source_proposal_run": (
                            {
                                **copy.deepcopy(self.source_run),
                                "review_outcome": copy.deepcopy(
                                    self.review_outcome
                                ),
                            }
                            if self.source_run is not None
                            else None
                        ),
                    }
                ],
                "capability_replan": (
                    {
                        "schema_version": "capability_replan_handoff.v1",
                        "status": self.replan_status,
                        "source_gap_id": gap_id,
                        "projection_digest": projection_digest,
                        "role_order": published_role_order,
                    }
                    if replan_fixture
                    or (
                        self.review_outcome is not None
                        and self.review_outcome.get("status") == "published"
                    )
                    else None
                ),
            }

        def _successor_workspace(self) -> dict[str, object]:
            if multi_field_replan:
                return {
                    "plan_token": self.successor_token,
                    "goal": goal,
                    "status": "plan_review",
                    "question_set": None,
                    "plan": {
                        **copy.deepcopy(plan),
                        "canonical_digest": "6" * 64,
                        "sections": [
                            {
                                "section_id": "frontend",
                                "applicability": "applicable",
                                "summary": "矩形尺寸输入与面积结果。",
                                "gaps": [],
                                "work_items": [
                                    {
                                        "work_item_id": "work_item_dimensions",
                                        "title": "rectangle_dimensions_input",
                                        "description": "接收整数宽度和高度。",
                                        "requirement_ids": ["requirement_rectangle"],
                                        "depends_on": [],
                                        "delivery_wave": 1,
                                        "acceptance_intent": "验证唯一面积计算事件。",
                                        "capsule_bindings": [
                                            {
                                                "capsule_id": "capsule_dimensions",
                                                "version_id": "version_dimensions",
                                                "canonical_hash": "1" * 64,
                                                "display_name": "矩形尺寸输入",
                                                "capability_kind": "interaction",
                                            }
                                        ],
                                    },
                                    {
                                        "work_item_id": "work_item_result",
                                        "title": "rectangle_area_result",
                                        "description": "只展示最终面积。",
                                        "requirement_ids": ["requirement_rectangle"],
                                        "depends_on": ["work_item_area"],
                                        "delivery_wave": 3,
                                        "acceptance_intent": "验证最终面积展示。",
                                        "capsule_bindings": [
                                            {
                                                "capsule_id": "capsule_result",
                                                "version_id": "version_result",
                                                "canonical_hash": "3" * 64,
                                                "display_name": "矩形面积结果",
                                                "capability_kind": "presentation",
                                            }
                                        ],
                                    },
                                ],
                            },
                            {
                                "section_id": "backend",
                                "applicability": "applicable",
                                "summary": "宽度乘以高度的确定性计算。",
                                "gaps": [],
                                "work_items": [
                                    {
                                        "work_item_id": "work_item_area",
                                        "title": "rectangle_area",
                                        "description": "计算矩形面积。",
                                        "requirement_ids": ["requirement_rectangle"],
                                        "depends_on": ["work_item_dimensions"],
                                        "delivery_wave": 2,
                                        "acceptance_intent": "验证整数乘法。",
                                        "capsule_bindings": [
                                            {
                                                "capsule_id": "capsule_area",
                                                "version_id": "version_area",
                                                "canonical_hash": "2" * 64,
                                                "display_name": "矩形面积计算",
                                                "capability_kind": "computation",
                                            }
                                        ],
                                    }
                                ],
                            },
                            {
                                "section_id": "data",
                                "applicability": "not_applicable",
                                "summary": "不需要独立数据层。",
                                "gaps": [],
                                "work_items": [],
                            },
                            {
                                "section_id": "infrastructure",
                                "applicability": "not_applicable",
                                "summary": "不需要独立基础设施层。",
                                "gaps": [],
                                "work_items": [],
                            },
                        ],
                    },
                    "plan_diff": None,
                    "confirmation": None,
                    "capability_gaps": [],
                    "capability_replan": {
                        "schema_version": "capability_replan_handoff.v1",
                        "status": "started",
                        "source_gap_id": gap_id,
                        "successor_plan_token": self.successor_token,
                        "handoff_digest": "5" * 64,
                        "role_order": published_role_order,
                        "acceptance_suggestions": [
                            {
                                "input": {
                                    "count": 1,
                                    "enabled": True,
                                    "label": "",
                                    "price": "1.2",
                                },
                                "expected_output": {
                                    "amount": "1.2",
                                    "approved": True,
                                    "note": "",
                                    "rank": 1,
                                },
                            },
                        ],
                    },
                }
            successor_plan = copy.deepcopy(plan)
            successor_plan["canonical_digest"] = "6" * 64
            successor_plan["sections"][1]["gaps"] = []
            successor_plan["sections"][0]["applicability"] = "applicable"
            successor_plan["sections"][0]["summary"] = "年数输入与月数结果。"
            successor_plan["sections"][1]["summary"] = "年数到月数的确定性换算。"
            successor_plan["sections"][0]["work_items"] = [
                {
                    "work_item_id": "work_item_years_input",
                    "title": "years_input",
                    "description": "接收整数年数。",
                    "requirement_ids": ["requirement_year_conversion"],
                    "depends_on": [],
                    "delivery_wave": 1,
                    "acceptance_intent": "验证唯一换算事件。",
                    "capsule_bindings": [
                        {
                            "capsule_id": "capsule_years_input",
                            "version_id": "version_years_input",
                            "canonical_hash": "1" * 64,
                            "display_name": "年数输入",
                            "capability_kind": "interaction",
                        }
                    ],
                },
                {
                    "work_item_id": "work_item_months_result",
                    "title": "months_result",
                    "description": "只展示最终月数。",
                    "requirement_ids": ["requirement_year_conversion"],
                    "depends_on": ["work_item_years_to_months"],
                    "delivery_wave": 3,
                    "acceptance_intent": "验证最终月数展示。",
                    "capsule_bindings": [
                        {
                            "capsule_id": "capsule_months_result",
                            "version_id": "version_months_result",
                            "canonical_hash": "3" * 64,
                            "display_name": "月数结果",
                            "capability_kind": "presentation",
                        }
                    ],
                },
            ]
            successor_plan["sections"][1]["work_items"] = [
                {
                    "work_item_id": "work_item_years_to_months",
                    "title": "years_to_months",
                    "description": "将年数乘以 12 转换为月数。",
                    "requirement_ids": ["requirement_year_conversion"],
                    "depends_on": ["work_item_years_input"],
                    "delivery_wave": 2,
                    "acceptance_intent": "验证整数年数换算。",
                    "capsule_bindings": [
                        {
                            "capsule_id": "capsule_years_to_months",
                            "version_id": "version_years_to_months",
                            "canonical_hash": "2" * 64,
                            "display_name": "年数转月数",
                            "capability_kind": "computation",
                        }
                    ],
                }
            ]
            return {
                "plan_token": self.successor_token,
                "goal": goal,
                "status": "plan_review",
                "question_set": None,
                "plan": successor_plan,
                "plan_diff": None,
                "confirmation": None,
                "capability_gaps": [],
                "capability_replan": {
                    "schema_version": "capability_replan_handoff.v1",
                    "status": "started",
                    "source_gap_id": gap_id,
                    "successor_plan_token": self.successor_token,
                    "handoff_digest": "5" * 64,
                    "role_order": [
                        "years_input",
                        "years_to_months",
                        "months_result",
                    ],
                    "acceptance_suggestions": [
                        {
                            "input": {"years": 1},
                            "expected_output": {"months": 12},
                        },
                        {
                            "input": {"years": 2},
                            "expected_output": {"months": 24},
                        },
                        {
                            "input": {"years": 10},
                            "expected_output": {"months": 120},
                        },
                    ],
                },
            }

        def initial_state(self):
            return {
                "ok": True,
                "data": {
                    "schema_version": "product_planning_state.v1",
                    "available": True,
                    "selected_model": {
                        "name": "fixture",
                        "digest": "d" * 64,
                        "parameter_count": 1,
                        "parameter_size": "1B",
                    },
                    "workspaces": [
                        {
                            "plan_token": plan_token,
                            "display_name": plan["product_name"],
                            "status": "plan_review",
                            "updated_at": "2026-08-03T00:00:00Z",
                            "plan_version": 1,
                            "confirmed": False,
                        }
                    ],
                    "candidate_generation_available": False,
                    "product_generation_performed": False,
                },
            }

        def get(self, *_args):
            return {"ok": True, "data": self._workspace()}

        def _workspace_by_token(self, _token):
            return {"plan": copy.deepcopy(plan)}

        @staticmethod
        def _read_capability_replan_handoff(_workspace):
            return None

        def start_capability_replan(self, *_args, **_kwargs):
            self.replan_calls += 1
            return {"ok": True, "data": self._successor_workspace()}

        def record_capability_gap_decision(
            self,
            _token,
            _plan_digest,
            _projection_digest,
            previous_digest,
            decision,
            behavior,
            reason,
            acceptance_cases,
            _catalog,
        ):
            expected = (
                self.decisions[-1]["canonical_digest"]
                if self.decisions
                else None
            )
            assert previous_digest == expected
            row = {
                "sequence": len(self.decisions) + 1,
                "decision": decision,
                "behavior_intent": behavior,
                "reason": reason,
                "acceptance_cases": copy.deepcopy(acceptance_cases),
                "canonical_digest": str(len(self.decisions) + 1) * 64,
            }
            self.decisions.append(row)
            return {"ok": True, "data": self._workspace()}

        def prepare_capability_source_proposal(
            self,
            _token,
            _plan_digest,
            _projection_digest,
            decision_digest,
            _catalog,
        ):
            assert self.decisions[-1]["canonical_digest"] == decision_digest
            self.prepare_calls += 1
            self.authorization = {
                "schema_version": (
                    "capability_source_proposal_authorization.v2"
                    if enum_fixture
                    else "capability_source_proposal_authorization.v1"
                ),
                "authorization_digest": "f" * 64,
                "locked_at": "2026-08-05T00:00:00.000Z",
                "status": "locked",
            }
            return {"ok": True, "data": self._workspace()}

    state_dir = tmp_path / "state"
    monkeypatch.setenv("REWEAVE_STATE_DIR", str(state_dir))
    store = CapsuleWarehouseStore(state_dir / "capsule_warehouse.sqlite3")
    planner = Planner()
    if preauthorized:
        planner.decisions = [
            {
                "sequence": 1,
                "decision": "authorize",
                "behavior_intent": "执行冻结的整数计算。",
                "reason": None,
                "acceptance_cases": [
                    {
                        "input": {"quantity": 5},
                        "expected_output": {
                            "quantity": 5,
                            "unit_price": 80,
                        },
                    }
                ],
                "canonical_digest": "1" * 64,
            }
        ]
        planner.authorization = {
            "authorization_digest": "f" * 64,
            "locked_at": "2026-08-05T00:00:00.000Z",
            "status": "locked",
        }
    service = ReweaveAppService(_NoLegacyEngine(), capsule_store=store)
    service._product_planner = planner
    if replan_fixture:
        capsule_details = (
            {
            "capsule_dimensions": {
                "version_id": "version_dimensions",
                "output_contract_json": {
                    "schema": "event_outputs.v1",
                    "events": {
                        "area_requested": {
                            "schema": "data_contract.v1",
                            "type": "object",
                            "properties": copy.deepcopy(input_properties),
                            "required": sorted(input_properties),
                            "additional_properties": False,
                        }
                    },
                },
            },
            "capsule_area": {
                "version_id": "version_area",
                "input_contract_json": {
                    "schema": "data_contract.v1",
                    "type": "object",
                    "properties": copy.deepcopy(input_properties),
                    "required": sorted(input_properties),
                    "additional_properties": False,
                },
                "output_contract_json": {
                    "schema": "data_contract.v1",
                    "type": "object",
                    "properties": copy.deepcopy(output_properties),
                    "required": sorted(output_properties),
                    "additional_properties": False,
                },
            },
            }
            if multi_field_replan
            else {
                "capsule_years_input": {
                    "version_id": "version_years_input",
                    "output_contract_json": {
                        "schema": "event_outputs.v1",
                        "events": {
                            "conversion_requested": {
                                "schema": "data_contract.v1",
                                "type": "object",
                                "properties": copy.deepcopy(input_properties),
                                "required": ["years"],
                                "additional_properties": False,
                            }
                        },
                    },
                },
                "capsule_years_to_months": {
                    "version_id": "version_years_to_months",
                    "input_contract_json": {
                        "schema": "data_contract.v1",
                        "type": "object",
                        "properties": copy.deepcopy(input_properties),
                        "required": ["years"],
                        "additional_properties": False,
                    },
                    "output_contract_json": {
                        "schema": "data_contract.v1",
                        "type": "object",
                        "properties": copy.deepcopy(output_properties),
                        "required": ["months"],
                        "additional_properties": False,
                    },
                },
            }
        )
        service.get_capsule_detail = lambda payload: {
            "ok": True,
            "data": {
                "versions": [
                    copy.deepcopy(capsule_details[payload["capsule_id"]])
                ]
            },
        }
    review_id = "review_" + "4" * 32
    decoy_review_id = "review_" + "5" * 32
    start_calls: list[dict[str, object]] = []

    def start_source_proposal(payload):
        start_calls.append(copy.deepcopy(payload))
        assert set(payload) == {
            "plan_token",
            "plan_digest",
            "projection_digest",
            "authorization_digest",
        }
        if start_error_code:
            return {
                "ok": False,
                "error": {"code": start_error_code},
            }
        planner.source_run = {
            "schema": "capability_source_proposal_run.v1",
            "run_id": "run_" + "3" * 32,
            "status": "review_required",
            "stage": "admission",
            "review_id": review_id,
        }
        return {
            "ok": True,
            "run_id": planner.source_run["run_id"],
            "status": "queued",
        }

    def get_source_run(payload):
        if (
            planner.source_run is None
            or payload.get("run_id") != planner.source_run["run_id"]
        ):
            return {
                "ok": False,
                "error": {"code": "intake_run_not_found"},
            }
        return {"ok": True, "data": copy.deepcopy(planner.source_run)}

    def review_item(current_review_id):
        return {
            "review_id": current_review_id,
            "candidate_status": "review_required",
            "display_name": (
                gap_title if current_review_id == review_id else "其他待复核能力"
            ),
            "capability_kind": "computation",
            "allowed_decisions": ["publish_general", "reject"],
            "candidate": {
                "candidate_origin": "deterministic_computation_adapter",
                "adapter_contract_version": adapter_contract_version,
                "resume_contract": (
                    "resubmit_ephemeral_capture.v2"
                    if adapter_contract_version == "computation_adapter.v3"
                    else "resubmit_ephemeral_capture.v1"
                ),
                "frozen_review_admission": {
                    "schema": "frozen_stage3_review_admission.v2",
                    "projection_digest": projection_digest,
                    "authorized_capability_key": capability_key,
                },
            },
        }

    def decide_source_review(payload):
        assert payload["review_id"] == review_id
        if payload["decision"] == "publish_general":
            assert payload["capability_key"] == capability_key
            assert payload["display_name"] == capability_group_display_name
            assert payload["role_key"] == (
                "hours_to_minutes"
                if time_fixture
                else "quantity_discount_policy"
            )
            assert payload["variant_key"] == "default"
            planner.review_outcome = {
                "status": "published",
                "review_id": review_id,
                "capsule_id": "capsule_" + "6" * 20,
                "version_id": "version_" + "7" * 20,
                "canonical_hash": "8" * 64,
            }
        else:
            assert payload == {
                "review_id": review_id,
                "decision": "reject",
            }
            planner.review_outcome = {
                "status": "rejected",
                "review_id": review_id,
            }
        return {"ok": True, "data": copy.deepcopy(planner.review_outcome)}

    service.start_product_capability_source_proposal = start_source_proposal
    service.get_intake_run = get_source_run
    service.list_review_items = lambda _payload=None: {
        "ok": True,
        "data": {
            "items": [
                review_item(decoy_review_id),
                review_item(review_id),
            ]
        },
    }
    service.list_capability_groups = lambda _payload=None: {
        "ok": True,
        "data": {
            "groups": [
                {
                    "capability_key": capability_key,
                    "display_name": capability_group_display_name,
                    "capsules": [],
                }
            ]
        },
    }
    service.list_backups = lambda _payload=None: {
        "ok": True,
        "data": {"backups": []},
    }
    service.list_supervision_models = lambda _payload=None: {
        "ok": True,
        "data": {"models": []},
    }
    service.decide_review_item = decide_source_review
    service._capability_source_proposal_review_outcome = (
        lambda current_review_id: copy.deepcopy(
            planner.review_outcome
            or {
                "status": "review_required",
                "review_id": current_review_id,
            }
        )
    )
    if replan_fixture:
        service._resolve_product_capability_replan = (
            lambda *_args: (
                {"publication_revision": 57},
                {"members": []},
                copy.deepcopy(projection),
            )
        )
    submitted_acceptance: list[dict[str, object]] = []
    if multi_field_replan:
        service.confirm_product_plan = lambda _payload: {
            "ok": True,
            "data": planner._successor_workspace(),
        }

        def confirm_acceptance(payload):
            submitted_acceptance.append(copy.deepcopy(payload))
            return {"ok": True, "data": {"canonical_digest": "a" * 64}}

        service.confirm_product_candidate_acceptance = confirm_acceptance
        service.start_confirmed_product_candidate = lambda _payload: {
            "ok": False,
            "error": {"code": "candidate_start_intentionally_stopped"},
        }
    qt_parts = desktop.import_qt_webengine()
    QApplication = qt_parts[0]
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    profile = QWebEngineProfile.defaultProfile()
    profile.setCachePath(str(tmp_path / "qweb-cache"))
    profile.setPersistentStoragePath(str(tmp_path / "qweb-storage"))
    window = None

    def pump(seconds: float = 0.03) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.005)

    try:
        with patch.object(desktop, "ReweaveAppService", return_value=service):
            window, bridge = desktop.create_reweave_window()
            window._reweave_bridge = bridge
            page = window.centralWidget().page()
            window.resize(1100, 720)
            window.move(-10000, -10000)
            window.show()

            def js(expression: str, timeout: float = 20) -> object:
                result: list[object] = []
                page.runJavaScript(expression, result.append)
                deadline = time.monotonic() + timeout
                while not result and time.monotonic() < deadline:
                    pump()
                if not result:
                    raise TimeoutError("javascript_callback_timeout")
                return result[0]

            def wait_js(expression: str, label: str) -> object:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    result = js(expression)
                    if result:
                        return result
                    pump(0.08)
                raise TimeoutError(label)

            wait_js(
                "window.ReweavePrototype.getState().productPlan.view === 'review'",
                "gap plan review",
            )
            assert js(
                "window.ReweavePrototype.getState().productPlan.capability_gap_count"
            ) == 1
            assert js(
                "document.getElementById('btn-confirm-and-generate').disabled"
            ) is True
            assert js(
                "document.querySelector('.product-acceptance').classList.contains('hidden')"
            ) is True
            js(
                "document.querySelector('[data-section-index=\"1\"]').click(); true"
            )
            wait_js(
                "document.querySelectorAll('.product-capability-gap').length === 1",
                "inline gap",
            )
            if replan_fixture:
                wait_js(
                    "!!document.querySelector("
                    "'[data-capability-replan-status=\"available\"] "
                    "[data-action=\"start-capability-replan\"]')",
                    "published capability replan action",
                )
                assert js(
                    "document.querySelector("
                    "'[data-capability-replan-status=\"available\"]'"
                    ").textContent.includes("
                    + (
                        "'rectangle_dimensions_input → rectangle_area → "
                        "rectangle_area_result')"
                        if multi_field_replan
                        else "'years_input → years_to_months → months_result')"
                    )
                ) is True
                assert window.centralWidget().grab().save(
                    str(tmp_path / f"{screenshot_prefix}-available-1100x720.png")
                )
                js(
                    "document.querySelector("
                    "'[data-action=\"start-capability-replan\"]'"
                    ").click(); true"
                )
                wait_js(
                    "window.ReweavePrototype.getState().productPlan.view === 'review' "
                    "&& window.ReweavePrototype.getState().productPlan.capability_gap_count === 0",
                    "replanned workspace review",
                )
                wait_js(
                    "document.querySelectorAll("
                    "'#product-acceptance-cases .product-acceptance-row'"
                    f").length === {1 if multi_field_replan else 3}",
                    "replan acceptance suggestions",
                )
                assert js(
                    "JSON.stringify(Array.from(document.querySelectorAll("
                    "'#product-acceptance-cases input'"
                    ")).map(node=>node.value))"
                ) == (
                    '["1","true","","1.2","1.2","true","","1"]'
                    if multi_field_replan
                    else '["1","12","2","24","10","120"]'
                )
                assert js(
                    "window.ReweavePrototype.getState().productPlan."
                    "acceptance_supported"
                ) is True
                assert js(
                    "document.getElementById('btn-confirm-and-generate').disabled"
                ) is False
                assert planner.replan_calls == 1
                assert js(
                    "window.ReweavePrototype.getState().productPlan.has_plan"
                ) is True
                assert window.centralWidget().grab().save(
                    str(tmp_path / f"{screenshot_prefix}-review-1100x720.png")
                )
                if multi_field_replan:
                    js(
                        "(() => {"
                        "const fields=Array.from(document.querySelectorAll("
                        "'#product-acceptance-cases input'));"
                        "const values=[' 2 ','true','  keep  ','001.2300',"
                        "'9007199254740991.1200','false','  ok  ','3'];"
                        "fields.forEach((field,index)=>{"
                        "field.value=values[index];"
                        "field.dispatchEvent(new Event('input',{bubbles:true}));"
                        "});"
                        "document.getElementById("
                        "'btn-confirm-and-generate').click();"
                        "return true;})()"
                    )
                    deadline = time.monotonic() + 20
                    while not submitted_acceptance and time.monotonic() < deadline:
                        pump(0.08)
                    assert submitted_acceptance == [
                        {
                            "plan_token": planner.successor_token,
                            "plan_digest": "6" * 64,
                            "acceptance_cases": [
                                {
                                    "requirement_ids": [
                                        "requirement_rectangle"
                                    ],
                                    "input": {
                                        "count": 2,
                                        "enabled": True,
                                        "label": "  keep  ",
                                        "price": "1.23",
                                    },
                                    "expected_output": {
                                        "amount": "9007199254740991.12",
                                        "approved": False,
                                        "note": "  ok  ",
                                        "rank": 3,
                                    },
                                }
                            ],
                        }
                    ]
                    return
                planner.replan_status = "capability_replan_handoff_conflict"
                window.centralWidget().reload()
                pump(0.8)
                wait_js(
                    "!!window.ReweavePrototype && "
                    "window.ReweavePrototype.getState().productPlan.view === 'review'",
                    "reloaded replan conflict",
                )
                js(
                    "document.querySelector('[data-section-index=\"1\"]').click(); true"
                )
                wait_js(
                    "!!document.querySelector("
                    "'[data-capability-replan-status="
                    "\"capability_replan_handoff_conflict\"]'"
                    ")",
                    "replan conflict failed closed",
                )
                assert js(
                    "document.querySelectorAll("
                    "'[data-action=\"start-capability-replan\"]'"
                    ").length"
                ) == 0
                return
            if enum_fixture:
                assert js(
                    "document.querySelectorAll("
                    "'.product-gap-case select').length"
                ) == 3
                assert js(
                    "document.querySelectorAll("
                    "'.product-gap-case input').length"
                ) == 0
                assert js(
                    "document.getElementById('screen-product-plan')"
                    ".textContent.includes("
                    "'DETERMINISTIC_TEST_FIXTURE_NOT_FORMAL_WAREHOUSE_STATE'"
                    ")"
                ) is True
                js(
                    "(() => {"
                    "const behavior=document.querySelector("
                    "'.product-gap-field textarea');"
                    "behavior.value='根据两个布尔条件返回有限状态。';"
                    "behavior.dispatchEvent(new Event('input',{bubbles:true}));"
                    "const fields=document.querySelectorAll("
                    "'.product-gap-case select');"
                    "fields[0].value='true';"
                    "fields[1].value='true';"
                    "fields[2].value='do_now';"
                    "fields.forEach(node=>node.dispatchEvent("
                    "new Event('input',{bubbles:true})));"
                    "const button=document.querySelector("
                    "'.product-gap-actions .btn-primary');"
                    "button.focus();button.click();return true;})()"
                )
            elif preauthorized:
                js(
                    "document.querySelector("
                    "'[data-action=\"start-capability-source-proposal\"]'"
                    ").click(); true"
                )
            elif time_fixture:
                assert js(
                    "document.querySelectorAll('.product-gap-case input[type=number]').length"
                ) == 2
                js(
                    "(() => {for(let i=0;i<2;i++){"
                    "Array.from(document.querySelectorAll('button.product-plan-text-action'))"
                    ".find(node=>node.textContent.includes('添加验收例')).click();"
                    "} return true;})()"
                )
                wait_js(
                    "document.querySelectorAll('.product-gap-case input[type=number]').length === 6",
                    "three time acceptance cases",
                )
                js(
                    "(() => {"
                    "const behavior=document.querySelector('.product-gap-field textarea');"
                    "behavior.value='将整数小时转换为分钟。';"
                    "behavior.dispatchEvent(new Event('input',{bubbles:true}));"
                    "const values=['1','60','2','120','24','1440'];"
                    "document.querySelectorAll('.product-gap-case input').forEach((field,index)=>{"
                    "field.value=values[index];"
                    "field.dispatchEvent(new Event('input',{bubbles:true}));"
                    "});"
                    "document.querySelector('.product-gap-actions .btn-primary').click();"
                    "return true;})()"
                )
            else:
                assert js(
                    "document.querySelectorAll('.product-gap-case input[type=number]').length"
                ) == 3
                js(
                    "(() => {"
                    "const behavior=document.querySelector('.product-gap-field textarea');"
                    "behavior.value='按数量计算折扣单价，并保留数量。';"
                    "behavior.dispatchEvent(new Event('input',{bubbles:true}));"
                    "const fields=document.querySelectorAll('.product-gap-case input');"
                    "fields[0].value='5';fields[0].dispatchEvent(new Event('input',{bubbles:true}));"
                    "fields[2].value='80';fields[2].dispatchEvent(new Event('input',{bubbles:true}));"
                    "document.querySelector('.product-gap-actions .btn-primary').click();"
                    "return true;})()"
                )
            if start_error_code:
                wait_js(
                    "!!document.querySelector("
                    f"'[data-source-proposal-error-code=\"{start_error_code}\"]'"
                    ")",
                    "structured source proposal start error",
                )
                assert js(
                    "document.querySelector("
                    f"'[data-source-proposal-error-code=\"{start_error_code}\"]'"
                    ").textContent.includes("
                    f"'{start_error_code}'"
                    ")"
                ) is True
                assert len(start_calls) == 1
                assert planner.source_run is None
                assert planner.prepare_calls == (0 if preauthorized else 1)
                assert js(
                    "document.getElementById('screen-product-plan')"
                    ".classList.contains('hidden')"
                ) is False
                return
            wait_js(
                "!!document.getElementById("
                f"'target-review-summary-{review_id}'"
                ")",
                "exact frozen review",
            )
            assert js(
                "document.getElementById('screen-capsule-ingestion')"
                ".classList.contains('hidden')"
            ) is False
            if enum_fixture:
                assert planner.decisions[-1]["acceptance_cases"] == [
                    {
                        "input": {"important": True, "urgent": True},
                        "expected_output": {"priority": "do_now"},
                    }
                ]
                assert planner.authorization["schema_version"] == (
                    "capability_source_proposal_authorization.v2"
                )
            elif time_fixture:
                assert planner.decisions[-1]["acceptance_cases"] == [
                    {"input": {"hours": 1}, "expected_output": {"minutes": 60}},
                    {
                        "input": {"hours": 2},
                        "expected_output": {"minutes": 120},
                    },
                    {
                        "input": {"hours": 24},
                        "expected_output": {"minutes": 1440},
                    },
                ]
            else:
                assert planner.decisions[-1]["acceptance_cases"] == [
                    {
                        "input": {"quantity": 5},
                        "expected_output": {
                            "quantity": 5,
                            "unit_price": 80,
                        },
                    }
                ]
            assert planner.prepare_calls == 1
            assert planner.source_run["status"] == "review_required"
            wait_js(
                "document.querySelectorAll('#warehouse-review-items details').length === 1",
                "only target review",
            )
            assert js(
                "document.getElementById("
                f"'target-review-summary-{review_id}'"
                ").parentElement.open"
            ) is True
            assert js(
                "document.getElementById("
                f"'target-review-summary-{decoy_review_id}'"
                ") === null"
            ) is True
            assert js(
                "document.querySelector('input[name=capability_key]').readOnly"
            ) is True
            assert js(
                "document.querySelector('input[name=display_name]').readOnly"
            ) is True
            assert js(
                "document.querySelector('input[name=role_key]').value"
            ) == ""
            assert js(
                "document.querySelector('input[name=variant_key]').value"
            ) == "default"
            review_screenshot = (
                tmp_path / f"{screenshot_prefix}-review-1100x720.png"
            )
            assert window.centralWidget().grab().save(str(review_screenshot))
            if enum_fixture and os.environ.get("REWEAVE_ENUM_GAP_SCREENSHOT"):
                shutil.copy2(
                    review_screenshot,
                    os.environ["REWEAVE_ENUM_GAP_SCREENSHOT"],
                )
            if time_fixture:
                js(
                    "(() => {"
                    "const role=document.querySelector('input[name=role_key]');"
                    "role.value='hours_to_minutes';"
                    "role.dispatchEvent(new Event('input',{bubbles:true}));"
                    "const select=document.querySelector("
                    "'.warehouse-review-decision select');"
                    "select.value='publish_general';"
                    "select.dispatchEvent(new Event('change',{bubbles:true}));"
                    "document.querySelector("
                    "'.warehouse-review-decision button').click();"
                    "return true;})()"
                )
                wait_js(
                    "document.getElementById('screen-product-plan')"
                    ".classList.contains('hidden') === false",
                    "published review returned to plan",
                )
                wait_js(
                    "!!document.querySelector("
                    "'[data-capability-replan-status=\"available\"] "
                    "[data-action=\"start-capability-replan\"]')",
                    "published capability requires explicit replan",
                )
                assert planner.review_outcome["status"] == "published"
                assert window.centralWidget().grab().save(
                    str(
                        tmp_path
                        / f"{screenshot_prefix}-published-1100x720.png"
                    )
                )
            else:
                js(
                    "(() => {"
                    "const select=document.querySelector("
                    "'.warehouse-review-decision select');"
                    "select.value='reject';"
                    "select.dispatchEvent(new Event('change',{bubbles:true}));"
                    "document.querySelector("
                    "'.warehouse-review-decision button').click();"
                    "return true;})()"
                )
                wait_js(
                    "document.getElementById('screen-product-plan')"
                    ".classList.contains('hidden') === false",
                    "rejected review returned to plan",
                )
                wait_js(
                    "!!document.querySelector('.product-gap-status.is-error')",
                    "rejected source proposal shown",
                )
                assert js(
                    "document.querySelectorAll("
                    "'[data-action=\"start-capability-replan\"]'"
                    ").length"
                ) == 0
                assert planner.review_outcome["status"] == "rejected"
                assert window.centralWidget().grab().save(
                    str(
                        tmp_path
                        / f"{screenshot_prefix}-rejected-1100x720.png"
                    )
                )

            planner.source_run = None
            planner.authorization = None
            planner.review_outcome = None
            planner.decisions = []
            planner.ambiguous = True
            window.centralWidget().reload()
            pump(0.8)
            wait_js(
                "!!window.ReweavePrototype && "
                "window.ReweavePrototype.getState().productPlan.view === 'review' && "
                "document.querySelector('.product-plan-section-button[data-section-index=\"1\"]') !== null",
                "reloaded review",
            )
            js(
                "document.querySelector('[data-section-index=\"1\"]').click(); true"
            )
            wait_js(
                "!!document.querySelector('.product-gap-status.is-error') && "
                "document.querySelector('.product-gap-status.is-error').textContent.includes('多个合法')",
                "ambiguous failed closed",
            )
            pump(0.1)
            assert window.centralWidget().grab().save(
                str(tmp_path / f"{screenshot_prefix}-ambiguous-1100x720.png")
            )
            assert js(
                "document.querySelectorAll('.product-gap-actions').length"
            ) == 0
    finally:
        if window is not None:
            window._reweave_close_service()
            window.close()
            window.deleteLater()
            pump()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            app.processEvents()


def test_product_capability_gap_decisions_render_and_fail_closed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _run_product_capability_gap_qweb_case(
        tmp_path,
        monkeypatch,
        time_fixture=False,
    )


def test_time_conversion_capability_gap_fixture_renders_and_fails_closed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _run_product_capability_gap_qweb_case(
        tmp_path,
        monkeypatch,
        time_fixture=True,
    )


def test_finite_enum_capability_gap_runs_once_to_exact_review(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _run_product_capability_gap_qweb_case(
        tmp_path,
        monkeypatch,
        time_fixture=False,
        enum_fixture=True,
    )


def test_capability_source_proposal_start_error_is_preserved(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _run_product_capability_gap_qweb_case(
        tmp_path,
        monkeypatch,
        time_fixture=False,
        start_error_code="capability_source_proposal_run_stale",
        preauthorized=True,
    )


def test_published_capability_replan_handoff_runs_once_and_opens_review(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _run_product_capability_gap_qweb_case(
        tmp_path,
        monkeypatch,
        time_fixture=False,
        replan_fixture=True,
    )


def test_multi_field_candidate_acceptance_renders_all_contract_fields(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _run_product_capability_gap_qweb_case(
        tmp_path,
        monkeypatch,
        time_fixture=False,
        multi_field_replan=True,
    )


def test_product_flow_builds_previews_exports_and_restores_real_candidate(
    tmp_path: Path, monkeypatch
) -> None:
    if shutil.which("node") is None:
        pytest.skip("Node is required for module_native composition")
    if not (ROOT / "node_modules" / "esbuild" / "package.json").is_file():
        pytest.skip("npm ci is required for module_native composition")
    if sys.platform.startswith("linux") and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        pytest.skip("A desktop GUI session is required")
    pytest.importorskip("PySide6.QtWebEngineCore")

    if os.environ.get("REWEAVE_PRODUCT_FLOW_CHILD") != "1":
        child_env = os.environ.copy()
        child_env["REWEAVE_PRODUCT_FLOW_CHILD"] = "1"
        child_env.pop("PYTEST_ADDOPTS", None)
        child = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                "-q",
                (
                    "tests/test_reweave_phase6_desktop.py::"
                    "test_product_flow_builds_previews_exports_and_restores_real_candidate"
                ),
            ],
            cwd=ROOT,
            env=child_env,
            capture_output=True,
            text=True,
            timeout=360,
        )
        assert child.returncode == 0, child.stdout + child.stderr
        return

    import copy

    from PySide6.QtCore import QCoreApplication, QEvent, QUrl
    from PySide6.QtWebEngineCore import QWebEngineProfile

    from pimos_lite import desktop_reweave_static as desktop
    from pimos_lite.reweave_agent_stdio import serve_jsonl
    from pimos_lite.reweave_app_service import ReweaveAppService
    from pimos_lite.reweave_capsule_store import CapsuleWarehouseStore
    from pimos_lite.reweave_plan_execution import (
        build_parameterized_execution_binding,
        build_parameterized_execution_offer,
        canonical_digest,
    )
    from tests.test_reweave_phase5_generation import (
        _NoLegacyEngine,
        _seed_capsule,
    )
    from tests.test_reweave_plan_execution import (
        _confirmed_plan,
        _parameterized_payload,
        _refresh,
        _store_snapshot,
    )

    goal = (
        "构建一个完全本地的报价计算页面：输入 1–10 的商品数量，"
        "按确认的固定单价计算并显示总价。"
    )
    plan_token = "plan_token_" + "d" * 48
    source_root = tmp_path / "source-sentinel"
    target_root = tmp_path / "target-sentinel"
    source_root.mkdir()
    target_root.mkdir()
    (source_root / "outside.js").write_text(
        "window.__outsideLoaded = true;\n", encoding="utf-8"
    )
    (target_root / "sentinel.txt").write_text("unchanged\n", encoding="utf-8")
    state_dir = tmp_path / "state"
    export_parent = tmp_path / "saved-products"
    export_parent.mkdir()
    monkeypatch.setenv("REWEAVE_STATE_DIR", str(state_dir))
    store = CapsuleWarehouseStore(state_dir / "capsule_warehouse.sqlite3")
    store.initialize()
    service = ReweaveAppService(_NoLegacyEngine(), capsule_store=store)
    capsule_ids = []
    for kind in ("presentation", "interaction", "computation"):
        capsule_id, _version_id = _seed_capsule(
            store,
            kind,
            capability_key="parameterized_quote_calculation",
            suffix=f"desktop_{kind}",
            payload=_parameterized_payload(kind),
        )
        capsule_ids.append(capsule_id)
    capsules, _scope = service._load_generation_capsules(
        capsule_ids,
        read_only=True,
    )
    plan, base_confirmation = _confirmed_plan(
        capsules,
        service._product_planning_catalog()["warehouse_revision"],
    )
    original_items = [
        copy.deepcopy(section["work_items"][0]) for section in plan["sections"]
    ]
    plan["schema_version"] = "product_plan.v2"
    plan["planning_rules_version"] = "reweave_product_planning_rules.v4"
    plan["prompt_version"] = "reweave_product_planning_prompt.v7"
    plan["sections"] = [
        {
            "section_id": "frontend",
            "applicability": "applicable",
            "summary": "前端交互与报价结果",
            "work_items": [original_items[0]],
            "gaps": [],
        },
        {
            "section_id": "backend",
            "applicability": "applicable",
            "summary": "本地输入、计算与运行验证",
            "work_items": original_items[1:],
            "gaps": [],
        },
        {
            "section_id": "data",
            "applicability": "not_applicable",
            "summary": "本产品不需要独立数据层。",
            "work_items": [],
            "gaps": [],
        },
        {
            "section_id": "infrastructure",
            "applicability": "not_applicable",
            "summary": "本产品不需要独立基础设施层。",
            "work_items": [],
            "gaps": [],
        },
    ]
    plan["goal"] = goal
    plan["goal_digest"] = canonical_digest(goal)
    for requirement in plan["requirements"]:
        requirement["source_digest"] = plan["goal_digest"]
    _refresh(plan, base_confirmation)
    question_set = {
        "schema_version": "product_plan_question_set.v4",
        "purpose": "capability_gap_target",
        "warehouse_revision": 71,
        "catalog_digest": "d" * 64,
        "target_context_digest": "e" * 64,
        "questions": [
            {
                "question_id": "question_capability_gap_target",
                "prompt": "请选择本次要完成的业务能力。",
                "options": [
                    {
                        "option_id": "option_workflow_classification",
                        "label": "工作流状态分类",
                        "impact": "输入重要与紧急条件；输出处理优先级；缺少一个计算能力。",
                        "recommended": False,
                        "forms_gap": True,
                    },
                    {
                        "option_id": "option_prism_volume",
                        "label": "长方体体积计算",
                        "impact": "输入长宽高；输出体积；缺少一个计算能力。",
                        "recommended": False,
                        "forms_gap": True,
                    },
                    {
                        "option_id": "option_no_match",
                        "label": "以上都不是",
                        "impact": "停止规划，不创建正式 capability gap。",
                        "recommended": False,
                        "forms_gap": False,
                    },
                ],
                "allow_custom": False,
            }
        ],
    }
    question_set["digest"] = canonical_digest(question_set)
    handoff_state: dict[str, object] = {}

    class DesktopPlanner:
        def __init__(
            self,
            *,
            status: str = "idle",
            confirmation: dict | None = None,
            acceptance_confirmation: dict | None = None,
        ) -> None:
            self.status = status
            self.selected_model: dict[str, object] | None = None
            self.confirmation = copy.deepcopy(confirmation)
            self.acceptance_confirmation = copy.deepcopy(
                acceptance_confirmation
            )

        def _projection(self) -> dict[str, object]:
            handoff = handoff_state.get("record")
            handoff_status = (
                handoff["status"] if isinstance(handoff, dict) else "none"
            )
            return {
                "plan_token": plan_token,
                "goal": goal,
                "status": self.status,
                "failure_code": (
                    "product_plan_capability_gap_target_unmatched"
                    if self.status == "failed"
                    else None
                ),
                "question_set": (
                    copy.deepcopy(question_set)
                    if self.status == "needs_clarification"
                    else None
                ),
                "plan": (
                    copy.deepcopy(plan)
                    if self.status in {"plan_review", "confirmed"}
                    else None
                ),
                "plan_diff": None,
                "confirmation": copy.deepcopy(self.confirmation),
                "agent_handoff": {
                    "schema_version": "agent_handoff_status.v1",
                    "status": handoff_status,
                    "created_at": (
                        handoff.get("created_at")
                        if isinstance(handoff, dict)
                        else None
                    ),
                    "revoked_at": (
                        handoff.get("revoked_at")
                        if isinstance(handoff, dict)
                        else None
                    ),
                },
            }

        def initial_state(self) -> dict[str, object]:
            workspaces = []
            if self.status != "idle":
                workspaces.append(
                    {
                        "plan_token": plan_token,
                        "display_name": plan["product_name"],
                        "status": self.status,
                        "updated_at": "2026-07-25T00:00:00Z",
                        "plan_version": plan["plan_version"],
                        "confirmed": self.status == "confirmed",
                    }
                )
            return {
                "ok": True,
                "data": {
                    "schema_version": "product_planning_state.v1",
                    "available": True,
                    "selected_model": copy.deepcopy(self.selected_model),
                    "workspaces": workspaces,
                    "candidate_generation_available": True,
                    "product_generation_performed": False,
                },
            }

        def start(
            self,
            requested_goal,
            _catalog,
            _cancel,
            *,
            resume_plan_token=None,
            phase_callback=None,
        ):
            assert requested_goal == goal
            assert resume_plan_token is None
            if phase_callback:
                phase_callback("requirements_outline")
            time.sleep(1.0)
            self.status = "needs_clarification"
            return {"ok": True, "data": self._projection()}

        def answer(
            self,
            token,
            digest,
            answers,
            _catalog,
            _cancel,
            *,
            phase_callback=None,
        ):
            assert token == plan_token
            assert digest == question_set["digest"]
            if answers == [
                {
                    "question_id": "question_capability_gap_target",
                    "source": "option",
                    "value": "option_no_match",
                }
            ]:
                self.status = "failed"
                return {
                    "ok": False,
                    "error": {
                        "code": (
                            "product_plan_capability_gap_target_unmatched"
                        ),
                        "message_key": (
                            "product_plan_capability_gap_target_unmatched"
                        ),
                    },
                    "data": self._projection(),
                }
            assert answers == [
                {
                    "question_id": "question_capability_gap_target",
                    "source": "option",
                    "value": "option_workflow_classification",
                }
            ]
            if phase_callback:
                phase_callback("frontend")
            self.status = "plan_review"
            return {"ok": True, "data": self._projection()}

        def get(self, token, _catalog=None, _parameter_capsules=None):
            if token != plan_token or self.status == "idle":
                return {
                    "ok": False,
                    "error": {
                        "code": "product_plan_not_found",
                        "message_key": "product_plan_not_found",
                    },
                }
            return {"ok": True, "data": self._projection()}

        def record_product_experience(self, *_args, **_kwargs):
            return None

        def confirm(
            self,
            token,
            digest,
            reviewed_plan,
            _catalog,
            parameter_capsules=None,
            parameter_confirmation=None,
        ):
            assert token == plan_token
            assert digest == plan["canonical_digest"]
            assert reviewed_plan == plan
            offer = build_parameterized_execution_offer(
                plan,
                parameter_capsules or [],
            )
            assert offer is not None
            if parameter_confirmation is None:
                projection = self._projection()
                projection["parameter_offer"] = offer
                return {
                    "ok": False,
                    "error": {
                        "code": "parameter_confirmation_required",
                        "message_key": "parameter_confirmation_required",
                    },
                    "data": projection,
                }
            binding = build_parameterized_execution_binding(
                plan,
                offer,
                parameter_confirmation,
            )
            receipt = {
                key: value
                for key, value in base_confirmation.items()
                if key != "receipt_digest"
            }
            receipt["schema_version"] = "product_plan_confirmation.v2"
            receipt["parameter_binding"] = binding
            receipt["receipt_digest"] = canonical_digest(receipt)
            if self.confirmation is not None and self.confirmation != receipt:
                return {
                    "ok": False,
                    "error": {
                        "code": "product_plan_confirmation_conflict",
                        "message_key": "product_plan_confirmation_conflict",
                    },
                }
            self.confirmation = copy.deepcopy(receipt)
            self.status = "confirmed"
            return {"ok": True, "data": self._projection()}

        def confirm_candidate_acceptance(self, token, record):
            assert token == plan_token
            if (
                self.acceptance_confirmation is not None
                and self.acceptance_confirmation != record
            ):
                return {
                    "ok": False,
                    "error": {
                        "code": "candidate_acceptance_confirmation_conflict",
                        "message_key": "candidate_acceptance_confirmation_conflict",
                    },
                }
            self.acceptance_confirmation = copy.deepcopy(record)
            return {
                "ok": True,
                "data": {
                    "acceptance_confirmation": copy.deepcopy(record),
                },
            }

        def get_candidate_acceptance_confirmation(self, token):
            assert token == plan_token
            if self.acceptance_confirmation is None:
                return {
                    "ok": False,
                    "error": {
                        "code": "candidate_acceptance_confirmation_required",
                        "message_key": "candidate_acceptance_confirmation_required",
                    },
                }
            return {
                "ok": True,
                "data": {
                    "acceptance_confirmation": copy.deepcopy(
                        self.acceptance_confirmation
                    )
                },
            }

        def create_agent_handoff(
            self,
            token,
            acceptance_confirmation_digest,
            capsule_facts_digest,
        ):
            assert token == plan_token
            current = handoff_state.get("record")
            if isinstance(current, dict) and current["status"] == "active":
                return {
                    "ok": False,
                    "error": {
                        "code": "agent_handoff_already_active",
                        "message_key": "agent_handoff_already_active",
                    },
                }
            attempt = int(handoff_state.get("attempt", 0)) + 1
            handoff_state["attempt"] = attempt
            handoff_token = "handoff_token_" + format(6 + attempt, "x") * 48
            handoff_state["token"] = handoff_token
            handoff_state["record"] = {
                "plan_token": plan_token,
                "plan_digest": plan["canonical_digest"],
                "plan_confirmation_digest": self.confirmation[
                    "receipt_digest"
                ],
                "acceptance_confirmation_digest": (
                    acceptance_confirmation_digest
                ),
                "capsule_facts_digest": capsule_facts_digest,
                "status": "active",
                "created_at": "2026-08-15T00:00:00.000Z",
                "revoked_at": None,
            }
            return {
                "ok": True,
                "data": {
                    "handoff_token": handoff_token,
                    "status": "active",
                    "created_at": "2026-08-15T00:00:00.000Z",
                },
            }

        def resolve_agent_handoff(self, token):
            record = handoff_state.get("record")
            if token != handoff_state.get("token") or not isinstance(
                record, dict
            ):
                return {
                    "ok": False,
                    "error": {
                        "code": "agent_handoff_not_found",
                        "message_key": "agent_handoff_not_found",
                    },
                }
            if record["status"] == "revoked":
                return {
                    "ok": False,
                    "error": {
                        "code": "agent_handoff_revoked",
                        "message_key": "agent_handoff_revoked",
                    },
                }
            return {"ok": True, "data": copy.deepcopy(record)}

        def get_agent_handoff_status(
            self,
            token,
            capsule_facts_digest=None,
        ):
            assert token == plan_token
            record = handoff_state.get("record")
            status = record["status"] if isinstance(record, dict) else "none"
            if (
                status == "active"
                and capsule_facts_digest is not None
                and record["capsule_facts_digest"] != capsule_facts_digest
            ):
                status = "stale"
            return {
                "ok": True,
                "data": {
                    "schema_version": "agent_handoff_status.v1",
                    "status": status,
                    "created_at": (
                        record.get("created_at")
                        if isinstance(record, dict)
                        else None
                    ),
                    "revoked_at": (
                        record.get("revoked_at")
                        if isinstance(record, dict)
                        else None
                    ),
                },
            }

        def revoke_agent_handoff(self, token):
            if token != handoff_state.get("token"):
                return {
                    "ok": False,
                    "error": {
                        "code": "agent_handoff_not_found",
                        "message_key": "agent_handoff_not_found",
                    },
                }
            return self.revoke_agent_handoff_for_plan(plan_token)

        def revoke_agent_handoff_for_plan(self, token):
            assert token == plan_token
            record = handoff_state.get("record")
            if not isinstance(record, dict):
                return {
                    "ok": True,
                    "data": {"status": "none", "revoked_at": None},
                }
            record["status"] = "revoked"
            record["revoked_at"] = "2026-08-15T00:01:00.000Z"
            return {
                "ok": True,
                "data": {
                    "status": "revoked",
                    "revoked_at": record["revoked_at"],
                },
            }

    planner = DesktopPlanner()
    service._product_planner = planner
    planning_model = {
        "name": "protocol-fixture",
        "digest": "e" * 64,
        "parameter_count": 1,
        "parameter_size": "1B",
        "eligible_small_model": True,
        "eligibility_reason": "eligible",
    }
    planning_model_calls: list[tuple[str, dict[str, object]]] = []
    original_get_product_plan_run = service.get_product_plan_run

    def list_planning_models(payload: dict[str, object]) -> dict[str, object]:
        assert payload == {}
        planning_model_calls.append(("list_product_planning_models", payload))
        return {"ok": True, "run_id": "product_plan_models_fixture"}

    def select_planning_model(payload: dict[str, object]) -> dict[str, object]:
        assert payload == {
            "name": planning_model["name"],
            "digest": planning_model["digest"],
        }
        planning_model_calls.append(("select_product_planning_model", payload))
        planner.selected_model = copy.deepcopy(planning_model)
        return {"ok": True, "run_id": "product_plan_select_fixture"}

    def get_product_plan_run(payload: dict[str, object]) -> dict[str, object]:
        run_id = str(payload.get("run_id") or "")
        if run_id == "product_plan_models_fixture":
            data = {"models": [copy.deepcopy(planning_model)]}
        elif run_id == "product_plan_select_fixture":
            data = {"model": copy.deepcopy(planning_model)}
        else:
            return original_get_product_plan_run(payload)
        return {
            "ok": True,
            "data": {
                "run_id": run_id,
                "status": "completed",
                "data": {"ok": True, "data": data},
            },
        }

    service.list_product_planning_models = list_planning_models
    service.select_product_planning_model = select_planning_model
    service.get_product_plan_run = get_product_plan_run
    warehouse_before = _store_snapshot(store)
    source_before = _tree_state(source_root)
    target_before = _tree_state(target_root)
    usage_before = _usage_state(store)
    products_before = _tree_state(state_dir / "products")

    qt_parts = desktop.import_qt_webengine()
    QApplication = qt_parts[0]
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    profile = QWebEngineProfile.defaultProfile()
    profile.setCachePath(str(tmp_path / "qweb-cache"))
    profile.setPersistentStoragePath(str(tmp_path / "qweb-storage"))

    class FixedDirectoryDialog:
        @staticmethod
        def getExistingDirectory(*_args, **_kwargs):
            return str(export_parent)

    def pump(seconds: float = 0.03) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.005)

    def close_window(window) -> None:
        if window is None:
            return
        for preview in list(
            getattr(window, "_reweave_bridge", object())._candidate_preview_windows
            if hasattr(getattr(window, "_reweave_bridge", None), "_candidate_preview_windows")
            else []
        ):
            preview.close()
            preview.deleteLater()
        window._reweave_close_service()
        window.close()
        window.deleteLater()
        pump()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()

    window = None
    restarted_window = None
    restarted_service = None
    try:
        with (
            patch.object(
                desktop,
                "import_qt_webengine",
                return_value=(*qt_parts[:5], FixedDirectoryDialog),
            ),
            patch.object(desktop, "ReweaveAppService", return_value=service),
        ):
            window, bridge = desktop.create_reweave_window()
            window._reweave_bridge = bridge
            page = window.centralWidget().page()
            assert (
                page.settings().testAttribute(
                    qt_parts[3].JavascriptCanAccessClipboard
                )
                is False
            )
            window.show()

            def js(expression: str, timeout: float = 20) -> object:
                result: list[object] = []
                page.runJavaScript(expression, result.append)
                deadline = time.monotonic() + timeout
                while not result and time.monotonic() < deadline:
                    pump()
                if not result:
                    raise TimeoutError("javascript_callback_timeout")
                return result[0]

            def wait_js(expression: str, timeout: float, label: str) -> object:
                deadline = time.monotonic() + timeout
                last: object = None
                while time.monotonic() < deadline:
                    last = js(expression)
                    if last:
                        return last
                    pump(0.08)
                raise TimeoutError(f"{label}:{last!r}")

            wait_js(
                "document.readyState === 'complete' && !!window.reweaveBridge && "
                "!document.getElementById('screen-product-plan').classList.contains('hidden')",
                30,
                "default product screen",
            )
            bridge_calls: list[str] = []
            original_call = bridge._phase4_call

            def observe_call(method_name: str, payload_json: str = "") -> str:
                bridge_calls.append(method_name)
                return original_call(method_name, payload_json)

            bridge._phase4_call = observe_call

            def assert_product_frame() -> None:
                frame = json.loads(
                    str(
                        js(
                            "JSON.stringify((() => {"
                                            "const bar=document.querySelector('#screen-product-plan > .product-plan-bar').getBoundingClientRect();"
                            "const stage=document.getElementById('product-plan-stage').getBoundingClientRect();"
                            "const back=document.getElementById('btn-product-plan-back').getBoundingClientRect();"
                            "return {scroll_x:window.scrollX,scroll_y:window.scrollY,"
                            "bar_left:bar.left,bar_top:bar.top,bar_right:bar.right,bar_bottom:bar.bottom,"
                            "back_left:back.left,back_right:back.right,stage_top:stage.top,"
                            "viewport_width:window.innerWidth,viewport_height:window.innerHeight};"
                            "})())"
                        )
                    )
                )
                assert frame["scroll_x"] == 0, frame
                assert frame["scroll_y"] == 0, frame
                assert frame["bar_left"] == 0, frame
                assert frame["bar_top"] == 0, frame
                assert frame["bar_right"] == frame["viewport_width"], frame
                assert 0 <= frame["back_left"] < frame["back_right"], frame
                assert frame["back_right"] <= frame["viewport_width"], frame
                assert frame["stage_top"] >= frame["bar_bottom"], frame
                assert frame["viewport_height"] >= 720, frame

            wait_js(
                "window.ReweavePrototype.getState().productPlan.active === true && "
                "window.ReweavePrototype.getState().productPlan.view === 'compose'",
                10,
                "product compose",
            )
            assert_product_frame()
            assert (
                js("document.getElementById('btn-submit-product-goal').disabled")
                is True
            )
            js("document.getElementById('btn-product-planner-configure').click(); true")
            wait_js(
                "document.getElementById('product-planner-select').options.length === 2",
                10,
                "planning model list",
            )
            js(
                "(() => {"
                "const select=document.getElementById('product-planner-select');"
                "select.value='0';"
                "select.dispatchEvent(new Event('change',{bubbles:true}));"
                "document.getElementById('btn-product-planner-use').click();"
                "return true;"
                "})()"
            )
            wait_js(
                "window.ReweavePrototype.getState().productPlan.planning_model_selected === true",
                10,
                "planning model selected",
            )
            assert planning_model_calls == [
                ("list_product_planning_models", {}),
                (
                    "select_product_planning_model",
                    {
                        "name": planning_model["name"],
                        "digest": planning_model["digest"],
                    },
                ),
            ]
            assert (
                js("document.getElementById('btn-submit-product-goal').disabled")
                is True
            )
            js(
                "(() => { const input = document.getElementById('product-plan-goal'); "
                f"input.value = {json.dumps(goal)}; "
                "input.dispatchEvent(new Event('input',{bubbles:true})); "
                "document.getElementById('btn-submit-product-goal').click(); return true; })()"
            )
            wait_js(
                "window.ReweavePrototype.getState().productPlan.view === 'progress'",
                5,
                "real planning status",
            )
            assert_product_frame()
            wait_js(
                "['questions','failed'].includes("
                "window.ReweavePrototype.getState().productPlan.view)",
                30,
                "blocking question",
            )
            assert (
                json.loads(
                    str(
                        js(
                            "JSON.stringify(window.ReweavePrototype.getState().productPlan)"
                        )
                    )
                )["view"]
                == "questions"
            ), (
                bridge_calls,
                [
                    {
                        key: value
                        for key, value in task.items()
                        if key not in {"cancel_event", "future"}
                    }
                    for task in service._management_tasks.values()
                ],
            )
            assert_product_frame()
            assert "start_product_plan" in bridge_calls
            assert "get_product_plan_run" in bridge_calls
            assert js(
                "document.querySelectorAll('#product-plan-question-form input[type=radio]').length"
            ) == 3
            assert js(
                "document.querySelectorAll('.product-question-custom').length"
            ) == 0
            assert set(
                json.loads(
                    str(
                        js(
                            "JSON.stringify(Array.from(document.querySelectorAll("
                            "'#product-plan-question-form strong')).map(node=>node.textContent))"
                        )
                    )
                )
            ) == {"工作流状态分类", "长方体体积计算", "以上都不是"}
            assert js(
                "document.getElementById('product-plan-status').getAttribute('aria-live')"
            ) == "polite"
            js(
                "document.querySelector('#product-plan-question-form input[type=radio]').focus(); true"
            )
            assert js(
                "document.activeElement === document.querySelector("
                "'#product-plan-question-form input[type=radio]')"
            )
            if os.environ.get("REWEAVE_MULTI_GAP_QUESTION_ONLY") == "1":
                assert not {
                    "confirm_product_plan",
                    "generate_product_candidate",
                    "save_product_candidate",
                }.intersection(bridge_calls)
                return
            if os.environ.get("REWEAVE_GAP_NO_MATCH_ONLY") == "1":
                js(
                    "(() => { const rows = document.querySelectorAll("
                    "'#product-plan-question-form input[type=radio]'); "
                    "rows[rows.length - 1].click(); "
                    "document.getElementById('btn-submit-product-answers').click(); "
                    "return true; })()"
                )
                wait_js(
                    "window.ReweavePrototype.getState().productPlan.view === 'failed'",
                    30,
                    "gap target unmatched",
                )
                assert (
                    js(
                        "document.getElementById('product-plan-failed-copy').textContent"
                    )
                    == "当前正式能力及可补齐缺口均不符合本次目标，"
                    "Reweave 已停止规划，未创建正式 capability gap。"
                )
                assert not {
                    "confirm_product_plan",
                    "generate_product_candidate",
                    "save_product_candidate",
                }.intersection(bridge_calls)
                return
            js(
                "document.querySelector('#product-plan-question-form input[type=radio]').click(); "
                "document.getElementById('btn-submit-product-answers').click(); true"
            )
            wait_js(
                "window.ReweavePrototype.getState().productPlan.view === 'review' && "
                "window.ReweavePrototype.getState().productPlan.acceptance_supported === true",
                30,
                "plan and acceptance shape",
            )
            assert js("document.querySelectorAll('.product-plan-section').length") == 4
            assert js("document.querySelectorAll('.product-plan-work-item').length") == 0
            assert js(
                "Array.from(document.querySelectorAll('.product-plan-section-summary'))"
                ".filter(node=>node.textContent.includes('不需要独立')).length"
            ) == 2
            assert js(
                "document.querySelectorAll('.product-plan-section-button[data-section-index]').length"
            ) == 2
            assert js("document.getElementById('product-review-title').textContent") == (
                "本地报价产品"
            )
            js("document.querySelector('.product-plan-section-button').click(); true")
            wait_js(
                "window.ReweavePrototype.getState().productPlan.section_open === true && "
                "document.querySelectorAll('.product-plan-work-item').length === 1",
                10,
                "plan section detail",
            )
            assert js(
                "!!document.querySelector('.product-plan-capability-link "
                ".product-plan-text-action')"
            )
            source_button_id = str(
                js(
                    "document.querySelector('.product-plan-capability-link "
                    ".product-plan-text-action').id"
                )
            )
            js(
                "document.getElementById(" + json.dumps(source_button_id) + ").focus(); "
                "document.getElementById(" + json.dumps(source_button_id) + ").click(); true"
            )
            wait_js(
                "!document.getElementById('screen-capsule-warehouse').classList.contains('hidden') && "
                "window.ReweavePrototype.getState().warehouse.plan_context_status === 'planContextMissing'",
                30,
                "exact plan binding fails closed without one source",
            )
            assert js(
                "document.getElementById('warehouse-context-status').textContent.includes("
                + json.dumps("未选择近似版本")
                + ")"
            )
            js("document.getElementById('btn-warehouse-scene-back').click(); true")
            wait_js(
                "!document.getElementById('screen-product-plan').classList.contains('hidden') && "
                "window.ReweavePrototype.getState().productPlan.section_open === true && "
                "document.activeElement && document.activeElement.id === "
                + json.dumps(source_button_id),
                10,
                "plan section and source focus restored",
            )
            js("document.getElementById('btn-product-plan-section-back').click(); true")
            wait_js(
                "window.ReweavePrototype.getState().productPlan.view === 'review' && "
                "document.querySelectorAll('.product-plan-section').length === 4",
                10,
                "plan overview restored",
            )
            js(
                "document.getElementById('btn-add-product-acceptance-case').click(); "
                "document.getElementById('btn-add-product-acceptance-case').click(); true"
            )
            js(
                "(() => {"
                "const inputs = document.querySelectorAll('[data-acceptance-field=input]');"
                "const outputs = document.querySelectorAll('[data-acceptance-field=expected]');"
                "['1','3','10'].forEach(function(value,index){"
                "inputs[index].value=value; inputs[index].dispatchEvent(new Event('input',{bubbles:true}));"
                "});"
                "['10','30','100'].forEach(function(value,index){"
                "outputs[index].value=value; outputs[index].dispatchEvent(new Event('input',{bubbles:true}));"
                "});"
                "return true;"
                "})()"
            )
            assert_product_frame()
            assert js(
                "document.getElementById('btn-confirm-and-agent').disabled"
            ) is False
            js(
                "document.getElementById('btn-confirm-and-agent').focus(); true"
            )
            assert js(
                "document.activeElement.id === 'btn-confirm-and-agent'"
            ) is True
            js("document.getElementById('btn-confirm-and-agent').click(); true")
            wait_js(
                "!document.getElementById('product-parameter-confirmation').classList.contains('hidden') "
                "&& !!document.querySelector('#product-parameter-confirmation input')",
                30,
                "parameter confirmation",
            )
            js(
                "(() => { const input = document.querySelector('#product-parameter-confirmation input'); "
                "input.value='10'; input.dispatchEvent(new Event('input',{bubbles:true})); "
                "document.getElementById('btn-confirm-and-agent').click(); return true; })()"
            )
            wait_js(
                "window.ReweavePrototype.getState().productPlan.view === 'handoff' && "
                "window.ReweavePrototype.getState().productPlan.agent_handoff_status === 'active'",
                30,
                "active Agent handoff",
            )
            assert bridge_calls.count("confirm_product_plan") == 2
            assert bridge_calls.count("confirm_product_candidate_acceptance") == 1
            assert handoff_state["attempt"] == 1
            assert bridge_calls.count("start_confirmed_product_candidate") == 0
            assert bridge_calls.count("suggest_product_plan_action") == 0
            assert bridge_calls.count("generate_product") == 0
            assert list(
                (state_dir / "product_candidates").glob("*/candidate.json")
            ) == []
            clipboard_line = app.clipboard().text()
            bind_request = json.loads(clipboard_line)
            assert bind_request == {
                "protocol": "reweave_agent_jsonl.v2",
                "id": "bind-user-handoff",
                "action": "bind_user_handoff",
                "payload": {
                    "handoff_token": "handoff_token_" + "7" * 48,
                },
            }
            shuttle_output = io.StringIO()
            serve_jsonl(
                service,
                io.StringIO(clipboard_line + "\n"),
                shuttle_output,
            )
            shuttle_response = json.loads(shuttle_output.getvalue())
            assert shuttle_response["ok"] is True
            assert shuttle_response["data"] == {"status": "bound"}
            app.clipboard().clear()
            assert js("typeof window.__agentClipboard === 'undefined'") is True
            handoff_token = bind_request["payload"]["handoff_token"]
            public_handoff_state = str(
                js("JSON.stringify(window.ReweavePrototype.getState())")
            )
            handoff_markup = str(js("document.documentElement.outerHTML"))
            handoff_visible = str(js("document.body.innerText"))
            assert handoff_token not in public_handoff_state
            assert handoff_token not in handoff_markup
            assert handoff_token not in handoff_visible
            assert "stdin" in handoff_visible
            screenshot_path = os.environ.get(
                "REWEAVE_HANDOFF_SCREENSHOT_PATH"
            )
            if screenshot_path:
                window.resize(1100, 720)
                pump(0.2)
                screenshot = window.centralWidget().grab()
                assert screenshot.size().width() == 1100
                assert screenshot.size().height() == 720
                assert screenshot.save(screenshot_path)
                window.resize(1280, 820)
                pump(0.1)
            js("document.getElementById('btn-revoke-agent-handoff').focus(); true")
            assert js(
                "document.activeElement.id === 'btn-revoke-agent-handoff'"
            ) is True
            js("document.getElementById('btn-revoke-agent-handoff').click(); true")
            wait_js(
                "window.ReweavePrototype.getState().productPlan.agent_handoff_status === 'revoked'",
                30,
                "revoked Agent handoff",
            )
            assert bridge_calls.count("revoke_local_agent_handoff") == 1

            original_clipboard_copy = desktop._copy_to_system_clipboard

            def fail_clipboard_copy(_value):
                raise RuntimeError("clipboard denied")

            desktop._copy_to_system_clipboard = fail_clipboard_copy
            js("document.getElementById('btn-reissue-agent-handoff').click(); true")
            wait_js(
                "window.ReweavePrototype.getState().productPlan.agent_handoff_status === 'revoked' && "
                "document.getElementById('product-agent-handoff-error').textContent === "
                "'agent_handoff_clipboard_failed'",
                30,
                "clipboard failure revokes handoff",
            )
            desktop._copy_to_system_clipboard = original_clipboard_copy
            assert handoff_state["attempt"] == 2
            assert bridge_calls.count("revoke_local_agent_handoff") == 1
            assert bridge_calls.count("start_confirmed_product_candidate") == 0
            js("document.getElementById('btn-direct-after-handoff').click(); true")
            wait_js(
                "window.ReweavePrototype.getState().productPlan.candidate_status === 'review_ready'",
                180,
                "review-ready candidate after explicit direct choice",
            )
            assert bridge_calls.count("start_confirmed_product_candidate") == 1
            assert_product_frame()
            candidate_records = list(
                (state_dir / "product_candidates").glob("*/candidate.json")
            )
            assert len(candidate_records) == 1
            candidate_record = json.loads(
                candidate_records[0].read_text(encoding="utf-8")
            )
            candidate_token = candidate_record["candidate_token"]
            candidate = service.get_product_candidate(
                {"candidate_token": candidate_token}
            )["data"]
            assert candidate["schema_version"] == "product_candidate.v2"
            assert candidate["status"] == "review_ready"
            assert candidate["acceptance"]["runtime_operational"] == "passed"
            assert candidate["acceptance"]["product_goal_conformance"] == "passed"
            assert [
                (
                    row["input"]["quantity"],
                    row["expected_output"]["total"],
                    row["actual_output"]["total"],
                )
                for row in candidate["acceptance"]["cases"]
            ] == [(1, 10, 10), (3, 30, 30), (10, 100, 100)]
            assert len(candidate["files"]) == 7
            assert {
                row["path"] for row in candidate["provenance"]["file_provenance"]
            } == {row["path"] for row in candidate["files"]}

            js("document.getElementById('btn-preview-product-candidate').click(); true")
            deadline = time.monotonic() + 30
            while not bridge._candidate_preview_windows and time.monotonic() < deadline:
                pump(0.08)
            assert len(bridge._candidate_preview_windows) == 1
            preview = bridge._candidate_preview_windows[0]
            preview_page = preview.centralWidget().page()

            def preview_js(expression: str, timeout: float = 20) -> object:
                result: list[object] = []
                preview_page.runJavaScript(expression, result.append)
                deadline = time.monotonic() + timeout
                while not result and time.monotonic() < deadline:
                    pump()
                if not result:
                    raise TimeoutError("preview_javascript_callback_timeout")
                return result[0]

            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if preview_js(
                    "document.readyState === 'complete' && "
                    "!!document.querySelector('[data-ref=quantity]')"
                ):
                    break
                pump(0.08)
            else:
                raise TimeoutError("candidate preview did not load")
            preview_js(
                "(() => { const quantity=document.querySelector('[data-ref=quantity]'); "
                "quantity.value='3'; document.querySelector('[data-action=calculate]').click(); "
                "return true; })()"
            )
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if str(
                    preview_js(
                        "document.querySelector('[data-ref=total]').textContent"
                    )
                ) == "30":
                    break
                pump(0.08)
            else:
                raise AssertionError("candidate preview returned the wrong total")
            assert (
                preview_page.acceptNavigationRequest(
                    QUrl("https://example.invalid/"), None, True
                )
                is False
            )
            assert (
                preview_page.acceptNavigationRequest(
                    QUrl.fromLocalFile(str(source_root / "outside.js")),
                    None,
                    False,
                )
                is False
            )
            assert (
                preview_page.settings().testAttribute(
                    qt_parts[3].LocalContentCanAccessRemoteUrls
                )
                is False
            )

            js("document.getElementById('btn-save-product-candidate').click(); true")
            wait_js(
                "document.getElementById('product-candidate-action-result').textContent.includes('保存')",
                30,
                "candidate saved",
            )
            saved_roots = [item for item in export_parent.iterdir() if item.is_dir()]
            assert len(saved_roots) == 1
            saved_root = saved_roots[0]
            for metadata in candidate["files"]:
                exported = saved_root / metadata["path"]
                assert exported.is_file() and not exported.is_symlink()
                assert hashlib.sha256(exported.read_bytes()).hexdigest() == (
                    metadata["sha256"]
                )
            js("document.getElementById('btn-save-product-candidate').click(); true")
            wait_js(
                "document.getElementById('product-candidate-action-result').textContent.includes('已经')",
                30,
                "candidate save idempotency",
            )
            assert len(list(export_parent.iterdir())) == 1

            public_state = str(
                js("JSON.stringify(window.ReweavePrototype.getState())")
            )
            markup = str(js("document.documentElement.outerHTML"))
            visible = str(js("document.body.innerText"))
            for secret in (
                plan_token,
                candidate_token,
                str(tmp_path),
                "workspace_id",
                "candidate_id",
                ".sqlite3",
            ):
                assert secret not in public_state
                assert secret not in markup
                assert secret not in visible

            first_candidate_digest = candidate["candidate_digest"]
            first_file_hashes = {
                item["path"]: item["sha256"] for item in candidate["files"]
            }
            first_confirmation = copy.deepcopy(planner.confirmation)
            first_acceptance = copy.deepcopy(planner.acceptance_confirmation)

        close_window(window)
        window = None
        restarted_planner = DesktopPlanner(
            status="confirmed",
            confirmation=first_confirmation,
            acceptance_confirmation=first_acceptance,
        )
        restarted_service = ReweaveAppService(
            _NoLegacyEngine(),
            capsule_store=store,
        )
        restarted_service._product_planner = restarted_planner
        with (
            patch.object(
                desktop,
                "import_qt_webengine",
                return_value=(*qt_parts[:5], FixedDirectoryDialog),
            ),
            patch.object(
                desktop,
                "ReweaveAppService",
                return_value=restarted_service,
            ),
        ):
            restarted_window, _restarted_bridge = desktop.create_reweave_window()
            restarted_page = restarted_window.centralWidget().page()
            restarted_window.show()

            def restarted_js(expression: str, timeout: float = 20) -> object:
                result: list[object] = []
                restarted_page.runJavaScript(expression, result.append)
                deadline = time.monotonic() + timeout
                while not result and time.monotonic() < deadline:
                    pump()
                if not result:
                    raise TimeoutError("restart_javascript_callback_timeout")
                return result[0]

            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if restarted_js(
                    "document.readyState === 'complete' && !!window.reweaveBridge"
                ):
                    break
                pump(0.08)
            else:
                raise TimeoutError("restarted desktop did not load")
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if restarted_js(
                    "window.ReweavePrototype.getState().productPlan.view === 'handoff' && "
                    "window.ReweavePrototype.getState().productPlan.agent_handoff_status === "
                    "'revoked'"
                ):
                    break
                pump(0.08)
            else:
                raise TimeoutError("revoked handoff did not restore")
            assert restarted_js(
                "window.ReweavePrototype.getState().productPlan.candidate_status === null"
            ) is True
            assert restarted_js(
                "!document.getElementById('btn-direct-after-handoff').classList.contains('hidden')"
            ) is True
            restarted_js(
                "document.getElementById('btn-direct-after-handoff').focus();"
                "document.getElementById('btn-direct-after-handoff').click(); true"
            )
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                if restarted_js(
                    "window.ReweavePrototype.getState().productPlan.candidate_status === "
                    "'review_ready'"
                ):
                    break
                pump(0.08)
            else:
                raise TimeoutError("explicit candidate restore failed")
            restored = restarted_service.get_product_candidate(
                {"candidate_token": candidate_token}
            )
            assert restored["ok"], restored
            assert restored["data"]["candidate_digest"] == first_candidate_digest
            assert {
                item["path"]: item["sha256"] for item in restored["data"]["files"]
            } == first_file_hashes
            for relative_path, expected_hash in first_file_hashes.items():
                opened = restarted_service.read_product_candidate_file(
                    {
                        "candidate_token": candidate_token,
                        "relative_path": relative_path,
                    }
                )
                assert opened["ok"], opened
                assert opened["data"]["sha256"] == expected_hash

        assert _store_snapshot(store) == warehouse_before
        assert _usage_state(store) == usage_before
        assert _tree_state(source_root) == source_before
        assert _tree_state(target_root) == target_before
        assert _tree_state(state_dir / "products") == products_before
    finally:
        close_window(restarted_window)
        close_window(window)
        if restarted_service is not None:
            restarted_service.close()
        service.close()


def test_multi_gap_question_ui_stops_before_plan_or_candidate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("REWEAVE_PRODUCT_FLOW_CHILD", "1")
    monkeypatch.setenv("REWEAVE_MULTI_GAP_QUESTION_ONLY", "1")
    test_product_flow_builds_previews_exports_and_restores_real_candidate(
        tmp_path,
        monkeypatch,
    )


def test_gap_target_no_match_stops_with_explicit_copy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("REWEAVE_PRODUCT_FLOW_CHILD", "1")
    monkeypatch.setenv("REWEAVE_GAP_NO_MATCH_ONLY", "1")
    test_product_flow_builds_previews_exports_and_restores_real_candidate(
        tmp_path,
        monkeypatch,
    )


def test_static_web_target_review_ui_with_real_service(
    tmp_path: Path, monkeypatch, caplog
) -> None:
    if shutil.which("node") is None:
        pytest.skip("Node is required for module_native composition")
    if not (ROOT / "node_modules" / "esbuild" / "package.json").is_file():
        pytest.skip("npm ci is required for module_native composition")
    if sys.platform.startswith("linux") and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        pytest.skip("A desktop GUI session is required")
    pytest.importorskip("PySide6.QtWebEngineCore")

    # The default Chromium profile outlives a closed window on macOS; this
    # acceptance needs a fresh process so its isolated cache paths stay safe.
    if os.environ.get("REWEAVE_REAL_E2E_CHILD") != "1":
        child_env = os.environ.copy()
        child_env["REWEAVE_REAL_E2E_CHILD"] = "1"
        child_env.pop("PYTEST_ADDOPTS", None)
        child = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                "-q",
                (
                    "tests/test_reweave_phase6_desktop.py::"
                    "test_static_web_target_review_ui_with_real_service"
                ),
            ],
            cwd=ROOT,
            env=child_env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert child.returncode == 0, child.stdout + child.stderr
        return

    from PySide6.QtCore import QCoreApplication, QEvent, qInstallMessageHandler
    from PySide6.QtWebEngineCore import QWebEngineProfile

    from pimos_lite import desktop_reweave_static as desktop
    from pimos_lite.composer.module_native import compose_capsule_product
    from pimos_lite.reweave_app_service import ReweaveAppService
    from pimos_lite.reweave_capsule_store import CapsuleWarehouseStore
    from tests.test_reweave_phase5_generation import _seed_capsule

    configured_target = os.environ.get("REWEAVE_SNAKE_JS_CHECKOUT", "").strip()
    fixed_snake_input = bool(configured_target)
    if fixed_snake_input:
        target = Path(configured_target).expanduser().resolve(strict=True)
        repository = SNAKE_JS_REPOSITORY
    else:
        target = tmp_path / "static-web-target"
        target.mkdir()
        (target / "index.html").write_text(
            "<!doctype html><html><head><link rel=\"stylesheet\" href=\"./styles.css\">"
            "</head><body><h1>Static target</h1>"
            "<script type=\"module\" src=\"./main.js\"></script></body></html>\n",
            encoding="utf-8",
        )
        (target / "styles.css").write_text("body { color: #222; }\n", encoding="utf-8")
        (target / "main.js").write_text(
            'import { value } from "./value.js";\nconsole.log(value);\n',
            encoding="utf-8",
        )
        (target / "value.js").write_text("export const value = 1;\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=target, check=True)
        subprocess.run(["git", "add", "."], cwd=target, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Reweave E2E",
                "-c",
                "user.email=reweave-e2e@example.invalid",
                "commit",
                "-qm",
                "fixture",
            ],
            cwd=target,
            check=True,
        )
        repository = "local-static-web-fixture"

    git_before = _git_target_state(target)
    if fixed_snake_input:
        assert git_before["head"] == SNAKE_JS_COMMIT
        origin = subprocess.run(
            ["git", "-C", str(target), "remote", "get-url", "origin"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert origin.removesuffix(".git") == SNAKE_JS_REPOSITORY
    assert git_before["status_clean"] is True

    state = tmp_path / "state"
    monkeypatch.setenv("REWEAVE_STATE_DIR", str(state))
    store = CapsuleWarehouseStore(state / "capsule_warehouse.sqlite3")
    store.initialize()
    capsule_ids: list[str] = []
    for kind in ("presentation", "interaction", "computation"):
        capsule_id, _version_id = _seed_capsule(store, kind)
        capsule_ids.append(capsule_id)

    class ObservedService(ReweaveAppService):
        def __init__(self) -> None:
            super().__init__(capsule_store=store)
            self.target_calls: list[str] = []
            self.profile_result: dict[str, object] | None = None
            self.patch_result: dict[str, object] | None = None

        def analyze_static_web_target(
            self, payload: dict[str, object] | None = None
        ) -> dict[str, object]:
            self.target_calls.append("analyze_static_web_target")
            result = super().analyze_static_web_target(payload)
            self.profile_result = result
            return result

        def generate_static_web_patch(
            self, payload: dict[str, object] | None = None
        ) -> dict[str, object]:
            self.target_calls.append("generate_static_web_patch")
            result = super().generate_static_web_patch(payload)
            self.patch_result = result
            return result

    service = ObservedService()
    initial_state = service.get_initial_state()
    eligible_ids = {
        row["capsule_id"]
        for row in initial_state["warehouseCapsules"]
        if row["generation_eligible"] is True
    }
    assert eligible_ids == set(capsule_ids)

    target_before = _tree_state(target, exclude_git=True)
    warehouse_revision_before = store.current_revision()
    usage_before = _usage_state(store)
    products_before = _tree_state(state / "products")

    class FixedDirectoryDialog:
        calls = 0

        @staticmethod
        def getExistingDirectory(*_args, **_kwargs) -> str:
            FixedDirectoryDialog.calls += 1
            return str(target)

    qt_parts = desktop.import_qt_webengine()
    QApplication = qt_parts[0]
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    profile = QWebEngineProfile.defaultProfile()
    qweb_cache = tmp_path / "qweb-cache"
    qweb_storage = tmp_path / "qweb-storage"
    profile.setCachePath(str(qweb_cache))
    profile.setPersistentStoragePath(str(qweb_storage))
    qt_messages: list[str] = []

    def qt_message_handler(_mode, _context, message) -> None:
        qt_messages.append(str(message))

    previous_qt_handler = qInstallMessageHandler(qt_message_handler)
    caplog.set_level(10, logger="reweave.desktop")
    window = None
    patch_data: dict[str, object] | None = None
    profile_data: dict[str, object] | None = None
    developer_evidence: dict[str, object] | None = None
    integration_state: dict[str, object] | None = None
    dom_probe: dict[str, object] | None = None
    review_text = ""
    bridge_calls_before_confirm: list[str] = []
    bridge_calls_after_confirm: list[str] = []
    composer_calls = 0

    def pump(seconds: float = 0.03) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.005)

    try:
        with (
            patch.object(
                desktop,
                "import_qt_webengine",
                return_value=(*qt_parts[:5], FixedDirectoryDialog),
            ),
            patch.object(desktop, "ReweaveAppService", return_value=service),
            patch(
                "pimos_lite.reweave_app_service.compose_capsule_product",
                wraps=compose_capsule_product,
            ) as composer,
        ):
            window, bridge = desktop.create_reweave_window()
            assert bridge._engine is service
            page = window.centralWidget().page()
            window.show()

            def js(expression: str, timeout: float = 20.0) -> object:
                result: list[object] = []
                page.runJavaScript(expression, result.append)
                deadline = time.monotonic() + timeout
                while not result and time.monotonic() < deadline:
                    pump()
                if not result:
                    raise TimeoutError("javascript_callback_timeout")
                return result[0]

            def wait_js(expression: str, timeout: float, label: str) -> object:
                deadline = time.monotonic() + timeout
                last: object = None
                while time.monotonic() < deadline:
                    last = js(expression)
                    if last:
                        return last
                    pump(0.08)
                raise TimeoutError(f"{label}:{last!r}")

            wait_js(
                "document.readyState === 'complete' && !!window.reweaveBridge && "
                "!document.getElementById('screen-product-plan').classList.contains('hidden')",
                30,
                "desktop_bridge",
            )
            assert js(
                "(() => {"
                "window.__reweaveBridgeCalls=[];"
                "const transport=qt.webChannelTransport;"
                "const send=transport.send.bind(transport);"
                "transport.send=function(raw){"
                "try { const data=typeof raw==='string' ? JSON.parse(raw) : raw;"
                "if(data && data.type===6 && data.object==='reweaveBridge') "
                "window.__reweaveBridgeCalls.push(String(data.method)); } catch (_) {}"
                "return send(raw); };"
                "return true;})()"
            ) is True
            js("document.getElementById('btn-open-target').click(); true")
            wait_js(
                "!document.getElementById('screen-target').classList.contains('hidden')",
                10,
                "target_screen",
            )
            js("document.getElementById('btn-select-target').click(); true")
            wait_js(
                "document.getElementById('target-selected-name').textContent.includes("
                + json.dumps(target.name)
                + ")",
                10,
                "target_selection",
            )
            assert FixedDirectoryDialog.calls == 1

            js("document.getElementById('btn-analyze-target').click(); true")
            wait_js(
                "!document.getElementById('target-profile-summary').classList.contains('hidden')",
                30,
                "target_profile",
            )
            assert service.profile_result and service.profile_result.get("ok") is True
            profile_data = service.profile_result["data"]

            for capsule_id in capsule_ids:
                clicked = js(
                    "(() => { const input = document.querySelector("
                    + json.dumps(
                        f'#target-capsule-cards input[value="{capsule_id}"]'
                    )
                    + "); if (!input) return false; input.click(); return true; })()"
                )
                assert clicked is True
            wait_js(
                "document.querySelectorAll('#target-capsule-cards input:checked').length === 3",
                10,
                "capsule_selection",
            )
            js(
                "(() => { const task=document.getElementById('target-task');"
                "task.value='Add quote calculator';"
                "task.dispatchEvent(new Event('input',{bubbles:true})); return true; })()"
            )
            wait_js(
                "!document.getElementById('btn-generate-target-patch').disabled",
                10,
                "generate_enabled",
            )
            js("document.getElementById('btn-generate-target-patch').click(); true")
            wait_js(
                "document.getElementById('screen-target').getAttribute('data-target-stage') === 'review' && "
                "!document.getElementById('target-review').hasAttribute('hidden') && "
                "document.getElementById('target-file-diffs').textContent.trim().length > 0 && "
                "document.getElementById('target-evidence-summary').textContent.trim().length > 0",
                60,
                "patch_review",
            )
            assert service.patch_result and service.patch_result.get("ok") is True
            patch_data = service.patch_result["data"]
            assert composer.call_count == 1
            composer_calls = composer.call_count
            assert patch_data["weave_plan"]["validation_steps"] == (
                TARGET_VALIDATION_STEPS
            )
            assert patch_data["evidence"]["status"] == "passed"
            assert [row["name"] for row in patch_data["evidence"]["checks"]] == (
                TARGET_EVIDENCE_CHECKS
            )
            assert all(
                row["passed"] is True for row in patch_data["evidence"]["checks"]
            )
            assert patch_data["evidence"]["target_project_write"] is False
            assert patch_data["evidence"]["product_store_write"] is False
            assert patch_data["evidence"]["usage_registration_write"] is False

            developer_text = str(
                js("document.getElementById('target-patch-developer').textContent")
            )
            developer_evidence = json.loads(developer_text)
            assert "after_content" not in developer_text
            assert developer_evidence["plan_id"] == patch_data["plan_id"]
            assert developer_evidence["target"]["snapshot_sha256"] == profile_data[
                "snapshot_sha256"
            ]
            assert {
                (row["capsule_id"], row["version_id"], row["canonical_hash"])
                for row in developer_evidence["weave_plan"]["capsules"]
            } == {
                (row["capsule_id"], row["version_id"], row["canonical_hash"])
                for row in patch_data["weave_plan"]["capsules"]
            }
            review_text = str(js("document.getElementById('target-review').textContent"))
            assert js(
                "document.querySelector('#target-review iframe[data-reweave-plan]') === null"
            )

            js("document.getElementById('target-developer-mode').click(); true")
            wait_js(
                "document.getElementById('screen-target').classList.contains('developer-mode')",
                10,
                "developer_mode",
            )
            bridge_calls_before_confirm = json.loads(
                str(js("JSON.stringify(window.__reweaveBridgeCalls)"))
            )
            js("document.getElementById('btn-confirm-target-patch').click(); true")
            wait_js(
                "document.getElementById('screen-target').getAttribute('data-target-stage') === 'confirmed' && "
                "document.getElementById('target-confirmation-receipt').textContent.trim().length > 0",
                10,
                "confirmation_receipt",
            )
            pump(0.2)
            bridge_calls_after_confirm = json.loads(
                str(js("JSON.stringify(window.__reweaveBridgeCalls)"))
            )
            assert bridge_calls_before_confirm == bridge_calls_after_confirm == [
                "choose_static_web_target",
                "analyze_static_web_target",
                "generate_static_web_patch",
            ]
            assert service.target_calls == [
                "analyze_static_web_target",
                "generate_static_web_patch",
            ]
            integration_state = json.loads(
                str(js("JSON.stringify(window.ReweavePrototype.getState().target)"))
            )
            assert integration_state == {
                "available": True,
                "profileReady": True,
                "patchReady": True,
                "planId": patch_data["plan_id"],
                "confirmed": True,
                "stage": "confirmed",
                "developerMode": True,
            }
            dom_probe = json.loads(
                str(
                    js(
                        "JSON.stringify({"
                        "text:document.body.textContent,"
                        "html:document.documentElement.outerHTML,"
                        "values:Array.from(document.querySelectorAll('input,textarea')).map(el=>el.value),"
                        "local:Object.keys(localStorage).sort().map(key=>[key,localStorage.getItem(key)]),"
                        "session:Object.keys(sessionStorage).sort().map(key=>[key,sessionStorage.getItem(key)])"
                        "})"
                    )
                )
            )
            assert str(target) not in json.dumps(dom_probe, ensure_ascii=False)
    finally:
        if window is not None:
            window.close()
            window.deleteLater()
            pump()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            app.processEvents()
        qInstallMessageHandler(previous_qt_handler)
        service.close()

    assert patch_data is not None
    assert profile_data is not None
    assert developer_evidence is not None
    assert integration_state is not None
    assert dom_probe is not None
    assert str(target) not in caplog.text
    assert all(str(target) not in message for message in qt_messages)
    target_path_bytes = str(target).encode("utf-8")
    assert not _contains_bytes(state, target_path_bytes)
    assert not _contains_bytes(qweb_cache, target_path_bytes)
    assert not _contains_bytes(qweb_storage, target_path_bytes)

    target_after = _tree_state(target, exclude_git=True)
    git_after = _git_target_state(target)
    warehouse_revision_after = store.current_revision()
    usage_after = _usage_state(store)
    products_after = _tree_state(state / "products")
    assert target_after == target_before
    assert git_after == git_before
    assert warehouse_revision_after == warehouse_revision_before
    assert usage_after == usage_before
    assert products_after == products_before

    patch_sha256 = _canonical_sha256(patch_data)
    plan3_acceptance = json.loads(
        (ROOT / "docs" / "reports" / "REWEAVE_STATIC_WEB_TARGET_PATCH_ACCEPTANCE.json").read_text(
            encoding="utf-8"
        )
    )
    if fixed_snake_input:
        assert profile_data["snapshot_sha256"] == SNAKE_JS_SNAPSHOT
        assert profile_data["snapshot_sha256"] == (
            plan3_acceptance["target"]["snapshot_sha256"]
        )
        assert patch_data["plan_id"] == SNAKE_JS_PLAN_ID
        assert patch_sha256 == SNAKE_JS_PATCH_SHA256

    capsule_versions = sorted(
        [
            {
                "capsule_id": row["capsule_id"],
                "version_id": row["version_id"],
                "canonical_hash": row["canonical_hash"],
                "capability_kind": row["capability_kind"],
            }
            for row in patch_data["weave_plan"]["capsules"]
        ],
        key=lambda row: (row["capsule_id"], row["version_id"]),
    )
    receipt: dict[str, object] = {
        "schema_version": "reweave_static_web_target_real_e2e_acceptance.v1",
        "completed_date": "2026-07-19",
        "verdict": "PASS",
        "input": {
            "repository": repository,
            "commit": git_before["head"],
            "entry_path": "index.html",
            "target_snapshot_sha256": profile_data["snapshot_sha256"],
            "target_git_clean_before": git_before["status_clean"],
            "target_git_clean_after": git_after["status_clean"],
        },
        "runtime_path": {
            "acceptance_scope": "real_qwebengine_real_bridge_real_app_service",
            "analyze_generate_stubbed": False,
            "target_bridge_calls": bridge_calls_after_confirm,
            "confirmation_bridge_calls": len(bridge_calls_after_confirm)
            - len(bridge_calls_before_confirm),
            "composer_version": patch_data["composer"]["composer_version"],
            "composer_calls": composer_calls,
        },
        "review": {
            "profile_schema": profile_data["schema_version"],
            "patch_schema": patch_data["schema_version"],
            "patch_status": patch_data["status"],
            "authorization_mode": patch_data["authorization"]["mode"],
            "strategy": patch_data["strategy"],
            "plan_id": patch_data["plan_id"],
            "patch_sha256": patch_sha256,
            "target_snapshot_sha256": profile_data["snapshot_sha256"],
            "capsule_versions": capsule_versions,
            "file_diff_visible": bool(review_text.strip()),
            "validation_evidence_visible": True,
            "validation_steps": patch_data["weave_plan"]["validation_steps"],
            "evidence_checks": patch_data["evidence"]["checks"],
            "developer_mode_completed": True,
        },
        "confirmation": {
            "kind": "in_memory_review_receipt",
            "confirmed": integration_state["confirmed"],
            "frontend_binding": {
                "plan_id": integration_state["planId"],
                "target_snapshot_sha256": profile_data["snapshot_sha256"],
            },
            "e2e_acceptance_binding": {
                "plan_id": patch_data["plan_id"],
                "target_snapshot_sha256": profile_data["snapshot_sha256"],
                "patch_sha256": patch_sha256,
                "capsule_versions": capsule_versions,
            },
            "bridge_call": False,
            "write_authorization": False,
        },
        "display_safety": {
            "target_absolute_path_in_dom": False,
            "target_absolute_path_in_log": False,
            "target_absolute_path_persisted": False,
            "after_content_rendered": False,
            "after_content_executed": False,
        },
        "plan3_contract": {
            "reference": "docs/reports/REWEAVE_STATIC_WEB_TARGET_PATCH_ACCEPTANCE.json",
            "target_snapshot_match": fixed_snake_input,
            "patch_schema_match": patch_data["schema_version"]
            == plan3_acceptance["patch"]["schema_version"],
            "patch_status_match": patch_data["status"]
            == plan3_acceptance["patch"]["status"],
            "strategy_match": patch_data["strategy"]
            == plan3_acceptance["patch"]["strategy"],
            "authorization_match": patch_data["authorization"]
            == plan3_acceptance["authorization"],
            "content_addressed_plan_id_consistent": patch_data["plan_id"]
            == patch_data["weave_plan"]["plan_id"],
            "fixed_input_plan_id_match": (
                patch_data["plan_id"] == SNAKE_JS_PLAN_ID
                if fixed_snake_input
                else None
            ),
            "fixed_input_patch_digest_match": (
                patch_sha256 == SNAKE_JS_PATCH_SHA256
                if fixed_snake_input
                else None
            ),
            "validation_steps_match": patch_data["weave_plan"]["validation_steps"]
            == TARGET_VALIDATION_STEPS,
            "evidence_checks_match": [
                row["name"] for row in patch_data["evidence"]["checks"]
            ]
            == TARGET_EVIDENCE_CHECKS,
            "evidence_all_passed": all(
                row["passed"] is True for row in patch_data["evidence"]["checks"]
            ),
        },
        "state_evidence": {
            "target_tree": {"before": target_before, "after": target_after},
            "target_git": {"before": git_before, "after": git_after},
            "warehouse_revision": {
                "before": warehouse_revision_before,
                "after": warehouse_revision_after,
            },
            "product_directory": {
                "before": products_before,
                "after": products_after,
            },
            "product_capsule_usage": {
                "before": usage_before,
                "after": usage_after,
            },
        },
        "zero_writes": {
            "target_tree_unchanged": target_after == target_before,
            "target_git_head_unchanged": git_after["head"] == git_before["head"],
            "target_git_status_unchanged": git_after["status_sha256"]
            == git_before["status_sha256"],
            "warehouse_revision_unchanged": warehouse_revision_after
            == warehouse_revision_before,
            "product_directory_unchanged": products_after == products_before,
            "product_capsule_usage_unchanged": usage_after == usage_before,
            "target_project_write": False,
            "product_store_write": False,
            "usage_registration_write": False,
            "apply": False,
            "commit": False,
            "rollback": False,
        },
        "scope_limit": {
            "target_apply_supported": False,
            "target_commit_supported": False,
            "target_rollback_supported": False,
            "target_cli_added": False,
            "react_vite_supported": False,
            "node_target_supported": False,
            "general_adapter_supported": False,
            "stage_g_modified": False,
        },
        "verification": {"real_e2e": {"passed": 1, "failed": 0}},
    }
    receipt["acceptance_sha256"] = _canonical_sha256(receipt)
    receipt_output = os.environ.get("REWEAVE_REAL_E2E_RECEIPT_PATH", "").strip()
    if receipt_output:
        Path(receipt_output).write_text(
            json.dumps(receipt, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def test_phase6_desktop_end_to_end_without_reload(tmp_path: Path, monkeypatch) -> None:
    if shutil.which("node") is None:
        pytest.skip("Node is required for Stage 6 generation")
    if not (ROOT / "node_modules" / "esbuild" / "package.json").is_file():
        pytest.skip("npm ci is required for Stage 6 generation")
    if sys.platform.startswith("linux") and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        pytest.skip("A desktop GUI session is required for Stage 6")

    pytest.importorskip("PySide6.QtWebEngineCore")
    from PySide6.QtCore import QCoreApplication, QEvent, QUrl
    from PySide6.QtWebEngineCore import (
        QWebEnginePage,
        QWebEngineProfile,
        QWebEngineSettings,
        QWebEngineUrlRequestInterceptor,
    )
    from PySide6.QtWebEngineWidgets import QWebEngineView

    source = tmp_path / "source"
    state = tmp_path / "state"
    shutil.copytree(FIXTURE, source)
    monkeypatch.setenv("REWEAVE_STATE_DIR", str(state))

    def source_snapshot() -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for path in sorted(source.rglob("*")):
            info = path.lstat()
            row: dict[str, object] = {
                "path": path.relative_to(source).as_posix(),
                "mode": stat.S_IMODE(info.st_mode),
                "mtime_ns": info.st_mtime_ns,
                "kind": "dir" if path.is_dir() else "file",
            }
            if path.is_file():
                content = path.read_bytes()
                row.update(
                    size=len(content), sha256=hashlib.sha256(content).hexdigest()
                )
            rows.append(row)
        return rows

    source_before = source_snapshot()
    model_name = "phase6-test-model"
    model_digest = "d" * 64

    class OllamaHandler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self._send({"models": [{"name": model_name, "digest": model_digest}]})

        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length))
            match = re.search(
                r'"capability_kind":"(presentation|interaction|computation)"',
                str(body.get("prompt") or ""),
            )
            kind = match.group(1) if match else "invalid"
            self._send(
                {
                    "response": json.dumps(
                        {
                            "schema_version": "capsule_supervision.v1",
                            "verdict": "approve",
                            "capability_kind": kind,
                            "semantic_summary": "Approved local quote capability.",
                            "keep_reason_codes": ["DECLARED_LOCAL_CAPABILITY"],
                            "remove_reason_codes": [],
                            "brand_signals": [],
                            "sensitive_data_status": "clear",
                            "hidden_dependency_codes": [],
                            "duplicate_suggestions": [],
                            "review_required": False,
                        },
                        sort_keys=True,
                    )
                }
            )

        def _send(self, value: object) -> None:
            encoded = json.dumps(value).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, _format, *_args) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), OllamaHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    from pimos_lite import desktop_reweave_static as desktop
    from pimos_lite.reweave_app_service import (
        ReweaveAppService,
        _canonical_manifest_bytes,
    )

    service = ReweaveAppService(
        ollama_base_url=f"http://127.0.0.1:{server.server_port}"
    )
    qt_parts = desktop.import_qt_webengine()
    QApplication = qt_parts[0]

    class FixedDirectoryDialog:
        @staticmethod
        def getExistingDirectory(*_args, **_kwargs) -> str:
            return str(source)

    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Reweave Stage 6 Test")
    window = None
    product_view = None
    product_page = None
    product_profile = None

    def pump(seconds: float = 0.01) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.005)

    def flush_deletes() -> None:
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()

    try:
        with (
            patch.object(
                desktop,
                "import_qt_webengine",
                return_value=(*qt_parts[:5], FixedDirectoryDialog),
            ),
            patch.object(desktop, "ReweaveAppService", return_value=service),
        ):
            window, bridge = desktop.create_reweave_window()
            assert bridge._engine is service
            view = window.centralWidget()
            page = view.page()
            window.show()

            def js(expression: str, timeout: float = 10.0, *, target=None):
                result: list[object] = []
                (target or page).runJavaScript(expression, result.append)
                deadline = time.monotonic() + timeout
                while not result and time.monotonic() < deadline:
                    pump()
                if not result:
                    raise TimeoutError("JavaScript callback timed out")
                return result[0]

            def wait_js(
                expression: str, timeout: float, label: str, *, target=None
            ):
                deadline = time.monotonic() + timeout
                last = None
                while time.monotonic() < deadline:
                    last = js(expression, target=target)
                    if last:
                        return last
                    pump(0.08)
                raise TimeoutError(f"{label}: last={last!r}")

            wait_js(
                "document.readyState === 'complete' && !!window.reweaveBridge",
                30,
                "desktop frontend bridge",
            )
            js(
                "window.__phase6_document_token = 'same-document'; "
                "document.getElementById('btn-view-runtime').click(); true"
            )
            wait_js(
                "!document.getElementById('screen-main').classList.contains('hidden')",
                10,
                "main screen",
            )
            assert window.isVisible()

            js("document.getElementById('btn-capsule-warehouse').click(); true")
            wait_js(
                "!document.getElementById('screen-capsule-warehouse').classList.contains('hidden') && "
                "!document.getElementById('btn-open-capsule-ingestion').classList.contains('hidden')",
                10,
                "empty warehouse management entry",
            )
            js("document.getElementById('btn-open-capsule-ingestion').click(); true")
            assert js(
                "!document.getElementById('warehouse-developer-mode').checked && "
                "!document.getElementById('capsule-warehouse-popover').classList.contains('developer-mode') && "
                "document.getElementById('capsule-ingestion-specimen').classList.contains('is-empty')"
            )
            assert js(
                "document.getElementById('capsule-warehouse-popover').title.length > 0 && "
                "document.getElementById('btn-warehouse-discover').title.length > 0 && "
                "getComputedStyle(document.getElementById('btn-warehouse-refresh-all')).display === 'none'"
            )
            assert js(
                "(() => { const toggle = document.getElementById('warehouse-developer-mode'); "
                "toggle.click(); return toggle.checked && "
                "document.getElementById('capsule-warehouse-popover').classList.contains('developer-mode') && "
                "getComputedStyle(document.getElementById('btn-warehouse-refresh-all')).display !== 'none'; })()"
            )
            js("document.getElementById('warehouse-developer-mode').click(); true")
            wait_js(
                "Array.from(document.querySelectorAll('#supervision-model-select option'))"
                f".some(option => option.textContent.startsWith('{model_name}'))",
                30,
                "supervision model list",
            )
            assert (
                js(
                    """(() => {
                      const select = document.getElementById('supervision-model-select');
                      const option = Array.from(select.options).find(
                        item => item.textContent.startsWith('phase6-test-model')
                      );
                      if (!option) return false;
                      select.value = option.value;
                      document.getElementById('btn-supervision-model-save').click();
                      return true;
                    })()"""
                )
                is True
            )
            deadline = time.monotonic() + 30
            selected = None
            while time.monotonic() < deadline:
                try:
                    selected = service._capsule_supervisor.selected_model()
                except Exception:
                    selected = None
                if selected and selected.get("name") == model_name:
                    break
                pump(0.08)
            assert selected and selected["digest"] == model_digest

            js("document.getElementById('btn-warehouse-discover').click(); true")
            wait_js(
                "!!document.querySelector('#warehouse-projects .warehouse-discovery')",
                30,
                "source discovery",
            )
            with service._capsule_store.read_connection() as connection:
                discovered_root = connection.execute(
                    "SELECT root_id FROM source_roots WHERE current_path = ?",
                    (str(source.resolve()),),
                ).fetchone()
            assert discovered_root is not None
            discovered_root_id = str(discovered_root["root_id"])
            selected_root = json.loads(
                str(
                    js(
                        """JSON.stringify((() => {
                          const controls = Array.from(document.querySelectorAll(
                            '#warehouse-projects select[data-source-root-selector="session"]'
                          ));
                          return {
                            count: controls.length,
                            selected: controls.map(item => item.value),
                            labels: controls.map(
                              item => item.options[item.selectedIndex]?.textContent || ''
                            ),
                            html: document.getElementById('warehouse-projects').outerHTML
                          };
                        })())"""
                    )
                )
            )
            assert selected_root["count"] == 2
            assert selected_root["selected"] == ["0", "0"]
            assert all(
                re.fullmatch(r"source · [0-9a-f]{6}", label)
                for label in selected_root["labels"]
            )
            assert str(source) not in selected_root["html"]
            assert discovered_root_id not in selected_root["html"]
            assert (
                js(
                    """(() => {
                      const form = document.querySelector('#warehouse-projects .warehouse-discovery');
                      const mode = form && form.querySelector('select');
                      if (!form || !mode) return false;
                      mode.value = 'clear';
                      mode.dispatchEvent(new Event('change', {bubbles:true}));
                      form.querySelector('button').click();
                      return true;
                    })()"""
                )
                is True
            )
            wait_js(
                "Array.from(document.querySelectorAll("
                "'#warehouse-projects [data-action=\"refresh-project\"]'))"
                ".some(button => !button.disabled)",
                30,
                "confirmed project",
            )
            js("document.getElementById('warehouse-developer-mode').click(); true")
            wait_js(
                "!!document.querySelector("
                "'#warehouse-projects [data-action=\"authorize-source-derived\"]')",
                30,
                "source-derived developer form",
            )
            assert js(
                "Array.from(document.querySelectorAll("
                "'#warehouse-projects select[data-source-root-selector=\"session\"]'))"
                ".every(item => item.value === '0')"
            )
            assert (
                js(
                    """(() => {
                      const button = document.querySelector(
                        '#warehouse-projects [data-action="authorize-source-derived"]'
                      );
                      if (!button) return false;
                      button.focus();
                      const panel = button.closest('fieldset');
                      return document.activeElement === button
                        && panel
                        && panel.querySelectorAll('textarea').length >= 2
                        && panel.querySelectorAll('input').length >= 7
                        && panel.textContent.includes('失败后不会自动重试')
                        && !panel.textContent.includes('review_id');
                    })()"""
                )
                is True
            )
            wait_js(
                "Array.from(document.querySelectorAll("
                "'#warehouse-projects [data-action=\"authorize-source-agent\"]'))"
                ".some(button => !button.disabled && "
                "getComputedStyle(button).display !== 'none')",
                30,
                "source Agent authorization action",
            )
            assert (
                js(
                    """(() => {
                      const button = Array.from(
                        document.querySelectorAll(
                          '#warehouse-projects [data-action="authorize-source-agent"]'
                        )
                      ).find(item => !item.disabled);
                      if (!button) return false;
                      button.click();
                      return true;
                    })()"""
                )
                is True
            )
            wait_js(
                "Array.from(document.querySelectorAll("
                "'#warehouse-projects [data-action=\"revoke-source-agent\"]'))"
                ".some(button => !button.disabled)",
                30,
                "active source Agent authorization",
            )
            source_binding_line = app.clipboard().text()
            source_bind_request = json.loads(source_binding_line)
            source_handoff_token = source_bind_request["payload"]["handoff_token"]
            assert re.fullmatch(
                r"source_handoff_token_[0-9a-f]{48}",
                source_handoff_token,
            )
            assert source_bind_request == {
                "protocol": "reweave_agent_jsonl.v2",
                "id": "bind-user-handoff",
                "action": "bind_user_handoff",
                "payload": {"handoff_token": source_handoff_token},
            }
            assert source_handoff_token not in str(
                js("document.documentElement.outerHTML")
            )
            assert source_handoff_token not in str(js("document.body.innerText"))
            assert source_handoff_token not in str(
                js("JSON.stringify(window.ReweavePrototype.getState())")
            )
            assert (
                js(
                    """(() => {
                      const button = Array.from(
                        document.querySelectorAll(
                          '#warehouse-projects [data-action="revoke-source-agent"]'
                        )
                      ).find(item => !item.disabled);
                      if (!button) return false;
                      button.click();
                      return true;
                    })()"""
                )
                is True
            )
            wait_js(
                "Array.from(document.querySelectorAll("
                "'#warehouse-projects [data-action=\"authorize-source-agent\"]'))"
                ".some(button => !button.disabled) && "
                "document.getElementById('warehouse-projects').textContent.includes("
                "'Agent 入库授权已撤销')",
                30,
                "revoked source Agent authorization",
            )
            app.clipboard().clear()
            prepublication_backup = service._capsule_store.create_backup("manual")
            assert (
                js(
                    """(() => {
                      const button = Array.from(
                        document.querySelectorAll(
                          '#warehouse-projects [data-action="refresh-project"]'
                        )
                      ).find(item => !item.disabled);
                      if (!button) return false;
                      button.click();
                      return true;
                    })()"""
                )
                is True
            )
            wait_js(
                "Number(document.getElementById('warehouse-review-count').textContent) === 3",
                180,
                "three atomic review items",
            )
            reviews = service.list_review_items({})
            assert reviews.get("ok") is True, reviews
            items = reviews["data"]["items"]
            assert len(items) == 3
            assert {item["candidate"]["capability_kind"] for item in items} == {
                "presentation",
                "interaction",
                "computation",
            }
            assert {item["candidate_status"] for item in items} == {
                "review_required"
            }
            wait_js(
                "Array.from(document.querySelectorAll('#warehouse-review-items .warehouse-review'))"
                ".some(item => Array.from(item.querySelectorAll('select option')).some("
                "option => option.value === 'publish_general'))",
                30,
                "publishable review action",
            )

            role_keys = {
                "presentation": "quote_summary",
                "interaction": "quote_input",
                "computation": "total_price",
            }
            for published_count in (1, 2, 3):
                kind = str(
                    js(
                        """(() => {
                          const row = Array.from(
                            document.querySelectorAll('#warehouse-review-items .warehouse-review')
                          ).find(item => Array.from(item.querySelectorAll('select option')).some(
                            option => option.value === 'publish_general'
                          ));
                          return row ? row.querySelector('p.warehouse-meta').textContent : '';
                        })()"""
                    )
                ).split(" · ", 1)[0]
                assert kind in role_keys
                values = json.dumps(
                    {
                        "capability_key": "quote_calculation",
                        "role_key": role_keys[kind],
                        "variant_key": "default",
                        "display_name": "Quote calculation",
                    }
                )
                assert (
                    js(
                        """(() => {
                          const values = %s;
                          const row = Array.from(
                            document.querySelectorAll('#warehouse-review-items .warehouse-review')
                          ).find(item => Array.from(item.querySelectorAll('select option')).some(
                            option => option.value === 'publish_general'
                          ));
                          if (!row) return false;
                          for (const [name, value] of Object.entries(values)) {
                            const input = row.querySelector(`[name="${name}"]`);
                            if (!input) return false;
                            input.value = value;
                            input.dispatchEvent(new Event('input', {bubbles:true}));
                          }
                          const decision = row.querySelector('.warehouse-review-decision select');
                          const submit = row.querySelector('.warehouse-review-decision button');
                          if (!decision || !submit) return false;
                          decision.value = 'publish_general';
                          decision.dispatchEvent(new Event('change', {bubbles:true}));
                          submit.click();
                          return true;
                        })()"""
                        % values
                    )
                    is True
                )
                deadline = time.monotonic() + 60
                capsule_count = 0
                while time.monotonic() < deadline:
                    groups_result = service.list_capability_groups({})
                    groups = groups_result.get("data", {}).get("groups", [])
                    capsule_count = sum(
                        len(group.get("capsules", [])) for group in groups
                    )
                    if capsule_count == published_count:
                        break
                    pump(0.08)
                assert capsule_count == published_count
                wait_js(
                    "Number(document.getElementById('warehouse-review-count').textContent) === "
                    f"{3 - published_count}",
                    30,
                    f"review refresh after publishing {kind}",
                )

            groups_result = service.list_capability_groups({})
            assert groups_result.get("ok") is True, groups_result
            groups = groups_result["data"]["groups"]
            assert len(groups) == 1
            capsules = groups[0]["capsules"]
            assert len(capsules) == 3
            version_ids = {row["current_version_id"] for row in capsules}
            version_hashes = {
                row["current_version_id"]: row["canonical_hash"]
                for row in capsules
            }
            assert {row["status"] for row in capsules} == {"active"}
            wait_js(
                "window.__phase6_document_token === 'same-document' && "
                "document.querySelectorAll('#capsule-strip [data-capsule-id]').length === 3",
                30,
                "published capsules visible without reload",
            )

            for expected_count in (1, 2, 3):
                assert (
                    js(
                        """(() => {
                          const used = new Set(Array.from(
                            document.querySelectorAll('#used-capsule-dock [data-capsule-id]')
                          ).map(item => item.dataset.capsuleId));
                          const capsule = Array.from(
                            document.querySelectorAll('#capsule-strip [data-capsule-id]')
                          ).find(item => !used.has(item.dataset.capsuleId));
                          if (!capsule) return false;
                          capsule.click();
                          document.getElementById('btn-use-in-task').click();
                          return true;
                        })()"""
                    )
                    is True
                )
                wait_js(
                    "Number(document.getElementById('used-count').textContent) === "
                    f"{expected_count}",
                    20,
                    f"selected capsule {expected_count}",
                )

            generate_ready = json.loads(
                js(
                    "JSON.stringify({"
                    "disabled: document.getElementById('btn-generate').disabled,"
                    "used_ids: window.ReweavePrototype.getState().usedCapsuleIds,"
                    "can_generate: window.ReweavePrototype.getState().bridge.shell.canGenerateProduct"
                    "})"
                )
            )
            assert generate_ready["disabled"] is False, generate_ready
            assert generate_ready["can_generate"] is True, generate_ready
            assert len(generate_ready["used_ids"]) == 3
            js(
                "document.getElementById('task-input').value = 'Build a quote calculator'; "
                "document.getElementById('btn-generate').click(); true"
            )
            wait_js(
                "!!document.querySelector('#generated-package.is-ready')",
                120,
                "formal product generation",
            )
            assert js("window.__phase6_document_token") == "same-document"
            entry = service.get_latest_product_entry_path()
            assert entry
            product_root = Path(entry).parent
            record = service._read_product_record(product_root)
            assert record["status"] == "registered"
            manifest_path = product_root / "manifest.json"
            manifest_bytes = manifest_path.read_bytes()
            manifest = json.loads(manifest_bytes)
            assert manifest_bytes == _canonical_manifest_bytes(manifest)
            assert hashlib.sha256(manifest_bytes).hexdigest() == record["manifest_digest"]
            assert {row["version_id"] for row in manifest["capsules"]} == version_ids
            assert {
                row["version_id"]: row["canonical_hash"]
                for row in manifest["capsules"]
            } == version_hashes
            expected_usage = {
                (row["version_id"], contribution)
                for row in manifest["capsules"]
                for contribution in row["contributions"]
            }
            with service._capsule_store.read_connection() as connection:
                usage = [
                    dict(row)
                    for row in connection.execute(
                        "SELECT * FROM product_capsule_usage WHERE product_id = ?",
                        (manifest["product_id"],),
                    )
                ]
            assert {
                (row["version_id"], row["contribution_role"]) for row in usage
            } == expected_usage
            assert {row["manifest_digest"] for row in usage} == {
                record["manifest_digest"]
            }
            assert {row["generated_at"] for row in usage} == {
                manifest["generated_at"]
            }
            provenance = json.loads(
                (product_root / "provenance.json").read_text(encoding="utf-8")
            )
            assert provenance["source_project_write"] is False

            class ProductInterceptor(QWebEngineUrlRequestInterceptor):
                def __init__(self, root: Path, parent=None):
                    super().__init__(parent)
                    self.root = root.resolve()
                    self.blocked: list[str] = []

                def interceptRequest(self, info) -> None:
                    url = info.requestUrl()
                    if url.toString() == "about:blank":
                        return
                    if url.isLocalFile():
                        try:
                            Path(url.toLocalFile()).resolve(strict=True).relative_to(
                                self.root
                            )
                            return
                        except (OSError, ValueError):
                            pass
                    self.blocked.append(url.toString())
                    info.block(True)

            product_view = QWebEngineView()
            product_profile = QWebEngineProfile(product_view)
            assert product_profile.isOffTheRecord()
            interceptor = ProductInterceptor(product_root, product_profile)
            product_profile.setUrlRequestInterceptor(interceptor)
            product_page = QWebEnginePage(product_profile, product_view)
            product_view.setPage(product_page)
            settings = product_page.settings()
            settings.setAttribute(
                QWebEngineSettings.LocalContentCanAccessFileUrls, True
            )
            settings.setAttribute(
                QWebEngineSettings.LocalContentCanAccessRemoteUrls, False
            )
            settings.setAttribute(QWebEngineSettings.DnsPrefetchEnabled, False)
            product_view.resize(900, 700)
            product_view.show()
            product_page.load(QUrl.fromLocalFile(str(Path(entry))))
            wait_js(
                "document.readyState === 'complete' && "
                "!!globalThis.__reweave_result && "
                "!!document.querySelector(\"[data-action='calculate']\")",
                30,
                "generated product load",
                target=product_page,
            )
            receipt_json = wait_js(
                """(() => {
                  const quantity = document.querySelector("[data-ref='quantity']");
                  const unitPrice = document.querySelector("[data-ref='unit-price']");
                  const button = document.querySelector("[data-action='calculate']");
                  const total = document.querySelector("[data-ref='total']");
                  if (!quantity || !unitPrice || !button || !total) return '';
                  quantity.value = '4';
                  unitPrice.value = '5';
                  button.click();
                  if (total.textContent !== '20') return '';
                  return JSON.stringify({
                    acceptance_scope: 'real_qwebengine_product_interaction',
                    total: total.textContent,
                    emission_count: globalThis.__reweave_result.emission_count,
                    runtime_status: globalThis.__reweave_result.status
                  });
                })()""",
                20,
                "real product click",
                target=product_page,
            )
            interaction_receipt = json.loads(receipt_json)
            assert interaction_receipt == {
                "acceptance_scope": "real_qwebengine_product_interaction",
                "total": "20",
                "emission_count": 1,
                "runtime_status": "passed",
            }
            assert interceptor.blocked == []
            assert source_snapshot() == source_before

            restore = service.restore_backup(
                {
                    "path": prepublication_backup["path"],
                    "expected_sha256": prepublication_backup["sha256"],
                }
            )
            assert restore.get("ok") is True, restore
            deadline = time.monotonic() + 30
            restore_run = None
            while time.monotonic() < deadline:
                restore_result = service.get_intake_run(
                    {"run_id": restore["run_id"]}
                )
                restore_data = restore_result.get("data", {})
                restore_run = restore_data.get("run", restore_data)
                if restore_run and restore_run.get("status") in {
                    "completed",
                    "failed",
                    "cancelled",
                }:
                    break
                pump(0.08)
            assert restore_run and restore_run["status"] == "completed"
            js(
                "document.getElementById('btn-supervision-model-refresh').click(); true"
            )
            wait_js(
                "window.__phase6_document_token === 'same-document' && "
                "document.querySelectorAll('#capsule-strip [data-capsule-id]').length === 0",
                30,
                "restored authoritative empty product state",
            )
            restored_ui = json.loads(
                js(
                    "JSON.stringify({"
                    "preview_hidden: document.getElementById('generated-preview').classList.contains('hidden'),"
                    "tree: document.getElementById('generated-tree').textContent.trim(),"
                    "capsule_meta: document.getElementById('gen-capsules-used').textContent,"
                    "response: document.getElementById('reweave-response').textContent,"
                    "preview_path_present: Object.prototype.hasOwnProperty.call("
                    "window.ReweavePrototype.getState().bridge, 'previewPath'),"
                    "used_ids: window.ReweavePrototype.getState().usedCapsuleIds"
                    "})"
                )
            )
            assert restored_ui["preview_hidden"] is True, restored_ui
            assert restored_ui["tree"] == "", restored_ui
            assert "0" in restored_ui["capsule_meta"], restored_ui
            assert restored_ui["response"] == "", restored_ui
            assert restored_ui["preview_path_present"] is False, restored_ui
            assert restored_ui["used_ids"] == [], restored_ui
            historical = service.get_initial_state()["capsuleIngestionV1"][
                "historicalProducts"
            ]
            assert historical == [
                {
                    "product_id": manifest["product_id"],
                    "status": "historical_version_unavailable_after_restore",
                    "manifest_digest": record["manifest_digest"],
                    "pre_restore_backup_path": restore_run["data"][
                        "pre_restore_backup_path"
                    ],
                }
            ]
            selector = (
                "[data-historical-product-id='" + manifest["product_id"] + "']"
            )
            wait_js(
                "!!document.querySelector(" + json.dumps(selector) + ")",
                10,
                "historical product diagnosis",
            )
            historical_text = js(
                "document.querySelector(" + json.dumps(selector) + ").textContent"
            )
            assert manifest["product_id"] in historical_text
            assert "historical_version_unavailable_after_restore" in historical_text
            assert record["manifest_digest"] in historical_text
            assert restore_run["data"]["pre_restore_backup_path"] not in historical_text
            assert "恢复前备份: 可用" in historical_text
            print(
                json.dumps(
                    {
                        "status": "passed",
                        "product_id": manifest["product_id"],
                        "manifest_digest": record["manifest_digest"],
                        "version_ids": sorted(version_ids),
                        "source_project_write": False,
                        "interaction": interaction_receipt,
                    },
                    sort_keys=True,
                )
            )
    finally:
        if product_page is not None:
            product_view.setPage(QWebEnginePage(product_view))
            product_page.deleteLater()
            flush_deletes()
        if product_profile is not None:
            product_profile.setUrlRequestInterceptor(None)
            product_profile.deleteLater()
            flush_deletes()
        if product_view is not None:
            product_view.close()
            product_view.deleteLater()
            flush_deletes()
        if window is not None:
            window.close()
            window.deleteLater()
            flush_deletes()
        service.close()
        pump(0.1)
        server.shutdown()
        server_thread.join(timeout=2)
        server.server_close()
