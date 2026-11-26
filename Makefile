.PHONY: cluster demo replay eval check reports export-reports
PYTHON ?= python3
cluster:
	kind get clusters | grep -Fxq oncall || kind create cluster --name oncall
demo: cluster
	docker build -t oncall-demo:local .
	kind load docker-image oncall-demo:local --name oncall
	kubectl --context kind-oncall apply -k ops
replay:
	$(PYTHON) -m triage.evaluate
eval:
	$(PYTHON) -m triage.live_eval $(EVAL_ARGS)
check:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m mypy triage shop
	$(PYTHON) -m pytest -q
reports:
	kubectl --context kind-oncall -n oncall exec deployment/triage -- sh -c 'ls /reports'
export-reports:
	mkdir -p reports
	pod=$$(kubectl --context kind-oncall -n oncall get pods -l app=triage --field-selector=status.phase=Running --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1].metadata.name}') && \
	kubectl --context kind-oncall -n oncall cp "$$pod:/reports/." reports
