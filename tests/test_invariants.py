import json
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from validate_invariants import validate

class InvariantGateTests(unittest.TestCase):
    def test_repository_invariants_have_executable_enforcement(self):
        self.assertEqual(validate(),[])
    def test_missing_test_enforcement_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/"contracts").mkdir()
            (root/"contracts"/"invariants.json").write_text(json.dumps({"invariants":[{"id":"INV-X","statement":"x","enforcement":["tests/missing.py"]}]}),encoding="utf-8")
            errors=validate(root)
            self.assertTrue(any("missing enforcement file" in e for e in errors))
    def test_duplicate_invariant_identity_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/"contracts").mkdir(); (root/"tests").mkdir(); (root/"tests"/"test_x.py").write_text("# enforcement",encoding="utf-8")
            item={"id":"INV-X","statement":"x","enforcement":["tests/test_x.py"]}
            (root/"contracts"/"invariants.json").write_text(json.dumps({"invariants":[item,item]}),encoding="utf-8")
            self.assertTrue(any("duplicate invariant id" in e for e in validate(root)))

if __name__ == "__main__": unittest.main()
