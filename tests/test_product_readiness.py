import importlib.util
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location("product_readiness",ROOT/"scripts"/"report_product_readiness.py")
module=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(module)

class ProductReadinessTests(unittest.TestCase):
    def test_current_repository_score_is_evidence_derived(self):
        report=module.evaluate()
        results=report["results"]
        passed=sum(1 for item in results if item["passed"])
        self.assertEqual(report["passed"],passed)
        self.assertEqual(report["total"],len(results))
        for category in ("build","production"):
            items=[item for item in results if item["category"]==category]
            expected=int(sum(1 for item in items if item["passed"])*100/len(items)) if items else 0
            self.assertEqual(report[category],expected)
        expected_overall=int(passed*100/len(results)) if results else 0
        self.assertEqual(report["overall"],expected_overall)
        missing={r["id"] for r in results if not r["passed"]}
        self.assertNotIn("BUILD-ARTIFACT-RUNTIME",missing)
        self.assertNotIn("PROD-ARTIFACT-VERIFY",missing)
        self.assertNotIn("PROD-ADAPTER-REGISTRY",missing)
        self.assertNotIn("PROD-REAL-SYSTEM",missing)
    def test_every_criterion_has_explicit_repository_evidence(self):
        report=module.evaluate()
        for item in report["results"]:
            self.assertIn(item["category"],{"build","production"})
            self.assertTrue(item["evidence"])
            for selector in item["evidence"]:
                self.assertTrue(selector["path"]); self.assertTrue(selector["contains"])

if __name__=="__main__": unittest.main()
