"""The gate itself: prove it goes red, one control at a time."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.check_knowledge_library_contract import (
    CONTRACT,
    INVARIANT_MARKERS,
    LIBRARY,
    SHELVES,
    STUDY,
    validate,
)

REAL_ROOT = Path(__file__).resolve().parents[1]
COPIED = (
    CONTRACT, SHELVES, LIBRARY,
    "src/bro_runtime/learning_memory.py",
    "src/bro_runtime/study_runtime.py",
    "scripts/bro_acquire_knowledge.py",
    "scripts/bro_interact.py",
)


class KnowledgeLibraryGateTests(unittest.TestCase):
    def tree(self) -> Path:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        for relative in COPIED:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(REAL_ROOT / relative, target)
        for item in self.contract(root)["invariants"]:
            for relative in item["tests"]:
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("# test\n", encoding="utf-8")
        return root

    def contract(self, root: Path) -> dict:
        return json.loads((root / CONTRACT).read_text(encoding="utf-8"))

    def shelves(self, root: Path) -> dict:
        return json.loads((root / SHELVES).read_text(encoding="utf-8"))

    def write(self, root: Path, relative: str, payload: dict) -> None:
        (root / relative).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def test_the_repository_as_it_stands_passes(self):
        self.assertEqual(validate(self.tree()), [])

    def test_an_invariant_whose_marker_left_the_source_is_caught(self):
        root = self.tree()
        source = root / LIBRARY
        source.write_text(source.read_text(encoding="utf-8").replace("def verify_corpus", "def check_files"),
                          encoding="utf-8")
        self.assertTrue(any("LIBRARY-APPROVAL-001" in error for error in validate(root)))

    def test_an_invariant_enforced_in_code_but_dropped_from_the_contract_is_caught(self):
        root = self.tree()
        contract = self.contract(root)
        removed = contract["invariants"].pop()["id"]
        self.write(root, CONTRACT, contract)
        self.assertTrue(any(removed in error and "absent from the contract" in error
                            for error in validate(root)))

    def test_an_invariant_declared_but_enforced_by_nothing_is_caught(self):
        root = self.tree()
        contract = self.contract(root)
        contract["invariants"].append({"id": "LIBRARY-INVENTED-001", "statement": "x",
                                       "tests": ["tests/test_knowledge_library.py"]})
        self.write(root, CONTRACT, contract)
        self.assertTrue(any("enforced by nothing" in error for error in validate(root)))

    def test_an_invariant_naming_a_test_file_that_does_not_exist_is_caught(self):
        root = self.tree()
        contract = self.contract(root)
        contract["invariants"][0]["tests"] = ["tests/test_nothing_at_all.py"]
        self.write(root, CONTRACT, contract)
        self.assertTrue(any("does not exist" in error for error in validate(root)))

    def test_a_library_that_reaches_the_network_is_caught(self):
        root = self.tree()
        source = root / LIBRARY
        source.write_text("import urllib.request\n" + source.read_text(encoding="utf-8"),
                          encoding="utf-8")
        self.assertTrue(any("must not reach the network" in error for error in validate(root)))

    def test_a_study_runtime_that_could_acquire_is_caught(self):
        root = self.tree()
        source = root / STUDY
        source.write_text(source.read_text(encoding="utf-8") + "\n# bro_acquire_knowledge\n",
                          encoding="utf-8")
        self.assertTrue(any("must not acquire anything" in error for error in validate(root)))

    def test_a_missing_shelf_is_caught(self):
        root = self.tree()
        manifest = self.shelves(root)
        manifest["shelves"] = [s for s in manifest["shelves"] if s["shelf"] != "armenian-language"]
        self.write(root, SHELVES, manifest)
        self.assertTrue(any("'armenian-language' is missing" in error for error in validate(root)))

    def test_an_unattributed_shelf_is_caught(self):
        root = self.tree()
        manifest = self.shelves(root)
        manifest["shelves"][0]["publisher"] = ""
        self.write(root, SHELVES, manifest)
        self.assertTrue(any("is missing publisher" in error for error in validate(root)))

    def test_an_unknown_authority_class_is_caught(self):
        root = self.tree()
        manifest = self.shelves(root)
        manifest["shelves"][0]["authority_class"] = "SOMEONES_BLOG"
        self.write(root, SHELVES, manifest)
        self.assertTrue(any("unknown authority class" in error for error in validate(root)))

    def test_an_unsupported_source_language_is_caught(self):
        root = self.tree()
        manifest = self.shelves(root)
        manifest["shelves"][0]["source_language"] = "de"
        self.write(root, SHELVES, manifest)
        self.assertTrue(any("unsupported source language" in error for error in validate(root)))

    def test_a_source_that_is_not_https_is_caught(self):
        root = self.tree()
        manifest = self.shelves(root)
        manifest["shelves"][0]["documents"][0]["url"] = "http://example.invalid/doc"
        self.write(root, SHELVES, manifest)
        self.assertTrue(any("not an https source" in error for error in validate(root)))

    def test_every_marker_the_gate_checks_is_present_in_the_real_tree(self):
        """A marker that drifted would make its invariant unenforceable in silence."""
        for identifier, markers in INVARIANT_MARKERS.items():
            for relative, marker in markers:
                text = (REAL_ROOT / relative).read_text(encoding="utf-8")
                self.assertIn(marker, text, f"{identifier}: {relative} lost {marker!r}")


if __name__ == "__main__":
    unittest.main()
