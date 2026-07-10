"""Run one declared preview behavior in an isolated QtWebEngine page."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "reweave_behavior_validation.v1"


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
    *,
    timeout: float = 10.0,
) -> dict[str, Any]:
    preview = Path(root).resolve() / "react_project" / "dist"
    if not (preview / "index.html").is_file():
        return _receipt("unavailable", "react_runtime_entry_missing")
    try:
        completed = subprocess.run(
            [sys.executable, "-m", __name__, "--react-child", str(preview), expected_text[:160]],
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


def _run_react_child(root: Path, expected_text: str) -> int:
    try:
        from PySide6.QtCore import QTimer, QUrl
        from PySide6.QtWebEngineCore import (
            QWebEnginePage,
            QWebEngineProfile,
            QWebEngineSettings,
            QWebEngineUrlRequestInterceptor,
        )
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print(json.dumps(_receipt("unavailable", "pyside6_unavailable")))
        return 0

    app = QApplication.instance() or QApplication(["reweave-react-validation"])
    console_messages: list[str] = []
    blocked_requests: list[str] = []
    allowed_root = root.resolve()

    class ValidationPage(QWebEnginePage):
        def javaScriptConsoleMessage(self, _level: Any, message: str, _line: int, _source: str) -> None:
            console_messages.append(message[:240])

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
            if not allowed:
                blocked_requests.append(scheme or "unknown")
                info.block(True)

    profile = QWebEngineProfile()
    request_interceptor = PreviewRequestInterceptor()
    profile.setUrlRequestInterceptor(request_interceptor)
    page = ValidationPage(profile)
    settings = page.settings()
    settings.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
    settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, False)
    output: dict[str, Any] = {}
    snapshot_js = (
        "JSON.stringify({text:(document.body.innerText||'').trim(),"
        "root:(document.getElementById('root')||{}).innerText||'',"
        "state:(document.body.innerText||'').trim()+'|'+"
        "Array.from(document.querySelectorAll('input,textarea,select')).map(function(el){"
        "return String(el.value||el.checked||'');}).join('|'),"
        "buttons:document.querySelectorAll('button').length})"
    )

    def finish(result: dict[str, Any]) -> None:
        result.setdefault("request_scope", "preview_root_only")
        result.setdefault("blocked_request_count", len(blocked_requests))
        if console_messages:
            result.setdefault("console_messages", console_messages[-5:])
        output.update(result)
        app.quit()

    def inspect_before(raw: Any) -> None:
        try:
            before = json.loads(raw) if isinstance(raw, str) else {}
        except json.JSONDecodeError:
            before = {}
        if not str(before.get("root") or "").strip():
            finish(_receipt("failed", "react_root_not_rendered"))
            return
        button_count = min(int(before.get("buttons") or 0), 12)
        if not button_count:
            finish(_receipt("needs_review", "react_button_not_found", rendered=True))
            return

        def try_button(index: int, current: dict[str, Any]) -> None:
            if index >= button_count:
                finish(
                    _receipt(
                        "needs_review",
                        "react_interaction_unchanged",
                        rendered=True,
                        interaction_present=True,
                        interaction_changed=False,
                        buttons_checked=button_count,
                    )
                )
                return

            def inspect_after(after_raw: Any) -> None:
                try:
                    after = json.loads(after_raw) if isinstance(after_raw, str) else {}
                except json.JSONDecodeError:
                    after = {}
                changed = str(current.get("state") or "") != str(after.get("state") or "")
                task_rendered = (
                    not expected_text
                    or expected_text in str(before.get("text") or "")
                    or expected_text in str(after.get("text") or "")
                )
                if changed:
                    finish(
                        _receipt(
                            "passed" if task_rendered else "needs_review",
                            "react_interaction_changed_dom"
                            if task_rendered
                            else "adapted_task_text_not_rendered",
                            rendered=True,
                            task_text_rendered=task_rendered,
                            interaction_present=True,
                            interaction_changed=True,
                            button_index=index,
                        )
                    )
                    return
                try_button(index + 1, after)

            script = (
                "(function(){var button=document.querySelectorAll('button')["
                f"{index}];if(!button||button.disabled)return false;button.click();return true;}})()"
            )
            page.runJavaScript(
                script,
                lambda clicked: (
                    QTimer.singleShot(500, lambda: page.runJavaScript(snapshot_js, inspect_after))
                    if clicked
                    else try_button(index + 1, current)
                ),
            )

        try_button(0, before)

    def loaded(ok: bool) -> None:
        if not ok:
            finish(_receipt("failed", "react_preview_load_failed"))
            return
        QTimer.singleShot(700, lambda: page.runJavaScript(snapshot_js, inspect_before))

    page.loadFinished.connect(loaded)
    page.load(QUrl.fromLocalFile(str((root / "index.html").resolve())))
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
    if len(sys.argv) == 4 and sys.argv[1] == "--react-child":
        raise SystemExit(_run_react_child(Path(sys.argv[2]).resolve(), sys.argv[3]))
    raise SystemExit("usage: python -m pimos_lite.reweave_behavior_runtime --child PREVIEW_ROOT")
