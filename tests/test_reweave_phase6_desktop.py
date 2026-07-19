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
