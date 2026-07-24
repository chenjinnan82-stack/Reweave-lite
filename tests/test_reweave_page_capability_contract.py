from __future__ import annotations

import copy
import unittest

from pimos_lite.reweave_page_capability_contract import (
    FORMAL_CAPSULE_IDENTITY_VERSION,
    PAGE_CAPABILITY_CONTRACT_VERSION,
    PAGE_CAPABILITY_DECLARATION_VERSION,
    build_formal_identity_binding_v2,
    build_page_capability_declaration_v2,
    build_page_capability_contract_v2,
    normalize_page_capability_declaration_v2,
    verify_formal_capsule_identity,
)


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


if __name__ == "__main__":
    unittest.main()
