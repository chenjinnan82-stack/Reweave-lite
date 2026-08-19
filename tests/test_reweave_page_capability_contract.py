from __future__ import annotations

import copy
import unittest

from pimos_lite import reweave_page_capability_contract as page_contract
from pimos_lite.reweave_capsule_store import canonicalize_capsule
from pimos_lite.reweave_page_capability_contract import (
    FORMAL_CAPSULE_IDENTITY_VERSION,
    PAGE_CAPABILITY_CONTRACT_VERSION,
    PAGE_CAPABILITY_DECLARATION_VERSION,
    build_formal_identity_binding_v2,
    build_page_capability_declaration_v2,
    build_page_capability_contract_v2,
    normalize_page_capability_declaration_v2,
    validate_formal_page_contract,
    verify_formal_capsule_identity,
)


def _formal_capsule(kind: str, html: str, css: str = "") -> dict:
    payload = {
        "capability_kind": kind,
        "activation": {},
        "input_contract": {},
        "output_contract": {},
        "error_contract": {},
        "runtime_allowlist": [],
        "dom_scope": {},
        "usage_scope": {},
        "html": html if kind != "computation" else "",
        "css": css if kind != "computation" else "",
        "javascript_modules": [],
        "assets": [],
    }
    canonical = canonicalize_capsule(payload)
    return {
        "capsule_id": f"capsule_{kind}",
        "version_id": f"version_{kind}",
        **canonical.payload,
        "canonical_hash": canonical.sha256,
    }


def _bind(
    capsule: dict,
    elements: list[dict],
) -> dict:
    declaration = build_page_capability_declaration_v2(
        capability_kind=capsule["capability_kind"],
        elements=elements,
    )
    payload = {
        key: capsule[key]
        for key in (
            "capability_kind",
            "activation",
            "input_contract",
            "output_contract",
            "error_contract",
            "runtime_allowlist",
            "dom_scope",
            "usage_scope",
            "html",
            "css",
            "javascript_modules",
            "assets",
        )
    }
    binding = build_formal_identity_binding_v2(
        canonical_payload_digest=canonicalize_capsule(payload).sha256,
        page_capability_declaration=declaration,
    )
    capsule["canonical_hash"] = binding["formal_identity_digest"]
    return {
        "capsule_id": capsule["capsule_id"],
        "version_id": capsule["version_id"],
        "capability_kind": capsule["capability_kind"],
        "canonical_hash": capsule["canonical_hash"],
        "page_capability_declaration": declaration,
    }


