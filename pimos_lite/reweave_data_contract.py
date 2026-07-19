"""Closed data_contract.v1 helpers for the non-active Reweave intake path."""

from __future__ import annotations

import json
import re
from decimal import Decimal, localcontext
from typing import Any


MAX_DEPTH = 8
MAX_PROPERTIES = 128
MAX_ENUM = 100
MAX_ARRAY_ITEMS = 1000
MAX_STRING_LENGTH = 10000
MAX_SYNTHETIC_FIXTURES = 64
MAX_SAFE_INTEGER = 9_007_199_254_740_991
MAX_SYNTHETIC_NODES = 65_536
MAX_SYNTHETIC_BYTES = 512 * 1024
FORBIDDEN_MEMBER_NAMES = {"__proto__", "prototype", "constructor"}
_DECIMAL = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")


class DataContractError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def normalize_data_contract(contract: dict[str, Any]) -> dict[str, Any]:
    """Validate and canonicalize one data_contract.v1 root."""
    state = {"properties": 0}
    return _normalize_node(contract, depth=0, root=True, state=state)


def contracts_compatible(source: dict[str, Any], target: dict[str, Any]) -> bool:
    """Return whether every source value is accepted by target."""
    return _compatible(normalize_data_contract(source), normalize_data_contract(target))


