import importlib.util
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location("product_readiness",ROOT/"scripts"/"report_product_readiness.py")
module=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(module)

class ProductReadinessTests(unittest.TestCase):
    def test_current_repository_score_is_evidence_derived(self):
        report=module.evaluate()
        self.assertEqual(report["build"],91)
        self.assertEqual(report["production"],20)
        self.assertEqual(report["overall"],59)
        self.assertEqual((report["passed"],report["total"]),(13,22))
        missing={r["id"] for r in report["results"] if not r["passed"]}
        self.assertIn("BUILD-ARTIFACT-RUNTIME",missing)
        self.assertIn("PROD-REAL-SYSTEM",missing)
    def test_every_criterion_has_explicit_repository_evidence(self):
        report=module.evaluate()
        for item in report["results"]:
            self.assertIn(item["category"],{"build","production"})
            self.assertTrue(item["evidence"])
            for selector in item["evidence"]:
                self.assertTrue(selector["path"]); self.assertTrue(selector["contains"])

if __name__=="__main__": unittest.main()
