"""Non-active Stage 3 safety, supervision, validation, and publication path."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import signal
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from pimos_lite.reweave_capsule_intake import (
    EXTRACTION_CONTRACT_VERSION,
    IntakeError,
    REDACTION_RULES_VERSION,
    ReweaveCapsuleIntake,
    _local_reference,
)
from pimos_lite.reweave_capsule_store import (
    CANONICALIZATION_VERSION,
    CapsuleWarehouseStore,
    canonicalize_capsule,
)
from pimos_lite.reweave_data_contract import (
    DataContractError,
    data_contract_accepts,
    generate_synthetic_fixtures,
    normalize_capsule_contracts,
)
from pimos_lite.reweave_process_environment import restricted_subprocess_environment


SECURITY_RULES_VERSION = "security_rules.v1"
SUPERVISION_RULES_VERSION = "supervision_rules.v1"
VALIDATION_CONTRACT_VERSION = "validation_contract.v1"
MAX_HTTP_BYTES = 1024 * 1024
MAX_ASSET_BYTES = 1024 * 1024
MAX_ASSET_TOTAL_BYTES = 5 * 1024 * 1024
MAX_HTML_DEPTH = 64

_SAFE_TAGS = frozenset(
    {
        "article", "button", "div", "em", "fieldset", "footer", "form",
        "h1", "h2", "h3", "h4", "h5", "h6", "header", "img", "input",
        "label", "legend", "li", "main", "ol", "option", "p", "section", "select",
        "small", "span", "strong", "table", "tbody", "td", "template",
        "textarea", "th", "thead", "tr", "ul",
    }
)
_VOID_TAGS = frozenset({"img", "input"})
_SAFE_INPUT_TYPES = frozenset({"checkbox", "number", "radio", "text"})
_SAFE_BUTTON_TYPES = frozenset({"button", "reset", "submit"})
_COMMON_ATTRIBUTES = frozenset({"class", "data-action", "data-ref", "data-state", "role"})
_FORM_ATTRIBUTES = frozenset(
    {
        "checked", "disabled", "max", "maxlength", "min", "minlength", "name",
        "placeholder", "readonly", "required", "selected", "step", "value",
    }
)
_CSS_PROPERTIES = frozenset(
    {
        "align-content", "align-items", "align-self", "aspect-ratio",
        "background-color", "border", "border-bottom", "border-bottom-color",
        "border-bottom-style", "border-bottom-width", "border-collapse",
        "border-color", "border-left", "border-left-color", "border-left-style",
        "border-left-width", "border-radius", "border-right", "border-right-color",
        "border-right-style", "border-right-width", "border-spacing", "border-style",
        "border-top", "border-top-color", "border-top-style", "border-top-width",
        "border-width", "box-shadow", "box-sizing", "caption-side", "color",
        "column-gap", "cursor", "display", "flex", "flex-basis", "flex-direction",
        "flex-flow", "flex-grow", "flex-shrink", "flex-wrap", "font-family",
        "font-size", "font-style", "font-weight", "gap", "grid-auto-columns",
        "grid-auto-flow", "grid-auto-rows", "grid-column", "grid-row",
        "grid-template-columns", "grid-template-rows", "height", "justify-content",
        "justify-items", "justify-self", "letter-spacing", "line-height", "list-style",
        "list-style-position", "list-style-type", "margin", "margin-bottom",
        "margin-left", "margin-right", "margin-top", "max-height", "max-width",
        "min-height", "min-width", "object-fit", "opacity", "order", "overflow",
        "overflow-wrap", "overflow-x", "overflow-y", "padding", "padding-bottom",
        "padding-left", "padding-right", "padding-top", "pointer-events", "position",
        "row-gap", "table-layout", "text-align", "text-decoration", "text-overflow",
        "text-transform", "user-select", "visibility", "white-space", "width",
        "word-break",
    }
)
_CSS_FORBIDDEN_WORDS = frozenset(
    {
        "animation", "attr", "calc", "clamp", "env", "expression", "fixed",
        "important", "max", "min", "sticky", "transform", "transition", "url", "var",
    }
)
_CSS_FUNCTIONS = frozenset({"hsl", "hsla", "rgb", "rgba"})
_CSS_PSEUDOS = frozenset(
    {
        "checked", "disabled", "first-child", "focus", "focus-visible", "hover",
        "last-child",
    }
)
_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*\Z")
_CLASS_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*\Z")
_SNAKE = re.compile(r"[a-z_][a-z0-9_]*\Z")
_MODEL_CODE = re.compile(r"[A-Za-z0-9_.:-]+\Z")
_EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_PHONE = re.compile(r"(?<!\d)(?:\+?\d[\d ()-]{7,}\d)(?!\d)")
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_RECORD_VALUE = re.compile(
    r"(?is)\b(?:customer|client|person|employee|patient|order|account|address|phone|email)"
    r"(?:[_-]?(?:id|name|number))?\b\s*[:=]\s*['\"]([^'\"]+)['\"]"
)
_SENSITIVE_NAME = re.compile(
    r"(?i)(?:customer|client|person|employee|patient|email|phone|address|account|card|secret|token|password)"
)


class Stage3Error(RuntimeError):
    def __init__(self, code: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.details = details


@dataclass(frozen=True)
class CleanAsset:
    logical_path: str
    media_type: str
    sha256: str
    size_bytes: int
    width: int
    height: int
    content: bytes


@dataclass(frozen=True)
class Stage3Artifact:
    canonical_payload: dict[str, Any]
    canonical_hash: str
    assets: tuple[CleanAsset, ...]
    cleaning_summary: dict[str, Any]
    security_result: dict[str, Any]
    supervision: dict[str, Any] | None = None
    supervision_response_hash: str | None = None
    model_name: str | None = None
    model_digest: str | None = None
    supervised_at: str | None = None
    validation: dict[str, Any] | None = None


class _HtmlTreeParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root: dict[str, Any] = {"tag": None, "attrs": [], "children": []}
        self.stack = [self.root]
        self.failed = False
        self.declarations = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.failed:
            return
        if len(self.stack) > MAX_HTML_DEPTH:
            self.failed = True
            return
        tag = tag.lower()
        names = [name.lower() for name, _value in attrs]
        if len(names) != len(set(names)):
            self.failed = True
            return
        node = {
            "tag": tag,
            "attrs": [(name.lower(), value if value is not None else None) for name, value in attrs],
            "children": [],
        }
        self.stack[-1]["children"].append(node)
        if tag not in _VOID_TAGS and tag not in {"area", "base", "br", "col", "embed", "hr", "link", "meta", "source", "track", "wbr"}:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if self.failed:
            return
        if self.stack[-1].get("tag") == tag.lower():
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        if self.failed:
            return
        tag = tag.lower()
        if len(self.stack) == 1 or self.stack[-1].get("tag") != tag:
            self.failed = True
            return
        self.stack.pop()

    def handle_data(self, data: str) -> None:
        if self.failed:
            return
        self.stack[-1]["children"].append(data)

    def handle_comment(self, _data: str) -> None:
        return

    def handle_pi(self, _data: str) -> None:
        self.failed = True

    def handle_decl(self, declaration: str) -> None:
        self.declarations += 1
        if (
            self.declarations > 1
            or len(self.stack) != 1
            or declaration.strip().casefold() != "doctype html"
        ):
            self.failed = True

    def close(self) -> None:
        super().close()
        if len(self.stack) != 1:
            self.failed = True


def sanitize_html(
    source: str,
    *,
    dom_scope: dict[str, Any],
    asset_paths: set[str],
    redact_strings: list[str],
    entry_relpath: str = "index.html",
    referenced_asset_paths: set[str] | None = None,
) -> str:
    parser = _HtmlTreeParser()
    try:
        parser.feed(source)
        parser.close()
    except Exception as exc:
        raise Stage3Error("html_parse_failed") from exc
    if parser.failed:
        raise Stage3Error("html_parse_failed")
    explicit: list[dict[str, Any]] = []
    mains: list[dict[str, Any]] = []
    forms: list[dict[str, Any]] = []

    def find(node: dict[str, Any]) -> None:
        attrs = dict(node.get("attrs", []))
        if "data-capsule-root" in attrs:
            explicit.append(node)
        if node.get("tag") == "main":
            mains.append(node)
        if node.get("tag") == "form":
            forms.append(node)
        for child in node.get("children", []):
            if isinstance(child, dict):
                find(child)

    find(parser.root)
    if explicit:
        root = explicit[0] if len(explicit) == 1 else None
    elif len(mains) == 1:
        root = mains[0]
    else:
        root = forms[0] if len(forms) == 1 else None
    if root is None:
        raise Stage3Error("html_capsule_root_invalid")

    selectors = set(str(item) for item in dom_scope.get("selectors", []))
    declared_attributes = set(str(item) for item in dom_scope.get("attributes", []))
    ids: dict[str, str] = {}
    rewritten_ids: set[str] = set()
    seen_selectors: set[str] = set()

    def clean_node(node: dict[str, Any]) -> str:
        tag = str(node["tag"])
        if tag not in _SAFE_TAGS:
            raise Stage3Error("html_tag_forbidden")
        attrs = dict(node["attrs"])
        attrs.pop("data-capsule-root", None)
        cleaned: dict[str, str | None] = {}
        for name, raw_value in attrs.items():
            value = "" if raw_value is None else str(raw_value)
            if name.startswith("on") or name in {
                "action", "enctype", "formaction", "href", "method", "srcset", "style", "target",
            }:
                raise Stage3Error("html_attribute_forbidden")
            if name == "id":
                rewritten = f"__CAPSULE_ID__-{value.lower()}"
                if (
                    not _TOKEN.fullmatch(value)
                    or value in ids
                    or rewritten in rewritten_ids
                ):
                    raise Stage3Error("html_id_invalid")
                ids[value] = rewritten
                rewritten_ids.add(rewritten)
                cleaned[name] = rewritten
                continue
            if name == "for":
                if tag != "label" or not _TOKEN.fullmatch(value):
                    raise Stage3Error("html_label_target_invalid")
                cleaned[name] = value
                continue
            if name in _COMMON_ATTRIBUTES or name.startswith("aria-"):
                if name == "class":
                    if any(not _CLASS_TOKEN.fullmatch(item) for item in value.split()):
                        raise Stage3Error("html_class_invalid")
                elif name.startswith("aria-") and not _TOKEN.fullmatch(name):
                    raise Stage3Error("html_attribute_forbidden")
                elif name.startswith("aria-") and name not in declared_attributes:
                    raise Stage3Error("html_attribute_not_declared")
                elif name == "data-state" and name not in declared_attributes:
                    raise Stage3Error("html_attribute_not_declared")
                elif name in {"data-action", "data-ref", "data-state", "role"} and not _TOKEN.fullmatch(value):
                    raise Stage3Error("html_attribute_value_invalid")
                if name in {"data-action", "data-ref"}:
                    seen_selectors.update({f"[{name}='{value}']", f'[{name}="{value}"]'})
                cleaned[name] = _redact_text(value, redact_strings)
                continue
            if tag in {"button", "fieldset", "form", "input", "option", "select", "textarea"} and name in _FORM_ATTRIBUTES:
                cleaned[name] = None if raw_value is None else _redact_text(value, redact_strings)
                continue
            if tag == "input" and name == "type":
                if value.lower() not in _SAFE_INPUT_TYPES:
                    raise Stage3Error("html_input_type_forbidden")
                cleaned[name] = value.lower()
                continue
            if tag == "button" and name == "type":
                if value.lower() not in _SAFE_BUTTON_TYPES:
                    raise Stage3Error("html_button_type_forbidden")
                cleaned[name] = value.lower()
                continue
            if tag == "img" and name in {"alt", "height", "loading", "src", "width"}:
                if name == "src":
                    try:
                        logical_asset = _local_reference(entry_relpath, value)
                    except Exception as exc:
                        raise Stage3Error("html_asset_not_registered") from exc
                    if logical_asset not in asset_paths:
                        raise Stage3Error("html_asset_not_registered")
                    if referenced_asset_paths is not None:
                        referenced_asset_paths.add(logical_asset)
                    cleaned[name] = logical_asset
                elif name == "loading":
                    if value not in {"eager", "lazy"}:
                        raise Stage3Error("html_image_loading_invalid")
                    cleaned[name] = value
                elif name in {"height", "width"}:
                    if not value.isdigit() or not 1 <= int(value) <= 4096:
                        raise Stage3Error("html_image_dimension_invalid")
                    cleaned[name] = value
                else:
                    cleaned[name] = _redact_text(value, redact_strings)
                continue
            if tag in {"td", "th"} and name in {"colspan", "rowspan"}:
                if not value.isdigit() or not 1 <= int(value) <= 20:
                    raise Stage3Error("html_table_span_invalid")
                cleaned[name] = value
                continue
            raise Stage3Error("html_attribute_forbidden")

        body = []
        for child in node["children"]:
            body.append(clean_node(child) if isinstance(child, dict) else html.escape(_redact_text(str(child), redact_strings), quote=False))
        attr_text = "".join(
            f" {name}" if value is None else f' {name}="{html.escape(value, quote=True)}"'
            for name, value in sorted(cleaned.items())
        )
        if tag in _VOID_TAGS:
            if body:
                raise Stage3Error("html_void_tag_has_children")
            return f"<{tag}{attr_text}>"
        return f"<{tag}{attr_text}>{''.join(body)}</{tag}>"

    cleaned_html = clean_node(root)
    missing = [selector for selector in selectors if selector.startswith(("[data-action", "[data-ref")) and selector not in seen_selectors]
    if missing:
        raise Stage3Error("html_declared_selector_missing")
    for original, rewritten in ids.items():
        cleaned_html = cleaned_html.replace(f' for="{html.escape(original, quote=True)}"', f' for="{rewritten}"')
    if re.search(r"\sfor=\"(?!__CAPSULE_ID__-)", cleaned_html):
        raise Stage3Error("html_label_target_invalid")
    return cleaned_html.replace("\r\n", "\n").replace("\r", "\n")


def sanitize_css(source: str, *, redact_strings: list[str]) -> str:
    text = _strip_css_comments(source)
    if "\\" in text:
        raise Stage3Error("css_escape_forbidden")
    folded = text.casefold()
    if any(item and item.casefold() in folded for item in redact_strings):
        raise Stage3Error("css_redaction_unsupported")
    rules = _split_css_rules(text)
    output: list[str] = []
    for selector_text, block in rules:
        branches = _split_css_items(selector_text, ",")
        selectors = [_scope_css_selector(item.strip()) for item in branches]
        declarations: list[str] = []
        for declaration in _split_css_items(block, ";"):
            if not declaration.strip():
                continue
            name, value = _split_css_declaration(declaration)
            if name not in _CSS_PROPERTIES:
                raise Stage3Error("css_property_forbidden")
            cleaned_value = _validate_css_value(name, value)
            declarations.append(f"  {name}: {cleaned_value};")
        if not declarations:
            raise Stage3Error("css_empty_rule_forbidden")
        output.append(f"{', '.join(selectors)} {{\n" + "\n".join(declarations) + "\n}")
    return "\n\n".join(output) + ("\n" if output else "")


def _strip_css_comments(source: str) -> str:
    output: list[str] = []
    index = 0
    quote: str | None = None
    while index < len(source):
        char = source[index]
        if quote:
            output.append(char)
            if char == quote:
                quote = None
            index += 1
            continue
        if char in {'"', "'"}:
            quote = char
            output.append(char)
            index += 1
            continue
        if source.startswith("/*", index):
            end = source.find("*/", index + 2)
            if end < 0:
                raise Stage3Error("css_comment_unclosed")
            index = end + 2
            continue
        output.append(char)
        index += 1
    if quote:
        raise Stage3Error("css_string_unclosed")
    return "".join(output)


def _split_css_rules(source: str) -> list[tuple[str, str]]:
    rules: list[tuple[str, str]] = []
    index = 0
    while index < len(source):
        while index < len(source) and source[index].isspace():
            index += 1
        if index == len(source):
            break
        if source[index] == "@":
            raise Stage3Error("css_at_rule_forbidden")
        start = index
        quote: str | None = None
        paren = 0
        while index < len(source):
            char = source[index]
            if quote:
                if char == quote:
                    quote = None
            elif char in {'"', "'"}:
                quote = char
            elif char == "(":
                paren += 1
            elif char == ")":
                paren -= 1
                if paren < 0:
                    raise Stage3Error("css_parenthesis_invalid")
            elif char == "{" and paren == 0:
                break
            elif char == "}" and paren == 0:
                raise Stage3Error("css_rule_invalid")
            index += 1
        if index == len(source) or quote or paren:
            raise Stage3Error("css_rule_unclosed")
        selector = source[start:index].strip()
        index += 1
        block_start = index
        quote = None
        paren = 0
        while index < len(source):
            char = source[index]
            if quote:
                if char == quote:
                    quote = None
            elif char in {'"', "'"}:
                quote = char
            elif char == "(":
                paren += 1
            elif char == ")":
                paren -= 1
                if paren < 0:
                    raise Stage3Error("css_parenthesis_invalid")
            elif char == "{" and paren == 0:
                raise Stage3Error("css_nesting_forbidden")
            elif char == "}" and paren == 0:
                break
            index += 1
        if index == len(source) or quote or paren:
            raise Stage3Error("css_rule_unclosed")
        rules.append((selector, source[block_start:index]))
        index += 1
    return rules


def _split_css_items(source: str, separator: str) -> list[str]:
    result: list[str] = []
    start = 0
    quote: str | None = None
    depth = 0
    for index, char in enumerate(source):
        if quote:
            if char == quote:
                quote = None
        elif char in {'"', "'"}:
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                raise Stage3Error("css_parenthesis_invalid")
        elif char == separator and depth == 0:
            result.append(source[start:index])
            start = index + 1
    if quote or depth:
        raise Stage3Error("css_token_invalid")
    result.append(source[start:])
    return result


def _scope_css_selector(selector: str) -> str:
    if not selector:
        raise Stage3Error("css_selector_empty")
    if any(token in selector.casefold() for token in (":root", "::", ":has(", ":not(")):
        raise Stage3Error("css_selector_forbidden")
    if "#" in selector or "*" in selector or "[" in selector and "]" not in selector:
        raise Stage3Error("css_selector_forbidden")
    index = 0
    while index < len(selector):
        char = selector[index]
        if char in "+~":
            raise Stage3Error("css_selector_forbidden")
        if char.isspace() or char == ">":
            index += 1
            continue
        if char == ".":
            index += 1
            start = index
            while index < len(selector) and (selector[index].isalnum() or selector[index] in "_-"):
                index += 1
            if not _CLASS_TOKEN.fullmatch(selector[start:index]):
                raise Stage3Error("css_class_invalid")
            continue
        if char == "[":
            end = selector.find("]", index + 1)
            if end < 0:
                raise Stage3Error("css_attribute_selector_invalid")
            content = selector[index + 1 : end].strip()
            name = content.split("=", 1)[0].strip()
            if name not in {"data-action", "data-ref", "data-state"} and not name.startswith("aria-"):
                raise Stage3Error("css_attribute_selector_forbidden")
            if "=" in content:
                value = content.split("=", 1)[1].strip()
                if len(value) < 2 or value[0] not in {'"', "'"} or value[-1] != value[0] or not _TOKEN.fullmatch(value[1:-1]):
                    raise Stage3Error("css_attribute_selector_invalid")
            index = end + 1
            continue
        if char == ":":
            index += 1
            start = index
            while index < len(selector) and (selector[index].isalnum() or selector[index] == "-"):
                index += 1
            pseudo = selector[start:index]
            if pseudo == "nth-child":
                if index >= len(selector) or selector[index] != "(":
                    raise Stage3Error("css_pseudo_forbidden")
                end = selector.find(")", index + 1)
                if end < 0 or not selector[index + 1 : end].isdigit() or int(selector[index + 1 : end]) < 1:
                    raise Stage3Error("css_pseudo_forbidden")
                index = end + 1
            elif pseudo not in _CSS_PSEUDOS:
                raise Stage3Error("css_pseudo_forbidden")
            continue
        start = index
        while index < len(selector) and (selector[index].isalnum() or selector[index] in "_-"):
            index += 1
        if index == start:
            raise Stage3Error("css_selector_forbidden")
        token = selector[start:index]
        if token == "__CAPSULE_ROOT__":
            continue
        if token not in _SAFE_TAGS:
            raise Stage3Error("css_tag_selector_forbidden")
    return selector if selector.startswith("__CAPSULE_ROOT__") else f"__CAPSULE_ROOT__ {selector}"


def _split_css_declaration(source: str) -> tuple[str, str]:
    if ":" not in source:
        raise Stage3Error("css_declaration_invalid")
    name, value = source.split(":", 1)
    name = name.strip().lower()
    if not _TOKEN.fullmatch(name):
        raise Stage3Error("css_property_invalid")
    return name, value.strip()


def _validate_css_value(name: str, value: str) -> str:
    if not value or any(char in value for char in "{}@!\\"):
        raise Stage3Error("css_value_forbidden")
    if name == "position" and value not in {"relative", "static"}:
        raise Stage3Error("css_position_forbidden")
    index = 0
    while index < len(value):
        char = value[index]
        if char.isspace() or char in ",/":
            index += 1
            continue
        if char in {'"', "'"}:
            end = value.find(char, index + 1)
            if end < 0:
                raise Stage3Error("css_string_unclosed")
            if any(ord(item) < 32 for item in value[index + 1 : end]):
                raise Stage3Error("css_string_invalid")
            index = end + 1
            continue
        if char == "#":
            index += 1
            start = index
            while index < len(value) and value[index] in "0123456789abcdefABCDEF":
                index += 1
            if index - start not in {3, 4, 6, 8}:
                raise Stage3Error("css_color_invalid")
            continue
        if char.isdigit() or char in "+-.":
            start = index
            if char in "+-":
                index += 1
            digits = 0
            dots = 0
            while index < len(value) and (value[index].isdigit() or value[index] == "."):
                digits += value[index].isdigit()
                dots += value[index] == "."
                index += 1
            if not digits or dots > 1:
                raise Stage3Error("css_number_invalid")
            unit_start = index
            while index < len(value) and (value[index].isalpha() or value[index] == "%"):
                index += 1
            unit = value[unit_start:index].lower()
            if unit not in {"", "%", "em", "fr", "px", "rem"}:
                raise Stage3Error("css_unit_forbidden")
            continue
        if char.isalpha() or char in "_-":
            start = index
            while index < len(value) and (value[index].isalnum() or value[index] in "_-"):
                index += 1
            word = value[start:index]
            folded = word.casefold()
            if folded in _CSS_FORBIDDEN_WORDS:
                raise Stage3Error("css_keyword_forbidden")
            if index < len(value) and value[index] == "(":
                if folded not in _CSS_FUNCTIONS:
                    raise Stage3Error("css_function_forbidden")
                end = value.find(")", index + 1)
                if end < 0 or "(" in value[index + 1 : end]:
                    raise Stage3Error("css_function_invalid")
                inner = value[index + 1 : end]
                if any(char not in "0123456789.,% /+-" for char in inner):
                    raise Stage3Error("css_function_invalid")
                index = end + 1
            continue
        raise Stage3Error("css_value_token_forbidden")
    return " ".join(value.split())


def _redact_text(value: str, terms: list[str]) -> str:
    result = value
    for term in sorted(set(terms), key=len, reverse=True):
        if not term:
            continue
        result = re.sub(re.escape(term), "[REDACTED]", result, flags=re.IGNORECASE)
    return result


def _sensitive_values(source: str) -> list[str]:
    values = _EMAIL.findall(source) + _PHONE.findall(source) + _CARD.findall(source)
    values.extend(_RECORD_VALUE.findall(source))
    return sorted(set(str(item) for item in values if item), key=len, reverse=True)


def _sensitive_html_values(source: str) -> list[str]:
    parser = _HtmlTreeParser()
    try:
        parser.feed(source)
        parser.close()
    except Exception:
        return []
    values: list[str] = _sensitive_values(html.unescape(source))

    def text_content(node: dict[str, Any]) -> str:
        return "".join(
            text_content(item) if isinstance(item, dict) else str(item)
            for item in node.get("children", [])
        ).strip()

    def visit(node: dict[str, Any]) -> None:
        attrs = dict(node.get("attrs", []))
        identity = " ".join(
            str(attrs.get(name) or "") for name in ("data-ref", "id", "name")
        )
        if _SENSITIVE_NAME.search(identity):
            for name in ("placeholder", "value"):
                if attrs.get(name):
                    values.append(str(attrs[name]))
            content = text_content(node)
            if content:
                values.append(content)
        for child in node.get("children", []):
            if isinstance(child, dict):
                visit(child)

    visit(parser.root)
    return sorted(set(values), key=len, reverse=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _uuid() -> str:
    return str(uuid.uuid4())


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def _loopback_base(value: str) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in {"127.0.0.1", "::1", "localhost"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise Stage3Error("ollama_loopback_required")
    try:
        parsed.port
    except ValueError as exc:
        raise Stage3Error("ollama_address_invalid") from exc
    return value.rstrip("/")


class OllamaSupervisor:
    """One loopback-only model selection and supervision path."""

    def __init__(self, store: CapsuleWarehouseStore) -> None:
        self.store = store

    def list_models(self, base_url: str) -> list[dict[str, str]]:
        payload, _raw = self._request(_loopback_base(base_url), "/api/tags")
        rows: list[dict[str, str]] = []
        if type(payload.get("models")) is not list:
            raise Stage3Error("ollama_response_invalid")
        for item in payload["models"]:
            if type(item) is not dict:
                continue
            name = item.get("name")
            digest = item.get("digest")
            if type(name) is str and name and type(digest) is str and digest:
                rows.append({"name": name, "digest": digest})
        return sorted(rows, key=lambda row: (row["name"], row["digest"]))

    def select_model(self, base_url: str, name: str, digest: str) -> dict[str, str]:
        base = _loopback_base(base_url)
        if {"name": name, "digest": digest} not in self.list_models(base):
            raise Stage3Error("ollama_model_not_available")
        selected = {
            "base_url": base,
            "name": name,
            "digest": digest,
            "selected_at": _now(),
        }
        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO app_settings(setting_key, value_json, updated_at) VALUES "
                "('capsule_supervision_model', ?, ?) ON CONFLICT(setting_key) DO UPDATE "
                "SET value_json = excluded.value_json, updated_at = excluded.updated_at",
                (_json(selected), selected["selected_at"]),
            )
            self.store.bump_revision(connection)
        return selected

    def selected_model(self) -> dict[str, str]:
        with self.store.read_connection() as connection:
            row = connection.execute(
                "SELECT value_json FROM app_settings WHERE setting_key = "
                "'capsule_supervision_model'"
            ).fetchone()
        if row is None:
            raise Stage3Error("ollama_model_not_selected")
        try:
            selected = json.loads(row[0])
        except (TypeError, json.JSONDecodeError) as exc:
            raise Stage3Error("ollama_selection_invalid") from exc
        if set(selected) != {"base_url", "name", "digest", "selected_at"}:
            raise Stage3Error("ollama_selection_invalid")
        return {key: str(value) for key, value in selected.items()}

    def supervise(
        self, summary: dict[str, Any], capability_kind: str
    ) -> tuple[dict[str, Any], str, dict[str, str]]:
        selected = self.selected_model()
        if {"name": selected["name"], "digest": selected["digest"]} not in self.list_models(
            selected["base_url"]
        ):
            raise Stage3Error("ollama_model_digest_changed")
        example = {
            "schema_version": "capsule_supervision.v1",
            "verdict": "approve",
            "capability_kind": capability_kind,
            "semantic_summary": "Describe the declared local capability.",
            "keep_reason_codes": ["DECLARED_LOCAL_CAPABILITY"],
            "remove_reason_codes": [],
            "brand_signals": [],
            "sensitive_data_status": "clear",
            "hidden_dependency_codes": [],
            "duplicate_suggestions": [],
            "review_required": False,
        }
        prompt = (
            "Return only one JSON object with exactly the keys and value types in this example: "
            + _json(example)
            + ". Use approve, review, or reject for verdict and keep capability_kind unchanged. "
            "You may supervise and name; do not change extraction boundaries, contracts, or code.\n"
            + _json(summary)
        )
        response, _http_raw = self._request(
            selected["base_url"],
            "/api/generate",
            {
                "model": selected["name"],
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0},
            },
        )
        raw_model_output = response.get("response")
        if type(raw_model_output) is not str or len(raw_model_output.encode("utf-8")) > MAX_HTTP_BYTES:
            raise Stage3Error("ollama_supervision_invalid")
        response_hash = hashlib.sha256(raw_model_output.encode("utf-8")).hexdigest()
        try:
            result = json.loads(raw_model_output)
        except json.JSONDecodeError as exc:
            raise Stage3Error("ollama_supervision_invalid") from exc
        return (
            _validate_supervision(result, capability_kind),
            response_hash,
            selected,
        )

    @staticmethod
    def _request(
        base_url: str, path: str, payload: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any], bytes]:
        data = None if payload is None else _json(payload).encode("utf-8")
        request = Request(
            f"{base_url}{path}",
            data=data,
            method="GET" if data is None else "POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        opener = build_opener(ProxyHandler({}), _NoRedirect())
        try:
            with opener.open(request, timeout=10) as response:
                raw = response.read(MAX_HTTP_BYTES + 1)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise Stage3Error("ollama_unavailable") from exc
        if len(raw) > MAX_HTTP_BYTES:
            raise Stage3Error("ollama_response_too_large")
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise Stage3Error("ollama_response_invalid") from exc
        if type(value) is not dict:
            raise Stage3Error("ollama_response_invalid")
        return value, raw


def _validate_supervision(value: Any, capability_kind: str) -> dict[str, Any]:
    required = {
        "schema_version",
        "verdict",
        "capability_kind",
        "semantic_summary",
        "keep_reason_codes",
        "remove_reason_codes",
        "brand_signals",
        "sensitive_data_status",
        "hidden_dependency_codes",
        "duplicate_suggestions",
        "review_required",
    }
    if type(value) is not dict or set(value) != required:
        raise Stage3Error("ollama_supervision_invalid")
    if (
        value["schema_version"] != "capsule_supervision.v1"
        or value["verdict"] not in {"approve", "review", "reject"}
        or value["capability_kind"] != capability_kind
        or type(value["semantic_summary"]) is not str
        or not 1 <= len(value["semantic_summary"]) <= 500
        or type(value["review_required"]) is not bool
        or value["sensitive_data_status"] not in {"clear", "redacted"}
    ):
        raise Stage3Error("ollama_supervision_invalid")
    for key in (
        "keep_reason_codes",
        "remove_reason_codes",
        "brand_signals",
        "hidden_dependency_codes",
    ):
        if type(value[key]) is not list or len(value[key]) > 100 or any(
            type(item) is not str
            or not item
            or len(item) > 100
            or not _MODEL_CODE.fullmatch(item)
            for item in value[key]
        ):
            raise Stage3Error("ollama_supervision_invalid")
    suggestions = value["duplicate_suggestions"]
    if type(suggestions) is not list or len(suggestions) > 20 or any(
        type(item) is not str
        or not item
        or len(item) > 200
        or not _MODEL_CODE.fullmatch(item)
        for item in suggestions
    ):
        raise Stage3Error("ollama_supervision_invalid")
    # Round-trip through strict JSON to reject floats, NaN, and non-JSON values.
    try:
        normalized = json.loads(_json(value))
    except (TypeError, ValueError) as exc:
        raise Stage3Error("ollama_supervision_invalid") from exc
    if _sensitive_values(_json(normalized)):
        raise Stage3Error("ollama_supervision_sensitive_output")
    return normalized


def _node_binary() -> str:
    node = os.environ.get("REWEAVE_NODE") or shutil.which("node")
    if not node:
        raise Stage3Error("node_unavailable")
    return node


def _desktop_python() -> str:
    configured = os.environ.get("REWEAVE_DESKTOP_PYTHON")
    root = Path(__file__).resolve().parents[1]
    candidates = (
        [Path(configured).expanduser()]
        if configured
        else [
            root / ".venv-reweave" / "bin" / "python",
            root / ".venv-reweave" / "Scripts" / "python.exe",
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    try:
        import PySide6  # noqa: F401
    except ImportError as exc:
        raise Stage3Error("pyside6_unavailable") from exc
    return sys.executable


def _run_json_command(
    command: list[str],
    request: dict[str, Any],
    *,
    cwd: Path,
    timeout: int,
    error_code: str,
    fail_on_stderr: bool = True,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd,
        env=env,
        start_new_session=os.name == "posix",
    )
    try:
        stdout, stderr = process.communicate(_json(request), timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.communicate()
        raise Stage3Error(f"{error_code}_timeout") from exc
    if (
        process.returncode
        or fail_on_stderr and stderr
        or len(stdout.encode("utf-8")) > MAX_HTTP_BYTES
    ):
        raise Stage3Error(error_code)
    try:
        result = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise Stage3Error(error_code) from exc
    if type(result) is not dict:
        raise Stage3Error(error_code)
    return result


def _analyze_javascript(candidate: dict[str, Any], redact_strings: list[str]) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    result = _run_json_command(
        [_node_binary(), str(root / "scripts" / "analyze_reweave_security.mjs")],
        {
            "mode": "candidate",
            "capability_kind": candidate["capability_kind"],
            "activation": candidate["activation"],
            "dom_scope": candidate["dom_scope"],
            "output_contract": candidate["output_contract"],
            "javascript_modules": candidate["javascript_modules"],
            "redact_strings": redact_strings,
        },
        cwd=root,
        timeout=15,
        error_code="javascript_security_analyzer_failed",
    )
    if result.get("status") != "passed":
        raise Stage3Error(str(result.get("error_code") or "javascript_security_rejected"))
    return result


def _bundle_javascript(
    modules: list[dict[str, str]], activation: dict[str, Any], directory: Path
) -> str:
    root = Path(__file__).resolve().parents[1]
    sources = directory / "modules"
    entry = str(activation.get("entry_module") or "")
    for module in modules:
        logical = str(module.get("path") or "")
        pure = PurePosixPath(logical)
        if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
            raise Stage3Error("javascript_module_path_invalid")
        target = sources.joinpath(*pure.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(module.get("source") or ""), encoding="utf-8", newline="\n")
    entry_path = sources.joinpath(*PurePosixPath(entry).parts)
    if not entry_path.is_file():
        raise Stage3Error("javascript_entry_module_missing")
    if not (root / "node_modules" / "esbuild" / "package.json").is_file():
        raise Stage3Error("esbuild_unavailable")
    bundle_path = directory / "bundle.js"
    build_script = (
        "import {build} from 'esbuild';"
        "const [entry,out]=process.argv.slice(1);"
        "await build({entryPoints:[entry],bundle:true,format:'iife',platform:'browser',"
        "globalName:'ReweaveCandidate',logLevel:'error',sourcemap:false,outfile:out});"
    )
    completed = subprocess.run(
        [
            _node_binary(),
            "--input-type=module",
            "--eval",
            build_script,
            str(entry_path),
            str(bundle_path),
        ],
        capture_output=True,
        text=True,
        cwd=root,
        timeout=15,
        check=False,
        env=restricted_subprocess_environment(),
    )
    if completed.returncode or completed.stderr or not bundle_path.is_file():
        raise Stage3Error("esbuild_bundle_failed")
    bundle = bundle_path.read_text(encoding="utf-8")
    checked = subprocess.run(
        [_node_binary(), "--check", str(bundle_path)],
        capture_output=True,
        text=True,
        cwd=directory,
        timeout=10,
        check=False,
        env=restricted_subprocess_environment(),
    )
    if checked.returncode or checked.stderr:
        raise Stage3Error("bundle_syntax_invalid")
    result = _run_json_command(
        [_node_binary(), str(root / "scripts" / "analyze_reweave_security.mjs")],
        {"mode": "bundle", "source": bundle},
        cwd=root,
        timeout=15,
        error_code="bundle_security_analyzer_failed",
    )
    if result.get("status") != "passed":
        raise Stage3Error(str(result.get("error_code") or "bundle_security_rejected"))
    return bundle


def _pyside_environment(temp_root: Path) -> dict[str, str]:
    env = restricted_subprocess_environment({
        "HOME": str(temp_root),
        "TMPDIR": str(temp_root),
        "TMP": str(temp_root),
        "TEMP": str(temp_root),
        "XDG_CACHE_HOME": str(temp_root / "cache"),
        "XDG_CONFIG_HOME": str(temp_root / "config"),
        "XDG_DATA_HOME": str(temp_root / "data"),
        "APPDATA": str(temp_root / "appdata"),
        "LOCALAPPDATA": str(temp_root / "localappdata"),
        "QT_QPA_PLATFORM": os.environ.get("QT_QPA_PLATFORM", "offscreen"),
        "QTWEBENGINE_CHROMIUM_FLAGS": "--disable-gpu",
        "QT_LOGGING_RULES": "*.debug=false;qt.webenginecontext.info=false",
    })
    for key in ("LANG", "LC_ALL"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    return env


def _clean_assets(
    source_bytes: dict[str, bytes],
) -> tuple[CleanAsset, ...]:
    worker = Path(__file__).with_name("reweave_capsule_worker.py")
    cleaned: list[CleanAsset] = []
    total = 0
    raw_total = 0
    expected_media_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }
    for index, logical in enumerate(sorted(source_bytes)):
        pure = PurePosixPath(logical)
        if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
            raise Stage3Error("asset_path_invalid")
        expected_media_type = expected_media_types.get(pure.suffix.lower())
        if expected_media_type is None:
            raise Stage3Error("image_format_forbidden")
        raw = source_bytes[logical]
        if len(raw) > MAX_ASSET_BYTES:
            raise Stage3Error("asset_size_forbidden")
        raw_total += len(raw)
        if raw_total > MAX_ASSET_TOTAL_BYTES:
            raise Stage3Error("capsule_asset_total_forbidden")
        with tempfile.TemporaryDirectory(prefix="reweave-image-") as temporary:
            directory = Path(temporary)
            input_name = f"input-{index}{pure.suffix.lower()}"
            output_name = f"cleaned-{index}{pure.suffix.lower()}"
            (directory / input_name).write_bytes(raw)
            result = _run_json_command(
                [_desktop_python(), str(worker)],
                {"mode": "image", "input": input_name, "output": output_name},
                cwd=directory,
                timeout=10,
                error_code="image_worker_failed",
                fail_on_stderr=False,
                env=_pyside_environment(directory),
            )
            if result.get("status") != "passed":
                raise Stage3Error(str(result.get("error_code") or "image_cleaning_failed"))
            if result.get("media_type") != expected_media_type:
                raise Stage3Error("image_format_mismatch")
            output = directory / output_name
            if not output.is_file():
                raise Stage3Error("image_worker_output_missing")
            content = output.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if digest != result.get("sha256") or len(content) != result.get("size_bytes"):
            raise Stage3Error("image_worker_output_mismatch")
        total += len(content)
        if total > MAX_ASSET_TOTAL_BYTES:
            raise Stage3Error("capsule_asset_total_forbidden")
        cleaned.append(
            CleanAsset(
                logical_path=logical,
                media_type=str(result["media_type"]),
                sha256=digest,
                size_bytes=len(content),
                width=int(result["width"]),
                height=int(result["height"]),
                content=content,
            )
        )
    return tuple(cleaned)


def _compute_result_valid(
    value: Any, output_contract: dict[str, Any], error_contract: dict[str, Any]
) -> bool:
    if type(value) is not dict or type(value.get("ok")) is not bool:
        return False
    if value["ok"] is True:
        return set(value) == {"ok", "value"} and data_contract_accepts(
            output_contract, value["value"]
        )
    if set(value) != {"ok", "error"} or type(value["error"]) is not dict:
        return False
    error = value["error"]
    if not {"code"} <= set(error) <= {"code", "field", "details"}:
        return False
    contract = error_contract.get("errors", {}).get(error.get("code"))
    if contract is None or error.get("field") != contract.get("field"):
        return False
    details = error.get("details", {})
    return data_contract_accepts(contract["details"], details)


def _validate_computation(
    payload: dict[str, Any], fixtures: dict[str, Any]
) -> dict[str, Any]:
    normal = list(fixtures["normal"])
    boundary = list(fixtures["boundary"])
    invalid = [item["value"] for item in fixtures["invalid"]]
    values = normal + boundary + invalid
    if not values:
        raise Stage3Error("compute_fixture_missing")
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="reweave-compute-") as temporary:
        directory = Path(temporary)
        _bundle_javascript(
            payload["javascript_modules"], payload["activation"], directory
        )
        result = _run_json_command(
            [
                _node_binary(),
                "--max-old-space-size=64",
                str(root / "scripts" / "validate_reweave_compute.mjs"),
            ],
            {
                "entrypoint": payload["activation"]["entrypoint"],
                "fixtures": values,
            },
            cwd=directory,
            timeout=10,
            error_code="compute_worker_failed",
            env=restricted_subprocess_environment(),
        )
    if result.get("status") != "passed" or type(result.get("cases")) is not list:
        raise Stage3Error(str(result.get("error_code") or "compute_validation_failed"))
    cases = result["cases"]
    if len(cases) != len(values):
        raise Stage3Error("compute_validation_case_mismatch")
    valid_count = len(normal) + len(boundary)
    if any(
        not _compute_result_valid(item, payload["output_contract"], payload["error_contract"])
        for item in cases
    ):
        raise Stage3Error("compute_output_contract_failed")
    if any(item.get("ok") is not True for item in cases[:valid_count]):
        raise Stage3Error("compute_valid_fixture_failed")
    if any(item.get("ok") is not False for item in cases[valid_count:]):
        raise Stage3Error("compute_invalid_fixture_failed")
    return {
        "schema_version": "runtime_validation.v1",
        "status": "passed",
        "acceptance_scope": "isolated_node_vm_computation",
        "normal_cases": len(normal),
        "boundary_cases": len(boundary),
        "invalid_cases": len(invalid),
        "repeatability_checked": True,
        "input_freeze_checked": True,
    }


def _qweb_harness(
    kind: str,
    entrypoint: str,
    fixtures: list[dict[str, Any]],
    normal_cases: int,
    boundary_cases: int,
    listener_bindings: list[dict[str, str]],
) -> str:
    request = _json(
        {
            "kind": kind,
            "entrypoint": entrypoint,
            "fixtures": fixtures,
            "normal_cases": normal_cases,
            "boundary_cases": boundary_cases,
            "listeners": listener_bindings,
        }
    )
    return f"""
