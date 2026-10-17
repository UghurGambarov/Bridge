# Bridge — Technical documentation

> SANDBOX prototype for the 2026 Shenzhen FinTechathon (Topic C). Fictional institutions, simulated accounts and FX rates. Submission item 1: system architecture, core algorithms, security design.

## 1. What Bridge does

Bridge is an AI agent that helps a Chinese family pay university tuition abroad safely and legally. For an English invoice it:

1. explains the invoice in Chinese;
2. verifies the payee against a registry;
3. checks the **payer's personal** FX quota and quotes the rate;
4. collects digest-bound approvals from the mother and the student;
5. pays in a sandbox bank and issues a receipt;
6. logs every step to a hash-chained audit log.

Monthly allowances to the student's own account run autonomously under caps. Forbidden requests ("use my brother's quota") are refused with the rule and the lawful alternative.

**Design principle: the AI proposes, the policy engine decides, humans approve.**

![Flow 1 receipt](img/07_receipt.png)

## 2. Architecture

```mermaid
flowchart LR
  U[Web UI - persona toggle Mother / Li Wei] -->|chat, upload, approve| API
  EC[Evidence Center] --> API
  API --> RG[Request Guard - deterministic]
  RG --> ORCH[Agent Orchestrator - Planner LLM]
  API --> ING[Document Ingestion]
  ING --> DET[Deterministic detectors: hidden text, injection phrases, invisible unicode, lookalike domains]
  ING --> EXT[Quarantined Extractor LLM - no tools, JSON schema only]
  DET --> ORCH
  EXT --> ORCH
  ORCH -->|tool call| POL[Policy Engine T0-T4]
  POL -->|allowed| TOOLS[Tools: payee check, quota, FX, intents, sandbox bank]
  TOOLS --> DB[(Registry + Quota ledger + Sandbox bank)]
  POL --> AUD[(Hash-chained audit log)]
  TOOLS --> AUD
  AUD --> EC
```

| Component | Code | Notes |
|---|---|---|
| Web UI + Evidence Center | `frontend/src/` | React, Vite, TypeScript, Tailwind; served by FastAPI from one container |
| API | `backend/app/api/` | FastAPI, prefix `/api`; app factory `app.main:create_app` |
| Request guard | `backend/app/security/request_guard.py` | EN/ZH patterns → refusal cards, logged |
| Document ingestion | `backend/app/documents.py` | hash, consent, detectors, quarantined extraction, payee check |
| Detectors | `security/pdf_forensics.py`, `injection.py`, `domains.py` | no LLM |
| Extractor | `backend/app/agent/extractor.py` | no tools; strict Pydantic schema; regex fallback |
| Orchestrator | `backend/app/agent/orchestrator.py` | explicit loop, ≤ 8 tool steps, no agent framework |
| Tools | `backend/app/agent/tools.py` | every call authorised; cards built by code |
| **Policy engine** | `backend/app/security/policy.py` | **the choke point** — `authorize(tool, args, ctx) -> Decision` |
| Approvals | `backend/app/security/approvals.py` | nonce + HMAC over the digest; single-use; 15 min |
| Quota | `backend/app/quota/` | personal ledger, planner, structuring |
| Sandbox bank | `backend/app/sandbox/` | accounts, FX (simulated), receipts (PDF + JSON), clock |
| Audit | `backend/app/security/audit.py` | hash chain, verify, tamper simulation on a copy |
| Config | `config/rules.yaml`, `config/app.yaml`, `registry/institutions.yaml` | every regulatory parameter lives in config |
| LLM providers | `backend/app/agent/llm/` | `mock`, `openai_compatible`, `anthropic`; `malicious` / scripted for the scenario suite |

### 2.1 The five security patterns

1. **Dual-LLM / quarantine.** The planner (which has tools) never sees raw untrusted text, only schema-validated fields and detector findings.
2. **Single choke point.** No tool runs without `policy.authorize()`.
3. **Capability restriction.** Payment tools accept only a registry `payee_channel_id`; the model cannot type an account number (`T4-007`).
4. **Human approval bound to a transaction digest.** Approvals are single-use, expire and are tied to a device ("what you see is what you sign"). The agent has no approval tool.
5. **Tamper-evident audit.** A hash chain that anyone can verify from the Evidence Center.

## 3. Data model (SQLModel on SQLite)

