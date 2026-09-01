.PHONY: validate invariants truth-boundaries remediation-wave readiness test check

validate:
	python3 scripts/validate_contracts.py

invariants:
	python3 scripts/validate_invariants.py

truth-boundaries:
	python3 scripts/validate_truth_boundaries.py

remediation-wave:
	python3 scripts/validate_remediation_wave.py

readiness:
	python3 scripts/report_product_readiness.py

test:
	PYTHONPATH=src python3 -m unittest discover -s tests -v

check: validate invariants truth-boundaries readiness test
