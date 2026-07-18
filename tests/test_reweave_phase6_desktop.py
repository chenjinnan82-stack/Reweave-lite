from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import pytest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "reweave_phase6_quote"


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
