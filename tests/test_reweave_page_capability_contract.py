from __future__ import annotations

import copy
import unittest

from pimos_lite.reweave_page_capability_contract import (
    PAGE_CAPABILITY_CONTRACT_VERSION,
    PAGE_CAPABILITY_DECLARATION_VERSION,
    build_page_capability_declaration_v2,
    build_page_capability_contract_v2,
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
