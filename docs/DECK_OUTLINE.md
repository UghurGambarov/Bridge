# Bridge — deck outline (≤ 10 minutes)

The team builds the slides from this outline, the screenshots in `docs/img/` (made by `make autopilot`) and the live numbers below (refreshed by `make docs`). Target about 50 seconds per slide; slide 11 is the buffer.

**Live results** _(auto)_

<!-- AUTO:RESULTS -->
Scenario suite run 2026-10-17T18:42:19 with model **MOCK — tests only**: **100.0% pass rate (39/39)**.

| Category | Passed | Total | Pass rate |
|---|---|---|---|
| normal | 7 | 7 | 100.0% |
| violation | 10 | 10 | 100.0% |
| attack | 18 | 18 | 100.0% |
| autonomy | 4 | 4 | 100.0% |
<!-- /AUTO:RESULTS -->

| # | Slide | Content | Screenshot | Speaker notes |
|---|---|---|---|---|
| 1 | **Problem** | "Chinese families struggle to pay tuition abroad safely and legally because of scams and foreign-exchange quota rules; existing tools only compare fees and do not check the payee or the rules; our agent verifies the payee, enforces the limits, and completes the payment under human approval." Plus 3 evidence bullets: (1) "real admission + fake fee payment" fraud in Wenzhou, about 10 students lost their places, > RMB 1M; (2) USD 50,000 per person per calendar year; above that, documents; (3) quota splitting (分拆购汇) is fined — one case: 34 people's quotas, USD 2.45M, RMB 830,000 fine | — | Open with the Wenzhou case. Sources in `docs/SOURCES.md` (to verify before the final). |
| 2 | **Persona** | Li Wei (19, Northbridge University, UK) and his mother Zhang Min (Hangzhou), who pays and cannot comfortably read English invoices | `01_intro` | Everything is fictional and sandboxed. |
| 3 | **Solution** | What Bridge does in 6 steps + architecture; theme "AI as a financial participant" — it completes tasks, not just advice | `18_outro` / Mermaid in `docs/TECHNICAL.md` | "The AI proposes, the policy engine decides, humans approve." |
| 4 | **Flow 1 — tuition paid safely** | Chinese summary → payee verified → personal quota → fingerprint → Li Wei confirms → receipt | `02`–`07` | Point at the same fingerprint on both devices: that second check stops agency fraud. |
| 5 | **Flow 2 — attacks blocked** | Agency "20% off" to a personal account → T4-001 + verification email to the registry address; hidden white text → revealed, T4-006, payee unchanged | `08`, `09` | The planner never saw the hidden text; the detectors did. |
| 6 | **Flow 3 — autonomy and a helpful refusal** | Monthly allowance auto-paid (T2); £2,000 above the cap → held; "use my brother's quota" → T4-003 + documented route | `10`–`12` | Real autonomy inside limits; refusals that help. |
| 7 | **Security design** | 5 patterns (dual-LLM, single choke point, capability restriction, digest-bound approval, tamper-evident audit) + tier table T0–T4 | `13` | A fully compromised model still cannot move money: cases A-10 to A-13 use a malicious planner. |
| 8 | **Compliance** | SAFE personal quota, anti-splitting, documented route; PIPL consent / masking / deletion; AI labels (1 Sep 2025); every rule with a source and status | `17` | Show the "to verify" badges honestly. |
| 9 | **Results** | Pass rate by category; attack table; chain verification; tamper detection | `14`–`16` | Numbers from the live report above. |
| 10 | **Risks & roadmap** | Known risks (`docs/SECURITY_SELF_ASSESSMENT.md` §7); licensed partner bank executes; WebAuthn approvals; live, signed registry; native-speaker review of Chinese text | — | Be explicit about what is simulated. |
| 11 | **Team** | — | — | — |

## Judging criteria map (40 / 30 / 30)

| Criterion | Weight | Where Bridge shows it |
|---|---|---|
| Task completion | 40% | Flow 1 end to end (upload → approvals → paid → receipt), allowance autonomy, documented route, evidence pack |
| Security & compliance | 30% | Policy engine T0–T4, digest-bound approvals, dual-LLM quarantine, scenario suite with attack cases, audit chain, rules with sources, PIPL controls |
| Innovation & interaction | 30% | Chinese–English bridge for the mother, two-person fingerprint check, revealed hidden text, refusals with the lawful route, Why panel, Evidence Center |
