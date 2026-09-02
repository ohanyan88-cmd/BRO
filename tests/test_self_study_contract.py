import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.check_self_study_contract import (
    CONTRACT,
    FORBIDDEN_IN_STUDY,
    INVARIANT_MARKERS,
    STUDY,
    validate,
)

REAL_ROOT = Path(__file__).resolve().parents[1]
COPIED = (
    "contracts/self_study.json",
    "src/bro_runtime/study_runtime.py",
    "src/bro_runtime/learning_memory.py",
    "src/bro_runtime/conversation.py",
    "src/bro_runtime/external_model.py",
    "scripts/bro_interact.py",
)


class SelfStudyContractGateTests(unittest.TestCase):
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

    def test_real_repository_self_study_contract_is_enforced(self):
        self.assertEqual(validate(REAL_ROOT), [])

    def test_synthetic_conforming_tree_passes(self):
        self.assertEqual(validate(self.tree()), [])

    def test_invariant_without_enforcement_mapping_fails_closed(self):
        root = self.tree()
        contract = self.contract(root)
        contract["invariants"].append({
            "id": "STUDY-WISHFUL-001", "statement": "BRO simply studies well",
            "enforcement": ["tests/test_study_runtime.py"],
        })
        self.write(root, contract)
        self.assertTrue(any("no executable enforcement mapping" in e for e in validate(root)))

    def test_losing_source_quote_verification_fails_closed(self):
        root = self.tree()
        path = root / STUDY
        text = path.read_text(encoding="utf-8")
        self.assertIn("def quote_is_in_source", text)
        path.write_text(text.replace("def quote_is_in_source", "def quote_is_anywhere"), encoding="utf-8")
        self.assertTrue(any("STUDY-VERIFY-001" in e for e in validate(root)))

    def test_a_network_client_in_the_study_runtime_fails_closed(self):
        root = self.tree()
        path = root / STUDY
        path.write_text(path.read_text(encoding="utf-8") + "\nfrom urllib.request import urlopen\n", encoding="utf-8")
        errors = validate(root)
        self.assertTrue(any("must not be able to act or write" in e for e in errors), errors)

    def test_a_promotion_call_in_the_study_runtime_fails_closed(self):
        root = self.tree()
        path = root / STUDY
        path.write_text(
            path.read_text(encoding="utf-8") + "\ndef go(memory, cid):\n    memory.promote_candidate(cid, promoted_by='bro')\n",
            encoding="utf-8",
        )
        errors = validate(root)
        self.assertTrue(any("promote_candidate" in e for e in errors), errors)

    def test_a_direct_store_write_in_the_study_runtime_fails_closed(self):
        root = self.tree()
        path = root / STUDY
        path.write_text(
            path.read_text(encoding="utf-8") + "\ndef go(c):\n    c.connection.execute('INSERT INTO bro_study_knowledge VALUES (1)')\n",
            encoding="utf-8",
        )
        errors = validate(root)
        self.assertTrue(any("connection.execute" in e or "INSERT INTO" in e for e in errors), errors)

    def test_a_surface_that_stops_studying_fails_closed(self):
        root = self.tree()
        (root / "scripts/bro_interact.py").write_text("# no longer studies\n", encoding="utf-8")
        errors = validate(root)
        self.assertTrue(any("study surface" in e for e in errors), errors)

    def test_dropping_the_authority_disclaimer_fails_closed(self):
        root = self.tree()
        contract = self.contract(root)
        contract["truth_boundary"]["not_claimed"] = ["Correctness of every model-proposed claim"]
        self.write(root, contract)
        errors = validate(root)
        self.assertTrue(any("model-weight training" in e for e in errors), errors)
        self.assertTrue(any("authority" in e for e in errors), errors)

    def test_missing_cycle_declaration_fails_closed(self):
        root = self.tree()
        contract = self.contract(root)
        contract["cycle"] = []
        self.write(root, contract)
        self.assertTrue(any("governed study cycle" in e for e in validate(root)))

    def test_every_mapped_invariant_is_declared_in_the_contract(self):
        declared = {item["id"] for item in json.loads((REAL_ROOT / CONTRACT).read_text(encoding="utf-8"))["invariants"]}
        self.assertEqual(declared, set(INVARIANT_MARKERS))

    def test_the_forbidden_set_covers_acting_writing_and_promoting(self):
        for token in ("urlopen", "subprocess", "promote_candidate", "approve_candidate", "INSERT INTO", "write_text"):
            self.assertIn(token, FORBIDDEN_IN_STUDY)


if __name__ == "__main__":
    unittest.main()
