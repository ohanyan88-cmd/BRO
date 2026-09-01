from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.validate_contracts import ROOT, validate


class ContractGateTests(unittest.TestCase):
    def test_repository_contracts_pass(self) -> None:
        self.assertEqual(validate(), [])

    def test_duplicate_primitive_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            shutil.copytree(ROOT, root)
            path = root / "contracts" / "registry.json"
            registry = json.loads(path.read_text(encoding="utf-8"))
            registry["contracts"].append(dict(registry["contracts"][0]))
            path.write_text(json.dumps(registry), encoding="utf-8")
            self.assertTrue(any("duplicate primitive" in error for error in validate(root)))

    def test_owner_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            shutil.copytree(ROOT, root)
            path = root / "contracts" / "registry.json"
            registry = json.loads(path.read_text(encoding="utf-8"))
            registry["contracts"][0]["owner"] = "MIND"
            path.write_text(json.dumps(registry), encoding="utf-8")
            self.assertTrue(any("schema owner mismatch" in error for error in validate(root)))

    def test_undefined_required_field_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            shutil.copytree(ROOT, root)
            path = root / "contracts" / "v0.1" / "task.schema.json"
            schema = json.loads(path.read_text(encoding="utf-8"))
            schema["required"].append("not_defined")
            path.write_text(json.dumps(schema), encoding="utf-8")
            self.assertTrue(any("required fields missing definitions" in error for error in validate(root)))


if __name__ == "__main__":
    unittest.main()

