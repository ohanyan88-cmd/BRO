#!/usr/bin/env python3
"""Report repository readiness-evidence coverage without upgrading it to proof."""
from __future__ import annotations
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CONFIG=ROOT/"contracts"/"product_readiness.json"

def evaluate():
    spec=json.loads(CONFIG.read_text(encoding="utf-8"))
    results=[]
    for criterion in spec["criteria"]:
        missing=[]
        for selector in criterion["evidence"]:
            path=ROOT/selector["path"]
            if not path.exists():
                missing.append(selector["path"]); continue
            text=path.read_text(encoding="utf-8")
            if selector["contains"] not in text:
                missing.append(f"{selector['path']}::{selector['contains']}")
        results.append({**criterion,"passed":not missing,"missing":missing})
    def score(category):
        items=[r for r in results if r["category"]==category]
        passed=sum(1 for r in items if r["passed"])
        return int(passed*100/len(items)) if items else 0,passed,len(items)
    build,bp,bt=score("build"); production,pp,pt=score("production")
    total_pass=bp+pp; total=bt+pt; overall=int(total_pass*100/total) if total else 0
    production_results=[r for r in results if r["category"]=="production"]
    assurance={level:sum(1 for r in production_results if r.get("assurance")==level and r["passed"])
               for level in ("simulation","external_system")}
    return {"build":build,"production":production,"overall":overall,"passed":total_pass,"total":total,
            "assurance":assurance,"results":results}

def main():
    report=evaluate()
    print(f"BRO REPOSITORY EVIDENCE COVERAGE: overall={report['overall']}% build={report['build']}% production-criteria={report['production']}% ({report['passed']}/{report['total']} selectors)")
    print("NOT A PRODUCTION-READINESS VERDICT: selectors establish source coverage only; CI execution and durable external acceptance evidence are separate requirements.")
    print(f"PRODUCTION ASSURANCE DECLARED: simulation={report['assurance']['simulation']} external-system={report['assurance']['external_system']}")
    missing=[r for r in report["results"] if not r["passed"]]
    if missing:
        print("MISSING:")
        for item in missing:
            print(f"- {item['id']}: {item['label']} -> {', '.join(item['missing'])}")

if __name__=="__main__": main()
