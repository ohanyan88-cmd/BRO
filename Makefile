.PHONY: validate invariants readiness test check

validate:
	python3 scripts/validate_contracts.py

invariants:
	python3 scripts/validate_invariants.py

readiness:
	python3 scripts/report_product_readiness.py

test:
	PYTHONPATH=src python3 -m unittest discover -s tests -v

check: validate invariants readiness test
