# Bridge — developer targets. On Windows without make, run the commands after each target directly
# (use .venv\Scripts\python instead of python).
PY ?= python

.PHONY: help install samples test scenarios serve dev dev-backend dev-frontend frontend docker phase1-demo

help:
	@echo "make install      install Python dependencies"
	@echo "make samples      generate the fictional sample documents into samples/"
	@echo "make test         unit tests + scenario suite (offline, mock LLM, no API keys)"
	@echo "make scenarios    run the scenario suite and write evidence/scenario_report.{json,md,html}"
	@echo "make serve        app at http://localhost:8000 (serves the built frontend)"
	@echo "make dev          backend with reload (:8000) + Vite dev server (:5173)"
	@echo "make frontend     install and build the frontend into frontend/dist"
	@echo "make docker       docker compose up --build (app at http://localhost:8000)"
	@echo "make phase1-demo  push payments through the policy engine and show the audit log"

install:
	$(PY) -m pip install -r backend/requirements-dev.txt
	cd frontend && npm ci --no-audit --no-fund

samples:
	$(PY) scripts/generate_samples.py

test:
	LLM_PROVIDER=mock $(PY) -m pytest

scenarios:
	LLM_PROVIDER=mock $(PY) scenarios/runner.py

serve:
	cd backend && $(PY) -m uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000

dev:
	$(MAKE) -j2 dev-backend dev-frontend

dev-backend:
	cd backend && $(PY) -m uvicorn app.main:create_app --factory --reload --port 8000

dev-frontend:
	cd frontend && npm run dev

frontend:
	cd frontend && npm ci --no-audit --no-fund && npm run build

docker:
	GIT_COMMIT=$$(git rev-parse --short HEAD) docker compose up --build

phase1-demo:
	$(PY) scripts/phase1_demo.py
