.PHONY: validate invariants test check

validate:
	python3 scripts/validate_contracts.py

invariants:
	python3 scripts/validate_invariants.py

test:
	PYTHONPATH=src python3 -m unittest discover -s tests -v

check: validate invariants test
