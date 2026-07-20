from __future__ import annotations

import hashlib
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
            js("document.getElementById('btn-open-capsule-ingestion').click(); true")
            wait_js(
                "document.getElementById('warehouse-projects').textContent.includes('Multiply source')",
                30,
                "project_row",
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
                            found: block?.textContent.includes('找到 1 个可进一步验证的计算功能。') || false,
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

            wait_js(
                "document.readyState === 'complete' && !!window.reweaveBridge && "
                "!document.getElementById('screen-main').classList.contains('hidden')",
                30,
                "desktop_bridge",
            )
            js("document.getElementById('task-input').value='Keep standalone task'; true")
            js("document.getElementById('btn-open-target').click(); true")
            wait_js(
                "!document.getElementById('screen-target').classList.contains('hidden')",
                10,
                "target_screen",
            )
            js("document.getElementById('btn-select-target').click(); true")
            wait_js(
                "document.getElementById('target-selected-name').textContent.includes('target-site')",
                10,
                "target_selection",
            )
            js("document.getElementById('btn-analyze-target').click(); true")
            wait_js(
                "document.getElementById('target-analysis-status').textContent.includes("
                "'frontend_contract_rejected')",
                10,
                "malformed_profile_rejected",
            )
            assert str(target) not in str(js("document.body.textContent"))
            js("document.getElementById('btn-analyze-target').click(); true")
            wait_js(
                "!document.getElementById('target-profile-summary').classList.contains('hidden')",
                10,
                "target_profile",
            )
            wait_js(
                "!!document.querySelector('#target-capsule-cards input[type=checkbox]')",
                10,
                "target_capsule",
            )
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
                "document.getElementById('target-review').classList.contains('hidden')"
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
                "!document.getElementById('target-review').classList.contains('hidden') && "
                "document.getElementById('target-file-diffs').textContent.includes('Existing target') && "
                "document.getElementById('target-evidence-summary').textContent.trim().length > 0",
                10,
                "patch_review",
            )
            assert "never render this field" not in str(
                js("document.getElementById('target-review').textContent")
            )
            assert str(target) not in str(js("document.body.textContent"))
            js("document.getElementById('target-developer-mode').click(); true")
            assert js(
                "document.getElementById('screen-target').classList.contains('developer-mode')"
            )
            calls_before_confirm = len(service.calls)
            js("document.getElementById('btn-confirm-target-patch').click(); true")
            wait_js(
                "document.getElementById('target-confirmation-receipt').textContent.trim().length > 0",
                10,
                "confirmation_receipt",
            )
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
                "!document.getElementById('screen-main').classList.contains('hidden')",
                10,
                "standalone_screen",
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
        capsule_id, version_id = _seed_capsule(
            store,
            kind,
            capability_key=capability_key,
            suffix=suffix,
            payload=successful_payload if suffix == "alpha_presentation" else None,
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

            wait_js(
                "document.readyState === 'complete' && !!window.reweaveBridge && "
                "!document.getElementById('screen-main').classList.contains('hidden')",
                30,
                "desktop main screen",
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

            js("document.getElementById('btn-capsule-warehouse').click(); true")
            wait_js(
                "window.ReweavePrototype.getState().warehouse.source_group_count === 5 && "
                "!window.ReweavePrototype.getState().warehouse.source_relations_loading && "
                "document.querySelectorAll('#warehouse-scene-nodes [data-project-key]').length === 5",
                30,
                "source project overview",
            )
            assert warehouse_state()["view"] == "overview"
            assert projection_bridge_payloads == []
            assert js("document.querySelectorAll('#warehouse-scene-links line').length") == 0
            overview_positions = json.loads(
                str(
                    js(
                        "JSON.stringify(Array.from(document.querySelectorAll("
                        "'#warehouse-scene-nodes [data-project-key]')).map(function (node) { "
                        "return [node.dataset.projectKey, node.style.left, node.style.top]; }))"
                    )
                )
            )
            assert len(overview_positions) == 5
            assert len({(row[1], row[2]) for row in overview_positions}) == 5
            overview_text = str(js("document.getElementById('warehouse-scene-nodes').textContent"))
            for expected_label in (
                "Readonly source A",
                "Readonly source B",
                "Readonly source C",
                "Versionless formal source",
                "Display-only source",
            ):
                assert expected_label in overview_text

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
                "document.querySelectorAll('#warehouse-scene-nodes [data-capsule-id]').length === 2",
                10,
                "project capsule constellation",
            )
            assert js("document.querySelectorAll('#warehouse-scene-links line').length") == 2
            formal_project_state = warehouse_state()
            assert formal_project_state["project_id"] == project_rows[0][2]
            assert projection_bridge_payloads == []
            assert not js("!!document.querySelector('.warehouse-node.is-center .warehouse-node-note')")

            js("document.getElementById('btn-warehouse-zoom-in').click(); true")
            assert js(
                "(() => { const canvas = document.getElementById('warehouse-scene-canvas'); "
                "canvas.focus(); return document.activeElement === canvas; })()"
            )
            QTest.keyClick(key_target, Qt.Key.Key_Right)
            pump()
            project_view = warehouse_state()
            assert project_view["canvas"]["scale"] > 1
            assert project_view["canvas"]["x"] < 0

            selected_id = capsule_rows[0][0]
            assert js(
                "(() => { const node = document.querySelector('#warehouse-scene-nodes "
                "[data-capsule-id=" + json.dumps(selected_id) + "]'); "
                "node.focus(); return document.activeElement === node; })()"
            )
            QTest.keyClick(key_target, Qt.Key.Key_Return)
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

            js("document.getElementById('btn-warehouse-code-zoom-in').click(); true")
            assert warehouse_state()["code_scale"] > 1
            js("document.getElementById('btn-warehouse-scene-back').click(); true")
            wait_js(
                "window.ReweavePrototype.getState().warehouse.view === 'project'",
                10,
                "return to project",
            )
            restored_project = warehouse_state()
            assert restored_project["canvas"] == project_view["canvas"]
            wait_js(
                "document.activeElement && document.activeElement.dataset.capsuleId === "
                + json.dumps(selected_id),
                10,
                "capsule focus restored",
            )

            js("document.getElementById('btn-warehouse-scene-back').click(); true")
            wait_js(
                "window.ReweavePrototype.getState().warehouse.view === 'overview'",
                10,
                "return to overview",
            )
            overview_before_search = warehouse_state()
            restored_positions = json.loads(
                str(
                    js(
                        "JSON.stringify(Array.from(document.querySelectorAll("
                        "'#warehouse-scene-nodes [data-project-key]')).map(function (node) { "
                        "return [node.dataset.projectKey, node.style.left, node.style.top]; }))"
                    )
                )
            )
            assert restored_positions == overview_positions
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
            assert warehouse_state()["canvas"] == overview_before_search["canvas"]

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
            assert warehouse_state()["canvas"] == overview_before_search["canvas"]

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
                "(() => { const node = Array.from(document.querySelectorAll("
                "'#warehouse-scene-nodes [data-project-key]')).find(function (item) { "
                "return item.textContent.includes('Versionless formal source'); }); "
                "node.click(); return true; })()"
            )
            wait_js(
                "window.ReweavePrototype.getState().warehouse.view === 'project' && "
                "window.ReweavePrototype.getState().warehouse.project_key === "
                + json.dumps("source:formal-source-without-exact-version"),
                10,
                "missing exact version fallback group",
            )
            missing_version_group_state = warehouse_state()
            assert missing_version_group_state["project_id"] is None
            assert js(
                "document.querySelector('.warehouse-node.is-center .warehouse-node-note').textContent === "
                + json.dumps("来源证据不足")
            )
            assert js("document.querySelectorAll('#warehouse-scene-links line').length") == 0
            assert js("document.querySelectorAll('#warehouse-scene-nodes [data-capsule-id]').length") == 1
            js(
                "document.querySelector('#warehouse-scene-nodes [data-capsule-id]').click(); true"
            )
            wait_js(
                "window.ReweavePrototype.getState().warehouse.view === 'code'",
                10,
                "missing exact version code page",
            )
            assert warehouse_state()["capsule_id"] == missing_version_capsule_id
            assert warehouse_state()["verified_core_code"] is False
            assert len(projection_bridge_payloads) == fallback_projection_calls
            assert js(
                "document.getElementById('warehouse-core-code').classList.contains('hidden') && "
                "!document.getElementById('warehouse-core-code-empty').classList.contains('hidden')"
            )
            js(
                "(() => { const toggle = document.getElementById('warehouse-code-developer-mode'); "
                "if (!toggle.checked) toggle.click(); return true; })()"
            )
            missing_version_evidence = json.loads(
                str(js("document.getElementById('warehouse-developer-evidence').textContent"))
            )
            assert missing_version_evidence["version"] == {}
            assert missing_version_evidence["source"]["project_id"] is None
            assert (
                missing_version_evidence["source"]["source_identity_status"]
                == "missing_exact_version_source_relation"
            )
            assert missing_version_evidence["source"]["relationships"] == []
            assert missing_version_evidence["core_code_projection"] is None
            assert len(projection_bridge_payloads) == fallback_projection_calls
            js("document.getElementById('btn-warehouse-scene-back').click(); true")
            wait_js(
                "window.ReweavePrototype.getState().warehouse.view === 'project'",
                10,
                "return from missing exact version code",
            )
            js("document.getElementById('btn-warehouse-scene-back').click(); true")
            wait_js(
                "window.ReweavePrototype.getState().warehouse.view === 'overview'",
                10,
                "return from missing exact version group",
            )

            assert js(
                "(() => { const node = Array.from(document.querySelectorAll("
                "'#warehouse-scene-nodes [data-project-key]')).find(function (item) { "
                "return item.textContent.includes('Display-only source'); }); "
                "node.click(); return true; })()"
            )
            wait_js(
                "window.ReweavePrototype.getState().warehouse.view === 'project' && "
                "window.ReweavePrototype.getState().warehouse.project_key.startsWith('label:')",
                10,
                "missing formal source identity group",
            )
            missing_identity_group_state = warehouse_state()
            assert missing_identity_group_state["project_id"] is None
            assert js("document.querySelectorAll('#warehouse-scene-links line').length") == 0
            assert js(
                "document.querySelector('.warehouse-node.is-center .warehouse-node-note').textContent === "
                + json.dumps("来源证据不足")
            )
            js(
                "document.querySelector('#warehouse-scene-nodes [data-capsule-id]').click(); true"
            )
            wait_js(
                "window.ReweavePrototype.getState().warehouse.view === 'code'",
                10,
                "missing formal source identity code page",
            )
            js(
                "(() => { const toggle = document.getElementById('warehouse-code-developer-mode'); "
                "if (!toggle.checked) toggle.click(); return true; })()"
            )
            missing_identity_evidence = json.loads(
                str(js("document.getElementById('warehouse-developer-evidence').textContent"))
            )
            assert missing_identity_evidence["source"]["project_id"] is None
            assert (
                missing_identity_evidence["source"]["source_identity_status"]
                == "missing_formal_source_identity"
            )
            assert missing_identity_evidence["source"]["relationships"] == []
            assert missing_identity_evidence["core_code_projection"] is None
            assert warehouse_state()["verified_core_code"] is False
            assert len(projection_bridge_payloads) == fallback_projection_calls
            js("document.getElementById('btn-warehouse-scene-back').click(); true")
            wait_js(
                "window.ReweavePrototype.getState().warehouse.view === 'project'",
                10,
                "return from missing formal source identity code",
            )
            js("document.getElementById('btn-warehouse-scene-back').click(); true")
            wait_js(
                "window.ReweavePrototype.getState().warehouse.view === 'overview'",
                10,
                "return from missing formal source identity group",
            )

            js("document.getElementById('btn-warehouse-zoom-in').click(); true")
            assert warehouse_state()["canvas"]["scale"] > 1
            js("document.getElementById('btn-warehouse-zoom-reset').click(); true")
            assert warehouse_state()["canvas"] == {"scale": 1, "x": 0, "y": 0}
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
    finally:
        if window is not None:
            window.close()
            window.deleteLater()
            pump()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            app.processEvents()


