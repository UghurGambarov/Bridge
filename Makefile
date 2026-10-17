# Bridge — developer targets. On Windows without make, run the commands after each target directly
# (use .venv\Scripts\python instead of python).
PY ?= python

.PHONY: help install samples test scenarios serve phase1-demo

help:
	@echo "make install      install Python dependencies"
	@echo "make samples      generate the fictional sample documents into samples/"
	@echo "make test         unit tests + scenario suite (offline, mock LLM, no API keys)"
	@echo "make scenarios    run the scenario suite and write evidence/scenario_report.{json,md,html}"
	@echo "make serve        API at http://localhost:8000 (frontend served when built)"
	@echo "make phase1-demo  push payments through the policy engine and show the audit log"

install:
	$(PY) -m pip install -r backend/requirements-dev.txt

samples:
	$(PY) scripts/generate_samples.py

test:
	LLM_PROVIDER=mock $(PY) -m pytest

scenarios:
	LLM_PROVIDER=mock $(PY) scenarios/runner.py

serve:
	cd backend && $(PY) -m uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000

phase1-demo:
	$(PY) scripts/phase1_demo.py