class PageCapabilityContractV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.provides = [
            {
                "selector": "[data-action='calculate']",
                "tag": "button",
                "reads": [],
                "writes": [],
                "events": ["click"],
            },
            {
                "selector": "[data-ref='quantity']",
                "tag": "input",
                "reads": ["value"],
                "writes": [],
                "events": [],
            },
            {
                "selector": "[data-ref='total']",
                "tag": "span",
                "reads": [],
                "writes": ["textContent"],
                "events": [],
            },
        ]
        self.requires = copy.deepcopy(self.provides)

    def build(self) -> dict:
        return build_page_capability_contract_v2(
            presentation_provides=self.provides,
            interaction_requires=self.requires,
        )

    def test_contract_is_canonical_and_order_independent(self) -> None:
        contract = self.build()
        reordered = build_page_capability_contract_v2(
            presentation_provides=list(reversed(self.provides)),
            interaction_requires=list(reversed(self.requires)),
        )
        self.assertEqual(PAGE_CAPABILITY_CONTRACT_VERSION, contract["schema_version"])
        self.assertEqual(contract, reordered)
        self.assertEqual(
            contract["canonical_digest"],
            "61e228156f05e4e6439cf3c41c7b49f35265014d8637920e379dd04690d3e663",
        )

    def test_stage3_declarations_are_role_specific_and_canonical(self) -> None:
        presentation = build_page_capability_declaration_v2(
            capability_kind="presentation",
            elements=self.provides,
        )
        interaction = build_page_capability_declaration_v2(
            capability_kind="interaction",
            elements=self.requires,
        )
        self.assertEqual(
            presentation["schema_version"],
            PAGE_CAPABILITY_DECLARATION_VERSION,
        )
        self.assertIn("provides", presentation)
        self.assertNotIn("requires", presentation)
        self.assertIn("requires", interaction)
        self.assertNotIn("provides", interaction)

    def test_formal_identity_binds_payload_and_declaration_digests(self) -> None:
        declaration = build_page_capability_declaration_v2(
            capability_kind="presentation",
            elements=self.provides,
        )
        binding = build_formal_identity_binding_v2(
            canonical_payload_digest="a" * 64,
            page_capability_declaration=declaration,
        )
        self.assertEqual(
            binding["schema_version"],
            FORMAL_CAPSULE_IDENTITY_VERSION,
        )
        self.assertEqual(binding["canonical_payload_digest"], "a" * 64)
        self.assertEqual(
            binding["page_capability_declaration_digest"],
            declaration["canonical_digest"],
        )
        self.assertNotEqual(binding["formal_identity_digest"], "a" * 64)
        summary = {
            "page_capability_declaration": declaration,
            "formal_identity_binding": binding,
        }
        self.assertEqual(
            verify_formal_capsule_identity(
                capability_kind="presentation",
                canonical_payload_digest="a" * 64,
                stored_canonical_hash=binding["formal_identity_digest"],
                extraction_summary=summary,
            ),
            binding,
        )

    def test_v1_v2_identity_matrix_fails_closed(self) -> None:
        payload_digest = "a" * 64
        self.assertIsNone(
            verify_formal_capsule_identity(
                capability_kind="presentation",
                canonical_payload_digest=payload_digest,
                stored_canonical_hash=payload_digest,
                extraction_summary={},
            )
        )
        declaration = build_page_capability_declaration_v2(
            capability_kind="presentation",
            elements=self.provides,
        )
        binding = build_formal_identity_binding_v2(
            canonical_payload_digest=payload_digest,
            page_capability_declaration=declaration,
        )
        invalid = (
            {"page_capability_declaration": declaration},
            {"formal_identity_binding": binding},
            {
                "page_capability_declaration": None,
                "formal_identity_binding": None,
            },
            {
                "page_capability_declaration": declaration,
                "formal_identity_binding": None,
            },
            {
                "page_capability_declaration": declaration,
                "formal_identity_binding": {
                    **binding,
                    "schema_version": "formal_capsule_identity.v999",
                },
            },
        )
        for summary in invalid:
            with self.subTest(summary=summary):
                with self.assertRaisesRegex(
                    ValueError, "formal_capsule_identity_invalid"
                ):
                    verify_formal_capsule_identity(
                        capability_kind="presentation",
                        canonical_payload_digest=payload_digest,
                        stored_canonical_hash=binding["formal_identity_digest"],
                        extraction_summary=summary,
                    )
        with self.assertRaisesRegex(ValueError, "formal_capsule_identity_invalid"):
            verify_formal_capsule_identity(
                capability_kind="presentation",
                canonical_payload_digest=payload_digest,
                stored_canonical_hash=payload_digest,
                extraction_summary={
                    "page_capability_declaration": None,
                    "formal_identity_binding": None,
                },
            )
        with self.assertRaisesRegex(ValueError, "formal_capsule_identity_invalid"):
            verify_formal_capsule_identity(
                capability_kind="computation",
                canonical_payload_digest=payload_digest,
                stored_canonical_hash=binding["formal_identity_digest"],
                extraction_summary={
                    "page_capability_declaration": declaration,
                    "formal_identity_binding": binding,
                },
            )

    def test_declaration_or_binding_tampering_fails_closed(self) -> None:
        declaration = build_page_capability_declaration_v2(
            capability_kind="presentation",
            elements=self.provides,
        )
        tampered = copy.deepcopy(declaration)
        tampered["provides"][0]["events"] = []
        with self.assertRaisesRegex(
            ValueError, "page_capability_declaration_invalid"
        ):
            normalize_page_capability_declaration_v2(tampered)

        binding = build_formal_identity_binding_v2(
            canonical_payload_digest="a" * 64,
            page_capability_declaration=declaration,
        )
        with self.assertRaisesRegex(ValueError, "formal_capsule_identity_invalid"):
            verify_formal_capsule_identity(
                capability_kind="presentation",
                canonical_payload_digest="a" * 64,
                stored_canonical_hash="b" * 64,
                extraction_summary={
                    "page_capability_declaration": declaration,
                    "formal_identity_binding": binding,
                },
            )

    def test_selector_quote_style_is_not_semantic(self) -> None:
        double_quoted = copy.deepcopy(self.requires)
        double_quoted[0]["selector"] = '[data-action="calculate"]'
        contract = build_page_capability_contract_v2(
            presentation_provides=self.provides,
            interaction_requires=double_quoted,
        )
        self.assertEqual(contract, self.build())

    def test_missing_element_fails_closed(self) -> None:
        self.provides = self.provides[1:]
        with self.assertRaisesRegex(ValueError, "page_capability_element_missing"):
            self.build()

    def test_mismatched_element_fails_closed(self) -> None:
        self.provides[0]["tag"] = "a"
        with self.assertRaisesRegex(ValueError, "page_capability_element_mismatch"):
            self.build()

    def test_missing_event_fails_closed(self) -> None:
        self.provides[0]["events"] = []
        with self.assertRaisesRegex(ValueError, "page_capability_event_missing"):
            self.build()

    def test_missing_read_fails_closed(self) -> None:
        self.provides[1]["reads"] = []
        with self.assertRaisesRegex(ValueError, "page_capability_read_missing"):
            self.build()

    def test_missing_write_fails_closed(self) -> None:
        self.provides[2]["writes"] = []
        with self.assertRaisesRegex(ValueError, "page_capability_write_missing"):
            self.build()

    def test_malformed_or_ambiguous_declarations_fail_closed(self) -> None:
        duplicate = copy.deepcopy(self.provides[0])
        self.provides.append(duplicate)
        with self.assertRaisesRegex(ValueError, "page_capability_element_duplicate"):
            self.build()

        self.provides.pop()
        self.requires[0]["events"] = ["dblclick"]
        with self.assertRaisesRegex(ValueError, "page_capability_operations_invalid"):
            self.build()

    def test_formal_page_contract_unifies_v1_and_v2(self) -> None:
        presentation = _formal_capsule(
            "presentation",
            "<main data-ref='page'>presentation</main>",
            "main { color: black; }",
        )
        interaction = _formal_capsule(
            "interaction",
            "<aside data-ref='interaction-only'></aside>",
            "button { cursor: pointer; }",
        )
        computation = _formal_capsule("computation", "")
        projections = [
            _bind(presentation, self.provides),
            _bind(interaction, self.requires),
        ]
        result = validate_formal_page_contract(
            [presentation, interaction, computation],
            projections,
        )
        self.assertEqual(
            set(result),
            {"mode", "provider_identity", "compatibility_digest"},
        )
        self.assertNotIn(
            "validate_formal_page_contract",
            page_contract.__all__,
        )
        self.assertEqual(result["mode"], "v2")
        self.assertEqual(
            result["provider_identity"],
            ("capsule_presentation", "version_presentation"),
        )
        self.assertEqual(
            result,
            validate_formal_page_contract(
                [computation, interaction, presentation],
                list(reversed(copy.deepcopy(projections))),
            ),
        )

        v1_presentation = _formal_capsule(
            "presentation",
            "<main data-ref='page'></main>",
            "main { color: black; }",
        )
        v1_interaction = _formal_capsule(
            "interaction",
            "<main data-ref='page'></main>",
            "main { cursor: default; }",
        )
        v1 = validate_formal_page_contract(
            [v1_presentation, v1_interaction, computation]
        )
        self.assertEqual(v1["mode"], "v1")
        v1_interaction["html"] = "<main data-ref='other'></main>"
        v1_interaction.pop("canonical_hash")
        with self.assertRaisesRegex(ValueError, "product_dom_contract_mismatch"):
            validate_formal_page_contract(
                [v1_presentation, v1_interaction, computation]
            )

    def test_formal_page_contract_v2_failures_are_specific(self) -> None:
        def fixture() -> tuple[list[dict], list[dict]]:
            presentation = _formal_capsule(
                "presentation",
                "<main data-ref='page'></main>",
            )
            interaction = _formal_capsule(
                "interaction",
                "<aside data-ref='interaction-only'></aside>",
            )
            computation = _formal_capsule("computation", "")
            return (
                [presentation, interaction, computation],
                [
                    _bind(presentation, self.provides),
                    _bind(interaction, self.requires),
                ],
            )

        provider_cases = {
            "page_capability_element_missing": self.provides[1:],
            "page_capability_element_mismatch": [
                {**copy.deepcopy(row), "tag": "a"}
                if row["selector"] == "[data-action='calculate']"
                else copy.deepcopy(row)
                for row in self.provides
            ],
            "page_capability_event_missing": [
                {**copy.deepcopy(row), "events": []}
                if row["selector"] == "[data-action='calculate']"
                else copy.deepcopy(row)
                for row in self.provides
            ],
            "page_capability_read_missing": [
                {**copy.deepcopy(row), "reads": []}
                if row["selector"] == "[data-ref='quantity']"
                else copy.deepcopy(row)
                for row in self.provides
            ],
            "page_capability_write_missing": [
                {**copy.deepcopy(row), "writes": []}
                if row["selector"] == "[data-ref='total']"
                else copy.deepcopy(row)
                for row in self.provides
            ],
        }
        for expected, elements in provider_cases.items():
            with self.subTest(expected=expected):
                capsules, projections = fixture()
                projections[0] = _bind(capsules[0], elements)
                with self.assertRaisesRegex(ValueError, expected):
                    validate_formal_page_contract(capsules, projections)

        capsules, projections = fixture()
        with self.assertRaisesRegex(
            ValueError, "formal_page_contract_version_mismatch"
        ):
            validate_formal_page_contract(capsules, projections[:1])

        interaction_only = [capsules[1], capsules[2]]
        with self.assertRaisesRegex(
            ValueError, "formal_page_contract_provider_missing"
        ):
            validate_formal_page_contract(interaction_only, projections[1:])

        tampered = copy.deepcopy(projections)
        tampered[0]["canonical_hash"] = "f" * 64
        with self.assertRaisesRegex(
            ValueError, "formal_page_contract_identity_invalid"
        ):
            validate_formal_page_contract(capsules, tampered)

        computation_projection = {
            **copy.deepcopy(projections[0]),
            "capsule_id": capsules[2]["capsule_id"],
            "version_id": capsules[2]["version_id"],
            "capability_kind": "computation",
            "canonical_hash": capsules[2]["canonical_hash"],
        }
        with self.assertRaisesRegex(
            ValueError, "formal_page_contract_identity_invalid"
        ):
            validate_formal_page_contract(capsules, [computation_projection])

        presentation = _formal_capsule(
            "presentation",
            "<main data-ref='page'></main>",
        )
        projection = _bind(presentation, self.provides)
        self.assertEqual(
            validate_formal_page_contract([presentation], [projection])["mode"],
            "v2",
        )

    def test_formal_page_contract_rejects_noncanonical_payloads(self) -> None:
        presentation = _formal_capsule(
            "presentation",
            "<main data-ref='page'></main>",
        )
        presentation["runtime_allowlist"] = ["scoped_ui_update", "scoped_ui_update"]
        presentation.pop("canonical_hash")
        with self.assertRaisesRegex(
            ValueError,
            "formal_page_contract_identity_invalid",
        ):
            validate_formal_page_contract([presentation])


if __name__ == "__main__":
    unittest.main()
