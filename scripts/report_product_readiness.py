#!/usr/bin/env python3
"""Report BRO product readiness from declared repository evidence selectors."""
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
    return {"build":build,"production":production,"overall":overall,"passed":total_pass,"total":total,"results":results}

def main():
    report=evaluate()
    print(f"BRO PRODUCT READINESS: overall={report['overall']}% build={report['build']}% production={report['production']}% ({report['passed']}/{report['total']} criteria)")
    missing=[r for r in report["results"] if not r["passed"]]
    if missing:
        print("MISSING:")
        for item in missing:
            print(f"- {item['id']}: {item['label']} -> {', '.join(item['missing'])}")

if __name__=="__main__": main()
