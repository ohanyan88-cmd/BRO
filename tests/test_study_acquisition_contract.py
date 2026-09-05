"""The acquisition gate itself: prove each control goes red when it is removed."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.check_study_acquisition_contract import (
    ACQUISITION,
    CONTRACT,
    INVARIANT_MARKERS,
    POLICY,
    STUDY,
    validate,
)

REAL_ROOT = Path(__file__).resolve().parents[1]
COPIED = (CONTRACT, POLICY, ACQUISITION, "src/bro_runtime/source_policy.py", STUDY,
          "src/bro_runtime/knowledge_library.py", "scripts/bro_interact.py")


class AcquisitionGateTests(unittest.TestCase):
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

    def contract(self, root):
        return json.loads((root / CONTRACT).read_text(encoding="utf-8"))

    def policy(self, root):
        return json.loads((root / POLICY).read_text(encoding="utf-8"))

    def write(self, root, relative, payload):
        (root / relative).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def test_the_repository_as_it_stands_passes(self):
        self.assertEqual(validate(self.tree()), [])

    def test_a_study_runtime_that_reaches_the_network_is_caught(self):
        root = self.tree()
        source = root / STUDY
        source.write_text("import urllib.request\n" + source.read_text(encoding="utf-8"),
                          encoding="utf-8")
        self.assertTrue(any("must not reach the network" in e for e in validate(root)))

    def test_a_study_runtime_that_imports_the_acquisition_module_is_caught(self):
        root = self.tree()
        source = root / STUDY
        source.write_text(source.read_text(encoding="utf-8") + "\n# study_acquisition\n",
                          encoding="utf-8")
        self.assertTrue(any("must not reach the network" in e for e in validate(root)))

    def test_a_mutating_verb_in_acquisition_is_caught(self):
        root = self.tree()
        source = root / ACQUISITION
        source.write_text(source.read_text(encoding="utf-8").replace(
            'method="GET"', 'method="POST"'), encoding="utf-8")
        errors = validate(root)
        self.assertTrue(any("must stay read-only" in e for e in errors))
        self.assertTrue(any("exactly one request verb" in e for e in errors))

    def test_a_second_request_verb_is_caught(self):
        root = self.tree()
        source = root / ACQUISITION
        source.write_text(source.read_text(encoding="utf-8") + '\nEXTRA = dict(method="GET")\n',
                          encoding="utf-8")
        self.assertTrue(any("exactly one request verb" in e for e in validate(root)))

    def test_an_invariant_whose_marker_left_the_source_is_caught(self):
        root = self.tree()
        source = root / ACQUISITION
        source.write_text(source.read_text(encoding="utf-8").replace(
            "def resolve_public_addresses", "def resolve_addresses"), encoding="utf-8")
        self.assertTrue(any("ACQ-SSRF-001" in e for e in validate(root)))

    def test_an_invariant_dropped_from_the_contract_is_caught(self):
        root = self.tree()
        contract = self.contract(root)
        removed = contract["invariants"].pop()["id"]
        self.write(root, CONTRACT, contract)
        self.assertTrue(any(removed in e and "absent from the contract" in e
                            for e in validate(root)))

    def test_a_tier_d_that_could_testify_is_caught(self):
        root = self.tree()
        policy = self.policy(root)
        policy["tiers"]["D"]["may_produce_verified_knowledge"] = True
        self.write(root, POLICY, policy)
        self.assertTrue(any("tier D must never produce verified knowledge" in e
                            for e in validate(root)))

    def test_an_auto_admitting_unclassified_tier_is_caught(self):
        root = self.tree()
        policy = self.policy(root)
        policy["tiers"]["UNCLASSIFIED"]["auto_admit"] = True
        self.write(root, POLICY, policy)
        self.assertTrue(any("never be admitted automatically" in e for e in validate(root)))

    def test_a_family_with_no_hosts_is_caught(self):
        root = self.tree()
        policy = self.policy(root)
        policy["families"][0]["hosts"] = []
        self.write(root, POLICY, policy)
        self.assertTrue(any("is missing hosts" in e for e in validate(root)))

    def test_an_entry_point_on_an_unclaimed_host_is_caught(self):
        root = self.tree()
        policy = self.policy(root)
        policy["families"][0]["entry_points"] = ["https://elsewhere.example/index"]
        self.write(root, POLICY, policy)
        self.assertTrue(any("does not claim" in e for e in validate(root)))

    def test_a_host_claimed_by_two_families_is_caught(self):
        root = self.tree()
        policy = self.policy(root)
        policy["families"][1]["hosts"].append(policy["families"][0]["hosts"][0])
        self.write(root, POLICY, policy)
        self.assertTrue(any("more than one family" in e for e in validate(root)))

    def test_a_denied_host_that_a_family_also_claims_is_caught(self):
        root = self.tree()
        policy = self.policy(root)
        policy["denied_hosts"].append(policy["families"][0]["hosts"][0])
        self.write(root, POLICY, policy)
        self.assertTrue(any("both denied and claimed" in e for e in validate(root)))

    def test_every_marker_the_gate_checks_exists_in_the_real_tree(self):
        for identifier, markers in INVARIANT_MARKERS.items():
            for relative, marker in markers:
                text = (REAL_ROOT / relative).read_text(encoding="utf-8")
                self.assertIn(marker, text, f"{identifier}: {relative} lost {marker!r}")


if __name__ == "__main__":
    unittest.main()
