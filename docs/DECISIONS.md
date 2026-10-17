# Design decisions

Where the spec was ambiguous we picked the simplest option that preserves the security guarantees (SPEC §17). Each entry: decision → why.

## Phase 1 — domain and security kernel

1. **Python 3.11 target, tested locally on 3.13.** The code avoids 3.12+ syntax; CI and Docker pin 3.11.
2. **Device key storage.** HMAC key = SHA-256(device_secret). The server stores only that hash (`Device.secret_hash`); the raw secret is returned once at enrolment and lives in the persona's browser. A database leak would still allow forging approvals, which is listed as known risk R-09; production uses WebAuthn / passkeys (asymmetric keys that never leave the device).
3. **Extra rule `SYS-003` (tool allow-list and strict arguments).** The spec requires unknown tools and extra fields to be denied but gives no rule ID; `SYS-003` names that control so every denial cites a rule.
4. **Any prompt-injection phrase in a payment document is forbidden (`T4-008`)**, not just scored. Content that instructs the AI is untrustworthy by definition; this is stricter than the score alone and costs little in false positives on real invoices.
5. **Forbidden-rule priority for documents:** crypto `T4-005` → personal account `T4-001` → bank-detail change `T4-006` → registry mismatch `T4-002` → injection `T4-008` → any other HIGH score `T4-002`. All signals are still shown.
6. **Sandbox clock.** `now = 2026-10-17 10:00 (Beijing) + real time since seeding + offset`. Dates in tests and demos are deterministic; "Advance clock" adds calendar months. Datetimes are stored naive, in Beijing time.
7. **Money.** Stored as exact decimal text, computed with `Decimal`, rounded half-up to cents at each conversion. USD equivalents (for the quota) go through CNY: `usd = round(amount × rate_cny / USD_CNY)`. The CNY 50 fee is a CNY charge and does not count toward the FX quota.
8. **Blocked intents are recorded** (status `blocked`, with the rule trace) whenever payer and channel are valid, so the Why panel and evidence can show them. Requests that fail schema, `T4-007`, `T4-003` or name an unknown channel create no intent.
9. **`held` = a T2 payment escalated to T3.** It is approved exactly like `pending_approval`.
10. **`T2-003` window.** Executed transfers to the same payee in the last 24 h are counted; the third and later attempts escalate. Earlier payments were individually within limits and already executed. The rolling 30-day cap catches the sum.
11. **`Q-003` counts live intents too**, not only executed ledger rows, so two purchasers cannot race to fund the same reference.
12. **Rotated text** (for example the `SANDBOX SAMPLE` watermark) is kept out of the extractor's input but is still scanned by the detectors.
13. **Data minimisation (`P-004`).** Raw uploads are not retained: we keep the SHA-256, the validated extracted fields and the findings (including hidden-span text, so the UI can reveal it). The agent can read only the payer's quota.
14. **Delete-my-data (`P-003`).** Documents, consents and devices are deleted and the person record is anonymised. Masked audit entries stay (they are the evidence chain and contain no clear-text PII). FX ledger rows stay because a bank must keep FX purchase records; they reference an ID only.
15. **Approval freshness (`T3-003`).** A challenge expires 15 minutes after issue, and at execution each approval must be at most 15 minutes old.
16. **`schedule_allowance` creates an inactive schedule** that the payer activates. Creating a standing autonomous instruction is a preparation step (T1), not an action.
17. **Autonomous allowance needs quota.** If the payer's remaining quota is too small, the allowance is held and the documented route is suggested (case T-04).
18. **No `make` on the Windows dev machine.** The Makefile targets the Linux CI and Docker; each target's command can be run directly.

## Phase 2 — agent and API

19. **`ask_clarifying_question` is a T0 tool.** The spec needs a `clarify` card for vague requests; making it a read-only tool keeps every card code-built and lets case N-04 assert that no T1+ tool ran.
20. **Pasted content is quarantined.** A chat message of 280+ characters or 4+ lines is ingested as a text document; the planner sees only a note, the document ID and (if short and harmless) the user's last line. This keeps the dual-LLM guarantee when someone pastes a WeChat message instead of uploading it.
21. **What the planner sees from a document:** schema-validated fields with account numbers masked and free-text fields sanitised (invisible characters stripped, any injection phrase replaced, truncated), plus detector counts. Never raw text, never hidden-span text.
22. **Step budget.** At most 8 tool calls per turn; after the 8th, one last call *without tools* lets the model write its reply.
23. **Execution after approvals.** When the last approval arrives, the API runs the agent with an `approvals_complete` event and the agent calls `execute_payment`, which the policy engine re-checks in full. The approval routes themselves never move money.
24. **Anthropic provider** uses the official `anthropic` SDK as an optional dependency (lazy import), default model `claude-opus-5-5`, effort `medium`, server-side refusal fallbacks enabled (`fallbacks: "default"`). Assistant content blocks (including thinking blocks) are stored and replayed unchanged, so the planner history is append-only. The OpenAI-compatible provider uses plain `httpx`.
25. **AI note in the Chinese summary** (real models only) is dropped if it contains any digit, so numbers can only come from the template.
26. **Status messages written by code** (allowance sent, bank verification) are labelled "System", not "AI-generated"; every planner message carries the AI-001 label.
27. **Scenario runner** drives the real API through FastAPI's TestClient on a fresh temp database per case. Rule IDs are collected from the audit log, cards and API errors, so a case passes only if the control actually fired.
28. **App factory.** Run with `uvicorn app.main:create_app --factory`; tests and the scenario suite build isolated apps with their own engine and LLM.
29. **Uploads** are limited to PDF, TXT and EML files of at most 5 MB.
30. **Admin endpoints are unauthenticated in the sandbox** (freeze, advance clock, reset). Every call is audited; production needs operator authentication (known risk R-14).
