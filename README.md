# Bridge

> 2026 Shenzhen FinTechathon (Shenzhen University × WeBank) · International Track · Topic C: Cross-border & Student Finance Assistant

**SANDBOX — fictional institutions, simulated accounts and FX rates.** No real payments, banks or personal data.

Chinese families struggle to pay tuition abroad safely and legally because of scams and foreign-exchange quota rules; existing tools only compare fees and do not check the payee or the rules; our agent verifies the payee, enforces the limits, and completes the payment under human approval.

**The AI proposes; the policy engine decides; humans approve.**

## Status

| Phase | Scope | State |
|---|---|---|
| 1 | Domain and security kernel: models, seed, registry, FX, personal quota, structuring, policy engine (all rule IDs), digest-bound approvals, hash-chained audit + tamper simulation, masking, sandbox bank + receipt PDFs, detectors, risk, request guard, sample generator, `rules.yaml` | Done |
| 2 | LLM providers, extractor, Chinese summary, orchestrator, tools, API, scenario suite | Next |
| 3 | UI (persona toggle, Why panel, Evidence Center), Docker | — |
| 4 | Evidence pack, demo autopilot, docs, CI badge | — |

## Quickstart (Phase 1)

```bash
python -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.txt     # Windows: .venv\Scripts\pip
python scripts/generate_samples.py                        # fictional sample documents -> samples/
python -m pytest                                          # offline, no API keys
python scripts/phase1_demo.py                             # payments allowed / held / blocked, audit chain verified
```

With `make`: `make install samples test phase1-demo`.

## Layout

```
backend/app/        config, models, seed, registry, sandbox/, quota/, security/ (policy.py is the choke point), agent/extractor.py
backend/tests/      unit tests
config/rules.yaml   every rule ID with params, lawful alternative, source, last_checked, status
config/app.yaml     simulated FX rates, fee, risk weights
registry/           verified (fictional) institution registry
scripts/            sample generator, Phase 1 demo
samples/            generated sample documents (SANDBOX SAMPLE)
docs/               DECISIONS, THIRD_PARTY, known_risks
```

License: MIT.
