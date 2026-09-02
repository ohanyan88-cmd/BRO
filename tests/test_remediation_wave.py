import json
import unittest
from pathlib import Path

from scripts.validate_remediation_wave import validate_declaration

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "contracts" / "remediation_policy.json").read_text(encoding="utf-8"))


class RemediationWavePolicyTests(unittest.TestCase):
    def test_subsystem_wave_requires_multiple_protected_files_and_scope_areas(self):
        body = """Remediation-Wave: Truth spine\nRoot-Cause: caller-controlled truth paths\nScope: evidence, completion\nWave-Class: SUBSYSTEM\n"""
        files = [
            "src/bro_runtime/immune.py",
            "src/bro_runtime/kernel.py",
            "tests/test_governed_evidence_boundary.py",
        ]
        errors = validate_declaration(body, files, POLICY)
        self.assertIn("SUBSYSTEM wave requires at least 3 protected files; found 2", errors)

    def test_declared_subsystem_wave_passes_when_scope_is_broad_enough(self):
        body = """Remediation-Wave: Truth spine\nRoot-Cause: caller-controlled truth paths\nScope: evidence, completion, voice\nWave-Class: SUBSYSTEM\n"""
        files = [
            "src/bro_runtime/immune.py",
            "src/bro_runtime/kernel.py",
            "scripts/validate_contracts.py",
            "tests/test_governed_evidence_boundary.py",
        ]
        self.assertEqual(validate_declaration(body, files, POLICY), [])

    def test_micro_fix_fails_closed_without_explicit_emergency(self):
        body = """Remediation-Wave: tiny patch\nRoot-Cause: urgent regression\nScope: evidence\nWave-Class: SUBSYSTEM\n"""
        errors = validate_declaration(body, ["src/bro_runtime/immune.py"], POLICY)
        self.assertTrue(any("at least 3 protected files" in error for error in errors))
        self.assertTrue(any("at least 2 distinct Scope areas" in error for error in errors))

    def test_emergency_requires_reason_but_may_be_small(self):
        body = """Remediation-Wave: hotfix\nRoot-Cause: production blocker\nScope: execution\nWave-Class: EMERGENCY\nEmergency-Reason: active production incident\n"""
        self.assertEqual(validate_declaration(body, ["src/bro_runtime/action_runtime.py"], POLICY), [])


class NarrowWaveTests(unittest.TestCase):
    """A small fix should not have to pad itself or call itself an emergency."""

    BODY = ("Remediation-Wave: acquisition pacing\n"
            "Root-Cause: every page of a shelf was fetched back to back\n"
            "Scope: knowledge-acquisition\n"
            "Wave-Class: NARROW\n"
            "Narrow-Justification: one file, one behaviour, five mutations\n")

    def test_a_declared_narrow_fix_passes_on_one_protected_file(self):
        self.assertEqual(
            validate_declaration(self.BODY, ["scripts/bro_acquire_knowledge.py",
                                             "tests/test_acquisition_pacing.py"], POLICY), [])

    def test_a_narrow_fix_still_has_to_justify_itself(self):
        body = self.BODY.replace("Narrow-Justification: one file, one behaviour, five mutations\n", "")
        errors = validate_declaration(body, ["scripts/bro_acquire_knowledge.py"], POLICY)
        self.assertTrue(any("Narrow-Justification" in error for error in errors))

    def test_a_subsystem_change_cannot_hide_in_the_narrow_lane(self):
        errors = validate_declaration(self.BODY, [
            "src/bro_runtime/kernel.py", "src/bro_runtime/immune.py",
            "scripts/validate_contracts.py", "contracts/invariants.json",
        ], POLICY)
        self.assertTrue(any("at most 2 protected files" in error for error in errors))

    def test_an_unknown_wave_class_is_still_refused(self):
        body = self.BODY.replace("Wave-Class: NARROW", "Wave-Class: TINY")
        errors = validate_declaration(body, ["scripts/bro_acquire_knowledge.py"], POLICY)
        self.assertTrue(any("unsupported Wave-Class" in error for error in errors))


class WavePolicyTriggerTests(unittest.TestCase):
    """The gate reads the PR body; the workflow must re-run when the body is edited."""

    def test_the_contract_workflow_reruns_on_an_edited_pull_request(self):
        workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/contracts.yml"
                    ).read_text(encoding="utf-8")
        self.assertIn("types: [opened, synchronize, reopened, edited]", workflow)


if __name__ == "__main__":
    unittest.main()
