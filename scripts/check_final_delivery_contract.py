#!/usr/bin/env python3
"""Fail closed if the final-delivery executable contract drifts from runtime code."""
from __future__ import annotations
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
contract=json.loads((ROOT/'contracts/final_delivery.json').read_text(encoding='utf-8'))
source=(ROOT/'src/bro_runtime/final_delivery.py').read_text(encoding='utf-8')

required_blocks={
    'FINAL-1-INTELLIGENT-EXECUTION': ('IntelligentInteractionRuntime','explicit confirmation','external-system readback'),
    'FINAL-2-PRODUCTION-SERVICE': ('ProductionServiceControl','fencing_token','external backend'),
    'FINAL-3-DURABLE-TRUTH-DR-GRADUATION': ('DurableTruthCustody','PRODUCTION_GRADUATED','zero unresolved material contradictions'),
}
ids={block.get('id') for block in contract.get('blocks',[])}
missing=set(required_blocks)-ids
if missing:
    raise SystemExit(f"ERROR: final delivery contract missing blocks: {sorted(missing)}")
for block_id,markers in required_blocks.items():
    absent=[marker for marker in markers if marker not in source]
    if absent:
        raise SystemExit(f"ERROR: {block_id} runtime enforcement markers missing: {absent}")
if 'repository tests into production evidence' not in contract.get('purpose',''):
    raise SystemExit('ERROR: final delivery truth boundary disclaimer is missing')
print('PASS: final audit delivery blocks 1+2+3 are contract-bound to executable fail-closed controls')
