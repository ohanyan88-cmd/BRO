import tempfile
import unittest
from pathlib import Path

from scripts.validate_truth_boundaries import validate


class TruthBoundaryGateTests(unittest.TestCase):
    def tree(self, files: dict[str, str]) -> Path:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        source = root / "src" / "bro_runtime"
        source.mkdir(parents=True)
        for name, content in files.items():
            (source / name).write_text(content, encoding="utf-8")
        return root

    def test_canonical_owner_locations_pass(self):
        root = self.tree({
            "immune.py": "Evidence(\nCompletionManifest(\n",
            "evidence_verification.py": "Evidence(\n",
            "supervision.py": "self.evidence.record(x)\nself.evidence.evaluate_completion(x)\n",
            "governed_supervision.py": "self.evidence._evaluate_bound_completion(x)\n",
            "replan.py": "kernel.mind.replan(plan_id, step_refs=refs, reason='verified reality')\n",
        })
        self.assertEqual(validate(root), [])

    def test_new_direct_evidence_writer_fails_closed(self):
        root = self.tree({"rogue.py": "kernel.supervisor.evidence.record(forged)\n"})
        errors = validate(root)
        self.assertTrue(any("direct Evidence ledger write" in error for error in errors))

    def test_new_completion_writer_fails_closed(self):
        root = self.tree({"rogue.py": "kernel.supervisor.evidence.evaluate_completion()\n"})
        errors = validate(root)
        self.assertTrue(any("direct completion evaluation" in error for error in errors))

    def test_legacy_callable_readback_opt_in_is_forbidden_in_production_source(self):
        root = self.tree({"rogue.py": "LiveReadbackRuntime(actions, allow_legacy_callable=True)\n"})
        errors = validate(root)
        self.assertTrue(any("legacy callable live readback opt-in" in error for error in errors))

    def test_new_direct_plan_revision_writer_fails_closed(self):
        root = self.tree({"rogue.py": "kernel.mind.replan(plan_id, step_refs=refs, reason='caller said so')\n"})
        errors = validate(root)
        self.assertTrue(any("canonical Plan revision writer" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