(() => {{
  const request = {request};
  const strictClone = (value, maxBytes, code) => {{
    const seen = new Set();
    const visit = (item) => {{
      if (item === null || typeof item === "string" || typeof item === "boolean") return;
      if (typeof item === "number") {{
        if (!Number.isFinite(item)) throw new Error(code);
        return;
      }}
      if (typeof item !== "object" || item instanceof Node) throw new Error(code);
      if (seen.has(item)) throw new Error(code);
      seen.add(item);
      if (Array.isArray(item)) {{
        for (const child of item) visit(child);
      }} else {{
        const prototype = Object.getPrototypeOf(item);
        if (prototype !== Object.prototype && prototype !== null) throw new Error(code);
        for (const key of Object.keys(item)) visit(item[key]);
      }}
      seen.delete(item);
    }};
    visit(value);
    const encoded = JSON.stringify(value);
    if (encoded === undefined || new TextEncoder().encode(encoded).length > maxBytes) {{
      throw new Error(code);
    }}
    return JSON.parse(encoded);
  }};
  const freeze = (value) => {{
    if (value && typeof value === "object" && !Object.isFrozen(value)) {{
      Object.values(value).forEach(freeze);
      Object.freeze(value);
    }}
    return value;
  }};
  const fail = (code) => ({{schema_version: "qweb_validation.v1", status: "failed", error_code: code}});
  const observableState = (root) => JSON.stringify([...root.querySelectorAll("*")].map((node) => ({{
    tag: node.tagName,
    text: node.textContent,
    value: "value" in node ? node.value : null,
    checked: "checked" in node ? node.checked : null,
    selectedIndex: "selectedIndex" in node ? node.selectedIndex : null,
    disabled: "disabled" in node ? node.disabled : null,
    hidden: node.hidden,
    className: node.className,
    scopedAttributes: [...node.attributes]
      .filter((item) => item.name.startsWith("data-") || item.name.startsWith("aria-"))
      .map((item) => [item.name, item.value])
      .sort((left, right) => left[0].localeCompare(right[0])),
  }})));
  const seedControls = (root) => {{
    for (const control of root.querySelectorAll("input,textarea")) {{
      if (control instanceof HTMLInputElement && control.type === "number") {{
        control.value = control.min || "0";
      }} else if (control instanceof HTMLInputElement && ["checkbox", "radio"].includes(control.type)) {{
        control.checked = false;
      }} else {{
        const minimum = Number(control.getAttribute("minlength") || 0);
        const maximum = Number(control.getAttribute("maxlength") || Math.max(minimum, 9));
        control.value = "x".repeat(Math.min(maximum, Math.max(minimum, 1)));
      }}
    }}
  }};
  try {{
    const root = document.getElementById("capsule-root");
    const outside = document.getElementById("outside-sentinel");
    const beforeOutside = outside.textContent;
    const pendingMutations = [];
    const observer = new MutationObserver((records) => pendingMutations.push(...records));
    observer.observe(document.documentElement, {{
      subtree: true,
      attributes: true,
      childList: true,
      characterData: true,
    }});
    const assertScopedMutations = () => {{
      pendingMutations.push(...observer.takeRecords());
      const escaped = pendingMutations.some(
        (record) => record.target !== root && !root.contains(record.target),
      );
      pendingMutations.length = 0;
      if (escaped) throw new Error("qweb_root_escape_detected");
    }};
    const candidate = ReweaveCandidate[request.entrypoint];
    if (typeof candidate !== "function") throw new Error("qweb_entrypoint_missing");
    const initialRoot = root.innerHTML;
    const cases = [];
    for (let index = 0; index < request.fixtures.length; index += 1) {{
      root.innerHTML = initialRoot;
      seedControls(root);
      observer.takeRecords();
      pendingMutations.length = 0;
      const fixture = freeze(strictClone(request.fixtures[index], 524288, "qweb_input_non_json"));
      if (request.kind === "presentation") {{
        const first = candidate(root, fixture);
        if (first !== undefined) throw new Error("presentation_return_forbidden");
        const firstState = observableState(root);
        const second = candidate(root, fixture);
        if (second !== undefined || observableState(root) !== firstState) {{
          throw new Error("presentation_repeat_render_failed");
        }}
        cases.push({{fixture_index: index, emissions: []}});
      }} else {{
        const emissions = [];
        let outputError = null;
        const dispose = candidate(root, {{
          input: fixture,
          emit(name, value) {{
            try {{
              emissions.push({{
                name,
                value: strictClone(value, 65536, "qweb_output_non_json"),
              }});
            }} catch (error) {{
              outputError = String(error && error.message || "qweb_output_non_json");
            }}
          }},
        }});
        if (typeof dispose !== "function") throw new Error("interaction_dispose_missing");
        for (const listener of request.listeners) {{
          const target = root.querySelector(listener.selector);
          if (!target) throw new Error("interaction_target_missing");
          const event = new Event(listener.event, {{cancelable: true, bubbles: false}});
          target.dispatchEvent(event);
          if (listener.event === "submit" && !event.defaultPrevented) {{
            throw new Error("submit_prevent_default_required");
          }}
        }}
        if (outputError !== null) throw new Error(outputError);
        const emittedBeforeDispose = emissions.length;
        dispose();
        const stateAfterFirstDispose = observableState(root);
        dispose();
        if (observableState(root) !== stateAfterFirstDispose) {{
          throw new Error("interaction_dispose_not_idempotent");
        }}
        for (const listener of request.listeners) {{
          root.querySelector(listener.selector).dispatchEvent(
            new Event(listener.event, {{cancelable: true, bubbles: false}})
          );
        }}
        if (emissions.length !== emittedBeforeDispose) throw new Error("interaction_emit_after_dispose");
        if (observableState(root) !== stateAfterFirstDispose) {{
          throw new Error("interaction_response_after_dispose");
        }}
        cases.push({{fixture_index: index, emissions}});
      }}
      assertScopedMutations();
      if (outside.textContent !== beforeOutside) throw new Error("qweb_root_escape_detected");
    }}
    observer.disconnect();
    globalThis.__reweave_result = {{
      schema_version: "qweb_validation.v1",
      status: "passed",
      normal_cases: request.normal_cases,
      boundary_cases: request.boundary_cases,
      cases,
      repeated_render: request.kind === "presentation",
      dispose_idempotent: request.kind === "interaction",
      remount_checked: request.kind === "interaction" && request.fixtures.length > 1,
    }};
  }} catch (error) {{
    globalThis.__reweave_result = fail(String(error && error.message || "qweb_harness_failed"));
  }}
}})();
"""


def _validate_qweb(
    payload: dict[str, Any],
    fixtures: dict[str, Any],
    assets: tuple[CleanAsset, ...],
    listener_bindings: list[dict[str, str]],
) -> dict[str, Any]:
    normal = list(fixtures.get("normal", []))
    boundary = list(fixtures.get("boundary", []))
    invalid = list(fixtures.get("invalid", []))
    values = normal + boundary
    if not normal:
        raise Stage3Error("qweb_fixture_missing")
    if any(not data_contract_accepts(payload["input_contract"], value) for value in values):
        raise Stage3Error("qweb_valid_fixture_contract_mismatch")
    if any(
        type(item) is not dict
        or "value" not in item
        or data_contract_accepts(payload["input_contract"], item["value"])
        for item in invalid
    ):
        raise Stage3Error("qweb_invalid_fixture_contract_mismatch")
    worker = Path(__file__).with_name("reweave_capsule_worker.py")
    with tempfile.TemporaryDirectory(prefix="reweave-qweb-") as temporary:
        directory = Path(temporary)
        bundle = _bundle_javascript(
            payload["javascript_modules"], payload["activation"], directory
        )
        (directory / "styles.css").write_text(
            payload["css"].replace("__CAPSULE_ROOT__", "#capsule-root"),
            encoding="utf-8",
            newline="\n",
        )
        app = bundle + _qweb_harness(
            payload["capability_kind"],
            payload["activation"]["entrypoint"],
            values,
            len(normal),
            len(boundary),
            listener_bindings,
        )
        (directory / "app.js").write_text(app, encoding="utf-8", newline="\n")
        for asset in assets:
            target = directory.joinpath(*PurePosixPath(asset.logical_path).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(asset.content)
        csp = (
            "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
            "font-src 'none'; connect-src 'none'; object-src 'none'; frame-src 'none'; "
            "worker-src 'none'; base-uri 'none'; form-action 'none'"
        )
        index = (
            "<!doctype html><html><head><meta charset=\"utf-8\">"
            f"<meta http-equiv=\"Content-Security-Policy\" content=\"{html.escape(csp, quote=True)}\">"
            "<link rel=\"stylesheet\" href=\"styles.css\"></head><body>"
            "<div id=\"outside-sentinel\">outside</div><div id=\"capsule-root\">"
            f"{payload['html']}</div><script src=\"app.js\"></script></body></html>"
        )
        (directory / "index.html").write_text(index, encoding="utf-8", newline="\n")
        allowed = ["index.html", "styles.css", "app.js"] + [
            asset.logical_path for asset in assets
        ]
        result = _run_json_command(
            [_desktop_python(), str(worker)],
            {"mode": "qweb", "entry": "index.html", "allow_files": allowed},
            cwd=directory,
            timeout=12,
            error_code="qweb_worker_failed",
            fail_on_stderr=False,
            env=_pyside_environment(directory),
        )
    if result.get("status") != "passed":
        code = str(result.get("error_code") or "qweb_validation_failed")
        details = _qweb_failure_details(result) if code == "qweb_request_blocked" else None
        raise Stage3Error(code, details)
    if result.get("acceptance_scope") != "real_qwebengine_runtime":
        raise Stage3Error("qweb_acceptance_scope_invalid")
    cases = result.get("cases")
    if (
        type(cases) is not list
        or len(cases) != len(values)
        or result.get("normal_cases") != len(normal)
        or result.get("boundary_cases") != len(boundary)
    ):
        raise Stage3Error("qweb_validation_case_mismatch")
    if payload["capability_kind"] == "interaction":
        emissions: list[Any] = []
        for index, case in enumerate(cases):
            if (
                type(case) is not dict
                or case.get("fixture_index") != index
                or type(case.get("emissions")) is not list
            ):
                raise Stage3Error("qweb_emissions_invalid")
            emissions.extend(case["emissions"])
        contracts = payload["output_contract"]["events"]
        for item in emissions:
            if (
                type(item) is not dict
                or set(item) != {"name", "value"}
                or item["name"] not in contracts
                or not data_contract_accepts(contracts[item["name"]], item["value"])
            ):
                raise Stage3Error("qweb_emission_contract_failed")
        emitted_names = sorted({str(item["name"]) for item in emissions})
        if emitted_names != sorted(contracts):
            raise Stage3Error("qweb_declared_emission_missing")
        result["emission_count"] = len(emissions)
        result["emission_names"] = emitted_names
        result["acceptance_scope"] = "real_qwebengine_interaction"
    else:
        if any(
            type(case) is not dict
            or case.get("fixture_index") != index
            or case.get("emissions") != []
            for index, case in enumerate(cases)
        ):
            raise Stage3Error("qweb_render_case_invalid")
        result["acceptance_scope"] = "real_qwebengine_render"
    result["invalid_cases"] = len(invalid)
    result.pop("cases", None)
    result.pop("blocked_requests", None)
    result.pop("console_messages", None)
    return result


def _qweb_failure_details(result: dict[str, Any]) -> dict[str, Any]:
    raw = result.get("blocked_requests")
    if type(raw) is not list or not raw or len(raw) > 100:
        raise Stage3Error("qweb_blocked_request_evidence_invalid")
    blocked: list[dict[str, str]] = []
    for item in raw:
        if type(item) is not dict or set(item) != {"scheme", "logical_path"}:
            raise Stage3Error("qweb_blocked_request_evidence_invalid")
        scheme = item.get("scheme")
        logical_path = item.get("logical_path")
        if (
            type(scheme) is not str
            or not re.fullmatch(r"[a-z][a-z0-9+.-]{0,31}|unknown", scheme)
            or type(logical_path) is not str
            or not logical_path
            or len(logical_path) > 256
            or any(ord(character) < 0x20 or ord(character) == 0x7F for character in logical_path)
        ):
            raise Stage3Error("qweb_blocked_request_evidence_invalid")
        blocked.append({"scheme": scheme, "logical_path": logical_path})
    return {"blocked_requests": blocked}


@dataclass(frozen=True)
class _PreparedReview:
    review: dict[str, Any]
    artifact: Stage3Artifact
    fixtures: dict[str, Any]
    snapshot_digest: str
    listener_bindings: list[dict[str, str]]


class ReweaveCapsuleStage3:
    """Explicit non-active Stage 3 service; callers still choose when to invoke it."""

    def __init__(
        self,
        store: CapsuleWarehouseStore,
        *,
        intake: ReweaveCapsuleIntake | None = None,
        supervisor: OllamaSupervisor | None = None,
    ) -> None:
        self.store = store
        self.intake = intake or ReweaveCapsuleIntake(store)
        self.supervisor = supervisor or OllamaSupervisor(store)

    def process_review(self, review_id: str) -> dict[str, Any]:
        review = self._review(review_id)
        if review["candidate_status"] != "extracted":
            raise Stage3Error("review_item_not_extracted")
        try:
            prepared = self._prepare(review)
        except Stage3Error as exc:
            if exc.code.startswith("source_changed"):
                raise
            return self._record_gate_failure(review, exc.code, details=exc.details)

        representative = self._same_run_representative(prepared)
        if representative is not None:
            return self._copy_representative(prepared.review, representative)

        matches = self._hash_matches(prepared.artifact.canonical_hash)
        eligible = [row for row in matches if self._eligible_exact(row)]
        identities = {str(row["capsule_id"]) for row in eligible}
        if len(identities) == 1:
            return self._attach_exact_duplicate(prepared, eligible[0])

        try:
            summary = self._supervision_summary(prepared)
            supervision, response_hash, model = self.supervisor.supervise(
                summary, prepared.artifact.canonical_payload["capability_kind"]
            )
            if supervision["verdict"] == "reject":
                return self._record_gate_failure(
                    prepared.review,
                    "supervision_rejected",
                    canonical_hash=prepared.artifact.canonical_hash,
                    supervision=supervision,
                    response_hash=response_hash,
                    model=model,
                )
            validation = self._runtime_validation(prepared)
        except Stage3Error as exc:
            return self._record_gate_failure(
                prepared.review,
                exc.code,
                canonical_hash=prepared.artifact.canonical_hash,
                details=exc.details,
            )

        artifact = Stage3Artifact(
            canonical_payload=prepared.artifact.canonical_payload,
            canonical_hash=prepared.artifact.canonical_hash,
            assets=prepared.artifact.assets,
            cleaning_summary=prepared.artifact.cleaning_summary,
            security_result=prepared.artifact.security_result,
            supervision=supervision,
            supervision_response_hash=response_hash,
            model_name=model["name"],
            model_digest=model["digest"],
            supervised_at=_now(),
            validation=validation,
        )
        prepared = _PreparedReview(
            review=prepared.review,
            artifact=artifact,
            fixtures=prepared.fixtures,
            snapshot_digest=prepared.snapshot_digest,
            listener_bindings=prepared.listener_bindings,
        )
        stale_current = {
            str(row["capsule_id"]): row
            for row in matches
            if row["version_id"] == row["current_version_id"]
            and row["status"] in {"active", "pending_revalidation"}
        }
        model_requires_review = bool(
            supervision["verdict"] == "review"
            or supervision["review_required"]
            or supervision["remove_reason_codes"]
            or supervision["brand_signals"]
            or supervision["hidden_dependency_codes"]
        )
        if len(stale_current) == 1 and len(identities) <= 1 and not model_requires_review:
            return self._publish_version(
                prepared,
                existing_capsule=next(iter(stale_current.values())),
                reason_code="rules_revalidated",
            )

        comparison = self._equivalence_comparison(prepared, matches)
        reasons = ["identity_assignment_required"]
        if len(identities) > 1:
            reasons.append("duplicate_identity_conflict")
        if model_requires_review:
            reasons.append("model_review_suggested")
        if comparison["candidates"]:
            reasons.append("manual_equivalence_review_required")
        comparison["reason_codes"] = sorted(set(reasons))
        return self._record_evidence(prepared, comparison, "review_required")

    def publish_review(
        self,
        review_id: str,
        *,
        decision: str,
        capability_key: str | None = None,
        role_key: str | None = None,
        variant_key: str = "default",
        display_name: str | None = None,
        target_capsule_id: str | None = None,
        retained_version_id: str | None = None,
    ) -> dict[str, Any]:
        review = self._review(review_id)
        if review["project_id"] is not None:
            try:
                context = self.intake._project_context(str(review["project_id"]))
                self.intake._effective_brand_profile(
                    context.project, context.source_root
                )
            except IntakeError as exc:
                raise Stage3Error(exc.code) from exc
        if self._representative_review_id(review) is not None:
            raise Stage3Error("same_run_duplicate_member_not_decidable")
        if (
            decision == "semantic_split"
            and review["candidate_status"] == "duplicate"
            and review["decision"] is None
        ):
            if not all(
                type(item) is str and _SNAKE.fullmatch(item)
                for item in (capability_key, role_key, variant_key)
            ) or not display_name or len(display_name) > 200:
                raise Stage3Error("capsule_key_invalid")
            return self._semantic_split_duplicate(
                review,
                capability_key=str(capability_key),
                role_key=str(role_key),
                variant_key=variant_key,
                display_name=display_name,
            )
        if review["candidate_status"] != "review_required" or review["decision"] is not None:
            raise Stage3Error("review_item_not_publishable")
        if decision == "merge_existing":
            if not retained_version_id:
                raise Stage3Error("retained_version_required")
            return self._merge_existing(review, retained_version_id)
        if decision not in {
            "publish_general",
            "publish_brand_limited",
            "replace_current",
            "create_variant",
            "semantic_split",
        }:
            raise Stage3Error("publication_decision_invalid")
        prepared = self._prepare(review)
        if prepared.artifact.canonical_hash != review["candidate_canonical_hash"]:
            raise Stage3Error("candidate_changed_since_validation")
        evidence = self._evidence(review)
        capability_kind = prepared.artifact.canonical_payload["capability_kind"]
        if not self._evidence_current(evidence, capability_kind):
            raise Stage3Error("stage3_evidence_expired")
        supervision = json.loads(review["supervision_result_json"] or "null")
        if type(supervision) is not dict:
            raise Stage3Error("stage3_evidence_missing")
        try:
            supervision = _validate_supervision(supervision, capability_kind)
        except Stage3Error as exc:
            raise Stage3Error("stage3_evidence_invalid") from exc
        response_hash = review["supervision_response_hash"]
        if type(response_hash) is not str or not re.fullmatch(r"[0-9a-f]{64}", response_hash):
            raise Stage3Error("stage3_evidence_invalid")
        prepared = _PreparedReview(
            review=review,
            artifact=Stage3Artifact(
                canonical_payload=prepared.artifact.canonical_payload,
                canonical_hash=prepared.artifact.canonical_hash,
                assets=prepared.artifact.assets,
                cleaning_summary=prepared.artifact.cleaning_summary,
                security_result=prepared.artifact.security_result,
                supervision=supervision,
                supervision_response_hash=response_hash,
                model_name=str(evidence["model_name"]),
                model_digest=str(evidence["model_digest"]),
                supervised_at=str(evidence["supervised_at"]),
                validation=evidence["validation"],
            ),
            fixtures=prepared.fixtures,
            snapshot_digest=prepared.snapshot_digest,
            listener_bindings=prepared.listener_bindings,
        )
        usage_kind = prepared.artifact.canonical_payload["usage_scope"].get("kind")
        if decision == "publish_general" and usage_kind != "general":
            raise Stage3Error("publication_usage_scope_mismatch")
        if decision == "publish_brand_limited" and usage_kind != "brand_limited":
            raise Stage3Error("publication_usage_scope_mismatch")
        existing = None
        semantic_split_from = None
        if decision == "replace_current":
            if not target_capsule_id:
                raise Stage3Error("target_capsule_required")
            target_evidence = self._comparison_candidate(
                review, capsule_id=target_capsule_id
            )
            if target_evidence is None or not (
                target_evidence.get("contract_match") is True
                or target_evidence.get("scope_revalidation_match") is True
            ):
                raise Stage3Error("target_not_in_comparison_evidence")
            existing = self._capsule(target_capsule_id)
            if existing["current_version_id"] != target_evidence.get("version_id"):
                raise Stage3Error("target_comparison_evidence_expired")
            with self.store.read_connection() as connection:
                target_ok = self._replace_target_eligible(
                    connection,
                    review,
                    target_capsule_id,
                    prepared.artifact.canonical_payload,
                )
            if not target_ok:
                raise Stage3Error("replace_current_requires_same_role_contract")
        else:
            if decision == "semantic_split":
                if not target_capsule_id:
                    raise Stage3Error("semantic_split_target_required")
                target_evidence = self._comparison_candidate(
                    review, capsule_id=target_capsule_id
                )
                if target_evidence is None:
                    raise Stage3Error("target_not_in_comparison_evidence")
                semantic_split_from = self._capsule(target_capsule_id)
                if semantic_split_from["current_version_id"] != target_evidence.get(
                    "version_id"
                ):
                    raise Stage3Error("target_comparison_evidence_expired")
            if not all(
                type(item) is str and _SNAKE.fullmatch(item)
                for item in (capability_key, role_key, variant_key)
            ):
                raise Stage3Error("capsule_key_invalid")
            if not display_name or len(display_name) > 200:
                raise Stage3Error("capability_display_name_invalid")
        return self._publish_version(
            prepared,
            existing_capsule=existing,
            capability_key=capability_key,
            role_key=role_key,
            variant_key=variant_key,
            display_name=display_name,
            decision=decision,
            reason_code="user_approved_publication",
            disable_capsule_id=(
                str(semantic_split_from["capsule_id"])
                if semantic_split_from is not None
                else None
            ),
            disable_version_id=(
                str(semantic_split_from["current_version_id"])
                if semantic_split_from is not None
                else None
            ),
        )

    def _semantic_split_duplicate(
        self,
        review: dict[str, Any],
        *,
        capability_key: str,
        role_key: str,
        variant_key: str,
        display_name: str,
    ) -> dict[str, Any]:
        retained_version_id = review.get("retained_version_id")
        with self.store.read_connection() as connection:
            retained = connection.execute(
                "SELECT cv.*, c.status, c.current_version_id, c.capability_kind "
                "FROM capsule_versions cv JOIN capsules c ON c.capsule_id = cv.capsule_id "
                "WHERE cv.version_id = ?",
                (retained_version_id,),
            ).fetchone()
        if retained is None or not self._eligible_exact(dict(retained)):
            raise Stage3Error("semantic_split_evidence_expired")
        prepared = self._prepare(review)
        if prepared.artifact.canonical_hash != retained["canonical_hash"]:
            raise Stage3Error("candidate_changed_since_validation")
        prepared = _PreparedReview(
            review=review,
            artifact=Stage3Artifact(
                canonical_payload=prepared.artifact.canonical_payload,
                canonical_hash=prepared.artifact.canonical_hash,
                assets=prepared.artifact.assets,
                cleaning_summary=prepared.artifact.cleaning_summary,
                security_result=prepared.artifact.security_result,
                supervision=json.loads(retained["supervision_result_json"]),
                supervision_response_hash=retained["supervision_response_hash"],
                model_name=retained["supervision_model_name"],
                model_digest=retained["supervision_model_digest"],
                supervised_at=retained["supervised_at"],
                validation=json.loads(retained["validation_result_json"]),
            ),
            fixtures=prepared.fixtures,
            snapshot_digest=prepared.snapshot_digest,
            listener_bindings=prepared.listener_bindings,
        )
        return self._publish_version(
            prepared,
            capability_key=capability_key,
            role_key=role_key,
            variant_key=variant_key,
            display_name=display_name,
            decision="semantic_split",
            reason_code="user_approved_semantic_split",
            disable_capsule_id=str(retained["capsule_id"]),
            disable_version_id=str(retained["version_id"]),
        )

    def reject_review(self, review_id: str, *, reason_code: str = "user_rejected") -> dict[str, Any]:
        review = self._review(review_id)
        if self._representative_review_id(review) is not None:
            raise Stage3Error("same_run_duplicate_member_not_decidable")
        if review["candidate_status"] in {"published", "duplicate", "merged", "rejected"}:
            raise Stage3Error("review_item_already_terminal")
        if review["decision"] is not None or not _SNAKE.fullmatch(reason_code):
            raise Stage3Error("review_rejection_invalid")
        now = _now()
        comparison = json.loads(review["equivalence_comparison_json"] or "{}")
        comparison["user_rejection_reason"] = reason_code
        with self.store.transaction() as connection:
            followers = self._same_run_followers(connection, review)
            updated = connection.execute(
                "UPDATE review_items SET candidate_status = 'rejected', decision = 'reject', "
                "decided_at = ?, equivalence_comparison_json = ?, updated_at = ? "
                "WHERE review_id = ? AND candidate_status = ? AND decision IS NULL",
                (now, _json(comparison), now, review_id, review["candidate_status"]),
            )
            if updated.rowcount != 1:
                raise Stage3Error("review_decision_conflict")
            for follower in followers:
                connection.execute(
                    "UPDATE review_items SET candidate_status = 'rejected', updated_at = ? "
                    "WHERE review_id = ?",
                    (now, follower["review_id"]),
                )
            self._sync_run_evidence(connection, str(review["run_id"]))
            self.store.bump_revision(connection)
        return {"review_id": review_id, "status": "rejected", "reason_code": reason_code}

    def _prepare(self, review: dict[str, Any]) -> _PreparedReview:
        if review["project_id"] is None:
            raise Stage3Error("stage3_project_source_required")
        try:
            summary = json.loads(review["sanitized_candidate_json"])
        except json.JSONDecodeError as exc:
            raise Stage3Error("sanitized_candidate_invalid") from exc
        if summary.get("rejected"):
            raise Stage3Error("candidate_already_rejected")
        try:
            context = self.intake._project_context(str(review["project_id"]))
            snapshot = self.intake.snapshot_project(str(review["project_id"]))
        except IntakeError as exc:
            raise Stage3Error(exc.code) from exc
        with self.store.read_connection() as connection:
            run = connection.execute(
                "SELECT snapshot_after FROM intake_runs WHERE run_id = ?",
                (review["run_id"],),
            ).fetchone()
        if run is None or run["snapshot_after"] != snapshot.digest:
            raise Stage3Error("source_changed_since_review")
        try:
            analysis, inventory = self.intake._extract(context, snapshot)
        except IntakeError as exc:
            raise Stage3Error(exc.code) from exc
        entry_rel = str(context.project["entry_relpath"])
        static_paths = {entry_rel}
        static_paths.update(
            _local_reference(entry_rel, item)
            for item in inventory.stylesheets + inventory.resources
        )
        snapshot_rows = {item.path: item for item in snapshot.entries}
        if any(path not in snapshot_rows for path in static_paths):
            raise Stage3Error("static_closure_changed")
        static_evidence = [
            {
                "path": path,
                "file_type": snapshot_rows[path].file_type,
                "sha256": snapshot_rows[path].sha256,
            }
            for path in sorted(static_paths)
        ]
        found: dict[str, Any] | None = None
        for candidate in analysis.get("candidates", []):
            modules = candidate.get("javascript_modules", [])
            source_hash = self.intake._candidate_source_hash(static_evidence, modules)
            candidate_id = self.intake._candidate_id(
                str(review["project_id"]), candidate, source_hash
            )
            if candidate_id == review["candidate_id"] and source_hash == review["source_hash"]:
                found = candidate
                break
        if found is None:
            raise Stage3Error("candidate_boundary_changed")
        try:
            (
                found["input_contract"],
                found["output_contract"],
                found["error_contract"],
            ) = normalize_capsule_contracts(
                found["capability_kind"],
                found["input_contract"],
                found["output_contract"],
                found["error_contract"],
            )
            fixtures = generate_synthetic_fixtures(found["input_contract"])
        except (DataContractError, KeyError, TypeError) as exc:
            raise Stage3Error(getattr(exc, "code", "data_contract_invalid")) from exc
        if (
            summary.get("input_contract") != found["input_contract"]
            or summary.get("output_contract") != found["output_contract"]
            or summary.get("error_contract") != found["error_contract"]
        ):
            raise Stage3Error("sensitive_contract_identifier_unsupported")

        html_source = snapshot.text.get(entry_rel, "")
        css_source = "\n".join(
            snapshot.text.get(_local_reference(entry_rel, item), "")
            for item in inventory.stylesheets
        )
        raw = "\n".join(
            [str(item.get("source") or "") for item in found["javascript_modules"]]
            + [str(item) for item in found.get("literal_values", [])]
            + [html.unescape(html_source), css_source]
        )
        sensitive_html_values = _sensitive_html_values(html_source)
        profile = self.intake._effective_brand_profile(context.project, context.source_root)
        sensitivity = self.intake._sensitivity(raw, profile)
        composed_sensitivity = self.intake._sensitivity(
            "\n".join(str(item) for item in found.get("composed_literal_values", [])),
            profile,
        )
        decisions = self.intake._bound_decisions(
            str(review["project_id"]), str(review["source_relpath"]), str(review["source_hash"])
        )
        if sensitivity["secret_count"]:
            raise Stage3Error("secret_literal_rejected")
        if decisions["sensitivity"] == "confirm_real_record_reject":
            raise Stage3Error("confirmed_real_record_rejected")
        if (sensitivity["ambiguous_count"] or sensitive_html_values) and decisions[
            "sensitivity"
        ] not in {
            "confirm_fictional_fixture",
            "confirm_safe_redaction",
        }:
            raise Stage3Error("sensitivity_confirmation_required_stage3")
        if composed_sensitivity["ambiguous_count"]:
            raise Stage3Error("composed_sensitive_string_unsupported")
        usage_scope = summary.get("usage_scope")
        if type(usage_scope) is not dict or usage_scope.get("kind") not in {
            "general",
            "brand_limited",
        }:
            raise Stage3Error("usage_scope_invalid")
        if usage_scope.get("kind") == "general" and set(usage_scope) != {"kind"}:
            raise Stage3Error("usage_scope_invalid")
        if usage_scope.get("kind") == "brand_limited":
            if set(usage_scope) != {
                "kind",
                "brand_profile_id",
                "brand_profile_digest",
            }:
                raise Stage3Error("usage_scope_invalid")
            try:
                uuid.UUID(str(usage_scope["brand_profile_id"]))
            except (ValueError, TypeError, AttributeError) as exc:
                raise Stage3Error("usage_scope_invalid") from exc
            if not re.fullmatch(r"[0-9a-f]{64}", str(usage_scope["brand_profile_digest"])):
                raise Stage3Error("usage_scope_invalid")
        if sensitivity["brand_count"]:
            if decisions["brand"] == "retain_brand_limited":
                expected_scope = {
                    "kind": "brand_limited",
                    "brand_profile_id": profile.get("id"),
                    "brand_profile_digest": profile.get("digest"),
                }
            elif decisions["brand"] == "remove_brand":
                expected_scope = {"kind": "general"}
            else:
                raise Stage3Error("brand_confirmation_required")
            if usage_scope != expected_scope:
                raise Stage3Error("usage_scope_decision_mismatch")
            if (
                decisions["brand"] == "remove_brand"
                and composed_sensitivity["brand_count"]
            ):
                raise Stage3Error("composed_brand_string_unsupported")
        elif usage_scope.get("kind") == "brand_limited" and (
            usage_scope.get("brand_profile_id") != profile.get("id")
            or usage_scope.get("brand_profile_digest") != profile.get("digest")
        ):
            raise Stage3Error("brand_profile_changed")

        redact_strings = _sensitive_values(raw) + sensitive_html_values
        if usage_scope.get("kind") == "general":
            redact_strings.extend(profile.get("terms", []))
        registered_asset_paths = sorted(
            {_local_reference(entry_rel, item) for item in inventory.resources}
        )
        if found["capability_kind"] == "computation":
            cleaned_html = ""
            asset_paths: list[str] = []
        else:
            referenced_asset_paths: set[str] = set()
            cleaned_html = sanitize_html(
                html_source,
                dom_scope=found["dom_scope"],
                asset_paths=set(registered_asset_paths),
                redact_strings=redact_strings,
                entry_relpath=entry_rel,
                referenced_asset_paths=referenced_asset_paths,
            )
            asset_paths = sorted(referenced_asset_paths)
        if (
            found["capability_kind"] != "computation"
            and asset_paths
            and decisions.get("asset") != "confirm_assets_contain_no_real_records"
        ):
            raise Stage3Error("asset_content_confirmation_required_stage3")
        logical_path_text = "\n".join(
            [str(item.get("path") or "") for item in found["javascript_modules"]]
            + asset_paths
        )
        path_terms = _sensitive_values(logical_path_text)
        if usage_scope.get("kind") == "general":
            path_terms.extend(profile.get("terms", []))
        if any(term.casefold() in logical_path_text.casefold() for term in path_terms if term):
            raise Stage3Error("sensitive_logical_path_unsupported")
        security = _analyze_javascript(found, sorted(set(redact_strings)))
        found["javascript_modules"] = security["javascript_modules"]
        cleaned_javascript = "\n".join(
            str(item.get("source") or "") for item in found["javascript_modules"]
        )
        if any(
            term and term.casefold() in cleaned_javascript.casefold()
            for term in redact_strings
        ):
            raise Stage3Error("javascript_redaction_incomplete")
        if (
            found["capability_kind"] != "computation"
            and asset_paths
            and profile.get("id")
            and usage_scope.get("kind") == "general"
        ):
            raise Stage3Error("brand_asset_requires_brand_limited")
        if found["capability_kind"] == "computation":
            cleaned_css = ""
            assets: tuple[CleanAsset, ...] = ()
        else:
            cleaned_css = sanitize_css(css_source, redact_strings=redact_strings)
            source_assets: dict[str, bytes] = {}
            for logical in asset_paths:
                try:
                    content, _mtime_ns = self.intake._read_stable_bytes(
                        context.path.joinpath(*PurePosixPath(logical).parts),
                        root=context.path,
                        relative=logical,
                    )
                except IntakeError as exc:
                    raise Stage3Error(exc.code) from exc
                if hashlib.sha256(content).hexdigest() != snapshot_rows[logical].sha256:
                    raise Stage3Error("source_changed_during_scan")
                source_assets[logical] = content
            assets = _clean_assets(source_assets)
        if any(
            term
            and term.casefold()
            in f"{cleaned_html}\n{cleaned_css}".casefold()
            for term in redact_strings
        ):
            raise Stage3Error("content_redaction_incomplete")
        activation = dict(found["activation"])
        if found["capability_kind"] == "interaction":
            activation["cleanup"] = "returned_dispose"
        runtime_allowlist = {
            "presentation": ["local_computation", "scoped_ui_update"],
            "interaction": [
                "declared_event_handling",
                "declared_output_emit",
                "memory_state",
                "scoped_input_read",
                "scoped_ui_update",
            ],
            "computation": ["local_computation"],
        }[found["capability_kind"]]
        if assets:
            runtime_allowlist.append("bundled_asset_read")
        canonical = canonicalize_capsule(
            {
                "capability_kind": found["capability_kind"],
                "activation": activation,
                "input_contract": found["input_contract"],
                "output_contract": found["output_contract"],
                "error_contract": found["error_contract"],
                "runtime_allowlist": runtime_allowlist,
                "dom_scope": found["dom_scope"],
                "usage_scope": usage_scope,
                "html": cleaned_html,
                "css": cleaned_css,
                "javascript_modules": found["javascript_modules"],
                "assets": [
                    {
                        "logical_path": item.logical_path,
                        "media_type": item.media_type,
                        "sha256": item.sha256,
                    }
                    for item in assets
                ],
            }
        )
        cleaning = {
            "schema_version": "capsule_cleaning.v1",
            "status": "passed",
            "redaction_count": len(set(redact_strings)),
            "html_cleaned": bool(cleaned_html),
            "css_cleaned": bool(cleaned_css),
            "asset_count": len(assets),
        }
        artifact = Stage3Artifact(
            canonical_payload=canonical.payload,
            canonical_hash=canonical.sha256,
            assets=assets,
            cleaning_summary=cleaning,
            security_result={
                "schema_version": "fixed_security.v1",
                "status": "passed",
                "security_rules_version": SECURITY_RULES_VERSION,
                "listener_bindings": security.get("listener_bindings", []),
            },
        )
        return _PreparedReview(
            review=review,
            artifact=artifact,
            fixtures=fixtures,
            snapshot_digest=snapshot.digest,
            listener_bindings=list(security.get("listener_bindings", [])),
        )

    def _review(self, review_id: str) -> dict[str, Any]:
        with self.store.read_connection() as connection:
            row = connection.execute(
                "SELECT * FROM review_items WHERE review_id = ?", (review_id,)
            ).fetchone()
        if row is None:
            raise Stage3Error("review_item_not_found")
        return dict(row)

    @staticmethod
    def _comparison(review: dict[str, Any]) -> dict[str, Any]:
        try:
            value = json.loads(review.get("equivalence_comparison_json") or "{}")
        except json.JSONDecodeError as exc:
            raise Stage3Error("equivalence_comparison_invalid") from exc
        if type(value) is not dict:
            raise Stage3Error("equivalence_comparison_invalid")
        return value

    @classmethod
    def _comparison_candidate(
        cls,
        review: dict[str, Any],
        *,
        capsule_id: str | None = None,
        version_id: str | None = None,
    ) -> dict[str, Any] | None:
        candidates = cls._comparison(review).get("candidates", [])
        if type(candidates) is not list:
            raise Stage3Error("equivalence_comparison_invalid")
        for candidate in candidates:
            if type(candidate) is not dict:
                raise Stage3Error("equivalence_comparison_invalid")
            if capsule_id is not None and candidate.get("capsule_id") != capsule_id:
                continue
            if version_id is not None and candidate.get("version_id") != version_id:
                continue
            return candidate
        return None

    @classmethod
    def _representative_review_id(cls, review: dict[str, Any]) -> str | None:
        comparison = cls._comparison(review)
        if "same_run_exact_duplicate" not in comparison.get("reason_codes", []):
            return None
        value = comparison.get("representative_review_id")
        return value if type(value) is str and value else None

    @classmethod
    def _same_run_followers(
        cls, connection: sqlite3.Connection, review: dict[str, Any]
    ) -> list[dict[str, Any]]:
        rows = connection.execute(
            "SELECT * FROM review_items WHERE run_id = ? AND review_id <> ? "
            "AND candidate_canonical_hash = ?",
            (
                review["run_id"],
                review["review_id"],
                review["candidate_canonical_hash"],
            ),
        ).fetchall()
        return [
            dict(row)
            for row in rows
            if cls._representative_review_id(dict(row)) == review["review_id"]
        ]

    def _capsule(self, capsule_id: str) -> dict[str, Any]:
        with self.store.read_connection() as connection:
            row = connection.execute(
                "SELECT * FROM capsules WHERE capsule_id = ?", (capsule_id,)
            ).fetchone()
        if row is None:
            raise Stage3Error("capsule_not_found")
        return dict(row)

    def _runtime_validation(self, prepared: _PreparedReview) -> dict[str, Any]:
        payload = prepared.artifact.canonical_payload
        if payload["capability_kind"] == "computation":
            return _validate_computation(payload, prepared.fixtures)
        return _validate_qweb(
            payload,
            prepared.fixtures,
            prepared.artifact.assets,
            prepared.listener_bindings,
        )

    @staticmethod
    def _supervision_summary(prepared: _PreparedReview) -> dict[str, Any]:
        payload = prepared.artifact.canonical_payload
        activation = {
            key: value
            for key, value in payload["activation"].items()
            if key != "entry_module"
        }
        return {
            "schema_version": "capsule_supervision_input.v1",
            "canonical_hash": prepared.artifact.canonical_hash,
            "capability_kind": payload["capability_kind"],
            "activation": activation,
            "input_contract": payload["input_contract"],
            "output_contract": payload["output_contract"],
            "error_contract": payload["error_contract"],
            "runtime_allowlist": payload["runtime_allowlist"],
            "dom_scope": payload["dom_scope"],
            "usage_scope": payload["usage_scope"],
            "cleaning_summary": prepared.artifact.cleaning_summary,
            "fixture_summary": {
                "normal_count": len(prepared.fixtures["normal"]),
                "boundary_count": len(prepared.fixtures["boundary"]),
                "invalid_count": len(prepared.fixtures["invalid"]),
            },
            "asset_metadata": [
                {
                    "logical_name": f"asset_{index}",
                    "media_type": item.media_type,
                    "sha256": item.sha256,
                    "width": item.width,
                    "height": item.height,
                }
                for index, item in enumerate(prepared.artifact.assets, start=1)
            ],
        }

    def _hash_matches(self, canonical_hash: str) -> list[dict[str, Any]]:
        with self.store.read_connection() as connection:
            rows = connection.execute(
                "SELECT cv.*, c.status, c.current_version_id, c.capability_key, "
                "c.role_key, c.variant_key, c.capability_kind FROM capsule_versions cv "
                "JOIN capsules c ON c.capsule_id = cv.capsule_id "
                "WHERE cv.canonical_hash = ? ORDER BY cv.created_at, cv.version_id",
                (canonical_hash,),
            ).fetchall()
        return [dict(row) for row in rows]

    @classmethod
    def _eligible_exact(cls, row: dict[str, Any]) -> bool:
        return (
            row["status"] == "active"
            and row["version_id"] == row["current_version_id"]
            and row["extraction_contract_version"] == EXTRACTION_CONTRACT_VERSION
            and row["redaction_rules_version"] == REDACTION_RULES_VERSION
            and row["canonicalization_version"] == CANONICALIZATION_VERSION
            and row["security_rules_version"] == SECURITY_RULES_VERSION
            and row["supervision_rules_version"] == SUPERVISION_RULES_VERSION
            and row["validation_contract_version"] == VALIDATION_CONTRACT_VERSION
            and cls._stored_version_evidence_eligible(row)
        )

    @classmethod
    def _stored_version_evidence_eligible(cls, row: dict[str, Any]) -> bool:
        try:
            supervision = json.loads(row["supervision_result_json"])
            validation = json.loads(row["validation_result_json"])
            extraction = json.loads(row["extraction_summary_json"])
            cleaning = json.loads(row["cleaning_summary_json"])
        except (KeyError, TypeError, json.JSONDecodeError):
            return False
        capability_kind = row.get("capability_kind")
        if (
            type(supervision) is not dict
            or type(validation) is not dict
            or type(extraction) is not dict
            or type(cleaning) is not dict
            or capability_kind not in {"presentation", "interaction", "computation"}
        ):
            return False
        evidence = extraction.get("stage3_evidence")
        if type(evidence) is not dict:
            return False
        has_approval = "human_approval" in evidence
        approval = evidence.get("human_approval")
        evidence_without_approval = dict(evidence)
        evidence_without_approval.pop("human_approval", None)
        if not cls._evidence_current(evidence_without_approval, capability_kind):
            return False
        if (
            evidence_without_approval["cleaning_summary"] != cleaning
            or evidence_without_approval["validation"] != validation
            or evidence_without_approval["model_name"]
            != row.get("supervision_model_name")
            or evidence_without_approval["model_digest"]
            != row.get("supervision_model_digest")
            or evidence_without_approval["supervised_at"] != row.get("supervised_at")
        ):
            return False
        response_hash = row.get("supervision_response_hash")
        if type(response_hash) is not str or re.fullmatch(r"[0-9a-f]{64}", response_hash) is None:
            return False
        try:
            normalized_supervision = _validate_supervision(supervision, capability_kind)
        except Stage3Error:
            return False
        if normalized_supervision != supervision or supervision["verdict"] == "reject":
            return False
        approval_valid = cls._human_approval_eligible(approval) if has_approval else False
        if has_approval and not approval_valid:
            return False
        human_review_required = bool(
            supervision["verdict"] == "review"
            or supervision["review_required"]
            or supervision["remove_reason_codes"]
            or supervision["brand_signals"]
            or supervision["hidden_dependency_codes"]
        )
        return not human_review_required or approval_valid

    @staticmethod
    def _human_approval_eligible(approval: Any) -> bool:
        return (
            type(approval) is dict
            and set(approval) == {"decision", "review_id", "decided_at"}
            and approval.get("decision")
            in {
                "publish_general",
                "publish_brand_limited",
                "replace_current",
                "create_variant",
                "semantic_split",
            }
            and type(approval.get("review_id")) is str
            and 1 <= len(approval["review_id"]) <= 200
            and type(approval.get("decided_at")) is str
            and 1 <= len(approval["decided_at"]) <= 64
        )

    def _same_run_representative(
        self, prepared: _PreparedReview
    ) -> dict[str, Any] | None:
        with self.store.read_connection() as connection:
            row = connection.execute(
                "SELECT * FROM review_items WHERE run_id = ? AND review_id <> ? "
                "AND candidate_canonical_hash = ? AND candidate_status IN "
                "('review_required', 'waiting_model', 'waiting_validation', 'rejected') "
                "ORDER BY updated_at, review_id LIMIT 1",
                (
                    prepared.review["run_id"],
                    prepared.review["review_id"],
                    prepared.artifact.canonical_hash,
                ),
            ).fetchone()
        return dict(row) if row is not None else None

    def _copy_representative(
        self, review: dict[str, Any], representative: dict[str, Any]
    ) -> dict[str, Any]:
        sanitized = json.loads(review["sanitized_candidate_json"])
        representative_summary = json.loads(representative["sanitized_candidate_json"])
        for key in ("stage3_evidence", "stage3_failure"):
            if key in representative_summary:
                sanitized[key] = representative_summary[key]
        comparison = {
            "schema_version": "equivalence_comparison.v1",
            "reason_codes": ["same_run_exact_duplicate"],
            "representative_review_id": representative["review_id"],
            "candidates": [],
        }
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE review_items SET candidate_status = ?, candidate_canonical_hash = ?, "
                "sanitized_candidate_json = ?, supervision_result_json = ?, "
                "supervision_response_hash = ?, equivalence_comparison_json = ?, updated_at = ? "
                "WHERE review_id = ?",
                (
                    representative["candidate_status"],
                    representative["candidate_canonical_hash"],
                    _json(sanitized),
                    representative["supervision_result_json"],
                    representative["supervision_response_hash"],
                    _json(comparison),
                    _now(),
                    review["review_id"],
                ),
            )
            self._sync_run_evidence(connection, str(review["run_id"]))
            self.store.bump_revision(connection)
        return {
            "review_id": review["review_id"],
            "status": representative["candidate_status"],
            "canonical_hash": representative["candidate_canonical_hash"],
            "same_run_representative": representative["review_id"],
        }

    def _record_gate_failure(
        self,
        review: dict[str, Any],
        code: str,
        *,
        canonical_hash: str | None = None,
        supervision: dict[str, Any] | None = None,
        response_hash: str | None = None,
        model: dict[str, str] | None = None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if code in {
            "sensitivity_confirmation_required_stage3",
            "asset_content_confirmation_required_stage3",
        }:
            status = "waiting_user"
        elif code.startswith("ollama_"):
            status = "waiting_model"
        elif code in {
            "node_unavailable",
            "esbuild_unavailable",
            "esbuild_bundle_failed",
            "bundle_syntax_invalid",
            "bundle_security_analyzer_failed",
            "javascript_security_analyzer_failed",
            "pyside6_unavailable",
            "compute_worker_failed",
            "compute_worker_failed_timeout",
            "image_worker_failed",
            "image_worker_failed_timeout",
            "qweb_worker_failed",
            "qweb_worker_failed_timeout",
            "qweb_timeout",
        }:
            status = "waiting_validation"
        else:
            status = "rejected"
        sanitized = json.loads(review["sanitized_candidate_json"])
        sanitized["stage3_failure"] = {
            "schema_version": "stage3_failure.v1",
            "error_code": code,
        }
        if details is not None:
            sanitized["stage3_failure"]["details"] = details
        if model:
            sanitized["stage3_failure"]["model_name"] = model["name"]
            sanitized["stage3_failure"]["model_digest"] = model["digest"]
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE review_items SET candidate_status = ?, candidate_canonical_hash = ?, "
                "sanitized_candidate_json = ?, supervision_result_json = ?, "
                "supervision_response_hash = ?, equivalence_comparison_json = ?, updated_at = ? "
                "WHERE review_id = ?",
                (
                    status,
                    canonical_hash,
                    _json(sanitized),
                    _json(supervision) if supervision else None,
                    response_hash,
                    _json(
                        {
                            "schema_version": "equivalence_comparison.v1",
                            "reason_codes": [code],
                            "candidates": [],
                        }
                    ),
                    _now(),
                    review["review_id"],
                ),
            )
            self._sync_run_evidence(connection, str(review["run_id"]))
            self.store.bump_revision(connection)
        return {
            "review_id": review["review_id"],
            "status": status,
            "error_code": code,
            "canonical_hash": canonical_hash,
        }

    def _equivalence_comparison(
        self, prepared: _PreparedReview, hash_matches: list[dict[str, Any]]
    ) -> dict[str, Any]:
        payload = prepared.artifact.canonical_payload
        with self.store.read_connection() as connection:
            rows = connection.execute(
                "SELECT c.capsule_id, c.capability_key, c.role_key, c.variant_key, "
                "c.status, cv.version_id, cv.canonical_hash, cv.activation_json, "
                "cv.input_contract_json, cv.output_contract_json, cv.error_contract_json, "
                "cv.runtime_allowlist_json, cv.dom_scope_json, cv.usage_scope_json, "
                "EXISTS (SELECT 1 FROM capsule_sources cs WHERE cs.version_id = cv.version_id "
                "AND cs.project_id = ?) AS project_contributed_current, "
                "EXISTS (SELECT 1 FROM capsule_status_events se "
                "WHERE se.capsule_id = c.capsule_id AND se.version_id = cv.version_id "
                "AND se.event_type = 'revalidation_required' "
                "AND se.reason_code = 'brand_profile_changed' "
                "AND se.to_status = 'pending_revalidation') AS brand_revalidation_required "
                "FROM capsules c JOIN capsule_versions cv ON cv.version_id = c.current_version_id "
                "WHERE c.capability_kind = ? AND c.status IN ('active', 'pending_revalidation') "
                "ORDER BY c.capability_key, c.role_key, c.variant_key LIMIT 100",
                (prepared.review["project_id"], payload["capability_kind"]),
            ).fetchall()
        exact_versions = {str(row["version_id"]) for row in hash_matches}
        candidates = []
        for row in rows:
            role_contract_match = all(
                json.loads(row[column]) == payload[payload_key]
                for column, payload_key in (
                    ("activation_json", "activation"),
                    ("input_contract_json", "input_contract"),
                    ("output_contract_json", "output_contract"),
                    ("error_contract_json", "error_contract"),
                    ("runtime_allowlist_json", "runtime_allowlist"),
                    ("dom_scope_json", "dom_scope"),
                )
            )
            current_scope = json.loads(row["usage_scope_json"])
            contract_match = (
                role_contract_match and current_scope == payload["usage_scope"]
            )
            scope_revalidation_match = (
                row["status"] == "pending_revalidation"
                and bool(row["project_contributed_current"])
                and bool(row["brand_revalidation_required"])
                and role_contract_match
                and current_scope != payload["usage_scope"]
            )
            if (
                contract_match
                or scope_revalidation_match
                or row["version_id"] in exact_versions
            ):
                candidates.append(
                    {
                        "capsule_id": row["capsule_id"],
                        "version_id": row["version_id"],
                        "capability_key": row["capability_key"],
                        "role_key": row["role_key"],
                        "variant_key": row["variant_key"],
                        "canonical_hash_equal": row["canonical_hash"]
                        == prepared.artifact.canonical_hash,
                        "contract_match": contract_match,
                        "scope_revalidation_match": scope_revalidation_match,
                    }
                )
        return {
            "schema_version": "equivalence_comparison.v1",
            "candidate_canonical_hash": prepared.artifact.canonical_hash,
            "automatic_semantic_merge": False,
            "candidates": candidates,
        }

    def _record_evidence(
        self,
        prepared: _PreparedReview,
        comparison: dict[str, Any],
        status: str,
    ) -> dict[str, Any]:
        artifact = prepared.artifact
        evidence = {
            "schema_version": "stage3_evidence.v1",
            "extraction_contract_version": EXTRACTION_CONTRACT_VERSION,
            "redaction_rules_version": REDACTION_RULES_VERSION,
            "canonicalization_version": CANONICALIZATION_VERSION,
            "security_rules_version": SECURITY_RULES_VERSION,
            "supervision_rules_version": SUPERVISION_RULES_VERSION,
            "validation_contract_version": VALIDATION_CONTRACT_VERSION,
            "model_name": artifact.model_name,
            "model_digest": artifact.model_digest,
            "supervised_at": artifact.supervised_at,
            "cleaning_summary": artifact.cleaning_summary,
            "security_result": artifact.security_result,
            "validation": artifact.validation,
        }
        sanitized = json.loads(prepared.review["sanitized_candidate_json"])
        sanitized["stage3_evidence"] = evidence
        sanitized.pop("stage3_failure", None)
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE review_items SET candidate_status = ?, candidate_canonical_hash = ?, "
                "sanitized_candidate_json = ?, supervision_result_json = ?, "
                "supervision_response_hash = ?, equivalence_comparison_json = ?, updated_at = ? "
                "WHERE review_id = ?",
                (
                    status,
                    artifact.canonical_hash,
                    _json(sanitized),
                    _json(artifact.supervision),
                    artifact.supervision_response_hash,
                    _json(comparison),
                    _now(),
                    prepared.review["review_id"],
                ),
            )
            self._sync_run_evidence(connection, str(prepared.review["run_id"]))
            self.store.bump_revision(connection)
        return {
            "review_id": prepared.review["review_id"],
            "status": status,
            "canonical_hash": artifact.canonical_hash,
            "validation_scope": artifact.validation.get("acceptance_scope")
            if artifact.validation
            else None,
        }

    @staticmethod
    def _evidence(review: dict[str, Any]) -> dict[str, Any]:
        try:
            summary = json.loads(review["sanitized_candidate_json"])
        except json.JSONDecodeError as exc:
            raise Stage3Error("stage3_evidence_missing") from exc
        evidence = summary.get("stage3_evidence")
        if type(evidence) is not dict:
            raise Stage3Error("stage3_evidence_missing")
        return evidence

    @staticmethod
    def _evidence_current(evidence: dict[str, Any], capability_kind: str) -> bool:
        required = {
            "schema_version",
            "extraction_contract_version",
            "redaction_rules_version",
            "canonicalization_version",
            "security_rules_version",
            "supervision_rules_version",
            "validation_contract_version",
            "model_name",
            "model_digest",
            "supervised_at",
            "cleaning_summary",
            "security_result",
            "validation",
        }
        if type(evidence) is not dict or set(evidence) != required:
            return False
        if not (
            evidence.get("schema_version") == "stage3_evidence.v1"
            and evidence.get("extraction_contract_version") == EXTRACTION_CONTRACT_VERSION
            and evidence.get("redaction_rules_version") == REDACTION_RULES_VERSION
            and evidence.get("canonicalization_version") == CANONICALIZATION_VERSION
            and evidence.get("security_rules_version") == SECURITY_RULES_VERSION
            and evidence.get("supervision_rules_version") == SUPERVISION_RULES_VERSION
            and evidence.get("validation_contract_version") == VALIDATION_CONTRACT_VERSION
            and type(evidence.get("model_name")) is str
            and bool(evidence["model_name"])
            and len(evidence["model_name"]) <= 200
            and type(evidence.get("model_digest")) is str
            and bool(evidence["model_digest"])
            and len(evidence["model_digest"]) <= 200
            and type(evidence.get("supervised_at")) is str
            and bool(evidence["supervised_at"])
        ):
            return False
        cleaning = evidence.get("cleaning_summary")
        if not (
            type(cleaning) is dict
            and set(cleaning)
            == {
                "schema_version",
                "status",
                "redaction_count",
                "html_cleaned",
                "css_cleaned",
                "asset_count",
            }
            and cleaning.get("schema_version") == "capsule_cleaning.v1"
            and cleaning.get("status") == "passed"
            and type(cleaning.get("redaction_count")) is int
            and cleaning["redaction_count"] >= 0
            and type(cleaning.get("asset_count")) is int
            and cleaning["asset_count"] >= 0
            and type(cleaning.get("html_cleaned")) is bool
            and type(cleaning.get("css_cleaned")) is bool
        ):
            return False
        security = evidence.get("security_result")
        if not (
            type(security) is dict
            and set(security)
            == {"schema_version", "status", "security_rules_version", "listener_bindings"}
            and security.get("schema_version") == "fixed_security.v1"
            and security.get("status") == "passed"
            and security.get("security_rules_version") == SECURITY_RULES_VERSION
            and type(security.get("listener_bindings")) is list
            and all(
                type(item) is dict
                and set(item) == {"selector", "event", "handler"}
                and all(type(item[key]) is str and item[key] for key in item)
                for item in security["listener_bindings"]
            )
        ):
            return False
        validation = evidence.get("validation")
        expected_scope = {
            "presentation": "real_qwebengine_render",
            "interaction": "real_qwebengine_interaction",
            "computation": "isolated_node_vm_computation",
        }.get(capability_kind)
        if not (
            expected_scope
            and type(validation) is dict
            and validation.get("status") == "passed"
            and validation.get("acceptance_scope") == expected_scope
            and type(validation.get("normal_cases")) is int
            and validation["normal_cases"] >= 1
            and type(validation.get("boundary_cases")) is int
            and validation["boundary_cases"] >= 0
            and type(validation.get("invalid_cases")) is int
            and validation["invalid_cases"] >= 0
        ):
            return False
        if capability_kind == "computation":
            return (
                set(validation)
                == {
                    "schema_version",
                    "status",
                    "acceptance_scope",
                    "normal_cases",
                    "boundary_cases",
                    "invalid_cases",
                    "repeatability_checked",
                    "input_freeze_checked",
                }
                and validation.get("schema_version") == "runtime_validation.v1"
                and validation.get("repeatability_checked") is True
                and validation.get("input_freeze_checked") is True
            )
        expected_qweb_keys = {
            "schema_version",
            "status",
            "normal_cases",
            "boundary_cases",
            "repeated_render",
            "dispose_idempotent",
            "remount_checked",
            "acceptance_scope",
            "invalid_cases",
        }
        if capability_kind == "interaction":
            expected_qweb_keys.update({"emission_count", "emission_names"})
        return (
            set(validation) == expected_qweb_keys
            and validation.get("schema_version") == "qweb_validation.v1"
            and type(validation.get("repeated_render")) is bool
            and type(validation.get("dispose_idempotent")) is bool
            and type(validation.get("remount_checked")) is bool
            and validation["repeated_render"] == (capability_kind == "presentation")
            and validation["dispose_idempotent"] == (capability_kind == "interaction")
            and validation["remount_checked"]
            == (
                capability_kind == "interaction"
                and validation["normal_cases"] + validation["boundary_cases"] > 1
            )
            and (
                capability_kind != "interaction"
                or (
                    type(validation.get("emission_count")) is int
                    and validation["emission_count"] >= 0
                    and type(validation.get("emission_names")) is list
                    and validation["emission_names"]
                    == sorted(set(validation["emission_names"]))
                    and all(type(item) is str and item for item in validation["emission_names"])
                )
            )
        )

    @staticmethod
    def _sync_run_evidence(connection: sqlite3.Connection, run_id: str) -> None:
        rows = connection.execute(
            "SELECT candidate_status, count(*) AS count FROM review_items "
            "WHERE run_id = ? GROUP BY candidate_status",
            (run_id,),
        ).fetchall()
        counts = {str(row["candidate_status"]): int(row["count"]) for row in rows}
        pending = any(
            counts.get(status, 0)
            for status in (
                "extracted",
                "waiting_user",
                "waiting_model",
                "waiting_validation",
                "review_required",
                "publishable",
            )
        )
        run = connection.execute(
            "SELECT counts_json, project_id, snapshot_after FROM intake_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if run is None:
            raise Stage3Error("intake_run_not_found")
        try:
            run_counts = json.loads(run["counts_json"])
        except (TypeError, json.JSONDecodeError):
            run_counts = {}
        run_counts["stage3_candidate_statuses"] = counts
        if pending:
            connection.execute(
                "UPDATE intake_runs SET counts_json = ? WHERE run_id = ?",
                (_json(run_counts), run_id),
            )
            if run["project_id"] is not None:
                connection.execute(
                    "UPDATE projects SET last_snapshot_hash = NULL, updated_at = ? "
                    "WHERE project_id = ?",
                    (_now(), run["project_id"]),
                )
        else:
            connection.execute(
                "UPDATE intake_runs SET counts_json = ?, "
                "security_rules_version = ?, supervision_rules_version = ?, "
                "validation_contract_version = ? WHERE run_id = ?",
                (
                    _json(run_counts),
                    SECURITY_RULES_VERSION,
                    SUPERVISION_RULES_VERSION,
                    VALIDATION_CONTRACT_VERSION,
                    run_id,
                ),
            )
            if run["project_id"] is not None and run["snapshot_after"] is not None:
                connection.execute(
                    "UPDATE projects SET last_snapshot_hash = ?, updated_at = ? "
                    "WHERE project_id = ?",
                    (run["snapshot_after"], _now(), run["project_id"]),
                )

    def _assert_snapshot(self, prepared: _PreparedReview) -> None:
        try:
            current = self.intake.snapshot_project(str(prepared.review["project_id"]))
        except IntakeError as exc:
            raise Stage3Error(exc.code) from exc
        if current.digest != prepared.snapshot_digest:
            raise Stage3Error("source_changed_during_scan")

    def _attach_exact_duplicate(
        self, prepared: _PreparedReview, version: dict[str, Any]
    ) -> dict[str, Any]:
        self._assert_snapshot(prepared)
        review = prepared.review
        sanitized = json.loads(review["sanitized_candidate_json"])
        sanitized["stage3_evidence"] = {
            "schema_version": "stage3_evidence.v1",
            "result": "eligible_active_current_exact_duplicate",
            "version_id": version["version_id"],
            "security_rules_version": SECURITY_RULES_VERSION,
            "supervision_rules_version": SUPERVISION_RULES_VERSION,
            "validation_contract_version": VALIDATION_CONTRACT_VERSION,
        }
        now = _now()
        comparison = _json(
            {
                "schema_version": "equivalence_comparison.v1",
                "reason_codes": ["eligible_active_current_exact_duplicate"],
                "candidates": [
                    {
                        "capsule_id": version["capsule_id"],
                        "version_id": version["version_id"],
                        "canonical_hash_equal": True,
                    }
                ],
            }
        )
        with self.store.transaction() as connection:
            current = connection.execute(
                "SELECT cv.*, c.status, c.current_version_id, c.capability_key, "
                "c.role_key, c.variant_key, c.capability_kind FROM capsule_versions cv "
                "JOIN capsules c ON c.capsule_id = cv.capsule_id WHERE cv.version_id = ?",
                (version["version_id"],),
            ).fetchone()
            if (
                current is None
                or current["capsule_id"] != version["capsule_id"]
                or current["canonical_hash"] != prepared.artifact.canonical_hash
                or not self._eligible_exact(dict(current))
            ):
                raise Stage3Error("exact_duplicate_target_expired")
            updated = connection.execute(
                "UPDATE review_items SET candidate_status = 'duplicate', "
                "candidate_canonical_hash = ?, sanitized_candidate_json = ?, "
                "retained_version_id = ?, equivalence_comparison_json = ?, updated_at = ? "
                "WHERE review_id = ? AND candidate_status = 'extracted' AND decision IS NULL",
                (
                    prepared.artifact.canonical_hash,
                    _json(sanitized),
                    version["version_id"],
                    comparison,
                    now,
                    review["review_id"],
                ),
            )
            if updated.rowcount != 1:
                raise Stage3Error("review_decision_conflict")
            connection.execute(
                "INSERT OR IGNORE INTO capsule_sources "
                "(source_link_id, version_id, project_id, source_identity, source_kind, "
                "source_relpath, source_hash, candidate_canonical_hash, relationship, read_at) "
                "VALUES (?, ?, ?, ?, 'project', ?, ?, ?, 'exact', ?)",
                (
                    f"src_{uuid.uuid4().hex}",
                    version["version_id"],
                    review["project_id"],
                    f"project:{review['project_id']}",
                    review["source_relpath"],
                    review["source_hash"],
                    prepared.artifact.canonical_hash,
                    now,
                ),
            )
            self._sync_run_evidence(connection, str(review["run_id"]))
            self.store.bump_revision(connection)
        return {
            "review_id": review["review_id"],
            "status": "duplicate",
            "capsule_id": version["capsule_id"],
            "version_id": version["version_id"],
            "model_called": False,
            "runtime_validation_run": False,
        }

    def _merge_existing(
        self, review: dict[str, Any], retained_version_id: str
    ) -> dict[str, Any]:
        comparison_target = self._comparison_candidate(
            review, version_id=retained_version_id
        )
        if comparison_target is None:
            raise Stage3Error("retained_version_not_in_comparison_evidence")
        prepared = self._prepare(review)
        if prepared.artifact.canonical_hash != review["candidate_canonical_hash"]:
            raise Stage3Error("candidate_changed_since_validation")
        with self.store.read_connection() as connection:
            target = connection.execute(
                "SELECT cv.*, c.current_version_id, c.status, c.capability_kind "
                "FROM capsule_versions cv JOIN capsules c ON c.capsule_id = cv.capsule_id "
                "WHERE cv.version_id = ?",
                (retained_version_id,),
            ).fetchone()
        if not self._merge_target_eligible(
            target,
            retained_version_id,
            comparison_target,
            prepared.artifact.canonical_payload,
        ):
            raise Stage3Error("retained_version_incompatible")
        self._assert_snapshot(prepared)
        now = _now()
        with self.store.transaction() as connection:
            current_target = connection.execute(
                "SELECT cv.*, c.current_version_id, c.status, c.capability_kind "
                "FROM capsule_versions cv JOIN capsules c ON c.capsule_id = cv.capsule_id "
                "WHERE cv.version_id = ?",
                (retained_version_id,),
            ).fetchone()
            if not self._merge_target_eligible(
                current_target,
                retained_version_id,
                comparison_target,
                prepared.artifact.canonical_payload,
            ):
                raise Stage3Error("retained_version_evidence_expired")
            updated = connection.execute(
                "UPDATE review_items SET candidate_status = 'merged', "
                "decision = 'merge_existing', retained_version_id = ?, decided_at = ?, "
                "updated_at = ? WHERE review_id = ? AND candidate_status = 'review_required' "
                "AND decision IS NULL",
                (retained_version_id, now, now, review["review_id"]),
            )
            if updated.rowcount != 1:
                raise Stage3Error("review_decision_conflict")
            followers = self._same_run_followers(connection, review)
            for source_review in [review, *followers]:
                connection.execute(
                    "INSERT OR IGNORE INTO capsule_sources "
                    "(source_link_id, version_id, project_id, source_identity, source_kind, "
                    "source_relpath, source_hash, candidate_canonical_hash, relationship, read_at) "
                    "VALUES (?, ?, ?, ?, 'project', ?, ?, ?, 'human_equivalent', ?)",
                    (
                        f"src_{uuid.uuid4().hex}",
                        retained_version_id,
                        source_review["project_id"],
                        f"project:{source_review['project_id']}",
                        source_review["source_relpath"],
                        source_review["source_hash"],
                        prepared.artifact.canonical_hash,
                        now,
                    ),
                )
            for follower in followers:
                connection.execute(
                    "UPDATE review_items SET candidate_status = 'merged', "
                    "retained_version_id = ?, updated_at = ? WHERE review_id = ?",
                    (retained_version_id, now, follower["review_id"]),
                )
            self._sync_run_evidence(connection, str(review["run_id"]))
            self.store.bump_revision(connection)
        return {
            "review_id": review["review_id"],
            "status": "merged",
            "retained_version_id": retained_version_id,
            "new_version": False,
        }

    def _merge_target_eligible(
        self,
        target: sqlite3.Row | None,
        retained_version_id: str,
        comparison_target: dict[str, Any],
        payload: dict[str, Any],
    ) -> bool:
        return bool(
            target is not None
            and target["capsule_id"] == comparison_target.get("capsule_id")
            and target["version_id"] == comparison_target.get("version_id")
            and self._eligible_exact(dict(target))
            and target["status"] == "active"
            and target["current_version_id"] == retained_version_id
            and target["capability_kind"] == payload["capability_kind"]
            and json.loads(target["input_contract_json"])
            == payload["input_contract"]
            and json.loads(target["output_contract_json"])
            == payload["output_contract"]
            and json.loads(target["error_contract_json"])
            == payload["error_contract"]
            and json.loads(target["usage_scope_json"])
            == payload["usage_scope"]
        )

    def _replace_target_eligible(
        self,
        connection: sqlite3.Connection,
        review: dict[str, Any],
        capsule_id: str,
        payload: dict[str, Any],
    ) -> bool:
        comparison_target = self._comparison_candidate(
            review, capsule_id=capsule_id
        )
        if comparison_target is None:
            return False
        target = connection.execute(
            "SELECT cv.*, c.status, c.current_version_id, c.capability_kind "
            "FROM capsules c JOIN capsule_versions cv "
            "ON cv.version_id = c.current_version_id WHERE c.capsule_id = ?",
            (capsule_id,),
        ).fetchone()
        if (
            target is None
            or target["version_id"] != comparison_target.get("version_id")
            or target["current_version_id"] != target["version_id"]
            or target["capability_kind"] != payload["capability_kind"]
            or target["status"] not in {"active", "pending_revalidation"}
        ):
            return False
        role_contract_match = all(
            json.loads(target[column]) == payload[payload_key]
            for column, payload_key in (
                ("activation_json", "activation"),
                ("input_contract_json", "input_contract"),
                ("output_contract_json", "output_contract"),
                ("error_contract_json", "error_contract"),
                ("runtime_allowlist_json", "runtime_allowlist"),
                ("dom_scope_json", "dom_scope"),
            )
        )
        if not role_contract_match:
            return False
        current_scope = json.loads(target["usage_scope_json"])
        if comparison_target.get("contract_match") is True:
            return current_scope == payload["usage_scope"]
        if comparison_target.get("scope_revalidation_match") is not True:
            return False
        return bool(
            target["status"] == "pending_revalidation"
            and current_scope != payload["usage_scope"]
            and connection.execute(
                "SELECT 1 FROM capsule_sources WHERE version_id = ? AND project_id = ?",
                (target["version_id"], review.get("project_id")),
            ).fetchone()
            and connection.execute(
                "SELECT 1 FROM capsule_status_events WHERE capsule_id = ? "
                "AND version_id = ? AND event_type = 'revalidation_required' "
                "AND reason_code = 'brand_profile_changed' "
                "AND to_status = 'pending_revalidation'",
                (capsule_id, target["version_id"]),
            ).fetchone()
        )

    def _publish_version(
        self,
        prepared: _PreparedReview,
        *,
        existing_capsule: dict[str, Any] | None = None,
        capability_key: str | None = None,
        role_key: str | None = None,
        variant_key: str | None = None,
        display_name: str | None = None,
        decision: str | None = None,
        reason_code: str,
        disable_capsule_id: str | None = None,
        disable_version_id: str | None = None,
    ) -> dict[str, Any]:
        artifact = prepared.artifact
        if (
            artifact.supervision is None
            or artifact.supervision_response_hash is None
            or artifact.model_name is None
            or artifact.model_digest is None
            or artifact.supervised_at is None
            or artifact.validation is None
        ):
            raise Stage3Error("stage3_evidence_missing")
        self._assert_snapshot(prepared)
        now = _now()
        review_summary = json.loads(prepared.review["sanitized_candidate_json"])
        review_summary["stage3_evidence"] = {
            "schema_version": "stage3_evidence.v1",
            "extraction_contract_version": EXTRACTION_CONTRACT_VERSION,
            "redaction_rules_version": REDACTION_RULES_VERSION,
            "canonicalization_version": CANONICALIZATION_VERSION,
            "security_rules_version": SECURITY_RULES_VERSION,
            "supervision_rules_version": SUPERVISION_RULES_VERSION,
            "validation_contract_version": VALIDATION_CONTRACT_VERSION,
            "model_name": artifact.model_name,
            "model_digest": artifact.model_digest,
            "supervised_at": artifact.supervised_at,
            "cleaning_summary": artifact.cleaning_summary,
            "security_result": artifact.security_result,
            "validation": artifact.validation,
        }
        if decision is not None:
            review_summary["stage3_evidence"]["human_approval"] = {
                "decision": decision,
                "review_id": prepared.review["review_id"],
                "decided_at": now,
            }
        if artifact.supervision.get("verdict") == "reject":
            raise Stage3Error("supervision_rejected")
        if artifact.supervision.get("verdict") == "review" and decision is None:
            raise Stage3Error("human_approval_required_for_review_verdict")
        payload = artifact.canonical_payload
        version_id = f"ver_{uuid.uuid4().hex}"
        capsule_id: str
        old_status: str
        expected_review_status = str(prepared.review["candidate_status"])
        if (
            (decision is None and expected_review_status != "extracted")
            or (
                decision == "semantic_split"
                and expected_review_status not in {"review_required", "duplicate"}
            )
            or (
                decision is not None
                and decision != "semantic_split"
                and expected_review_status != "review_required"
            )
        ):
            raise Stage3Error("review_decision_conflict")
        try:
            with self.store.transaction() as connection:
                updated = connection.execute(
                    "UPDATE review_items SET candidate_status = 'publishable', decision = ?, "
                    "retained_version_id = ?, "
                    "decided_at = CASE WHEN ? IS NULL THEN decided_at ELSE ? END, updated_at = ? "
                    "WHERE review_id = ? AND candidate_status = ? AND decision IS NULL",
                    (
                        decision,
                        disable_version_id
                        if decision == "semantic_split"
                        else prepared.review.get("retained_version_id"),
                        decision,
                        now,
                        now,
                        prepared.review["review_id"],
                        expected_review_status,
                    ),
                )
                if updated.rowcount != 1:
                    raise Stage3Error("review_decision_conflict")
                if decision == "replace_current":
                    live_review = connection.execute(
                        "SELECT project_id, equivalence_comparison_json FROM review_items "
                        "WHERE review_id = ?",
                        (prepared.review["review_id"],),
                    ).fetchone()
                    if (
                        existing_capsule is None
                        or live_review is None
                        or not self._replace_target_eligible(
                            connection,
                            dict(live_review),
                            str(existing_capsule["capsule_id"]),
                            payload,
                        )
                    ):
                        raise Stage3Error("replace_current_target_expired")
                if disable_capsule_id is not None:
                    live_review = connection.execute(
                        "SELECT equivalence_comparison_json FROM review_items WHERE review_id = ?",
                        (prepared.review["review_id"],),
                    ).fetchone()
                    target_evidence = self._comparison_candidate(
                        dict(live_review) if live_review is not None else {},
                        capsule_id=disable_capsule_id,
                    )
                    split_target = connection.execute(
                        "SELECT status, current_version_id, capability_kind FROM capsules "
                        "WHERE capsule_id = ?",
                        (disable_capsule_id,),
                    ).fetchone()
                    if (
                        decision != "semantic_split"
                        or target_evidence is None
                        or target_evidence.get("version_id") != disable_version_id
                        or split_target is None
                        or split_target["status"] != "active"
                        or split_target["current_version_id"] != disable_version_id
                        or split_target["capability_kind"] != payload["capability_kind"]
                    ):
                        raise Stage3Error("semantic_split_target_invalid")
                if existing_capsule is None:
                    if (
                        capability_key is None
                        or role_key is None
                        or variant_key is None
                        or display_name is None
                    ):
                        raise Stage3Error("capsule_identity_required")
                    connection.execute(
                        "INSERT INTO capability_groups "
                        "(capability_key, display_name, created_at, updated_at) VALUES (?, ?, ?, ?) "
                        "ON CONFLICT(capability_key) DO NOTHING",
                        (capability_key, display_name, now, now),
                    )
                    if connection.execute(
                        "SELECT 1 FROM capsules WHERE capability_key = ? AND role_key = ? "
                        "AND variant_key = ?",
                        (capability_key, role_key, variant_key),
                    ).fetchone():
                        raise Stage3Error("capsule_identity_conflict")
                    capsule_id = f"cap_{uuid.uuid4().hex}"
                    old_status = "pending_revalidation"
                    connection.execute(
                        "INSERT INTO capsules "
                        "(capsule_id, capability_key, role_key, variant_key, capability_kind, "
                        "status, current_version_id, created_at) VALUES (?, ?, ?, ?, ?, "
                        "'pending_revalidation', NULL, ?)",
                        (
                            capsule_id,
                            capability_key,
                            role_key,
                            variant_key,
                            payload["capability_kind"],
                            now,
                        ),
                    )
                else:
                    capsule_id = str(existing_capsule["capsule_id"])
                    current = connection.execute(
                        "SELECT * FROM capsules WHERE capsule_id = ?", (capsule_id,)
                    ).fetchone()
                    if current is None or current["capability_kind"] != payload["capability_kind"]:
                        raise Stage3Error("capsule_kind_mismatch")
                    if current["current_version_id"] != existing_capsule["current_version_id"]:
                        raise Stage3Error("target_comparison_evidence_expired")
                    if current["status"] == "disabled" and decision is None:
                        raise Stage3Error("disabled_capsule_requires_user_enable")
                    old_status = str(current["status"])
                version_number = int(
                    connection.execute(
                        "SELECT coalesce(max(version_number), 0) + 1 FROM capsule_versions "
                        "WHERE capsule_id = ?",
                        (capsule_id,),
                    ).fetchone()[0]
                )
                connection.execute(
                    "INSERT INTO capsule_versions (version_id, capsule_id, version_number, "
                    "extraction_contract_version, extraction_summary_json, redaction_rules_version, "
                    "canonicalization_version, canonical_hash, activation_json, input_contract_json, "
                    "output_contract_json, error_contract_json, runtime_allowlist_json, dom_scope_json, "
                    "usage_scope_json, html_text, css_text, javascript_modules_json, "
                    "cleaning_summary_json, security_rules_version, supervision_rules_version, "
                    "supervision_model_name, supervision_model_digest, supervised_at, "
                    "supervision_result_json, supervision_response_hash, validation_contract_version, "
                    "validation_result_json, created_at) VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        version_id,
                        capsule_id,
                        version_number,
                        EXTRACTION_CONTRACT_VERSION,
                        _json(review_summary),
                        REDACTION_RULES_VERSION,
                        CANONICALIZATION_VERSION,
                        artifact.canonical_hash,
                        _json(payload["activation"]),
                        _json(payload["input_contract"]),
                        _json(payload["output_contract"]),
                        _json(payload["error_contract"]),
                        _json(payload["runtime_allowlist"]),
                        _json(payload["dom_scope"]),
                        _json(payload["usage_scope"]),
                        payload["html"],
                        payload["css"],
                        _json(payload["javascript_modules"]),
                        _json(artifact.cleaning_summary),
                        SECURITY_RULES_VERSION,
                        SUPERVISION_RULES_VERSION,
                        artifact.model_name,
                        artifact.model_digest,
                        artifact.supervised_at,
                        _json(artifact.supervision),
                        artifact.supervision_response_hash,
                        VALIDATION_CONTRACT_VERSION,
                        _json(artifact.validation),
                        now,
                    ),
                )
                for asset in artifact.assets:
                    connection.execute(
                        "INSERT INTO capsule_assets "
                        "(asset_id, version_id, logical_path, media_type, sha256, size_bytes, "
                        "width, height, content) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            f"asset_{uuid.uuid4().hex}",
                            version_id,
                            asset.logical_path,
                            asset.media_type,
                            asset.sha256,
                            asset.size_bytes,
                            asset.width,
                            asset.height,
                            asset.content,
                        ),
                    )
                connection.execute(
                    "INSERT INTO capsule_sources "
                    "(source_link_id, version_id, project_id, source_identity, source_kind, "
                    "source_relpath, source_hash, candidate_canonical_hash, relationship, read_at) "
                    "VALUES (?, ?, ?, ?, 'project', ?, ?, ?, 'published_implementation', ?)",
                    (
                        f"src_{uuid.uuid4().hex}",
                        version_id,
                        prepared.review["project_id"],
                        f"project:{prepared.review['project_id']}",
                        prepared.review["source_relpath"],
                        prepared.review["source_hash"],
                        artifact.canonical_hash,
                        now,
                    ),
                )
                followers = self._same_run_followers(connection, prepared.review)
                for follower in followers:
                    connection.execute(
                        "INSERT OR IGNORE INTO capsule_sources "
                        "(source_link_id, version_id, project_id, source_identity, source_kind, "
                        "source_relpath, source_hash, candidate_canonical_hash, relationship, read_at) "
                        "VALUES (?, ?, ?, ?, 'project', ?, ?, ?, 'exact', ?)",
                        (
                            f"src_{uuid.uuid4().hex}",
                            version_id,
                            follower["project_id"],
                            f"project:{follower['project_id']}",
                            follower["source_relpath"],
                            follower["source_hash"],
                            artifact.canonical_hash,
                            now,
                        ),
                    )
                connection.execute(
                    "UPDATE capsules SET current_version_id = ?, status = 'active' "
                    "WHERE capsule_id = ?",
                    (version_id, capsule_id),
                )
                connection.execute(
                    "INSERT INTO capsule_status_events "
                    "(event_id, capsule_id, event_type, from_status, to_status, version_id, "
                    "reason_code, created_at) VALUES (?, ?, 'current_version_changed', ?, "
                    "'active', ?, ?, ?)",
                    (
                        f"event_{uuid.uuid4().hex}",
                        capsule_id,
                        old_status,
                        version_id,
                        reason_code,
                        now,
                    ),
                )
                updated = connection.execute(
                    "UPDATE review_items SET candidate_status = 'published', "
                    "candidate_canonical_hash = ?, sanitized_candidate_json = ?, updated_at = ? "
                    "WHERE review_id = ? AND candidate_status = 'publishable' AND decision IS ?",
                    (
                        artifact.canonical_hash,
                        _json(review_summary),
                        now,
                        prepared.review["review_id"],
                        decision,
                    ),
                )
                if updated.rowcount != 1:
                    raise Stage3Error("review_decision_conflict")
                for follower in followers:
                    connection.execute(
                        "UPDATE review_items SET candidate_status = 'duplicate', "
                        "retained_version_id = ?, updated_at = ? WHERE review_id = ?",
                        (version_id, now, follower["review_id"]),
                    )
                if disable_capsule_id is not None:
                    if disable_capsule_id == capsule_id:
                        raise Stage3Error("semantic_split_identity_unchanged")
                    previous = connection.execute(
                        "SELECT status, current_version_id, capability_kind FROM capsules "
                        "WHERE capsule_id = ?",
                        (disable_capsule_id,),
                    ).fetchone()
                    if (
                        previous is None
                        or previous["status"] != "active"
                        or previous["current_version_id"] != disable_version_id
                        or previous["capability_kind"] != payload["capability_kind"]
                    ):
                        raise Stage3Error("semantic_split_target_invalid")
                    disabled = connection.execute(
                        "UPDATE capsules SET status = 'disabled' WHERE capsule_id = ? "
                        "AND status = 'active' AND current_version_id = ?",
                        (disable_capsule_id, disable_version_id),
                    )
                    if disabled.rowcount != 1:
                        raise Stage3Error("semantic_split_target_invalid")
                    connection.execute(
                        "INSERT INTO capsule_status_events "
                        "(event_id, capsule_id, event_type, from_status, to_status, version_id, "
                        "reason_code, created_at) VALUES (?, ?, 'disabled', ?, 'disabled', ?, "
                        "'semantic_split', ?)",
                        (
                            f"event_{uuid.uuid4().hex}",
                            disable_capsule_id,
                            previous["status"],
                            previous["current_version_id"],
                            now,
                        ),
                    )
                self._sync_run_evidence(connection, str(prepared.review["run_id"]))
                self.store.bump_revision(connection)
        except sqlite3.IntegrityError as exc:
            raise Stage3Error("capsule_publication_integrity_failed") from exc
        return {
            "review_id": prepared.review["review_id"],
            "status": "published",
            "capsule_id": capsule_id,
            "version_id": version_id,
            "version_number": version_number,
            "canonical_hash": artifact.canonical_hash,
        }
