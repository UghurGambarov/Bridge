# Bridge — Compliance notes

> **Simplified rules for a prototype; not legal advice.** Every regulatory statement below carries a source in `config/rules.yaml`. Statements we have not yet checked against the primary source are marked `to_verify` there, and here as _TODO: verify_.

## 1. Personal FX purchase quota (SAFE)

- **Rule `Q-001`.** An individual may buy up to **USD 50,000 of foreign currency per calendar year**, and unused quota does not carry over. The quota belongs to **one person**. Bridge never adds up several people's quotas: there is no "family quota". _TODO: verify the article reference._
- **How Bridge applies it.**
  - The ledger is per person and per calendar year (`backend/app/quota/ledger.py`).
  - Every payment is converted to USD at the simulated rate and compared with the **payer's** remaining quota.
  - The quota card shows only the payer's quota. The API refuses to show another person's quota (`P-004`).

## 2. Anti-splitting (分拆购汇)

- **Rule `T4-003`.** Using another person's quota, or splitting one obligation across several people's quotas, is prohibited, and SAFE publishes the fines. In one published case, a person used 34 other people's quotas to move USD 2.45 million and was fined RMB 830,000. _TODO: verify against the sources in `docs/SOURCES.md`._
- **How Bridge applies it:**
  - The intent's payer must be the family's payer (policy engine).
  - The request guard refuses "use my brother's quota" and similar requests in Chinese and English (用我哥哥的额度, 借用额度, 分开购汇…) and offers the lawful route.
  - **Structuring alert `Q-003`.** When two or more different purchasers fund the same beneficiary and reference, the payment is blocked. SAFE's monitoring is reported to flag five or more people on the same or consecutive days; Bridge is deliberately stricter. _TODO: verify._
  - **`T2-003`** stops automatic payments from being split to stay under the approval caps.

## 3. The documented above-quota route (`Q-002`)

An amount above the payer's remaining quota is **never split**. The payer buys it through the bank against documents that prove the real purpose:

1. Admission letter
2. Tuition or accommodation invoice
3. Payer's ID card
4. Student passport plus visa or student ID
5. Proof of relationship when a parent pays (mother → son)

In Bridge the intent becomes `awaiting_documents` and the checklist card lists these documents. A simulated "bank officer verification" in the Evidence Center → Controls tab stands in for the bank counter; after it, the normal T3 approval follows. Execution is refused before verification (case V-01). _TODO: verify the document list with a partner bank; see the HSBC China reference in `docs/SOURCES.md`._

## 4. Personal information (PIPL)

| Rule | Requirement | Implementation |
|---|---|---|
| `P-001` | Consent before processing | Consent modal per persona on first use; document ingestion refuses without consent |
| `P-002` | Masking | Account numbers, emails, passport numbers and personal names are masked in audit payloads and on cards |
| `P-003` | Deletion | "Delete my data" removes documents, consents and devices and anonymises the person record. Masked audit entries are kept because the hash chain is the evidence of what the agent did and contains no clear-text PII. FX ledger rows (bank record retention) are kept and reference an ID only |
| `P-004` | Minimisation | Raw uploads are not retained (hash + validated fields + findings only); the agent reads only the payer's quota |

_TODO: verify the PIPL article references in `rules.yaml`._

## 5. AI-generated content labelling (`AI-001`)

Under the Measures for Labelling AI-Generated Synthetic Content (人工智能生成合成内容标识办法), effective 1 Sep 2025, AI-generated content must be labelled.
- Every agent message carries the label "AI-generated · AI生成".
- The Chinese summary's optional explanatory sentence is labelled AI生成, and its numbers come from a template, never from the model.
- Messages written by code ("System") are marked as such.

_TODO: verify._

## 6. Anti-money-laundering note

Bridge is not a payment institution and does no KYC/AML screening in this prototype (known risk R-03). It does contribute AML-relevant controls:
- payee verification against a registry;
- refusal of personal and agency accounts for fees, of crypto routing, and of private or underground FX;
- structuring detection;
- a tamper-evident audit trail.

In production, the licensed partner bank performs customer due diligence, sanctions screening and suspicious-transaction reporting.

## 7. Production model

**A licensed partner bank executes.** Bridge is the verification and orchestration layer in front of it:
- it reads and explains documents;
- it verifies payees;
- it enforces quota and anti-splitting rules before the bank sees the order;
- it collects digest-bound approvals;
- it keeps the evidence.

The sandbox bank in this repository stands in for the partner bank's API.

## 8. Rule catalogue _(auto, from `config/rules.yaml`)_