def normalize_capsule_contracts(
    capability_kind: str,
    input_contract: dict[str, Any],
    output_contract: dict[str, Any],
    error_contract: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if capability_kind not in {"presentation", "interaction", "computation"}:
        raise DataContractError("capability_kind_invalid")
    normalized_input = normalize_data_contract(input_contract)
    if normalized_input["type"] != "object":
        raise DataContractError("capsule_input_root_must_be_object")
    if capability_kind == "presentation":
        if output_contract != {"schema": "no_output.v1"}:
            raise DataContractError("presentation_output_contract_invalid")
        normalized_output = {"schema": "no_output.v1"}
    elif capability_kind == "interaction":
        if type(output_contract) is not dict or set(output_contract) != {"schema", "events"}:
            raise DataContractError("event_outputs_contract_invalid")
        events = output_contract.get("events")
        if (
            output_contract.get("schema") != "event_outputs.v1"
            or type(events) is not dict
            or len(events) != 1
            or any(
                not _valid_member_name(name)
                for name in events
            )
        ):
            raise DataContractError("event_outputs_contract_invalid")
        normalized_events = {
            name: normalize_data_contract(events[name]) for name in sorted(events)
        }
        if any(contract["type"] != "object" for contract in normalized_events.values()):
            raise DataContractError("event_output_root_must_be_object")
        normalized_output = {"schema": "event_outputs.v1", "events": normalized_events}
    else:
        normalized_output = normalize_data_contract(output_contract)
        if normalized_output["type"] != "object":
            raise DataContractError("compute_output_root_must_be_object")
    normalized_error = _normalize_error_contract(error_contract, normalized_input)
    return normalized_input, normalized_output, normalized_error


def data_contract_accepts(contract: dict[str, Any], value: Any) -> bool:
    return _accepts(normalize_data_contract(contract), value)


def generate_synthetic_fixtures(contract: dict[str, Any]) -> dict[str, Any]:
    """Generate bounded synthetic values; callers must pass a redacted contract."""
    normalized = normalize_data_contract(contract)
    _ensure_fixture_shape_budget(normalized)
    normal = _sample(normalized)
    boundaries: list[Any] = []
    invalid: list[dict[str, Any]] = []
    _collect_cases(normalized, normal, "", boundaries, invalid)
    boundary_values = _unique_json(boundaries)[:MAX_SYNTHETIC_FIXTURES]
    invalid_values = _select_invalid(
        invalid,
        _applicable_invalid_families(normalized),
        MAX_SYNTHETIC_FIXTURES,
    )
    if not _accepts(normalized, normal):
        raise DataContractError("synthetic_fixture_generation_failed")
    if any(not _accepts(normalized, item) for item in boundary_values):
        raise DataContractError("synthetic_boundary_generation_failed")
    if any(_accepts(normalized, item["value"]) for item in invalid_values):
        raise DataContractError("synthetic_invalid_generation_failed")
    fixtures = {
        "schema": "synthetic_fixtures.v1",
        "normal": [normal],
        "boundary": boundary_values,
        "invalid": invalid_values,
    }
    _ensure_fixture_payload_budget(fixtures)
    return fixtures


def _normalize_node(
    node: Any,
    *,
    depth: int,
    root: bool,
    state: dict[str, int],
) -> dict[str, Any]:
    if type(node) is not dict:
        raise DataContractError("data_contract_node_not_object")
    if depth > MAX_DEPTH:
        raise DataContractError("data_contract_depth_exceeded")
    schema = node.get("schema")
    if root and schema != "data_contract.v1":
        raise DataContractError("data_contract_schema_invalid")
    if not root and "schema" in node:
        raise DataContractError("nested_data_contract_schema_forbidden")
    kind = node.get("type")
    if kind not in {"object", "array", "string", "boolean", "integer", "decimal"}:
        raise DataContractError("data_contract_type_invalid")

    prefix = {"schema": "data_contract.v1"} if root else {}
    if kind == "object":
        _only_keys(
            node,
            {"schema", "type", "properties", "required", "additional_properties"}
            if root
            else {"type", "properties", "required", "additional_properties"},
        )
        properties = node.get("properties")
        required = node.get("required")
        if type(properties) is not dict or any(
            not _valid_member_name(name)
            for name in properties
        ):
            raise DataContractError("object_properties_invalid")
        if type(required) is not list or any(type(name) is not str for name in required):
            raise DataContractError("object_required_invalid")
        if node.get("additional_properties") is not False:
            raise DataContractError("additional_properties_must_be_false")
        if len(required) != len(set(required)) or not set(required) <= set(properties):
            raise DataContractError("object_required_not_properties_subset")
        state["properties"] += len(properties)
        if state["properties"] > MAX_PROPERTIES:
            raise DataContractError("data_contract_properties_exceeded")
        normalized_properties = {
            name: _normalize_node(
                properties[name], depth=depth + 1, root=False, state=state
            )
            for name in sorted(properties)
        }
        return {
            **prefix,
            "type": "object",
            "properties": normalized_properties,
            "required": sorted(required),
            "additional_properties": False,
        }

    if kind == "array":
        _only_keys(
            node,
            {"schema", "type", "items", "min_items", "max_items"}
            if root
            else {"type", "items", "min_items", "max_items"},
        )
        minimum = _bounded_int(node.get("min_items", 0), 0, MAX_ARRAY_ITEMS, "array_min")
        maximum = _bounded_int(node.get("max_items"), 0, MAX_ARRAY_ITEMS, "array_max")
        if minimum > maximum:
            raise DataContractError("array_range_invalid")
        return {
            **prefix,
            "type": "array",
            "items": _normalize_node(
                node.get("items"), depth=depth + 1, root=False, state=state
            ),
            "min_items": minimum,
            "max_items": maximum,
        }

    if kind == "string":
        _only_keys(
            node,
            {"schema", "type", "min_length", "max_length", "enum"}
            if root
            else {"type", "min_length", "max_length", "enum"},
        )
        minimum = _bounded_int(node.get("min_length", 0), 0, MAX_STRING_LENGTH, "string_min")
        maximum = _bounded_int(node.get("max_length"), 0, MAX_STRING_LENGTH, "string_max")
        if minimum > maximum:
            raise DataContractError("string_range_invalid")
        result: dict[str, Any] = {
            **prefix,
            "type": "string",
            "min_length": minimum,
            "max_length": maximum,
        }
        if "enum" in node:
            result["enum"] = _normalize_enum(
                node["enum"], "string", minimum=minimum, maximum=maximum
            )
        return result

    if kind == "boolean":
        _only_keys(node, {"schema", "type"} if root else {"type"})
        return {**prefix, "type": "boolean"}

    if kind == "integer":
        _only_keys(
            node,
            {"schema", "type", "minimum", "maximum", "enum"}
            if root
            else {"type", "minimum", "maximum", "enum"},
        )
        minimum = _strict_int(node.get("minimum"), "integer_minimum_invalid")
        maximum = _strict_int(node.get("maximum"), "integer_maximum_invalid")
        if minimum > maximum:
            raise DataContractError("integer_range_invalid")
        result = {**prefix, "type": "integer", "minimum": minimum, "maximum": maximum}
        if "enum" in node:
            result["enum"] = _normalize_enum(
                node["enum"], "integer", minimum=minimum, maximum=maximum
            )
        return result

    _only_keys(
        node,
        {"schema", "type", "minimum", "maximum", "max_scale", "enum"}
        if root
        else {"type", "minimum", "maximum", "max_scale", "enum"},
    )
    minimum = canonical_decimal(node.get("minimum"))
    maximum = canonical_decimal(node.get("maximum"))
    scale = _bounded_int(node.get("max_scale"), 0, 18, "decimal_scale")
    if Decimal(minimum) > Decimal(maximum):
        raise DataContractError("decimal_range_invalid")
    if _scale(minimum) > scale or _scale(maximum) > scale:
        raise DataContractError("decimal_bound_scale_exceeded")
    result = {
        **prefix,
        "type": "decimal",
        "minimum": minimum,
        "maximum": maximum,
        "max_scale": scale,
    }
    if "enum" in node:
        result["enum"] = _normalize_enum(
            node["enum"], "decimal", minimum=minimum, maximum=maximum, scale=scale
        )
    return result


def canonical_decimal(value: Any) -> str:
    if type(value) is not str or not _DECIMAL.fullmatch(value):
        raise DataContractError("decimal_value_invalid")
    if value.startswith("-") and Decimal(value) == 0:
        raise DataContractError("decimal_negative_zero_forbidden")
    unsigned = value[1:] if value.startswith("-") else value
    integer = unsigned.split(".", 1)[0]
    if len(integer) > 18:
        raise DataContractError("decimal_integer_digits_exceeded")
    normalized = format(Decimal(value), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    if Decimal(normalized) == 0:
        return "0"
    return normalized


def _normalize_error_contract(
    contract: Any, input_contract: dict[str, Any]
) -> dict[str, Any]:
    if type(contract) is not dict or set(contract) != {"schema", "errors"}:
        raise DataContractError("error_contract_invalid")
    errors = contract.get("errors")
    if (
        contract.get("schema") != "error_contract.v1"
        or type(errors) is not dict
        or any(
            not _valid_member_name(code)
            for code in errors
        )
    ):
        raise DataContractError("error_contract_invalid")
    normalized: dict[str, Any] = {}
    for code in sorted(errors):
        row = errors[code]
        if type(row) is not dict or set(row) != {"field", "details"}:
            raise DataContractError("error_contract_entry_invalid")
        field = row.get("field")
        if field is not None and (
            type(field) is not str or field not in input_contract["properties"]
        ):
            raise DataContractError("error_contract_field_invalid")
        details = normalize_data_contract(row.get("details"))
        if details["type"] != "object":
            raise DataContractError("error_details_root_must_be_object")
        normalized[code] = {"field": field, "details": details}
    return {"schema": "error_contract.v1", "errors": normalized}


def _normalize_enum(
    values: Any,
    kind: str,
    *,
    minimum: Any,
    maximum: Any,
    scale: int | None = None,
) -> list[Any]:
    if type(values) is not list or not values or len(values) > MAX_ENUM:
        raise DataContractError("enum_invalid")
    normalized: list[Any] = []
    for value in values:
        if kind == "string":
            if (
                type(value) is not str
                or not _is_utf8(value)
                or not minimum <= _utf16_length(value) <= maximum
            ):
                raise DataContractError("string_enum_value_invalid")
            item = value
        elif kind == "integer":
            item = _strict_int(value, "integer_enum_value_invalid")
            if not minimum <= item <= maximum:
                raise DataContractError("integer_enum_value_invalid")
        else:
            item = canonical_decimal(value)
            if not Decimal(minimum) <= Decimal(item) <= Decimal(maximum):
                raise DataContractError("decimal_enum_value_invalid")
            if scale is None or _scale(item) > scale:
                raise DataContractError("decimal_enum_scale_exceeded")
        normalized.append(item)
    return sorted(set(normalized), key=Decimal if kind == "decimal" else None)


def _only_keys(node: dict[str, Any], allowed: set[str]) -> None:
    if set(node) - allowed:
        raise DataContractError("data_contract_keyword_forbidden")


def _valid_member_name(value: Any) -> bool:
    return (
        type(value) is str
        and bool(value)
        and value not in FORBIDDEN_MEMBER_NAMES
        and _is_utf8(value)
        and not any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
    )


def _is_utf8(value: str) -> bool:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _strict_int(value: Any, code: str) -> int:
    if type(value) is not int or not -MAX_SAFE_INTEGER <= value <= MAX_SAFE_INTEGER:
        raise DataContractError(code)
    return value


def _bounded_int(value: Any, minimum: int, maximum: int, code: str) -> int:
    value = _strict_int(value, f"{code}_invalid")
    if not minimum <= value <= maximum:
        raise DataContractError(f"{code}_out_of_range")
    return value


def _scale(value: str) -> int:
    return len(value.split(".", 1)[1]) if "." in value else 0


def _compatible(source: dict[str, Any], target: dict[str, Any]) -> bool:
    if source["type"] != target["type"]:
        return False
    if "enum" in target:
        if "enum" not in source or not set(source["enum"]) <= set(target["enum"]):
            return False
    kind = source["type"]
    if kind == "object":
        source_properties = source["properties"]
        target_properties = target["properties"]
        if not set(source_properties) <= set(target_properties):
            return False
        if not set(target["required"]) <= set(source["required"]):
            return False
        return all(
            _compatible(value, target_properties[name])
            for name, value in source_properties.items()
        )
    if kind == "array":
        return (
            source["min_items"] >= target["min_items"]
            and source["max_items"] <= target["max_items"]
            and _compatible(source["items"], target["items"])
        )
    if kind == "string":
        return (
            source["min_length"] >= target["min_length"]
            and source["max_length"] <= target["max_length"]
        )
    if kind == "integer":
        return source["minimum"] >= target["minimum"] and source["maximum"] <= target["maximum"]
    if kind == "decimal":
        return (
            Decimal(source["minimum"]) >= Decimal(target["minimum"])
            and Decimal(source["maximum"]) <= Decimal(target["maximum"])
            and source["max_scale"] <= target["max_scale"]
        )
    return True


def _accepts(contract: dict[str, Any], value: Any) -> bool:
    if "enum" in contract and value not in contract["enum"]:
        return False
    kind = contract["type"]
    if kind == "object":
        if type(value) is not dict or not set(value) <= set(contract["properties"]):
            return False
        if not set(contract["required"]) <= set(value):
            return False
        return all(_accepts(contract["properties"][key], item) for key, item in value.items())
    if kind == "array":
        return (
            type(value) is list
            and contract["min_items"] <= len(value) <= contract["max_items"]
            and all(_accepts(contract["items"], item) for item in value)
        )
    if kind == "string":
        return (
            type(value) is str
            and _is_utf8(value)
            and contract["min_length"] <= _utf16_length(value) <= contract["max_length"]
        )
    if kind == "boolean":
        return type(value) is bool
    if kind == "integer":
        return (
            type(value) is int
            and -MAX_SAFE_INTEGER <= value <= MAX_SAFE_INTEGER
            and contract["minimum"] <= value <= contract["maximum"]
        )
    if type(value) is not str:
        return False
    try:
        canonical = canonical_decimal(value)
    except DataContractError:
        return False
    return (
        canonical == value
        and Decimal(contract["minimum"]) <= Decimal(value) <= Decimal(contract["maximum"])
        and _scale(value) <= contract["max_scale"]
    )


def _sample(contract: dict[str, Any], boundary: str | None = None) -> Any:
    if contract.get("enum"):
        return contract["enum"][0 if boundary != "maximum" else -1]
    kind = contract["type"]
    if kind == "object":
        return {
            name: _sample(child)
            for name, child in contract["properties"].items()
            if name in contract["required"]
        }
    if kind == "array":
        length = contract["min_items"]
        if boundary == "maximum":
            length = contract["max_items"]
        elif boundary is None and length == 0 and contract["max_items"] > 0:
            length = 1
        return [_sample(contract["items"]) for _ in range(length)]
    if kind == "string":
        length = contract["min_length"]
        if boundary == "maximum":
            length = contract["max_length"]
        elif boundary is None:
            length = min(contract["max_length"], max(contract["min_length"], 6))
        return "x" * length
    if kind == "boolean":
        return False if boundary != "maximum" else True
    if kind == "integer":
        return contract["maximum"] if boundary == "maximum" else contract["minimum"]
    return contract["maximum"] if boundary == "maximum" else contract["minimum"]


def _collect_cases(
    contract: dict[str, Any],
    normal: Any,
    path: str,
    boundaries: list[Any],
    invalid: list[dict[str, Any]],
) -> None:
    kind = contract["type"]
    if kind == "object":
        for name in contract["required"]:
            value = dict(normal)
            value.pop(name, None)
            invalid.append({"reason": f"missing_required:{path}{name}", "value": value})
        extra = dict(normal)
        extra["__unexpected__"] = True
        invalid.append({"reason": f"additional_property:{path}", "value": extra})
        for name, child in contract["properties"].items():
            base = dict(normal)
            base[name] = _sample(child, "minimum")
            boundaries.append(base)
            other = dict(normal)
            other[name] = _sample(child, "maximum")
            boundaries.append(other)
            child_boundaries: list[Any] = []
            child_invalid: list[dict[str, Any]] = []
            _collect_cases(child, _sample(child), f"{path}{name}.", child_boundaries, child_invalid)
            for item in child_boundaries:
                value = dict(normal)
                value[name] = item
                boundaries.append(value)
            for item in child_invalid:
                value = dict(normal)
                value[name] = item["value"]
                invalid.append({"reason": item["reason"], "value": value})
        invalid.append({"reason": f"wrong_type:{path}", "value": None})
        return
    if kind == "array":
        boundaries.extend([_sample(contract, "minimum"), _sample(contract, "maximum")])
        if contract["min_items"] > 0:
            invalid.append({"reason": f"array_too_short:{path}", "value": []})
        invalid.append(
            {
                "reason": f"array_too_long:{path}",
                "value": [_sample(contract["items"])] * (contract["max_items"] + 1),
            }
        )
        if contract["max_items"] > 0:
            base = _sample(contract)
            child_boundaries: list[Any] = []
            child_invalid: list[dict[str, Any]] = []
            _collect_cases(
                contract["items"],
                _sample(contract["items"]),
                f"{path}[].",
                child_boundaries,
                child_invalid,
            )
            for item in child_boundaries:
                value = list(base)
                value[0] = item
                boundaries.append(value)
            for item in child_invalid:
                value = list(base)
                value[0] = item["value"]
                invalid.append({"reason": item["reason"], "value": value})
        invalid.append({"reason": f"wrong_type:{path}", "value": None})
        return
    if contract.get("enum"):
        boundaries.extend([contract["enum"][0], contract["enum"][-1]])
        invalid.append({"reason": f"enum_value:{path}", "value": None})
        return
    if kind == "string":
        boundaries.extend([_sample(contract, "minimum"), _sample(contract, "maximum")])
        if contract["min_length"] > 0:
            invalid.append({"reason": f"string_too_short:{path}", "value": ""})
        invalid.append({"reason": f"string_too_long:{path}", "value": "x" * (contract["max_length"] + 1)})
    elif kind == "integer":
        boundaries.extend([contract["minimum"], contract["maximum"]])
        invalid.append(
            {"reason": f"integer_below:{path}", "value": contract["minimum"] - 1}
        )
        invalid.append(
            {"reason": f"integer_above:{path}", "value": contract["maximum"] + 1}
        )
    elif kind == "decimal":
        boundaries.extend([contract["minimum"], contract["maximum"]])
        with localcontext() as context:
            context.prec = 64
            quantum = Decimal(1).scaleb(-contract["max_scale"])
            below = Decimal(contract["minimum"]) - quantum
            above = Decimal(contract["maximum"]) + quantum
            over_scale = Decimal(contract["minimum"]) + Decimal(1).scaleb(
                -(contract["max_scale"] + 1)
            )
        invalid.extend(
            [
                {
                    "reason": f"decimal_below:{path}",
                    "value": format(below, "f"),
                },
                {
                    "reason": f"decimal_above:{path}",
                    "value": format(above, "f"),
                },
            ]
        )
        sample = _sample(contract)
        invalid.append(
            {
                "reason": f"decimal_noncanonical:{path}",
                "value": f"{sample}0" if "." in sample else f"{sample}.0",
            }
        )
        if Decimal(contract["minimum"]) < Decimal(contract["maximum"]):
            invalid.append(
                {
                    "reason": f"decimal_scale:{path}",
                    "value": format(over_scale, "f"),
                }
            )
    elif kind == "boolean":
        boundaries.extend([False, True])
        invalid.append({"reason": f"boolean_type:{path}", "value": 0})
    invalid.append({"reason": f"wrong_type:{path}", "value": None})


def _unique_json(values: list[Any]) -> list[Any]:
    seen: set[str] = set()
    result: list[Any] = []
    for value in values:
        key = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _unique_invalid(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for value in values:
        key = f"{value['reason']}:{json.dumps(value['value'], ensure_ascii=False, sort_keys=True, separators=(',', ':'))}"
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _applicable_invalid_families(contract: dict[str, Any]) -> set[str]:
    if contract.get("enum"):
        return {"enum_value"}
    kind = contract["type"]
    if kind == "object":
        families = {"additional_property", "wrong_type"}
        if contract["required"]:
            families.add("missing_required")
        for child in contract["properties"].values():
            families.update(_applicable_invalid_families(child))
        return families
    if kind == "array":
        families = {"array_too_long", "wrong_type"}
        if contract["min_items"] > 0:
            families.add("array_too_short")
        if contract["max_items"] > 0:
            families.update(_applicable_invalid_families(contract["items"]))
        return families
    if kind == "string":
        families = {"string_too_long", "wrong_type"}
        if contract["min_length"] > 0:
            families.add("string_too_short")
        return families
    if kind == "integer":
        return {"integer_below", "integer_above", "wrong_type"}
    if kind == "decimal":
        families = {
            "decimal_below",
            "decimal_above",
            "decimal_noncanonical",
            "wrong_type",
        }
        if Decimal(contract["minimum"]) < Decimal(contract["maximum"]):
            families.add("decimal_scale")
        return families
    return {"boolean_type", "wrong_type"}


def _select_invalid(
    values: list[dict[str, Any]], expected: set[str], limit: int
) -> list[dict[str, Any]]:
    unique = _unique_invalid(values)
    by_family: dict[str, dict[str, Any]] = {}
    for item in unique:
        family = str(item["reason"]).split(":", 1)[0]
        by_family.setdefault(family, item)
    if set(by_family) != expected:
        raise DataContractError("synthetic_invalid_coverage_failed")
    if len(by_family) > limit:
        raise DataContractError("synthetic_invalid_budget_exceeded")

    selected = list(by_family.values())
    selected_ids = {id(item) for item in selected}
    for item in unique:
        if len(selected) >= limit:
            break
        if id(item) not in selected_ids:
            selected.append(item)
    return selected


def _utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le", errors="surrogatepass")) // 2


def _ensure_fixture_shape_budget(contract: dict[str, Any]) -> None:
    nodes, size = _maximum_fixture_shape(contract)
    if nodes > MAX_SYNTHETIC_NODES:
        raise DataContractError("synthetic_fixture_node_budget_exceeded")
    if size > MAX_SYNTHETIC_BYTES:
        raise DataContractError("synthetic_fixture_byte_budget_exceeded")


def _maximum_fixture_shape(contract: dict[str, Any]) -> tuple[int, int]:
    kind = contract["type"]
    if kind == "object":
        children = [
            (name, _maximum_fixture_shape(child))
            for name, child in contract["properties"].items()
        ]
        nodes = 1 + sum(child_nodes for _, (child_nodes, _) in children)
        size = 2 + max(0, len(children) - 1)
        size += sum(
            len(json.dumps(name, ensure_ascii=False).encode("utf-8")) + 1 + child_size
            for name, (_, child_size) in children
        )
        return nodes, size
    if kind == "array":
        child_nodes, child_size = _maximum_fixture_shape(contract["items"])
        length = contract["max_items"] + 1
        return 1 + length * child_nodes, 2 + max(0, length - 1) + length * child_size
    if kind == "string":
        enum = contract.get("enum")
        if enum:
            size = max(
                len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
                for value in enum
            )
        else:
            size = contract["max_length"] + 3
        return 1, size
    if kind == "boolean":
        return 1, 5
    if kind == "integer":
        return 1, max(len(str(contract["minimum"])), len(str(contract["maximum"])))
    return 1, max(len(contract["minimum"]), len(contract["maximum"])) + 2


def _ensure_fixture_payload_budget(fixtures: dict[str, Any]) -> None:
    nodes = 0
    stack: list[Any] = [fixtures]
    while stack:
        value = stack.pop()
        nodes += 1
        if nodes > MAX_SYNTHETIC_NODES:
            raise DataContractError("synthetic_fixture_node_budget_exceeded")
        if type(value) is dict:
            stack.extend(value.values())
        elif type(value) is list:
            stack.extend(value)
    try:
        size = len(
            json.dumps(
                fixtures,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
    except UnicodeEncodeError as exc:
        raise DataContractError("synthetic_fixture_utf8_invalid") from exc
    if size > MAX_SYNTHETIC_BYTES:
        raise DataContractError("synthetic_fixture_byte_budget_exceeded")
