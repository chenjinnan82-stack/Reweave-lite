"""Canonical Reweave-lite Stage4 behavior-module extractor.

The source was migrated from Stage4 baseline ``ab8e62d``. Reweave-lite owns
this copy; the old Stage4 worktree is reference history, not a sync source.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from pimos_lite.capsule_module.contract import validate_module_capsule


_FORBIDDEN_LOGIC = re.compile(
    r"\b(?:document|window|localStorage|sessionStorage|fetch|XMLHttpRequest|WebSocket|eval|require)\b"
)
_SECRET = re.compile(
    r"(?is)(?:api[_-]?key|secret|token|password|access[_-]?key|secret[_-]?key)\s*['\"]?\s*[:=]\s*"
    r"(?:['\"][^'\"]+['\"]|[^\s<;]+)|Bearer\s+[A-Za-z0-9\-._~+/]+=*|"
    r"\bsk-[A-Za-z0-9]{8,}\b|-----BEGIN [A-Z ]*PRIVATE KEY-----"
)
_REMOTE_HTML_RESOURCE = re.compile(
    r"(?is)\b(?:src|href|action|poster|srcset|data)\s*=\s*['\"]?\s*"
    r"(?://|/|(?:\.\./)+|%2e|(?!(?:data):)[a-z][a-z0-9+.-]*:)"
)
_REMOTE_META_REFRESH = re.compile(
    r"(?is)<meta\b[^>]*http-equiv\s*=\s*['\"]?refresh[^>]*url\s*=\s*"
    r"(?:[a-z][a-z0-9+.-]*:|/|(?:\.\./)+|%2e)"
)
_REMOTE_CSS_RESOURCE = re.compile(
    r"(?is)(?:url\s*\(\s*['\"]?\s*(?!data:)(?:[a-z][a-z0-9+.-]*:|/|(?:\.\./)+|%2e)|@import\b)"
)
_IGNORED_SOURCE_DIRS = {".git", ".venv", "__pycache__", "build", "coverage", "dist", "node_modules", "venv"}
_MAX_ROLE_FILES = 64
_MAX_SOURCE_TEXT_BYTES = 1024 * 1024


class _UiParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.inputs: list[dict[str, str]] = []
        self.actions: list[dict[str, str]] = []
        self.outputs: list[dict[str, str]] = []
        self.collections: list[dict[str, Any]] = []
        self.stylesheets: list[str] = []
        self.scripts: list[str] = []
        self.script_count = 0
        self._label_text = ""
        self._inside_label = False
        self._output: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        element_id = values.get("id", "").strip()
        if tag == "label":
            self._inside_label = True
            self._label_text = ""
        elif tag == "link" and "stylesheet" in values.get("rel", "").lower() and values.get("href"):
            self.stylesheets.append(values["href"])
        elif tag == "script":
            self.script_count += 1
            if values.get("src"):
                self.scripts.append(values["src"])
        elif tag in {"input", "select", "textarea"} and element_id:
            self.inputs.append(
                {
                    "id": element_id,
                    "type": "selection" if tag == "select" else values.get("type", "text"),
                    "label": self._label_text.strip(),
                }
            )
        elif tag == "button" and element_id:
            self.actions.append({"id": element_id, "event": "click"})
        elif tag == "output" and element_id:
            self._output = {"id": element_id, "text": ""}
            self.outputs.append(self._output)
        elif tag == "tbody" and element_id and values.get("data-record-fields"):
            self.collections.append(
                {
                    "id": element_id,
                    "fields": [field.strip() for field in values["data-record-fields"].split(",") if field.strip()],
                }
            )

    def handle_endtag(self, tag: str) -> None:
        if tag == "label":
            self._inside_label = False
        elif tag == "output":
            self._output = None

    def handle_data(self, data: str) -> None:
        if self._inside_label:
            self._label_text += data
        if self._output is not None:
            self._output["text"] += data


def extract_behavior_module_capsule(
    source_root: str | Path,
    *,
    role: str,
    source_id: str = "",
    source_capsule_id: str = "",
) -> dict[str, Any]:
    """Extract one deliberately small, typed behavior capsule from a read-only source folder."""
    capsules = extract_behavior_module_capsules(
        source_root,
        role=role,
        source_id=source_id,
        source_capsule_id=source_capsule_id,
    )
    if len(capsules) != 1:
        raise ValueError(f"{role}_source_has_multiple_behavior_modules")
    return capsules[0]


def extract_behavior_module_capsules(
    source_root: str | Path,
    *,
    role: str,
    source_id: str = "",
    source_capsule_id: str = "",
) -> list[dict[str, Any]]:
    """Extract every closed behavior module for one role without modifying the source."""
    root = Path(source_root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("source_root_not_directory")
    if role not in {"ui", "logic", "data"}:
        raise ValueError("role_must_be_ui_logic_or_data")
    source_box_id = source_id or root.name
    source_key = _slug(source_box_id)
    if role == "ui":
        try:
            capsules = [_extract_ui(root, source_key, source_box_id, source_capsule_id)]
        except ValueError as strict_error:
            if _fatal_source_error(strict_error) or str(strict_error) == "ui_source_runtime_network_resource_not_allowed":
                raise
            capsules = _extract_event_behavior_modules(
                root, source_key, source_box_id, source_capsule_id
            )["ui"]
            if not capsules:
                raise strict_error
    elif role == "logic":
        try:
            capsules = _extract_logic_modules(root, source_key, source_box_id, source_capsule_id)
        except ValueError as strict_error:
            if _fatal_source_error(strict_error):
                raise
            try:
                capsules = _extract_event_behavior_modules(
                    root, source_key, source_box_id, source_capsule_id
                )["logic"]
            except ValueError as fallback_error:
                if _fatal_source_error(fallback_error):
                    raise
                try:
                    capsules = _extract_class_state_logic_modules(
                        root, source_key, source_box_id, source_capsule_id
                    )
                except ValueError as state_error:
                    if _fatal_source_error(state_error):
                        raise
                    raise strict_error from None
            if not capsules:
                raise strict_error
    else:
        capsules = _extract_data_modules(root, source_key, source_box_id, source_capsule_id)
    for capsule in capsules:
        validation = validate_module_capsule(capsule)
        if not validation["valid"]:
            codes = ",".join(str(row.get("code") or "invalid") for row in validation["errors"])
            raise ValueError(f"extracted_module_invalid:{codes}")
    return capsules


def _read_source_text(root: Path, name: str) -> str:
    path = root / name
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"source_path_outside_root:{name}")
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f"source_symlink_not_allowed:{name}")
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError):
        raise ValueError(f"source_path_outside_root:{name}") from None
    if not resolved.is_file():
        raise ValueError(f"source_file_missing:{name}")
    if resolved.stat().st_size > _MAX_SOURCE_TEXT_BYTES:
        raise ValueError(f"source_file_too_large:{name}")
    text = resolved.read_text(encoding="utf-8")
    if _SECRET.search(text):
        raise ValueError(f"source_secret_detected:{name}")
    return text


def _candidate_source_files(root: Path, suffix: str) -> list[Path]:
    paths: list[Path] = []
    for directory, names, files in os.walk(root, followlinks=False):
        base = Path(directory)
        names[:] = [
            name
            for name in names
            if name not in _IGNORED_SOURCE_DIRS and not (base / name).is_symlink()
        ]
        for name in files:
            if Path(name).suffix.lower() == suffix:
                paths.append((base / name).relative_to(root))
                if len(paths) > _MAX_ROLE_FILES:
                    raise ValueError(f"too_many_{suffix.lstrip('.')}_source_files")
    return sorted(paths)


def _extract_ui(root: Path, source_id: str, source_box_id: str, source_capsule_id: str) -> dict[str, Any]:
    html_path = root / "index.html"
    style_path = root / "styles.css"
    if not html_path.is_file() or not style_path.is_file():
        raise ValueError("ui_source_requires_index_html_and_styles_css")
    html = _read_source_text(root, "index.html")
    styles = _read_source_text(root, "styles.css")
    if _REMOTE_HTML_RESOURCE.search(html) or _REMOTE_META_REFRESH.search(html) or _REMOTE_CSS_RESOURCE.search(styles):
        raise ValueError("ui_source_runtime_network_resource_not_allowed")
    parser = _UiParser()
    parser.feed(html)
    if parser.script_count:
        raise ValueError("ui_source_must_not_include_script")
    if not parser.inputs or len(parser.actions) != 1 or len(parser.outputs) != 1:
        raise ValueError("ui_source_requires_inputs_one_action_one_output")

    action_id = parser.actions[0]["id"]
    output = parser.outputs[0]
    output_type, initial = _literal_type(output["text"].strip())
    input_ports = [
        {
            "id": row["id"],
            "semantic_key": _semantic_key(row.get("label") or row["id"]),
            "value_type": _html_value_type(row["type"]),
            "read": {"kind": "dom_value", "selector": f"#{row['id']}"},
        }
        for row in parser.inputs
    ]
    ports: dict[str, Any] = {
        "inputs": input_ports,
        "actions": [{"id": action_id, "semantic_key": "primary_action", "event": "click", "target": f"#{action_id}"}],
        "outputs": [
            {
                "id": output["id"],
                "semantic_key": "result",
                "value_type": output_type,
                "write": {"kind": "dom_property", "selector": f"#{output['id']}", "property": "textContent"},
            }
        ],
        "state": [
            {
                "id": output["id"],
                "semantic_key": "result",
                "value_type": output_type,
                "initial": initial,
                "changes_on": action_id,
                "expected_change": _ui_expected_change(action_id),
            }
        ],
    }
    if parser.collections:
        ports["collections"] = [
            {
                "id": row["id"],
                "semantic_key": "records",
                "value_type": "record_list",
                "write": {
                    "kind": "dom_table_rows",
                    "selector": f"#{row['id']}",
                    "fields": row["fields"],
                },
            }
            for row in parser.collections
        ]
    return _capsule(
        source_id=source_id,
        role="ui",
        module_kind="behavior_ui",
        tags=_behavior_tags(
            ["behavior", "ui", "form"],
            [*(row["semantic_key"] for row in input_ports), action_id, output["id"]],
        ),
        files=[("index.html", html), ("styles.css", styles)],
        anchors=[*(row["id"] for row in parser.inputs), action_id, output["id"]],
        ports=ports,
        evidence=["index.html", "styles.css"],
        source_box_id=source_box_id,
        source_capsule_id=source_capsule_id,
        identity=action_id,
        summary=(
            f"UI action {action_id}: reads {', '.join(row['semantic_key'] for row in input_ports)}; "
            f"writes result as {output_type}"
        ),
    )


def _local_frontend_asset(reference: str) -> str:
    value = reference.split("#", 1)[0].split("?", 1)[0].strip()
    relative = Path(value)
    if not value or re.match(r"^(?:[a-z]+:)?//", value, re.IGNORECASE):
        raise ValueError("ui_source_runtime_network_resource_not_allowed")
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"source_path_outside_root:{reference}")
    return relative.as_posix().removeprefix("./")


def _extract_event_behavior_modules(
    root: Path,
    source_id: str,
    source_box_id: str,
    source_capsule_id: str,
) -> dict[str, list[dict[str, Any]]]:
    if not (root / "index.html").exists():
        raise ValueError("event_behavior_requires_index_html")
    html = _read_source_text(root, "index.html")
    if _REMOTE_HTML_RESOURCE.search(html) or _REMOTE_META_REFRESH.search(html):
        raise ValueError("ui_source_runtime_network_resource_not_allowed")
    if re.search(r"(?is)\son[a-z]+\s*=", html):
        raise ValueError("event_behavior_inline_handler_not_supported")
    parser = _UiParser()
    parser.feed(html)
    if len(parser.stylesheets) != 1 or len(parser.scripts) != 1 or parser.script_count != 1:
        raise ValueError("event_behavior_requires_one_local_style_and_script")
    style_name = _local_frontend_asset(parser.stylesheets[0])
    script_name = _local_frontend_asset(parser.scripts[0])
    styles = _read_source_text(root, style_name)
    script = _read_source_text(root, script_name)
    if _REMOTE_CSS_RESOURCE.search(styles):
        raise ValueError("ui_source_runtime_network_resource_not_allowed")

    analysis = _analyze_javascript(script_name, script)
    behaviors = analysis.get("behaviors") if isinstance(analysis, dict) else None
    if not isinstance(behaviors, list) or not behaviors:
        raise ValueError("event_behavior_has_no_closed_action")

    inputs_by_id = {row["id"]: row for row in parser.inputs}
    actions_by_id = {row["id"]: row for row in parser.actions}
    outputs_by_id = {row["id"]: row for row in parser.outputs}
    normalized_html = re.sub(r"(?is)<script\b[^>]*>.*?</script\s*>", "", html)
    normalized_html = normalized_html.replace(parser.stylesheets[0], "styles.css")
    ui_modules: dict[str, dict[str, Any]] = {}
    logic_modules: dict[str, dict[str, Any]] = {}
    for behavior in behaviors:
        if not isinstance(behavior, dict):
            continue
        action = behavior.get("action") if isinstance(behavior.get("action"), dict) else {}
        output = behavior.get("output") if isinstance(behavior.get("output"), dict) else {}
        logic = behavior.get("logic") if isinstance(behavior.get("logic"), dict) else {}
        action_id = str(action.get("id") or "")
        output_id = str(output.get("id") or "")
        function_name = str(logic.get("name") or "")
        function_source = str(logic.get("source") or "")
        input_rows = behavior.get("inputs") if isinstance(behavior.get("inputs"), list) else []
        if (
            action_id not in actions_by_id
            or output_id not in outputs_by_id
            or not function_name
            or not function_source
            or not input_rows
            or any(not isinstance(row, dict) or str(row.get("id") or "") not in inputs_by_id for row in input_rows)
        ):
            continue
        input_value_types = [
            _html_value_type(str(inputs_by_id[str(row["id"])].get("type") or "text"))
            for row in input_rows
        ]
        try:
            logic_module = _logic_capsule_from_event(
                logic,
                script_name,
                source_id,
                source_box_id,
                source_capsule_id,
                input_value_types,
            )
        except ValueError:
            continue
        logic_ports = logic_module["ports"]["inputs"]
        if len(logic_ports) != len(input_rows):
            continue
        output_type = str(logic_module["ports"]["outputs"][0]["value_type"])
        input_ports = []
        for row, logic_port in zip(input_rows, logic_ports, strict=True):
            control = inputs_by_id[str(row["id"])]
            value_type = _html_value_type(str(control.get("type") or "text"))
            if value_type != logic_port["value_type"]:
                break
            input_ports.append(
                {
                    "id": str(row["id"]),
                    "semantic_key": str(logic_port["semantic_key"]),
                    "value_type": value_type,
                    "read": {"kind": "dom_value", "selector": f"#{row['id']}"},
                }
            )
        else:
            initial_type, initial = _literal_type(str(outputs_by_id[output_id].get("text") or "").strip())
            if initial_type != output_type:
                initial = _initial_value(output_type)
            ui_module = _capsule(
                source_id=source_id,
                role="ui",
                module_kind="behavior_ui",
                tags=_behavior_tags(
                    ["behavior", "ui", "form"],
                    [*(row["semantic_key"] for row in input_ports), action_id, output_id],
                ),
                files=[("index.html", normalized_html), ("styles.css", styles)],
                anchors=[*(row["id"] for row in input_ports), action_id, output_id],
                ports={
                    "inputs": input_ports,
                    "actions": [
                        {
                            "id": action_id,
                            "semantic_key": "primary_action",
                            "event": str(action.get("event") or "click"),
                            "target": f"#{action_id}",
                        }
                    ],
                    "outputs": [
                        {
                            "id": output_id,
                            "semantic_key": "result",
                            "value_type": output_type,
                            "write": {
                                "kind": "dom_property",
                                "selector": f"#{output_id}",
                                "property": str(output.get("property") or "textContent"),
                            },
                        }
                    ],
                    "state": [
                        {
                            "id": output_id,
                            "semantic_key": "result",
                            "value_type": output_type,
                            "initial": initial,
                            "changes_on": action_id,
                            "expected_change": _ui_expected_change(action_id),
                        }
                    ],
                },
                evidence=["index.html", style_name],
                source_box_id=source_box_id,
                source_capsule_id=source_capsule_id,
                identity=action_id,
                summary=f"UI action {action_id}: calls {function_name} and writes {output_id}",
            )
            ui_modules[ui_module["module_capsule_id"]] = ui_module
            logic_modules[logic_module["module_capsule_id"]] = logic_module
    if not ui_modules or not logic_modules:
        raise ValueError("event_behavior_has_no_closed_action")
    return {"ui": list(ui_modules.values()), "logic": list(logic_modules.values())}


def _analyze_javascript(filename: str, source: str) -> dict[str, Any]:
    analyzer = Path(__file__).resolve().parents[2] / "scripts" / "analyze_reweave_behavior.mjs"
    try:
        completed = subprocess.run(
            ["node", str(analyzer)],
            input=json.dumps({"filename": filename, "source": source}),
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
            cwd=analyzer.parent.parent,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("behavior_ast_runtime_unavailable") from None
    try:
        analysis = json.loads(completed.stdout) if completed.returncode == 0 else {}
    except json.JSONDecodeError:
        analysis = {}
    return analysis if isinstance(analysis, dict) else {}


def _extract_class_state_logic_modules(
    root: Path,
    source_id: str,
    source_box_id: str,
    source_capsule_id: str,
) -> list[dict[str, Any]]:
    modules: dict[str, dict[str, Any]] = {}
    for path in _candidate_source_files(root, ".js"):
        relative = path.as_posix()
        script = _read_source_text(root, relative)
        analysis = _analyze_javascript(relative, script)
        rows = analysis.get("state_behaviors") if isinstance(analysis, dict) else None
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                capsule = _logic_capsule_from_state_behavior(
                    row,
                    relative,
                    source_id,
                    source_box_id,
                    source_capsule_id,
                )
            except ValueError:
                continue
            modules[capsule["module_capsule_id"]] = capsule
    if not modules:
        raise ValueError("class_state_has_no_closed_transition")
    return list(modules.values())


def _extract_logic_modules(root: Path, source_id: str, source_box_id: str, source_capsule_id: str) -> list[dict[str, Any]]:
    paths = _candidate_source_files(root, ".js")
    if not paths:
        raise ValueError("logic_source_requires_javascript_file")
    modules: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in paths:
        try:
            modules.append(
                _extract_logic_file(
                    root,
                    path,
                    source_id,
                    source_box_id,
                    source_capsule_id,
                )
            )
        except ValueError as exc:
            if _fatal_source_error(exc):
                raise
            errors.append(f"{path.as_posix()}:{exc}")
    if modules:
        return modules
    raise ValueError(errors[0] if len(errors) == 1 else "logic_source_has_no_closed_behavior_modules")


def _extract_logic_file(
    root: Path,
    path: Path,
    source_id: str,
    source_box_id: str,
    source_capsule_id: str,
) -> dict[str, Any]:
    relative = path.as_posix()
    script = _read_source_text(root, relative)
    if _FORBIDDEN_LOGIC.search(script):
        raise ValueError("logic_source_must_not_access_runtime_or_dom")
    if len(re.findall(r"\bfunction\s+[A-Za-z_$][\w$]*\s*\(", script)) != 1:
        raise ValueError("logic_source_requires_one_named_returning_function")
    return _logic_capsule_from_script(
        script,
        relative,
        source_id,
        source_box_id,
        source_capsule_id,
    )


def _logic_capsule_from_script(
    script: str,
    relative: str,
    source_id: str,
    source_box_id: str,
    source_capsule_id: str,
) -> dict[str, Any]:
    match = re.fullmatch(
        r"\s*(?P<prefix>(?:(?:const|let|var)\s+[A-Za-z_$][\w$]*\s*=\s*(?:\[\]|\{\}|-?\d+(?:\.\d+)?|true|false|'[^']*'|\"[^\"]*\")\s*;\s*)*)"
        r"function\s+(?P<name>[A-Za-z_$][\w$]*)\s*\((?P<params>[^)]*)\)\s*\{(?P<body>.*)\}\s*;?\s*",
        script,
        re.DOTALL,
    )
    if not match or "return" not in match.group("body"):
        raise ValueError("logic_source_requires_one_named_returning_function")
    function_name = match.group("name")
    body = match.group("body")
    params = [row.strip() for row in match.group("params").split(",") if row.strip()]
    if not params:
        raise ValueError("logic_source_requires_function_inputs")
    action_id = _slug(function_name)
    output_type = _logic_output_type(body)
    expected_change = "incremented" if ".push(" in body and ".length" in body else _ui_expected_change(function_name)
    input_ports = [_logic_input_port(name, function_name, body) for name in params]
    input_summary = ", ".join(f"{row['semantic_key']}:{row['value_type']}" for row in input_ports)
    return _capsule(
        source_id=source_id,
        role="logic",
        module_kind="behavior_state" if expected_change != "updated" else "behavior_logic",
        tags=_behavior_tags(
            ["behavior", "logic"],
            [*(row["semantic_key"] for row in input_ports), function_name, "result"],
        ),
        files=[("app.js", script)],
        anchors=[function_name],
        ports={
            "inputs": input_ports,
            "actions": [{"id": action_id, "semantic_key": "primary_action", "event": "call", "target": function_name}],
            "outputs": [{"id": "result", "semantic_key": "result", "value_type": output_type, "write": {"kind": "return"}}],
            "state": [
                {
                    "id": "result",
                    "semantic_key": "result",
                    "value_type": output_type,
                    "initial": _initial_value(output_type),
                    "changes_on": action_id,
                    "expected_change": expected_change,
                }
            ],
        },
        evidence=[relative],
        source_box_id=source_box_id,
        source_capsule_id=source_capsule_id,
        identity=f"{Path(relative).with_suffix('').as_posix()}-{function_name}",
        summary=f"Function {function_name}: {input_summary} -> result:{output_type}",
    )


def _logic_capsule_from_event(
    logic: dict[str, Any],
    relative: str,
    source_id: str,
    source_box_id: str,
    source_capsule_id: str,
    input_value_types: list[str],
) -> dict[str, Any]:
    function_name = str(logic.get("name") or "")
    script = str(logic.get("source") or "")
    params = [str(row) for row in logic.get("params", []) if isinstance(row, str) and row]
    if (
        not function_name
        or not params
        or len(params) != len(input_value_types)
        or _FORBIDDEN_LOGIC.search(script)
        or not re.search(rf"\bfunction\s+{re.escape(function_name)}\s*\(", script)
        or "return" not in script
    ):
        raise ValueError("event_logic_function_contract_invalid")
    action_id = _slug(function_name)
    output_type = _logic_output_type(script)
    input_ports = [
        {
            "id": _slug(name),
            "semantic_key": _semantic_key(name),
            "value_type": value_type,
            "read": {"kind": "argument"},
        }
        for name, value_type in zip(params, input_value_types, strict=True)
    ]
    input_summary = ", ".join(f"{row['semantic_key']}:{row['value_type']}" for row in input_ports)
    return _capsule(
        source_id=source_id,
        role="logic",
        module_kind="behavior_logic",
        tags=_behavior_tags(
            ["behavior", "logic"],
            [*(row["semantic_key"] for row in input_ports), function_name, "result"],
        ),
        files=[("app.js", script)],
        anchors=[function_name],
        ports={
            "inputs": input_ports,
            "actions": [
                {
                    "id": action_id,
                    "semantic_key": "primary_action",
                    "event": "call",
                    "target": function_name,
                }
            ],
            "outputs": [
                {
                    "id": "result",
                    "semantic_key": "result",
                    "value_type": output_type,
                    "write": {"kind": "return"},
                }
            ],
            "state": [
                {
                    "id": "result",
                    "semantic_key": "result",
                    "value_type": output_type,
                    "initial": _initial_value(output_type),
                    "changes_on": action_id,
                    "expected_change": "updated",
                }
            ],
        },
        evidence=[relative],
        source_box_id=source_box_id,
        source_capsule_id=source_capsule_id,
        identity=f"{Path(relative).with_suffix('').as_posix()}-{function_name}",
        summary=f"Function {function_name}: {input_summary} -> result:{output_type}",
    )


def _logic_capsule_from_state_behavior(
    behavior: dict[str, Any],
    relative: str,
    source_id: str,
    source_box_id: str,
    source_capsule_id: str,
) -> dict[str, Any]:
    class_name = str(behavior.get("class_name") or "")
    function_name = str(behavior.get("method_name") or "")
    state_property = str(behavior.get("state_property") or "")
    script = str(behavior.get("source") or "")
    params = [str(row) for row in behavior.get("params", []) if isinstance(row, str) and row]
    if (
        not class_name
        or not function_name
        or not state_property
        or not params
        or _FORBIDDEN_LOGIC.search(script)
        or not re.fullmatch(
            rf"\s*function\s+{re.escape(function_name)}\s*\([^)]*\)\s*\{{\s*return\b.*;\s*\}}\s*",
            script,
            re.DOTALL,
        )
    ):
        raise ValueError("class_state_function_contract_invalid")
    output_type = _logic_output_type(script)
    input_ports = [_logic_input_port(name, function_name, script) for name in params]
    action_id = _slug(function_name)
    state_id = _slug(state_property)
    input_summary = ", ".join(f"{row['semantic_key']}:{row['value_type']}" for row in input_ports)
    capsule = _capsule(
        source_id=source_id,
        role="logic",
        module_kind="behavior_state",
        tags=_behavior_tags(
            ["behavior", "logic", "state"],
            [*(row["semantic_key"] for row in input_ports), class_name, function_name, state_property],
        ),
        files=[("app.js", script)],
        anchors=[f"{class_name}.{function_name}", state_property],
        ports={
            "inputs": input_ports,
            "actions": [
                {
                    "id": action_id,
                    "semantic_key": "primary_action",
                    "event": "call",
                    "target": function_name,
                }
            ],
            "outputs": [
                {
                    "id": "result",
                    "semantic_key": "result",
                    "value_type": output_type,
                    "write": {"kind": "return"},
                }
            ],
            "state": [
                {
                    "id": state_id,
                    "semantic_key": _semantic_key(state_property),
                    "value_type": output_type,
                    "initial": _initial_value(output_type),
                    "changes_on": action_id,
                    "expected_change": "updated",
                }
            ],
        },
        evidence=[relative],
        source_box_id=source_box_id,
        source_capsule_id=source_capsule_id,
        identity=f"{Path(relative).with_suffix('').as_posix()}-{class_name}-{function_name}",
        summary=f"State projection {class_name}.{function_name}: {input_summary} -> {state_property}:{output_type}",
    )
    source_symbol = str(behavior.get("evidence") or "")
    capsule["provenance"]["source_symbol"] = f"{relative}#{class_name}.{function_name}"
    capsule["provenance"]["source_symbol_sha256"] = hashlib.sha256(source_symbol.encode("utf-8")).hexdigest()
    capsule["provenance"]["extraction_mode"] = "pure_state_projection"
    return capsule


def _extract_data_modules(root: Path, source_id: str, source_box_id: str, source_capsule_id: str) -> list[dict[str, Any]]:
    candidates = _candidate_source_files(root, ".json")
    accepted: list[tuple[Path, str, dict[str, Any]]] = []
    rejected: list[str] = []
    for path in candidates:
        try:
            relative = path.as_posix()
            text = _read_source_text(root, relative)
            accepted.append((path, text, _record_list_payload(text)))
        except (json.JSONDecodeError, ValueError) as exc:
            if isinstance(exc, ValueError) and _fatal_source_error(exc):
                raise
            rejected.append(str(exc))
    if not accepted:
        reason = rejected[0] if not accepted and len(rejected) == 1 else "data_source_requires_one_flat_record_list_json"
        raise ValueError(reason)
    modules: list[dict[str, Any]] = []
    for path, text, data_records in accepted:
        relative = path.as_posix()
        fields = [str(row["name"]) for row in data_records["fields"]]
        modules.append(
            _capsule(
                source_id=source_id,
                role="data",
                module_kind="behavior_data",
                tags=_behavior_tags(["behavior", "data", "records"], fields),
                files=[(relative, text)],
                anchors=fields,
                payload={"data_records": data_records},
                ports={
                    "inputs": [],
                    "actions": [],
                    "outputs": [
                        {
                            "id": "records",
                            "semantic_key": "records",
                            "value_type": "record_list",
                            "write": {"kind": "provide"},
                        }
                    ],
                    "state": [],
                },
                evidence=[relative],
                source_box_id=source_box_id,
                source_capsule_id=source_capsule_id,
                identity=path.with_suffix("").as_posix(),
                summary=f"Record data: {len(data_records['records'])} rows; fields {', '.join(fields)}",
            )
        )
    return modules


def _capsule(
    *,
    source_id: str,
    role: str,
    module_kind: str,
    tags: list[str],
    files: list[tuple[str, str]],
    anchors: list[str],
    payload: dict[str, Any] | None = None,
    ports: dict[str, Any],
    evidence: list[str],
    source_box_id: str,
    source_capsule_id: str,
    identity: str = "",
    summary: str,
) -> dict[str, Any]:
    suffix = f"-{_slug(identity)}" if identity else ""
    module_id = f"module-{source_id}-{role}{suffix}"
    return {
        "module_capsule_version": "module_capsule.v1",
        "module_capsule_id": module_id,
        "library_key": f"source/{source_id}/{role}{suffix}",
        "module_kind": module_kind,
        "capability_tags": tags,
        "capability_summary": summary,
        "status": "active",
        "governance": {"conflicts_with": [], "requires": [], "provides": [f"{source_id}_{role}"]},
        "payload": payload
        or {
            "fragment_bundle": {
                "merge_strategy": "behavior_adapter",
                "anchor_hooks": anchors,
                "files_partial": [{"path": path, "content": content} for path, content in files],
            }
        },
        "ports": ports,
        "provenance": {
            "source_preview_id": f"source-{source_id}",
            "source_box_id": source_box_id,
            "source_capsule_ids": [source_capsule_id or source_id],
            "evidence_refs": evidence,
            "evidence_sha256": {
                path: hashlib.sha256(content.encode("utf-8")).hexdigest()
                for path, (_output_path, content) in zip(evidence, files)
            },
        },
        "permissions": {
            "model_call": False,
            "network_call": False,
            "runtime_network_access": False,
            "source_read": True,
            "source_boundary_escape": False,
            "workspace_write": False,
            "store_write": False,
            "capsule_promotion_allowed": False,
        },
    }


def _html_value_type(value: str) -> str:
    if value == "selection":
        return "selection"
    if value in {"number", "range"}:
        return "number"
    if value in {"checkbox", "radio", "file"}:
        raise ValueError("ui_input_type_not_supported")
    return "string"


def _literal_type(value: str) -> tuple[str, Any]:
    try:
        return "number", float(value) if "." in value else int(value)
    except ValueError:
        return "string", value


def _parameter_type(name: str, body: str) -> str:
    if re.search(rf"\b{re.escape(name)}\s*\.\s*(?:filter|map|reduce|find|some|every)\s*\(", body):
        return "record_list"
    if re.search(rf"\b{re.escape(name)}\s*\.\s*(?:trim|toLowerCase|toUpperCase)\s*\(", body):
        return "string"
    if re.search(rf"(?:\b{re.escape(name)}\b\s*\+\s*['\"]|['\"][^'\"]*['\"]\s*\+\s*\b{re.escape(name)}\b)", body):
        return "string"
    if re.search(rf"(?:\b{re.escape(name)}\b\s*[+\-*/]|[+\-*/]\s*\b{re.escape(name)}\b)", body):
        return "number"
    if re.search(rf"\[\s*{re.escape(name)}\s*\]", body):
        return "selection"
    raise ValueError(f"logic_input_type_ambiguous:{name}")


def _logic_output_type(body: str) -> str:
    if re.search(r"\breturn\s+(?:true|false)\b", body):
        return "boolean"
    if re.search(r"\breturn\b[^;]*(?:['\"][^'\"]*['\"]\s*\+|\+\s*['\"])", body):
        return "string"
    if re.search(r"\breturn\b[^;]*(?:[+\-*/]|\.length|Number\s*\(|parse(?:Int|Float)\s*\()", body):
        return "number"
    return "string"


def _logic_input_port(name: str, function_name: str, body: str) -> dict[str, Any]:
    value_type = _parameter_type(name, body)
    semantic_key = _semantic_key(name)
    context = [
        token
        for token in _semantic_key(function_name).split("_")
        if token not in {"add", "build", "calculate", "compute", "create", "delete", "remove", "run", "save", "set", "submit", "toggle", "update"}
    ]
    if value_type == "string" and semantic_key in {"id", "label", "name", "text", "title", "value"} and len(context) == 1:
        semantic_key = f"{context[0]}_{semantic_key}"
    port = {
        "id": _slug(name),
        "semantic_key": semantic_key,
        "value_type": value_type,
        "read": {"kind": "argument"},
    }
    if value_type == "record_list":
        port["required_fields"] = _record_callback_fields(body)
    return port


def _record_callback_fields(body: str) -> list[str]:
    variables = set(re.findall(r"\.(?:filter|map|find|some|every)\s*\(\s*\(?\s*([A-Za-z_$][\w$]*)", body))
    variables.update(
        re.findall(r"\.reduce\s*\(\s*\(\s*[A-Za-z_$][\w$]*\s*,\s*([A-Za-z_$][\w$]*)", body)
    )
    return sorted(
        {
            field
            for variable in variables
            for field in re.findall(rf"\b{re.escape(variable)}\.([A-Za-z_$][\w$]*)", body)
        }
    )


def _record_list_payload(text: str) -> dict[str, Any]:
    rows = json.loads(text)
    if not isinstance(rows, list) or not rows or len(rows) > 500 or not all(isinstance(row, dict) for row in rows):
        raise ValueError("data_records_requires_1_to_500_objects")
    names = list(rows[0])
    if not names or len(names) > 32 or any(set(row) != set(names) for row in rows):
        raise ValueError("data_records_schema_mismatch")
    fields = [{"name": name, "value_type": _scalar_type(rows[0][name])} for name in names]
    schema = {row["name"]: row["value_type"] for row in fields}
    if any(_scalar_type(row[name]) != schema[name] for row in rows for name in names):
        raise ValueError("data_records_field_type_mismatch")
    return {"schema_version": "record_list.v1", "fields": fields, "records": rows}


def _scalar_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    raise ValueError("data_records_nested_value_not_supported")


def _ui_expected_change(action_id: str) -> str:
    words = set(_semantic_key(action_id).split("_"))
    if words & {"add", "increase", "increment"}:
        return "incremented"
    if words & {"decrease", "decrement", "remove"}:
        return "decremented"
    if "toggle" in words:
        return "toggled"
    return "updated"


def _initial_value(value_type: str) -> Any:
    return {"number": 0, "boolean": False}.get(value_type, "")


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    if not slug:
        raise ValueError("source_id_not_slugifiable")
    return slug


def _semantic_key(value: str) -> str:
    words = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value).lower()
    words = re.sub(r"[^a-z0-9]+", "_", words).strip("_")
    aliases = {"count": "quantity", "qty": "quantity"}
    return "_".join(aliases.get(word, word) for word in words.split("_") if word)


def _behavior_tags(base: list[str], values: list[str]) -> list[str]:
    tags = list(base)
    for value in values:
        semantic = _semantic_key(value)
        raw = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value).lower()
        raw = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
        tags.extend([semantic, *semantic.split("_"), raw, *raw.split("_")])
    return list(dict.fromkeys(tag for tag in tags if tag))


def _fatal_source_error(error: ValueError) -> bool:
    return str(error).startswith(
        (
            "source_path_outside_root:",
            "source_secret_detected:",
            "source_symlink_not_allowed:",
            "source_file_too_large:",
        )
    )


__all__ = ["extract_behavior_module_capsule", "extract_behavior_module_capsules"]