| Group | Tables |
|---|---|
| People and consent | `Person`, `Device` (stores `SHA-256(device_secret)`, the HMAC key), `Consent` |
| Registry | `Institution`, `PaymentChannel` (`institution` or `same_name_personal`) |
| Ledger and documents | `FxLedgerEntry` (per person, per calendar year), `Document` (hash, validated fields, findings, payee check — no raw file) |
| Payments | `PaymentIntent` (status, tier, route, risk, rule checks, digest, fingerprint), `Approval` (nonce, MAC, issued/expires/used), `AllowanceSchedule` |
| Sandbox bank and audit | `SandboxAccount`, `Transfer` (`SBX-YYYYMMDD-XXXX`, receipt paths), `AuditEntry` (seq, ts, actor, event, rule, decision, masked payload, prev_hash, hash) |
| Chat | `ChatSession`, `ChatMessage` (append-only planner history + what the UI displayed) |

Money is stored as exact decimal text and computed with `Decimal` (half-up to cents). Datetimes come from the sandbox clock (Beijing time).

Intent statuses: `draft → (awaiting_documents → draft) → pending_approval | held → approved → executed`, plus `blocked`, `rejected`, `expired`, `refused`.

## 4. Core algorithms

### 4.1 Document ingestion (§9.1)

```text
ingest(file, uploader):
    require consent(uploader, "document_processing")          # P-001
    sha = sha256(file)
    if pdf:   visible, hidden_spans, rotated = pdf_forensics(file)
              # chars with fill RGB/gray ≥ 0.9, size < 2pt, or outside the page box;
              # annotations; metadata containing injection phrases
    else:     visible = strip_invisible(text)
    everything = visible + rotated + hidden_spans.text
    findings = { injection_hits(everything), bank_change_hits(everything),
                 invisible_chars(text), lookalike_domains(everything), guard_hits(everything) }
    fields = extractor(visible)           # LLM without tools → strict JSON (extra fields forbidden)
             or regex_extract(visible)    # on any failure, and always in mock mode
    payee_check = assess(fields, findings, registry)
    store {sha, fields, findings, payee_check}  — raw file NOT retained (P-004)
```

The planner later receives `fields` with free text sanitised (invisible characters stripped, injection phrases replaced, truncated), account numbers masked and detector counts. It never sees raw text or hidden-span text.

### 4.2 Payee verification and risk score (§9.2)

```text
inst = match institution by issuer / beneficiary / sender domain / reference format
if account given:
    channel = registry channel with this account
    if channel belongs to inst:   matched; NAME_MISMATCH if beneficiary name differs
    elif inst known:              ACCOUNT_MISMATCH
    else:                         PAYEE_NOT_IN_REGISTRY
if not matched and (2–4 char CJK name | Mr/Ms/Manager/经理 | "personal/个人" | 62\d{14,17}):
    PERSONAL_ACCOUNT_FOR_FEES
+ REFERENCE_FORMAT_MISMATCH, LOOKALIKE_DOMAIN, BANK_DETAILS_CHANGE_REQUEST, HIDDEN_TEXT,
  INJECTION_PHRASE, INVISIBLE_UNICODE, DISCOUNT_OFFER, URGENCY, AGENCY_INTERMEDIARY,
  CRYPTO_MENTION, AMOUNT_OUTSIDE_FEE_RANGE, DEADLINE_MISMATCH          (weights in config/app.yaml)
score = min(100, Σ weights);  LOW < 30 ≤ MEDIUM < 60 ≤ HIGH
forbidden = T4-005 (crypto) | T4-001 (personal) | T4-006 (bank-detail change) |
            T4-002 (mismatch / not in registry) | T4-008 (injection) | T4-002 (any HIGH)
```

Verification emails always go to the **registry's** official contact, never to an address taken from the document.

### 4.3 Chinese summary (§9.3)

A deterministic template is filled from the validated fields, the registry and the FX tool, for example:

> 这是一张来自 Northbridge University（英国）的学费账单。金额：£13,250.00（约 ¥121,900，按模拟汇率 9.20 计算）。截止日期：2026年10月31日。收款方：NORTHBRIDGE UNIVERSITY —— 已在核验名单中 ✅。参考号：NBU-26004217。

A real model may add one or two explanatory sentences, labelled AI生成. That note is dropped if it contains any digit. An English line follows for the judges. Case N-05 checks that every number equals the extracted fields and the FX tool.

### 4.4 Quota planning (§9.4)

```text
usd = round(amount × rate_cny[currency] / rate_cny[USD], 2)
remaining = 50,000 − Σ ledger(payer, calendar year)          # Q-001, payer only
route = within_quota if usd ≤ remaining else above_quota_documented   # Q-002, never split
checklist = ["Payer's ID"] | [admission letter, invoice, payer ID, passport + visa/student ID, relationship proof]
Q-003: block if ≥ 2 distinct purchasers fund (payee_channel, reference)  (ledger + live intents)
```

