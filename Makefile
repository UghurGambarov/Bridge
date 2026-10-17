# Bridge — developer targets. On Windows without make, run the commands after each target directly
# (use .venv\Scripts\python instead of python).
PY ?= python

.PHONY: help install samples test phase1-demo

help:
	@echo "make install      install Python dependencies"
	@echo "make samples      generate the fictional sample documents into samples/"
	@echo "make test         unit tests (offline, mock LLM, no API keys)"
	@echo "make phase1-demo  push payments through the policy engine and show the audit log"

install:
	$(PY) -m pip install -r backend/requirements-dev.txt

samples:
	$(PY) scripts/generate_samples.py

test:
	LLM_PROVIDER=mock $(PY) -m pytest

phase1-demo:
	$(PY) scripts/phase1_demo.py
