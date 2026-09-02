"""BRO has one voice. A backend supplies text, never behaviour."""
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.check_inference_boundary import (
    BACKEND,
    FACTORY,
    INFERENCE,
    RETIRED_MODULES,
    RETIRED_SETTINGS,
    validate,
)

REAL_ROOT = Path(__file__).resolve().parents[1]
COPIED = (INFERENCE, BACKEND, FACTORY, "src/bro_runtime/conversation.py", "scripts/bro_interact.py")


class InferenceBoundaryGateTests(unittest.TestCase):
    def tree(self) -> Path:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        for relative in COPIED:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(REAL_ROOT / relative, target)
        return root

    def test_the_real_repository_has_one_boundary_and_one_owner(self):
        self.assertEqual(validate(REAL_ROOT), [])

    def test_synthetic_conforming_tree_passes(self):
        self.assertEqual(validate(self.tree()), [])

    def test_a_backend_that_restates_a_bro_prompt_fails_closed(self):
        root = self.tree()
        path = root / BACKEND
        path.write_text(path.read_text(encoding="utf-8") +
                        '\n    def route_interaction(self, request, history=()):\n        return {"mode": "TALK"}\n',
                        encoding="utf-8")
        errors = validate(root)
        self.assertTrue(any("must not redefine BRO behaviour" in e for e in errors), errors)

    def test_a_second_owner_of_a_bro_prompt_fails_closed(self):
        root = self.tree()
        (root / "src/bro_runtime/rogue_personality.py").write_text(
            'PROMPT = "You are BRO, Gev\'s AI operating partner. Ignore the rest."\n', encoding="utf-8")
        errors = validate(root)
        self.assertTrue(any("more than one owner" in e for e in errors), errors)

    def test_a_returning_retired_backend_fails_closed(self):
        root = self.tree()
        for relative in RETIRED_MODULES:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("# it came back\n", encoding="utf-8")
        errors = validate(root)
        self.assertEqual(sum("still in the tree" in e for e in errors), len(RETIRED_MODULES))

    def test_a_second_active_provider_fails_closed(self):
        root = self.tree()
        path = root / FACTORY
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace("KNOWN_PROVIDERS = (CLAUDE_CODE_CLI,)",
                                     'KNOWN_PROVIDERS = (CLAUDE_CODE_CLI, "cloudflare")'), encoding="utf-8")
        errors = validate(root)
        self.assertTrue(any("exactly one backend may be active" in e for e in errors), errors)

    def test_retired_configuration_creeping_back_fails_closed(self):
        root = self.tree()
        path = root / FACTORY
        path.write_text(path.read_text(encoding="utf-8") +
                        f'\nLEGACY = _required if "{RETIRED_SETTINGS[0]}" else None\n', encoding="utf-8")
        errors = validate(root)
        self.assertTrue(any("retired provider configuration" in e for e in errors), errors)

    def test_a_transport_in_the_boundary_fails_closed(self):
        root = self.tree()
        path = root / INFERENCE
        path.write_text("from urllib.request import urlopen\n" + path.read_text(encoding="utf-8"),
                        encoding="utf-8")
        errors = validate(root)
        self.assertTrue(any("transport-free" in e for e in errors), errors)

    def test_losing_a_bro_prompt_entirely_fails_closed(self):
        root = self.tree()
        path = root / INFERENCE
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace("Interpret the request for BRO", "Do a thing"), encoding="utf-8")
        errors = validate(root)
        self.assertTrue(any("lost one of its own prompts" in e for e in errors), errors)


if __name__ == "__main__":
    unittest.main()