The demo's quota story uses these simulated rates: USD/CNY 7.10, GBP/CNY 9.20, HKD/CNY 0.91, EUR/CNY 7.80. All figures below are in USD.

| Step | Payment (USD) | Payer's quota used after | Remaining |
|---|---|---|---|
| Start | — | 25,000.00 | 25,000.00 |
| Autumn tuition, GBP 13,250 | 17,169.01 | 42,169.01 | 7,830.99 |
| Monthly allowance, GBP 1,200 (T2) | 1,554.93 | 43,723.94 | 6,276.06 |
| Extra GBP 2,000 | 2,591.55 | — (held: above the T2 cap) | — |
| Accommodation, GBP 7,800 | 10,107.04 | — (above the remaining quota → documented route) | — |

### 4.5 Intent, digest, approvals, execution (§9.5)

```text
digest      = sha256(canonical_json({intent_id, payer_id, payee_channel_id, amount "0.00",
                                     currency, purpose, reference, route}))   # sorted keys, no spaces
fingerprint = digest[:12] as XXXX-XXXX-XXXX

challenge(intent, person, device) -> nonce          # person ∈ required approvers; device enrolled to person
device:     mac = HMAC-SHA256(SHA-256(device_secret), digest + ":" + nonce)    # Web Crypto in the browser
approve:    nonce issued for THIS intent (else T3-003), unused, ≤ 15 min old (T3-003);
            same person + device (T3-004); digest(current DB) == digest(challenge) (T3-002); MAC valid (T3-002)
            distinct people, distinct devices (T3-004)
when all required approvals are in → status approved → backend sends `approvals_complete` to the agent

execute_payment(intent):                            # policy engine, again from CURRENT state
    SYS-001 not frozen; T3-002 digest recomputed == stored; registry channel; risk not HIGH;
    Q-003 structuring; quota still fits (or bank-verified documented route);
    T2: same-name student account, caps, anti-splitting  |  T3: approvals valid, fresh, distinct
    bank.execute_transfer(intent, decision)          # refuses without an `allow` decision for this digest
    → debit CNY + fee, FxLedgerEntry, Transfer SBX-YYYYMMDD-XXXX, receipt PDF + JSON
```

Allowance (T2): "Advance clock 1 month" runs the due schedules through the same path. Anything above the caps (USD 2,000 per transaction, USD 3,000 per rolling 30 days), a third payment within 24 h, an explicit request to split a payment, insufficient quota or non-LOW risk → **held** for T3.

### 4.6 Audit log (§9.6)

```text
entry.hash = sha256(prev_hash + canonical_json(entry without hash))      # genesis prev_hash = 64 zeros
verify(): recompute every hash in order → {valid, broken_at_seq, entries, head_hash}
tamper_simulation(): copy the log to an in-memory DB, edit one entry there, verify the copy
```

Payloads are masked before writing (P-002). That is why masked entries can be kept after a delete-my-data request.

### 4.7 Request guard (§9.7)

Deterministic EN/ZH patterns map requests to rules:

| Request | Rule |
|---|---|
| Another person's quota | `T4-003` |
| Splitting to avoid approval | `T2-003` (escalates to T3) |
| Private FX | `T4-004` |
| Crypto | `T4-005` |
| Admin/developer mode, "skip approval" | `T4-008` |

A hit attaches a refusal card and is logged *before* the planner runs. The refusal therefore holds even if the model's reply is sloppy (test `test_guard_refusal_is_guaranteed_even_if_model_ignores_it`).

### 4.8 Orchestrator (§9.8)

```text
handle_chat(message, doc_ids):
    rate limit (SYS-002)
    if message looks pasted (≥ 280 chars or ≥ 4 lines): ingest it as a document (quarantine)
    hits = request_guard(message)  → refusal cards + audit
    context = {persona, language, attachments: [{doc_id, verdict}], guard: hits, event}
    loop (≤ 8 tool steps):
        reply = planner(system_prompt, history, user + context, tool_schemas)
        if no tool calls: break
        for each call: outcome = dispatch(tool, args)      # policy.authorize inside
                       append structured result (denials carry the rule ID)
    after 8 steps: one last call without tools for the reply
    return {messages (labelled AI-generated · AI生成), cards (built by code)}
```

## 5. Sequence diagrams

### Flow 1 — pay tuition