def test_product_plan_ide_prototype_round_trip_is_read_only(
    tmp_path: Path, monkeypatch
) -> None:
    if sys.platform.startswith("linux") and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        pytest.skip("A desktop GUI session is required")
    pytest.importorskip("PySide6.QtWebEngineCore")

    if os.environ.get("REWEAVE_PRODUCT_PLAN_CHILD") != "1":
        child_env = os.environ.copy()
        child_env["REWEAVE_PRODUCT_PLAN_CHILD"] = "1"
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
                    "test_product_plan_ide_prototype_round_trip_is_read_only"
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

    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWebEngineCore import QWebEngineProfile

    from pimos_lite import desktop_reweave_static as desktop
    from pimos_lite.reweave_app_service import ReweaveAppService
    from pimos_lite.reweave_capsule_store import CapsuleWarehouseStore
    from tests.test_reweave_phase5_generation import _seed_capsule

    source_root = tmp_path / "readonly-source"
    source_root.mkdir()
    (source_root / "index.html").write_text("<main>prototype source</main>\n", encoding="utf-8")
    untouched_target = tmp_path / "untouched-target"
    untouched_target.mkdir()
    (untouched_target / "sentinel.txt").write_text("do not write\n", encoding="utf-8")
    state_dir = tmp_path / "state"
    monkeypatch.setenv("REWEAVE_STATE_DIR", str(state_dir))
    store = CapsuleWarehouseStore(state_dir / "capsule_warehouse.sqlite3")
    store.initialize()
    service = ReweaveAppService(capsule_store=store)

    root = service._capsule_intake.bind_source_root(
        source_root, root_kind="single_project"
    )
    project = service._capsule_intake.confirm_project(
        str(service._capsule_intake.discover_projects(str(root["root_id"]))[0]["project_id"])
    )
    project_id = str(project["project_id"])
    capsule_id, version_id = _seed_capsule(
        store,
        "presentation",
        capability_key="product_plan_prototype_navigation",
        suffix="product_plan_prototype",
    )
    with store.transaction() as connection:
        connection.execute(
            "UPDATE projects SET display_name = ? WHERE project_id = ?",
            ("Prototype source", project_id),
        )
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
                "product-plan-prototype-source",
                version_id,
                project_id,
                f"project:{project_id}",
                hashlib.sha256((source_root / "index.html").read_bytes()).hexdigest(),
                canonical_hash,
                "2026-07-20T00:00:00Z",
            ),
        )
        store.bump_revision(connection)

    def warehouse_state() -> dict[str, object]:
        tables = ("capsules", "capsule_versions", "capsule_sources", "product_capsule_usage")
        with store.read_connection() as connection:
            rows = [
                {
                    "table": table,
                    "rows": [
                        dict(row)
                        for row in connection.execute(f"SELECT * FROM {table} ORDER BY rowid")
                    ],
                }
                for table in tables
            ]
        return {"revision": store.current_revision(), "sha256": _canonical_sha256(rows)}

    source_before = _tree_state(source_root)
    target_before = _tree_state(untouched_target)
    warehouse_before = warehouse_state()
    usage_before = _usage_state(store)
    products_before = _tree_state(state_dir / "products")

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

            def product_state() -> dict[str, object]:
                return json.loads(
                    str(js("JSON.stringify(window.ReweavePrototype.getState().productPlan)"))
                )

            wait_js(
                "document.readyState === 'complete' && !!window.reweaveBridge && "
                "!document.getElementById('screen-main').classList.contains('hidden')",
                30,
                "desktop main screen",
            )
            bridge_calls: list[str] = []
            original_phase4_call = bridge._phase4_call

            def observe_phase4_call(method_name: str, payload_json: str = "") -> str:
                bridge_calls.append(method_name)
                return original_phase4_call(method_name, payload_json)

            bridge._phase4_call = observe_phase4_call

            # Prime the already-existing warehouse read cache outside the measured prototype flow.
            js("document.getElementById('btn-capsule-warehouse').click(); true")
            wait_js(
                "!window.ReweavePrototype.getState().warehouse.source_relations_loading",
                30,
                "warehouse read cache",
            )
            assert bridge_calls == ["get_capsule_detail"]
            js("document.getElementById('btn-warehouse-scene-back').click(); true")
            wait_js(
                "!document.getElementById('screen-main').classList.contains('hidden')",
                10,
                "return from cache prime",
            )
            measured_bridge_start = len(bridge_calls)
            js(
                "window.__productPlanNetworkCalls = 0; "
                "window.__productPlanXhrOpen = XMLHttpRequest.prototype.open; "
                "XMLHttpRequest.prototype.open = function () { "
                "window.__productPlanNetworkCalls += 1; "
                "return window.__productPlanXhrOpen.apply(this, arguments); }; true"
            )

            js("document.getElementById('btn-open-product-plan').click(); true")
            wait_js(
                "window.ReweavePrototype.getState().productPlan.active === true",
                10,
                "product plan scene",
            )
            goal = "Build a local operations dashboard"
            js(
                "(() => { const goal = document.getElementById('product-plan-goal'); "
                f"goal.value = {json.dumps(goal)}; goal.focus(); "
                "document.getElementById('btn-submit-product-goal').click(); return true; })()"
            )
            wait_js(
                "window.ReweavePrototype.getState().productPlan.fixture_visible === true",
                10,
                "prototype fixture",
            )
            overview = product_state()
            assert overview["scope"] == "prototype_only"
            assert overview["prototype_id"] == "product-plan-prototype-001"
            assert overview["goal_entered"] is True
            assert js("document.querySelectorAll('.product-plan-section').length") == 4
            assert js(
                "Array.from(document.querySelectorAll('.prototype-note')).some(function (item) { "
                "return !item.closest('.hidden') && item.textContent.includes('原型数据'); })"
            )

            js(
                "(() => { const frontend = document.querySelector('[data-section-id=frontend]'); "
                "const backend = document.querySelector('[data-section-id=backend]'); "
                "if (frontend.open) frontend.querySelector('summary').click(); "
                "if (!backend.open) backend.querySelector('summary').click(); return true; })()"
            )
            pump(0.1)
            js(
                "(() => { const toggle = document.getElementById('product-plan-developer-mode'); "
                "toggle.click(); const stage = document.getElementById('product-plan-stage'); "
                "stage.style.height = '180px'; stage.scrollTop = 90; "
                "const button = document.getElementById('btn-open-product-review-backend'); "
                "button.focus(); button.click(); return true; })()"
            )
            wait_js(
                "window.ReweavePrototype.getState().productPlan.view === 'review' && "
                "window.ReweavePrototype.getState().productPlan.section_id === 'backend'",
                10,
                "backend review",
            )
            review_state = product_state()
            assert review_state["developer_mode"] is True
            assert review_state["expanded"] == {
                "frontend": False,
                "backend": True,
                "data": False,
                "infrastructure": False,
            }
            assert js("document.getElementById('product-review-empty').textContent") == (
                "真实候选尚未生成"
            )
            evidence = json.loads(
                str(js("document.getElementById('product-plan-developer-evidence').textContent"))
            )
            assert evidence["scope"] == "prototype_only"
            assert evidence["candidate"] == {
                "capsule_id": capsule_id,
                "evidence_status": "prototype_navigation_only",
                "formal_match_claimed": False,
                "validation_claimed": False,
            }
            assert evidence["calls"] == {"bridge": 0, "network": 0, "model": 0}
            assert evidence["writes"] == 0

            js(
                "(() => { const stage = document.getElementById('product-plan-stage'); "
                "const capsule = document.querySelector("
                "'.product-review-capsule[data-capsule-id]'); capsule.focus(); "
                "stage.scrollTop = 70; capsule.click(); return true; })()"
            )
            wait_js(
                "window.ReweavePrototype.getState().warehouse.active === true && "
                "window.ReweavePrototype.getState().warehouse.view === 'project' && "
                f"window.ReweavePrototype.getState().warehouse.focused_node === {json.dumps('capsule:' + capsule_id)}",
                15,
                "focused warehouse capsule",
            )
            assert js(
                "!document.getElementById('btn-warehouse-return-product-plan').classList.contains('hidden')"
            )
            assert js("document.getElementById('warehouse-scene-query').value") == capsule_id
            assert bridge_calls[measured_bridge_start:] == []
            js("document.getElementById('btn-warehouse-return-product-plan').click(); true")
            wait_js(
                "!document.getElementById('screen-product-plan').classList.contains('hidden') && "
                "window.ReweavePrototype.getState().productPlan.view === 'review' && "
                "document.activeElement.classList.contains('product-review-capsule')",
                10,
                "product review restored",
            )
            restored = product_state()
            assert restored["section_id"] == "backend"
            assert restored["developer_mode"] is True
            assert restored["expanded"] == review_state["expanded"]
            assert js("document.getElementById('product-plan-stage').scrollTop") == 70
            assert js("window.__productPlanNetworkCalls") == 0
            assert bridge_calls[measured_bridge_start:] == []
            assert str(js("document.documentElement.textContent")).find(str(source_root.resolve())) == -1
            assert _tree_state(source_root) == source_before
            assert _tree_state(untouched_target) == target_before
            assert warehouse_state() == warehouse_before
            assert _usage_state(store) == usage_before
            assert _tree_state(state_dir / "products") == products_before
    finally:
        if window is not None:
            window.close()
            window.deleteLater()
            pump()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            app.processEvents()
        service.close()


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
                "!document.getElementById('screen-main').classList.contains('hidden')",
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
                "!document.getElementById('target-review').classList.contains('hidden') && "
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
                "!document.getElementById('capsule-warehouse-popover').classList.contains('developer-mode')"
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
                "Array.from(document.querySelectorAll('#warehouse-projects .warehouse-row button'))"
                ".some(button => !button.disabled)",
                30,
                "confirmed project",
            )
            prepublication_backup = service._capsule_store.create_backup("manual")
            assert (
                js(
                    """(() => {
                      const button = Array.from(
                        document.querySelectorAll('#warehouse-projects .warehouse-row button')
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
                ".some(item => Array.from(item.querySelectorAll('button')).some("
                "button => button.dataset.decision === 'publish_general'))",
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
                          ).find(item => Array.from(item.querySelectorAll('button')).some(
                            button => button.dataset.decision === 'publish_general'
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
                          ).find(item => Array.from(item.querySelectorAll('button')).some(
                            button => button.dataset.decision === 'publish_general'
                          ));
                          if (!row) return false;
                          for (const [name, value] of Object.entries(values)) {
                            const input = row.querySelector(`[name="${name}"]`);
                            if (!input) return false;
                            input.value = value;
                            input.dispatchEvent(new Event('input', {bubbles:true}));
                          }
                          Array.from(row.querySelectorAll('button')).find(
                            button => button.dataset.decision === 'publish_general'
                          ).click();
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
                    "preview_path: window.ReweavePrototype.getState().bridge.previewPath,"
                    "used_ids: window.ReweavePrototype.getState().usedCapsuleIds"
                    "})"
                )
            )
            assert restored_ui["preview_hidden"] is True, restored_ui
            assert restored_ui["tree"] == "", restored_ui
            assert "0" in restored_ui["capsule_meta"], restored_ui
            assert restored_ui["response"] == "", restored_ui
            assert restored_ui["preview_path"] is None, restored_ui
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
            assert restore_run["data"]["pre_restore_backup_path"] in historical_text
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
