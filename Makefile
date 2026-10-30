PY ?= .venv/bin/python

.PHONY: install test demo cost eval samples screenshots azure-package

install:
	python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"

test:
	$(PY) -m pytest

demo:
	$(PY) -m orderline demo

cost:
	$(PY) -m orderline cost

# Calls the real model on the 12 sample PDFs (costs money): run `python evals/run_eval.py --yes`.
eval:
	$(PY) evals/run_eval.py

samples:
	$(PY) scripts/make_samples.py

screenshots: demo
	$(PY) scripts/screenshots.py

azure-package:
	rm -rf build/azure && mkdir -p build/azure
	cp azure/function_app.py azure/host.json azure/requirements.txt config/columns.yaml build/azure/
	cp -R orderline build/azure/orderline
	@echo "Function app package in build/azure (publish with: cd build/azure && func azure functionapp publish <APP_NAME>)"
