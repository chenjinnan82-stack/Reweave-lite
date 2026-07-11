"""Run one declared preview behavior in an isolated QtWebEngine page."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote


SCHEMA_VERSION = "reweave_behavior_validation.v1"


def _is_preview_static_request(root: Path, url_path: str) -> bool:
    relative = unquote(url_path or "/").lstrip("/") or "index.html"
    cursor = root
    for part in Path(relative).parts:
        cursor /= part
        if cursor.is_symlink():
            return False
    try:
        candidate = cursor.resolve()
        candidate.relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return candidate.is_file() and not candidate.is_symlink()


def _is_console_error(level: Any) -> bool:
    name = str(getattr(level, "name", level)).lower()
    if "error" in name:
        return True
    try:
        return int(level) == 2
    except (TypeError, ValueError):
        return False


def _receipt(status: str, reason: str, **extra: Any) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "reason": reason,
        "runner": "qt_webengine",
        "source_project_write": False,
        "network_call": False,
        **extra,
    }


def validate_preview_behavior(root: str | Path, *, timeout: float = 8.0) -> dict[str, Any]:
    preview = Path(root).resolve()
    contract_path = preview / "behavior_contract.json"
    if not contract_path.is_file():
        return _receipt("not_run", "no_closed_behavior_module")
    try:
        completed = subprocess.run(
            [sys.executable, "-m", __name__, "--child", str(preview)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _receipt("unavailable", type(exc).__name__.lower())
    lines = [line for line in completed.stdout.splitlines() if line.strip().startswith("{")]
    if not lines:
        return _receipt("unavailable", "qt_runner_failed", detail=completed.stderr[-240:])
    try:
        result = json.loads(lines[-1])
    except json.JSONDecodeError:
        return _receipt("unavailable", "invalid_qt_runner_result")
    return result if isinstance(result, dict) else _receipt("unavailable", "invalid_qt_runner_result")


def validate_react_preview_behavior(
    root: str | Path,
    expected_text: str,
    runtime_contract: dict[str, Any] | None = None,
    *,
    timeout: float = 10.0,
) -> dict[str, Any]:
    preview = Path(root).resolve() / "react_project" / "dist"
    if not (preview / "index.html").is_file():
        return _receipt("unavailable", "react_runtime_entry_missing")
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                __name__,
                "--react-child",
                str(preview),
                expected_text[:160],
                json.dumps(runtime_contract or {}, separators=(",", ":")),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _receipt("unavailable", type(exc).__name__.lower())
    lines = [line for line in completed.stdout.splitlines() if line.strip().startswith("{")]
    if not lines:
        return _receipt("unavailable", "qt_runner_failed", detail=completed.stderr[-240:])
    try:
        result = json.loads(lines[-1])
    except json.JSONDecodeError:
        return _receipt("unavailable", "invalid_qt_runner_result")
    return result if isinstance(result, dict) else _receipt("unavailable", "invalid_qt_runner_result")


def _run_react_child(root: Path, expected_text: str, runtime_contract: dict[str, Any] | None = None) -> int:
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    try:
        from PySide6.QtCore import Qt, QTimer, QUrl
        from PySide6.QtWebEngineCore import (
            QWebEnginePage,
            QWebEngineProfile,
            QWebEngineSettings,
            QWebEngineUrlRequestInterceptor,
        )
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print(json.dumps(_receipt("unavailable", "pyside6_unavailable")))
        return 0

    app = QApplication.instance() or QApplication(["reweave-react-validation"])
    console_messages: list[str] = []
    console_errors: list[str] = []
    blocked_requests: list[str] = []
    allowed_root = root.resolve()

    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, _format: str, *_args: Any) -> None:
            pass

    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        partial(QuietHandler, directory=str(allowed_root)),
    )
    Thread(target=server.serve_forever, daemon=True).start()
    preview_port = int(server.server_port)

    class ValidationPage(QWebEnginePage):
        def javaScriptConsoleMessage(self, _level: Any, message: str, _line: int, _source: str) -> None:
            console_messages.append(message[:240])
            if _is_console_error(_level):
                console_errors.append(message[:240])

    class PreviewRequestInterceptor(QWebEngineUrlRequestInterceptor):
        def interceptRequest(self, info: Any) -> None:
            url = info.requestUrl()
            scheme = url.scheme().lower()
            if scheme in {"data", "blob", "about"}:
                return
            allowed = False
            if scheme == "file":
                try:
                    Path(url.toLocalFile()).resolve().relative_to(allowed_root)
                    allowed = True
                except (OSError, ValueError):
                    pass
            elif scheme == "http" and url.host() == "127.0.0.1" and url.port() == preview_port:
                allowed = _is_preview_static_request(allowed_root, url.path())
                if not allowed and url.path() == "/favicon.ico":
                    info.block(True)
                    return
            if not allowed:
                blocked_requests.append(url.path() or scheme or "unknown")
                info.block(True)

    profile = QWebEngineProfile()
    request_interceptor = PreviewRequestInterceptor()
    profile.setUrlRequestInterceptor(request_interceptor)
    page = ValidationPage(profile)
    view = QWebEngineView()
    view.resize(960, 600)
    view.setAttribute(Qt.WA_DontShowOnScreen, True)
    view.setPage(page)
    view.show()
    settings = page.settings()
    settings.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
    settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, False)
    output: dict[str, Any] = {}
    initial_pixmap: Any = None
    expected_json = json.dumps(expected_text)
    runtime_contract_json = json.dumps(runtime_contract or {})
    snapshot_js = (
        "JSON.stringify({text:(document.body.innerText||'').trim(),"
        "root:(document.getElementById('root')||{}).innerText||'',"
        "taskVisible:(function(expected){if(!expected)return true;"
        "var walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);var node;"
        "while((node=walker.nextNode())){if(!(node.nodeValue||'').includes(expected))continue;"
        "var el=node.parentElement;if(!el)continue;var rect=el.getBoundingClientRect();var style=getComputedStyle(el);"
        "if(style.visibility!=='hidden'&&style.display!=='none'&&rect.width>0&&rect.height>0&&"
        "rect.bottom>0&&rect.right>0&&rect.top<innerHeight&&rect.left<innerWidth)return true;}return false;})("
        + expected_json
        + "),"
        "interaction:(function(declared){var buttons=Array.from(document.querySelectorAll('button'));"
        "if(declared.mode==='declared_navigation_state'){var navButtons=document.querySelectorAll(declared.control_selector||'nav button');"
        "if(navButtons.length)return {selector:declared.control_selector||'nav button',buttonIndex:0,candidateCount:Math.min(navButtons.length,8),stateKind:'class'};}"
        "if(declared.mode==='declared_control_disappears'){var textButtons=Array.from(document.querySelectorAll('button')).filter(function(button){return (button.innerText||'').trim()===declared.control_text;});"
        "if(textButtons.length)return {controlText:declared.control_text,buttonIndex:0,candidateCount:1,stateKind:'control_presence'};}"
        "if(declared.mode==='declared_group_to_textbox'){var groupButtons=document.querySelectorAll(declared.control_selector);"
        "if(groupButtons.length&&document.querySelector(declared.state_selector))return {selector:declared.control_selector,buttonIndex:0,candidateCount:Math.min(groupButtons.length,8),stateKind:'selector_value',stateSelector:declared.state_selector};}"
        "if(declared.status==='closed')return null;"
        "for(var i=0;i<buttons.length;i++){var button=buttons[i];"
        "for(var j=0;j<3;j++){var attr=['aria-expanded','aria-pressed','aria-selected'][j];"
        "if(button.hasAttribute(attr))return {selector:'button',buttonIndex:i,candidateCount:1,stateKind:'attribute',stateAttribute:attr};}"
        "var controlled=button.getAttribute('aria-controls');"
        "if(controlled&&document.getElementById(controlled))return {selector:'button',buttonIndex:i,candidateCount:1,stateKind:'target',targetId:controlled};}"
        "return null;})(" + runtime_contract_json + ")})"
    )

    def state_script(interaction: dict[str, Any]) -> str:
        return (
            "(function(contract){var buttons=contract.controlText?Array.from(document.querySelectorAll('button')).filter(function(button){return (button.innerText||'').trim()===contract.controlText;}):Array.from(document.querySelectorAll(contract.selector||'button'));"
            "var button=buttons[contract.buttonIndex];"
            "if(contract.stateKind==='control_presence')return button?'present':'missing';"
            "if(contract.stateKind==='selector_value'){var field=document.querySelector(contract.stateSelector);return field?String(field.value):null;}"
            "if(!button)return null;"
            "if(contract.stateKind==='attribute')return String(button.getAttribute(contract.stateAttribute));"
            "if(contract.stateKind==='class')return String(button.className);"
            "var target=document.getElementById(contract.targetId);if(!target)return null;"
            "return [target.textContent,target.hidden,target.className,target.getAttribute('aria-hidden')].join('|');})("
            + json.dumps(interaction)
            + ")"
        )

    def finish(result: dict[str, Any]) -> None:
        if output:
            return
        if result.get("status") == "passed" and console_errors:
            result["status"] = "needs_review"
            result["reason"] = "react_script_error"
        result.setdefault("request_scope", "preview_origin_only")
        result.setdefault("blocked_request_count", len(blocked_requests))
        if blocked_requests:
            result.setdefault("blocked_requests", blocked_requests[-5:])
        result.setdefault("local_http_call", True)
        result.setdefault("external_network_call", False)
        if result.get("status") in {"passed", "needs_review"} and result.get("rendered"):
            preview_image = root / "preview.png"
            pixmap = view.grab()
            if pixmap.isNull() and initial_pixmap is not None:
                pixmap = initial_pixmap
            if not pixmap.isNull() and pixmap.save(str(preview_image), "PNG"):
                result["preview_image"] = "react_project/dist/preview.png"
                result["preview_output_write"] = True
        if console_messages:
            result.setdefault("console_messages", console_messages[-5:])
        if console_errors:
            result.setdefault("console_errors", console_errors[-5:])
        output.update(result)
        server.shutdown()
        server.server_close()
        app.quit()

    def inspect_before(raw: Any) -> None:
        nonlocal initial_pixmap
        try:
            before = json.loads(raw) if isinstance(raw, str) else {}
        except json.JSONDecodeError:
            before = {}
        if not str(before.get("root") or "").strip():
            finish(_receipt("failed", "react_root_not_rendered"))
            return
        initial_pixmap = view.grab()
        interaction = before.get("interaction") if isinstance(before.get("interaction"), dict) else None
        if not interaction:
            finish(
                _receipt(
                    "needs_review",
                    "react_explicit_interaction_contract_missing",
                    rendered=True,
                    task_text_rendered=bool(before.get("taskVisible")),
                )
            )
            return

        def try_candidate(candidate_index: int) -> None:
            interaction["buttonIndex"] = candidate_index

            def click_after_state(before_state: Any) -> None:
                def inspect_after(after_state: Any) -> None:
                    changed = before_state != after_state
                    if blocked_requests:
                        status = "needs_review"
                        reason = "react_interaction_requires_blocked_request"
                    elif changed:
                        status = "passed" if before.get("taskVisible") else "needs_review"
                        reason = "react_declared_state_changed" if before.get("taskVisible") else "adapted_task_text_not_rendered"
                    elif candidate_index + 1 < int(interaction.get("candidateCount") or 1):
                        try_candidate(candidate_index + 1)
                        return
                    else:
                        status = "needs_review"
                        reason = "react_declared_state_unchanged"
                    finish(
                        _receipt(
                            status,
                            reason,
                            rendered=True,
                            task_text_rendered=bool(before.get("taskVisible")),
                            interaction_present=True,
                            interaction_changed=changed,
                            interaction_contract=interaction,
                        )
                    )

                click_js = (
                    "(function(contract){var buttons=contract.controlText?Array.from(document.querySelectorAll('button')).filter(function(button){return (button.innerText||'').trim()===contract.controlText;}):Array.from(document.querySelectorAll(contract.selector||'button'));var button=buttons["
                    + str(candidate_index)
                    + "];if(!button||button.disabled)return false;button.click();return true;})("
                    + json.dumps(interaction)
                    + ")"
                )

                def clicked(ok: Any) -> None:
                    if not ok:
                        finish(_receipt("needs_review", "react_interaction_target_missing", rendered=True))
                        return
                    QTimer.singleShot(500, lambda: page.runJavaScript(state_script(interaction), inspect_after))

                page.runJavaScript(click_js, clicked)

            page.runJavaScript(state_script(interaction), click_after_state)

        try_candidate(0)

    def loaded(ok: bool) -> None:
        if not ok:
            finish(_receipt("failed", "react_preview_load_failed"))
            return
        QTimer.singleShot(700, lambda: page.runJavaScript(snapshot_js, inspect_before))

    page.loadFinished.connect(loaded)
    page.load(QUrl(f"http://127.0.0.1:{preview_port}/"))
    QTimer.singleShot(8000, lambda: finish(_receipt("unavailable", "validation_timeout")))
    app.exec()
    print(json.dumps(output or _receipt("unavailable", "empty_validation_result"), ensure_ascii=False))
    return 0


def _run_child(root: Path) -> int:
    try:
        from PySide6.QtCore import QTimer, QUrl
        from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print(json.dumps(_receipt("unavailable", "pyside6_unavailable")))
        return 0

    try:
        contract = json.loads((root / "behavior_contract.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print(json.dumps(_receipt("failed", "invalid_behavior_contract")))
        return 0
    interactions = contract.get("interactions") if isinstance(contract.get("interactions"), dict) else {}
    events = interactions.get("events") if isinstance(interactions.get("events"), list) else []
    state_ids = [str(item) for item in interactions.get("state_target_ids", []) if item]
    state_selectors = [str(item) for item in interactions.get("state_target_selectors", []) if item]
    state_ids.extend(
        str(item.get("target_id"))
        for item in events
        if isinstance(item, dict) and item.get("target_id") and str(item.get("target_id")) not in state_ids
    )
    state_selectors.extend(
        str(item.get("target_selector"))
        for item in events
        if isinstance(item, dict)
        and item.get("target_selector")
        and str(item.get("target_selector")) not in state_selectors
    )
    mode = str(contract.get("interaction_mode") or "user_event")
    if not (state_ids or state_selectors) or (mode != "passive_timer" and not events):
        print(json.dumps(_receipt("failed", "incomplete_behavior_contract", interaction_mode=mode)))
        return 0

    app = QApplication.instance() or QApplication(["reweave-behavior-validation"])
    profile = QWebEngineProfile()
    page = QWebEnginePage(profile)
    settings = page.settings()
    settings.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
    settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, False)
    output: dict[str, Any] = {}
    state_targets = [{"kind": "id", "value": item} for item in state_ids]
    state_targets.extend({"kind": "selector", "value": item} for item in state_selectors)
    state_json = json.dumps(state_targets)

    snapshot_js = f"""(function(){{
      return JSON.stringify({state_json}.map(function(target){{
        var el=target.kind==='id' ? document.getElementById(target.value) : document.querySelector(target.value);
        return {{target:target.value,value:el ? String(el.value || el.textContent || el.checked || '').trim().slice(0,200) : null}};
      }}));
    }})()"""

    def finish(result: dict[str, Any]) -> None:
        output.update(result)
        app.quit()

    def compare(before: Any) -> None:
        def done(after: Any) -> None:
            try:
                before_rows = json.loads(before) if isinstance(before, str) else []
                after_rows = json.loads(after) if isinstance(after, str) else []
            except json.JSONDecodeError:
                before_rows = after_rows = []
            observations = []
            for old, new in zip(before_rows, after_rows):
                if not isinstance(old, dict) or not isinstance(new, dict):
                    continue
                observations.append(
                    {
                        "target": old.get("target"),
                        "before": old.get("value"),
                        "after": new.get("value"),
                        "changed": old.get("value") != new.get("value"),
                    }
                )
            changed = any(item["changed"] for item in observations)
            finish(
                _receipt(
                    "passed" if changed else "failed",
                    "observable_state_changed" if changed else "observable_state_unchanged",
                    interaction_mode=mode,
                    observations=observations,
                )
            )

        page.runJavaScript(snapshot_js, done)

    def trigger(before: Any) -> None:
        if mode == "passive_timer":
            QTimer.singleShot(3500, lambda: compare(before))
            return
        event = events[0] if isinstance(events[0], dict) else {}
        target_id = str(event.get("target_id") or "")
        target_selector = str(event.get("target_selector") or "")
        event_name = str(event.get("event") or "click")
        trigger_js = f"""(function(){{
          var el={json.dumps(target_id)} ? document.getElementById({json.dumps(target_id)}) : document.querySelector({json.dumps(target_selector)});
          if(!el) return false;
          if({json.dumps(event_name)}==='click' && typeof el.click==='function') el.click();
          else el.dispatchEvent(new Event({json.dumps(event_name)},{{bubbles:true}}));
          return true;
        }})()"""

        def triggered(ok: Any) -> None:
            if not ok:
                finish(_receipt("failed", "interaction_target_missing", interaction_mode=mode))
                return
            QTimer.singleShot(1500, lambda: compare(before))

        page.runJavaScript(trigger_js, triggered)

    def loaded(ok: bool) -> None:
        if not ok:
            finish(_receipt("failed", "preview_load_failed", interaction_mode=mode))
            return
        if mode == "passive_timer":
            prepare_passive_js = f"""(function(){{
              {state_json}.forEach(function(target){{
                var el=target.kind==='id' ? document.getElementById(target.value) : document.querySelector(target.value);
                if(!el) return;
                if('value' in el) el.value='__reweave_probe__';
                else el.textContent='__reweave_probe__';
              }});
              return true;
            }})()"""
            page.runJavaScript(prepare_passive_js, lambda _ok: page.runJavaScript(snapshot_js, trigger))
            return
        prepare_js = """(function(){
          document.querySelectorAll('input').forEach(function(el,i){
            if(el.type==='checkbox'||el.type==='radio') el.checked=true;
            else if(el.type==='number'||el.type==='range') el.value=String(i+2);
            else if(!el.value) el.value='Reweave test';
          });
          document.querySelectorAll('select').forEach(function(el){if(el.options.length) el.selectedIndex=Math.min(1,el.options.length-1);});
          return true;
        })()"""
        page.runJavaScript(prepare_js, lambda _ok: page.runJavaScript(snapshot_js, trigger))

    page.loadFinished.connect(loaded)
    page.load(QUrl.fromLocalFile(str((root / "index.html").resolve())))
    QTimer.singleShot(6500, lambda: finish(_receipt("unavailable", "validation_timeout", interaction_mode=mode)))
    app.exec()
    print(json.dumps(output or _receipt("unavailable", "empty_validation_result"), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--child":
        raise SystemExit(_run_child(Path(sys.argv[2]).resolve()))
    if len(sys.argv) == 5 and sys.argv[1] == "--react-child":
        try:
            declared_contract = json.loads(sys.argv[4])
        except json.JSONDecodeError:
            declared_contract = {}
        raise SystemExit(_run_react_child(Path(sys.argv[2]).resolve(), sys.argv[3], declared_contract))
    raise SystemExit("usage: python -m pimos_lite.reweave_behavior_runtime --child PREVIEW_ROOT")
