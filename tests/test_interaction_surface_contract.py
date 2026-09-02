import json
import tempfile
import unittest
from pathlib import Path

from scripts.check_interaction_surface_contract import (
    CONTRACT,
    CONVERSATION,
    ENTRYPOINT,
    FINAL_DELIVERY,
    REQUIREMENT_MARKERS,
    SURFACE,
    validate,
)

REAL_ROOT = Path(__file__).resolve().parents[1]


class InteractionSurfaceContractGateTests(unittest.TestCase):
    def tree(self, *, contract: dict | None = None, entrypoint: str | None = None) -> Path:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        # The stub sources always mirror the real repository; only the contract file is
        # the thing under test, so a contract that declares more than the code has must
        # still fail.
        real = json.loads((REAL_ROOT / CONTRACT).read_text(encoding="utf-8"))
        payload = real if contract is None else contract
        (root / "contracts").mkdir(parents=True)
        (root / CONTRACT).write_text(json.dumps(payload), encoding="utf-8")

        sources: dict[str, list[str]] = {
            FINAL_DELIVERY: ["class IntelligentInteractionRuntime:", "real capability execution requires external-system readback"],
            # Modes come from the contract so a newly declared mode cannot silently
            # pass here while the real InteractionMode never gained it.
            CONVERSATION: ["class ConversationalInteractionSurface:"]
            + [f'{mode} = "{mode}"' for mode in real.get("modes", {})],
            SURFACE: ["class InteractionSurface:"],
            ENTRYPOINT: ["import argparse", "def executor(intent, specialist):", '    required("BRO_GITHUB_TOKEN")'],
        }
        for markers in REQUIREMENT_MARKERS.values():
            for relative, marker in markers:
                if marker not in "\n".join(sources.get(relative, [])):
                    sources.setdefault(relative, []).append(marker)
        if entrypoint is not None:
            sources[ENTRYPOINT] = entrypoint.splitlines()
        for relative, lines in sources.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return root

    def test_real_repository_contract_is_enforced(self):
        self.assertEqual(validate(REAL_ROOT), [])

    def test_synthetic_conforming_tree_passes(self):
        self.assertEqual(validate(self.tree()), [])

    def test_requirement_without_enforcement_mapping_fails_closed(self):
        contract = json.loads((REAL_ROOT / CONTRACT).read_text(encoding="utf-8"))
        contract["requirements"]["human_approves_everything"] = True
        errors = validate(self.tree(contract=contract))
        self.assertTrue(any("no executable enforcement mapping" in e for e in errors), errors)

    def test_lost_materiality_marker_fails_closed(self):
        root = self.tree()
        path = root / FINAL_DELIVERY
        marker = "self.material_floor = bool(material_floor)"
        text = path.read_text(encoding="utf-8")
        self.assertIn(marker, text)
        path.write_text(text.replace(marker, ""), encoding="utf-8")
        errors = validate(root)
        self.assertTrue(any("materiality_owned_by_runtime_not_model" in e for e in errors), errors)

    def test_lost_confirmation_marker_fails_closed(self):
        root = self.tree()
        path = root / FINAL_DELIVERY
        marker = "material interpreted scope requires explicit confirmation"
        text = path.read_text(encoding="utf-8")
        self.assertIn(marker, text)
        path.write_text(text.replace(marker, ""), encoding="utf-8")
        errors = validate(root)
        self.assertTrue(any("explicit_material_scope_confirmation" in e for e in errors), errors)

    def test_action_credentials_outside_act_path_fail_closed(self):
        root = self.tree(entrypoint='import argparse\n\n\ndef build_model():\n    required("BRO_GITHUB_TOKEN")\n')
        errors = validate(root)
        self.assertTrue(any("outside the ACT path" in e for e in errors), errors)

    def test_missing_entrypoint_fails_closed(self):
        root = self.tree()
        (root / ENTRYPOINT).unlink()
        errors = validate(root)
        self.assertTrue(any("declared entrypoint is missing" in e for e in errors), errors)

    def test_lowered_assurance_floor_fails_closed(self):
        contract = json.loads((REAL_ROOT / CONTRACT).read_text(encoding="utf-8"))
        contract["assurance_floor_for_act"] = "repository"
        errors = validate(self.tree(contract=contract))
        self.assertTrue(any("unsupported assurance floor" in e for e in errors), errors)

    def test_undeclared_mode_fails_closed(self):
        contract = json.loads((REAL_ROOT / CONTRACT).read_text(encoding="utf-8"))
        contract["modes"]["DEPLOY"] = "anything"
        errors = validate(self.tree(contract=contract))
        self.assertTrue(any("not an InteractionMode member" in e for e in errors), errors)


if __name__ == "__main__":
    unittest.main()