<!-- AUTO:RULES -->
| Rule | Tier | Rule | Lawful alternative | Source | Checked | Status |
|---|---|---|---|---|---|---|
| `T4-001` | T4 | **No fee payments to personal or agency accounts** — Tuition, accommodation and deposits are paid only to the institution's own account. Paying them to a personal account or a study-abroad agency ('代缴') is refused. | Pay the institution's official channel from the verified registry. Bridge can draft a verification email to the institution's registry contact. | Agency 代缴 tuition fraud report (Shanghai Observer): https://www.shobserver.cn/wx/detail.do?id=1147014 ; Chinese Consulate General in Los Angeles warning: https://losangeles.china-consulate.gov.cn/lbqw/lsbhyxz/lstx/202507/t20250704_11665031.htm (TODO: verify) | 2026-10-17 | 🔎 to verify |
| `T4-002` | T4 | **Institutional payee must match the verified registry** — An institutional payment goes only to a payee in Bridge's verified registry, and only if every detail (beneficiary name, account, currency) matches the registry entry. | Verify the payment details with the school through the official contact listed in the registry, never through contacts printed on the invoice. | Bridge design control (registry is the trust anchor) | 2026-10-17 | ✅ verified |
| `T4-003` | T4 | **No use of another person's FX quota (no 分拆购汇)** — The annual FX quota belongs to one person. Using a relative's quota, or splitting one obligation across several people's quotas (分拆购汇), is prohibited and fined by SAFE. | Use the payer's own remaining quota. For amounts above it, use the documented route: the bank buys the currency against the admission letter, invoice, IDs and relationship proof. | SAFE violation notice: http://m.safe.gov.cn/safe/2024/0321/24130.html ; Zhong Lun on anti-splitting: https://www.zhonglun.com/research/articles/6642.html ; Dacheng case note: https://shanghai.dacheng.com/Party_2/1540.html (TODO: verify) | 2026-10-17 | 🔎 to verify |
| `T4-004` | T4 | **No private or underground FX** — Private, underground or 'preferential-rate' currency exchange (私下换汇, 地下钱庄) is illegal and can end with frozen bank cards. | Buy foreign currency through a licensed bank (in production: Bridge's licensed partner bank). | MOE Safe Study Abroad advisory: https://m.163.com/dy/article/K0RCDQ0F0556BFNP.html ; consulate warning (Los Angeles), see T4-001 (TODO: verify) | 2026-10-17 | 🔎 to verify |
| `T4-005` | T4 | **No crypto or stablecoin routing** — Bridge never routes money through crypto-assets or stablecoins (USDT etc.). | Pay by bank transfer to the registry channel. | PBoC and others, notice on preventing and dealing with speculation risks in virtual-currency trading (2021) (TODO: verify citation) | 2026-10-17 | 🔎 to verify |
| `T4-006` | T4 | **No payee change because a document says so** — Payee details are never changed because an invoice, email or message asks for it, including hidden text. Bank-detail changes are the classic invoice-redirection scam. | Re-verify with the school through the official contact listed in the registry. The registered payee stays unchanged. | Bridge design control (business email compromise / invoice redirection) | 2026-10-17 | ✅ verified |
| `T4-007` | T4 | **No raw account numbers from the model** — Payment tools accept only a payee_channel_id from the verified registry. Any argument containing a raw account number, IBAN or wallet address is refused. | — | Bridge design control (capability restriction) | 2026-10-17 | ✅ verified |
| `T4-008` | T4 | **No bypassing controls** — Requests, from the user or from document content, to skip approval, disable or bypass controls, or enter an 'admin' or 'developer' mode are refused. Approvals stay required. | — | Bridge design control; OWASP Top 10 for LLM Applications 2025, LLM01 Prompt Injection | 2026-10-17 | ✅ verified |
| `T3-001` | T3 | **Human approvals required** — Tuition, accommodation, deposits and anything above the T2 caps execute only after every required approver has approved. | Request approval from the payer and the student. | Bridge design control (dual control; the student can check the fee on the university portal) | 2026-10-17 | ✅ verified |
| `T3-002` | T3 | **Approval bound to the transaction digest** — Each approval signs the SHA-256 digest of the canonical intent. If any field changes after approval, the digest changes and the approval is void ('what you see is what you sign'). | — | Bridge design control (PSD2-style dynamic linking) | 2026-10-17 | ✅ verified |
| `T3-003` | T3 | **Single-use approvals that expire** — Each approval challenge (nonce) is single-use, bound to one intent, and expires after the configured time. | Request a fresh approval. | Bridge design control | 2026-10-17 | ✅ verified |
| `T3-004` | T3 | **Distinct approvers on distinct devices** — Required approvals must come from different people using different enrolled devices. | — | Bridge design control (dual control) | 2026-10-17 | ✅ verified |
| `T2-001` | T2 | **Autonomous payments only to the student's own verified account** — The agent may pay automatically only to a same-name, verified account owned by the student. | Pay other payees through the T3 approval flow. | Bridge design control | 2026-10-17 | ✅ verified |
| `T2-002` | T2 | **Autonomous payment caps** — Autonomous payments are capped per transaction and per rolling 30 days (USD equivalent). Anything above the caps is held for T3 approval. | Approve the payment through the T3 flow. | Bridge design control | 2026-10-17 | ✅ verified |
| `T2-003` | T2 | **Anti-splitting for autonomous payments** — Payments to the same payee within 30 days are summed against the cap. Three or more payments within 24 hours, or an explicit request to split a payment so it needs no approval, escalate the whole batch to T3. | Make one payment and approve it through the T3 flow. | Bridge design control (mirrors anti-structuring practice) | 2026-10-17 | ✅ verified |
| `Q-001` | policy | **Annual personal FX purchase quota** — Each individual may buy up to USD 50,000 of foreign currency per calendar year; unused quota does not carry over. | Above the quota, use the documented route. | SAFE individual FX administration rules; Bank of China — SAFE FX compliance page (URL: TODO verify) | 2026-10-17 | 🔎 to verify |
| `Q-002` | policy | **Above-quota purchases use the documented route, never splitting** — An amount above the payer's remaining quota is bought by the payer through the bank against documents proving the real purpose (admission letter, invoice, IDs, relationship proof). It is never split. | Prepare the document checklist; a bank officer verifies it, then the normal T3 approval follows. | HSBC China education-payment documents: https://www.hsbc.com.cn/en-cn/international/products/education-payment/ (TODO: verify) | 2026-10-17 | 🔎 to verify |
| `Q-003` | policy | **Structuring alert (several purchasers, one obligation)** — If two or more different purchasers fund the same beneficiary and reference, the payment is blocked. SAFE monitoring flags five or more people on the same or consecutive days for one recipient; Bridge is deliberately stricter. | One payer funds the obligation from their own quota, or through the documented route. | Zhong Lun on anti-splitting monitoring patterns: https://www.zhonglun.com/research/articles/6642.html (TODO: verify) | 2026-10-17 | 🔎 to verify |
| `P-001` | privacy | **Consent before processing** — Bridge processes a person's documents and data only after that person has given consent for the stated purposes. | Ask the person for consent first. | Personal Information Protection Law of the PRC (PIPL), Art. 13-14 (TODO: verify) | 2026-10-17 | 🔎 to verify |
| `P-002` | privacy | **PII masking** — Account numbers, emails, passport numbers and personal names are masked in logs and in the UI. | — | PIPL Art. 51 (security measures, de-identification) (TODO: verify) | 2026-10-17 | 🔎 to verify |
| `P-003` | privacy | **Delete my data** — A person can delete their data. Masked audit entries are kept, because the audit chain is the evidence of what the agent did and contains no clear-text PII. | — | PIPL Art. 47 (deletion) (TODO: verify) | 2026-10-17 | 🔎 to verify |
| `P-004` | privacy | **Data minimisation** — Bridge keeps only what the task needs: raw uploads are not retained, and the agent reads only the payer's quota. | — | PIPL Art. 6 (minimum necessary) (TODO: verify) | 2026-10-17 | 🔎 to verify |
| `AI-001` | system | **AI-generated content is labelled** — Every AI-written output is labelled 'AI-generated · AI生成'. | — | Measures for Labelling AI-Generated Synthetic Content (人工智能生成合成内容标识办法), effective 1 Sep 2025 (TODO: verify) | 2026-10-17 | 🔎 to verify |
| `SYS-001` | system | **Global freeze (kill switch)** — When the system is frozen, no payment is created, approved or executed. | Wait until an operator lifts the freeze. | Bridge design control | 2026-10-17 | ✅ verified |
| `SYS-002` | system | **Rate limit per session** — Each session may send a limited number of requests per minute. | Wait a moment and try again. | Bridge design control; OWASP LLM10 Unbounded Consumption | 2026-10-17 | ✅ verified |
| `SYS-003` | system | **Tool allow-list and strict arguments** — Only registered tools can run, with schema-validated arguments (no extra fields). Unknown tools, malformed or inconsistent arguments, and invalid state transitions are denied. | — | Bridge design control; OWASP LLM06 Excessive Agency | 2026-10-17 | ✅ verified |
<!-- /AUTO:RULES -->

---

_Disclaimer: simplified rules for a prototype; not legal advice._