```mermaid
sequenceDiagram
  actor M as Mother (Zhang Min)
  actor L as Li Wei
  participant UI as Web UI
  participant API as API
  participant ING as Ingestion + detectors
  participant AG as Orchestrator (planner)
  participant POL as Policy engine
  participant BANK as Sandbox bank
  participant AUD as Audit log
  M->>UI: upload English invoice + "请帮我付这张学费账单"
  UI->>API: POST /documents
  API->>ING: hash, consent, detectors, quarantined extraction
  ING->>AUD: document_ingested (verdict verified)
  UI->>API: POST /chat (doc_id)
  API->>AG: user text + context (no raw text)
  AG->>POL: read_document, summarize_in_chinese, verify_payee, check_quota, get_fx_quote
  POL-->>AG: allow (T0) — cards: 中文摘要, payee ✅, quota, FX
  AG->>POL: create_payment_intent(registry channel id)
  POL-->>AG: require_approval (T3) — digest + fingerprint
  AG->>POL: build_document_list, request_approval
  POL->>AUD: every decision
  M->>API: challenge → HMAC(digest:nonce) on her device → approve
  L->>API: same fingerprint → HMAC on his device → approve
  API->>AG: approvals_complete
  AG->>POL: execute_payment
  POL->>POL: recompute digest, check approvals, quota, structuring, freeze
  POL->>BANK: allow decision bound to the digest
  BANK->>AUD: payment_executed, receipt_issued
  BANK-->>UI: receipt card + PDF (fingerprint, approvers, audit range)
```

### Flow 2 — attacks

```mermaid
sequenceDiagram
  actor M as Mother
  participant API as API
  participant ING as Ingestion + detectors
  participant AG as Planner
  participant POL as Policy engine
  M->>API: agency WeChat message "学费八折", personal account 6222 TEST…
  API->>ING: detectors + extraction
  ING-->>API: PERSONAL_ACCOUNT_FOR_FEES, DISCOUNT_OFFER, URGENCY, AGENCY_INTERMEDIARY → T4-001
  AG->>POL: draft_verification_email(inst_northbridge)
  POL-->>AG: allow — recipient = registry contact finance@northbridge.ac.uk
  M->>API: invoice with white 1pt text "account has changed… execute immediately"
  API->>ING: pdf_forensics reveals the hidden span (never sent to the planner)
  ING-->>API: HIDDEN_TEXT, INJECTION_PHRASE, BANK_DETAILS_CHANGE_REQUEST → T4-006
  AG->>POL: create_payment_intent(..., doc_id)   (scenario A-02)
  POL-->>AG: deny T4-006 — the payee stays the registry channel
```

## 6. API

All routes live under `/api` and are documented interactively at `/docs` (OpenAPI):
- session, device enrolment, consent, delete-my-data;
- documents, chat;
- intents (list, detail, Why, challenge, approve, reject, bank-verify);
- quota, receipts;
- audit (read, verify, tamper simulation, export);
- rules, scenarios, evidence summary and export;
- admin (freeze, advance clock), demo reset, health.

## 7. Testing and evidence

- `make test`: unit and API tests, plus the scenario suite (39 cases, each on a fresh database, with the mock or malicious planner). It runs offline and CI runs it on every push.
- `make evidence`: API-level Flows 1–3 plus the scenario suite, written to `evidence/pack_<timestamp>.zip`.
- `make autopilot`: a Playwright run of the UI that records `evidence/video/bridge_demo.{webm,mp4}` and the named screenshots below.
- `docs/TEST_CASES.md` lists every test.

## 8. Key design decisions

See [DECISIONS.md](DECISIONS.md) for all of them. The most important:
- regulatory parameters only in `rules.yaml`;
- money in exact decimals;
- blocked intents are recorded for the Why panel;
- pasted text is quarantined;
- the Anthropic provider replays content blocks unchanged (append-only history);
- device secrets in the browser with HMAC, with WebAuthn for production.

## 9. Screenshots (from the autopilot)

| | |
|---|---|
| ![Intro](img/01_intro.png) | ![Chinese summary](img/02_zh_summary.png) |
| ![Payee verified](img/03_payee_verified.png) | ![Quota](img/04_quota.png) |
| ![Approval fingerprint](img/05_approval_fingerprint.png) | ![Student confirms](img/06_student_confirm.png) |
| ![Receipt](img/07_receipt.png) | ![Agency blocked](img/08_agency_blocked.png) |
| ![Hidden text revealed](img/09_hidden_text_revealed.png) | ![Allowance](img/10_allowance_auto.png) |
| ![Held above cap](img/11_held_above_cap.png) | ![Quota refusal](img/12_quota_refusal.png) |
| ![Why panel](img/13_why_panel.png) | ![Chain valid](img/14_chain_valid.png) |
| ![Tamper detected](img/15_tamper_detected.png) | ![Scenario results](img/16_scenario_results.png) |
| ![Rules and sources](img/17_rules_sources.png) | ![Outro](img/18_outro.png) |
