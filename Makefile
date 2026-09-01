.PHONY: validate test check

validate:
	python3 scripts/validate_contracts.py

test:
	python3 -m unittest discover -s tests -v

check: validate test

