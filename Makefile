.PHONY: validate test check

validate:
	python3 scripts/validate_contracts.py

test:
	PYTHONPATH=src python3 -m unittest discover -s tests -v

check: validate test
