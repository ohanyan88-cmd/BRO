import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.check_learning_contract import (
    BOUNDARY,
    CONTRACT,
    GATE,
    INVARIANT_MARKERS,
    LESSON_WRITERS,
    MEMORY,
    SCAN_EXEMPT,
    validate,
)

REAL_ROOT = Path(__file__).resolve().parents[1]
COPIED = (
    "contracts/learning_memory.json",
    "contracts/learning_memory_readiness.json",
    "src/bro_runtime/learning_boundary.py",
    "src/bro_runtime/learning_memory.py",
    "src/bro_runtime/conversation.py",
    "src/bro_runtime/final_delivery.py",
    "src/bro_runtime/external_model.py",
    "scripts/bro_interact.py",
    "scripts/run_production_intelligent_acceptance.py",
)


class LearningContractGateTests(unittest.TestCase):
    def tree(self) -> Path:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        for relative in COPIED:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(REAL_ROOT / relative, target)
        (root / "tests").mkdir(exist_ok=True)
        for item in json.loads((REAL_ROOT / CONTRACT).read_text(encoding="utf-8"))["invariants"]:
            for relative in item["enforcement"]:
                (root / relative).write_text("# enforcement\n", encoding="utf-8")
        return root

    def contract(self, root: Path) -> dict:
        return json.loads((root / CONTRACT).read_text(encoding="utf-8"))

    def write(self, root: Path, contract: dict) -> None:
        (root / CONTRACT).write_text(json.dumps(contract), encoding="utf-8")

    def test_real_repository_learning_contract_is_enforced(self):
        self.assertEqual(validate(REAL_ROOT), [])

    def test_synthetic_conforming_tree_passes(self):
        self.assertEqual(validate(self.tree()), [])

    def test_invariant_without_enforcement_mapping_fails_closed(self):
        root = self.tree()
        contract = self.contract(root)
        contract["invariants"].append({
            "id": "LEARN-WISHFUL-001", "statement": "BRO simply learns well",
            "enforcement": ["tests/test_learning_boundary.py"],
        })
        self.write(root, contract)
        errors = validate(root)
        self.assertTrue(any("no executable enforcement mapping" in e for e in errors), errors)

    def test_invariant_without_a_test_file_fails_closed(self):
        root = self.tree()
        contract = self.contract(root)
        contract["invariants"][0]["enforcement"] = ["tests/test_does_not_exist.py"]
        self.write(root, contract)
        errors = validate(root)
        self.assertTrue(any("missing enforcement file" in e for e in errors), errors)

    def test_lost_evidence_marker_fails_closed(self):
        root = self.tree()
        path = root / BOUNDARY
        text = path.read_text(encoding="utf-8")
        self.assertIn("EXTERNAL_ASSURANCE", text)
        path.write_text(text.replace("EXTERNAL_ASSURANCE", "ANY_ASSURANCE"), encoding="utf-8")
        errors = validate(root)
        self.assertTrue(any("LEARN-EVIDENCE-001" in e for e in errors), errors)

    def test_model_owning_the_pattern_key_fails_closed(self):
        root = self.tree()
        path = root / BOUNDARY
        marker = 'proposed["pattern_key"] = self.pattern_key(context, receipt)'
        text = path.read_text(encoding="utf-8")
        self.assertIn(marker, text)
        path.write_text(text.replace(marker, "pass"), encoding="utf-8")
        errors = validate(root)
        self.assertTrue(any("LEARN-MODEL-001" in e for e in errors), errors)

    def test_a_second_learning_authority_fails_closed(self):
        root = self.tree()
        (root / "src/bro_runtime/rogue_learner.py").write_text(
            "def go(memory):\n    memory.record_outcome(request='x', success=True, learning={'a': 1})\n",
            encoding="utf-8",
        )
        errors = validate(root)
        self.assertTrue(any("outside the governed learning boundary" in e for e in errors), errors)

    def test_a_declared_submitter_that_stops_submitting_fails_closed(self):
        root = self.tree()
        path = root / "scripts/run_production_intelligent_acceptance.py"
        path.write_text("# no longer submits anything\n", encoding="utf-8")
        errors = validate(root)
        self.assertTrue(any("declared as a learning submitter" in e for e in errors), errors)

    def test_dropping_the_training_disclaimer_fails_closed(self):
        root = self.tree()
        contract = self.contract(root)
        contract["truth_boundary"]["not_claimed"] = ["Semantic quality of every model-derived lesson"]
        self.write(root, contract)
        errors = validate(root)
        self.assertTrue(any("model-weight training" in e for e in errors), errors)
        self.assertTrue(any("self-modifying code" in e for e in errors), errors)

    def test_missing_readiness_contract_fails_closed(self):
        root = self.tree()
        (root / "contracts/learning_memory_readiness.json").unlink()
        errors = validate(root)
        self.assertTrue(any("readiness contract" in e for e in errors), errors)

    def test_scan_exemption_is_narrow_and_explicit(self):
        self.assertEqual(SCAN_EXEMPT, LESSON_WRITERS | {GATE})
        self.assertEqual(LESSON_WRITERS, {BOUNDARY, MEMORY})

    def test_every_mapped_invariant_is_declared_in_the_contract(self):
        declared = {item["id"] for item in json.loads((REAL_ROOT / CONTRACT).read_text(encoding="utf-8"))["invariants"]}
        self.assertEqual(declared, set(INVARIANT_MARKERS))


if __name__ == "__main__":
    unittest.main()
