.PHONY: validate invariants truth-boundaries remediation-wave readiness production-deployment final-delivery-contract interaction-surface-contract learning-contract self-study-contract inference-boundary test check

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

production-deployment:
	python3 scripts/validate_production_deployment.py

final-delivery-contract:
	python3 scripts/check_final_delivery_contract.py

interaction-surface-contract:
	python3 scripts/check_interaction_surface_contract.py

learning-contract:
	python3 scripts/check_learning_contract.py

self-study-contract:
	python3 scripts/check_self_study_contract.py

inference-boundary:
	python3 scripts/check_inference_boundary.py

test:
	PYTHONPATH=src python3 -m unittest discover -s tests -v

check: validate invariants truth-boundaries readiness production-deployment final-delivery-contract interaction-surface-contract learning-contract self-study-contract inference-boundary test
