# Bridge

> 2026 Shenzhen FinTechathon (Shenzhen University × WeBank) · International Track · Topic C: Cross-border & Student Finance Assistant

**SANDBOX — fictional institutions, simulated accounts and FX rates.** No real payments, banks or personal data.

Chinese families struggle to pay tuition abroad safely and legally because of scams and foreign-exchange quota rules; existing tools only compare fees and do not check the payee or the rules; our agent verifies the payee, enforces the limits, and completes the payment under human approval.

**The AI proposes; the policy engine decides; humans approve.**

## Status

| Phase | Scope | State |
|---|---|---|
| 1 | Domain and security kernel: models, seed, registry, FX, personal quota, structuring, policy engine (all rule IDs), digest-bound approvals, hash-chained audit + tamper simulation, masking, sandbox bank + receipt PDFs, detectors, risk, request guard, sample generator, `rules.yaml` | Done |
| 2 | LLM providers (mock, malicious, OpenAI-compatible, Anthropic), quarantined extractor, Chinese summary, orchestrator, tools, full API, scenario suite (39 cases, 100% in mock mode) | Done |
| 3 | React UI (persona toggle Mother / Li Wei, cards, Why panel, approval + consent modals, Evidence Center, demo mode, intro/outro), single-container Docker | Done |
| 4 | Evidence pack script, demo autopilot, docs, CI badge | Next |

## Quickstart (Docker)

```bash
docker compose up --build          # app at http://localhost:8000 (mock model unless .env sets a provider)
```

Open http://localhost:8000, accept the sandbox consent, pick `northbridge_invoice_autumn.pdf` from **Sample docs…**, approve as **Mother**, switch to **Li Wei** and confirm. The Evidence Center (top right) verifies the hash chain, runs the scenario suite and exports the evidence pack. Demo mode: http://localhost:8000/?demo=1 (caption bar), title cards at `/intro` and `/outro`.

## Quickstart (development)

```bash
python -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.txt     # Windows: .venv\Scripts\pip
cp .env.example .env                                      # optional: choose an LLM provider
python scripts/generate_samples.py                        # fictional sample documents -> samples/
python -m pytest                                          # unit tests + scenario suite, offline, no API keys
python scenarios/runner.py                                # writes evidence/scenario_report.{json,md,html}
cd frontend && npm ci && npm run build && cd ..                          # UI -> frontend/dist
cd backend && python -m uvicorn app.main:create_app --factory --port 8000   # app at http://localhost:8000
```

With `make`: `make install samples test scenarios frontend serve`, or `make dev` for the backend with reload plus the Vite dev server on :5173. API docs: http://localhost:8000/docs.

### LLM providers (`.env`)

| `LLM_PROVIDER` | Notes |
|---|---|
| `mock` (default) | Deterministic, offline; used by tests and CI. The UI shows `MOCK — tests only`. |
| `openai_compatible` | `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` — OpenAI, DeepSeek, Qwen (DashScope compatible mode), Ollama, OpenRouter... |
| `anthropic` | `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` (default `claude-opus-5-5`); needs `pip install anthropic`. |

Whatever the model does, the policy engine decides: every security guarantee holds with the `malicious` planner used by the scenario suite.

## Layout

```
backend/app/        config, models, seed, registry, sandbox/, quota/, security/ (policy.py is the choke point), agent/extractor.py
backend/tests/      unit tests
config/rules.yaml   every rule ID with params, lawful alternative, source, last_checked, status
config/app.yaml     simulated FX rates, fee, risk weights
registry/           verified (fictional) institution registry
backend/app/agent/  orchestrator, tools, quarantined extractor, Chinese summary, LLM providers, prompts
backend/app/api/    FastAPI routes (session, chat, documents, intents, quota, audit, evidence, admin, demo)
scenarios/          cases.yaml (39 cases) and runner.py
frontend/           React + Vite + TypeScript + Tailwind UI (served by FastAPI in production)
evidence/           latest scenario report
scripts/            sample generator, Phase 1 demo
samples/            generated sample documents (SANDBOX SAMPLE)
docs/               DECISIONS, THIRD_PARTY, known_risks
```

License: MIT.
