/* eslint-disable @typescript-eslint/no-explicit-any */
import { useState } from "react";
import { Card } from "../lib/api";
import { money, usd } from "../lib/format";
import { useStore } from "../lib/store";
import { Chip, RuleChecks, Seal, Shell, SourceText, StatusBadge } from "./common";
import { IntentCard } from "./IntentCard";

export function CardView({ card, delay }: { card: Card; delay: number }) {
  switch (card.type) {
    case "zh_summary":
      return <ZhSummary c={card} delay={delay} />;
    case "payee_check":
      return <PayeeCheck c={card} delay={delay} />;
    case "quota":
      return <Quota c={card} delay={delay} />;
    case "fx_quote":
      return <FxQuote c={card} delay={delay} />;
    case "intent":
      return <IntentCard c={card} delay={delay} />;
    case "refusal":
      return <Refusal c={card} delay={delay} />;
    case "checklist":
      return <Checklist c={card} delay={delay} />;
    case "email_draft":
      return <EmailDraft c={card} delay={delay} />;
    case "receipt":
      return <Receipt c={card} delay={delay} />;
    case "clarify":
      return <Clarify c={card} delay={delay} />;
    case "explanation":
      return <Explanation c={card} delay={delay} />;
    case "approval_status":
      return <ApprovalStatus c={card} delay={delay} />;
    default:
      return null;
  }
}

type P = { c: any; delay: number };
const TONE_TEXT = { pass: "text-pass", warn: "text-warn", block: "text-block" } as const;

function ZhSummary({ c, delay }: P) {
  const tone = c.verdict === "blocked" ? "block" : c.verdict === "verified" ? "pass" : c.verdict === "warning" ? "warn" : undefined;
  return (
    <Shell testid="card-zh-summary" eyebrow="中文摘要 · Chinese summary" tone={tone} delay={delay}
      right={<Chip tone="neutral" title="Every number comes from the extracted fields and the FX tool">Numbers from code</Chip>}>
      <p lang="zh-CN" className="text-[17px] leading-[1.75] text-ink">{c.zh}</p>
      <p className="mt-2 border-t border-dashed border-rule pt-2 text-[13px] italic leading-relaxed text-ink-mute">{c.en}</p>
      {c.ai_note && (
        <div className="mt-2 rounded-md bg-paper-sunk px-3 py-2 text-[13.5px]">
          <span className="chip-neutral mr-2">{c.ai_note.label}</span>
          {c.ai_note.text}
        </div>
      )}
    </Shell>
  );
}

function PayeeCheck({ c, delay }: P) {
  const tone = c.verdict === "verified" ? "pass" : c.verdict === "blocked" ? "block" : c.verdict === "warning" ? "warn" : undefined;
  const title =
    c.verdict === "verified" ? "Payee verified against the registry" :
    c.verdict === "blocked" ? `Payment blocked${c.forbidden_rule ? ` — ${c.forbidden_rule}` : ""}` :
    c.verdict === "warning" ? "Caution: verify before paying" :
    c.verdict === "no_payee" ? "No payment details in this document" : "Payee not verified";
  return (
    <Shell testid="card-payee-check" eyebrow="Payee check · 收款方核验" tone={tone} delay={delay}
      right={<Chip tone={tone ?? "neutral"}>{c.level} · risk {c.score}</Chip>}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className={`font-display text-[19px] leading-tight ${tone ? TONE_TEXT[tone] : ""}`}>{title}</div>
          {c.matched_beneficiary && (
            <div className="mt-1 text-[13.5px] text-ink-soft">
              {c.matched_beneficiary} · <span className="font-mono">{c.matched_account_masked}</span> · registry channel{" "}
              <code className="font-mono text-[12px]">{c.matched_channel_id}</code>
            </div>
          )}
          {!c.matched_beneficiary && c.institution_name && (
            <div className="mt-1 text-[13.5px] text-ink-soft">Claims to be from {c.institution_name}. Registry contact: {c.official_contact_email}</div>
          )}
        </div>
        <ScoreMeter score={c.score} />
      </div>
      {c.hidden_spans?.length > 0 && (
        <div data-testid="hidden-text" className="mt-3 rounded-md border border-block-line bg-block-bg px-3 py-2.5">
          <div className="text-[12.5px] font-semibold text-block">
            Hidden text found: {c.hidden_spans.map((s: any) => s.description).join("; ")}
          </div>
          {c.hidden_spans.map((s: any, i: number) => (
            <p key={i} className="mt-1.5 font-mono text-[12.5px] leading-relaxed text-ink">“{s.text}”</p>
          ))}
          <div className="mt-1.5 text-[11.5px] text-ink-mute">Invisible to a human reader; never shown to the planner. The registered payee stays unchanged.</div>
        </div>
      )}
      {c.signals?.length > 0 && (
        <ul className="mt-3 space-y-1.5">
          {c.signals.map((s: any) => (
            <li key={s.code} className="grid grid-cols-[auto_1fr_auto] items-baseline gap-2 text-[13px]">
              <code className="font-mono text-[11.5px] text-ink-soft">{s.code}</code>
              <span className="text-ink">{s.explanation}{s.detail ? <span className="text-ink-mute"> — {s.detail}</span> : null}</span>
              <span className="num text-[12px] text-ink-mute">+{s.weight}</span>
            </li>
          ))}
        </ul>
      )}
      {c.notices?.map((n: string) => (
        <div key={n} className="mt-2 text-[13px] text-warn">⏰ {n}</div>
      ))}
    </Shell>
  );
}

function ScoreMeter({ score }: { score: number }) {
  const tone = score >= 60 ? "bg-block" : score >= 30 ? "bg-warn" : "bg-pass";
  return (
    <div className="w-28 shrink-0 text-right">
      <div className="num font-display text-[26px] leading-none">{score}</div>
      <div className="mt-1 h-1.5 w-full rounded-full bg-paper-sunk">
        <div className={`h-1.5 rounded-full ${tone}`} style={{ width: `${Math.max(3, score)}%` }} />
      </div>
      <div className="mt-1 text-[10.5px] text-ink-mute">0 · 30 · 60 · 100</div>
    </div>
  );
}

function Quota({ c, delay }: P) {
  const limit = Number(c.annual_limit_usd);
  const used = Number(c.used_usd);
  const pay = c.this_payment_usd ? Number(c.this_payment_usd) : 0;
  const fits = c.fits !== false;
  const usedPct = (used / limit) * 100;
  const payPct = Math.min((pay / limit) * 100, 100 - usedPct);
  return (
    <Shell testid="card-quota" eyebrow={`Payer's personal FX quota ${c.year} · Q-001`} tone={pay ? (fits ? "pass" : "warn") : undefined} delay={delay}
      right={<Chip tone="neutral">per person · no family quota</Chip>}>
      <div className="relative h-4 w-full overflow-hidden rounded-sm border border-rule-strong bg-paper">
        <div className="absolute inset-y-0 left-0 bg-ink" style={{ width: `${usedPct}%` }} />
        {pay > 0 && (
          <div
            className={`absolute inset-y-0 ${fits ? "bg-pass" : "bg-warn"}`}
            style={{ left: `${usedPct}%`, width: `${payPct}%`,
              backgroundImage: "repeating-linear-gradient(45deg, rgba(255,255,255,.35) 0 4px, transparent 4px 8px)" }}
          />
        )}
      </div>
      <div className="mt-1 flex justify-between text-[11px] text-ink-mute num"><span>0</span><span>USD 50,000 per calendar year</span></div>
      <dl className="kv mt-3">
        <dt>Used this year</dt><dd>{usd(c.used_usd)}</dd>
        {pay > 0 && (<><dt>This payment</dt><dd>≈ {usd(c.this_payment_usd)}</dd></>)}
        <dt>{pay > 0 ? "Remaining after" : "Remaining"}</dt>
        <dd className="font-semibold">{usd(pay > 0 ? c.remaining_after_usd : c.remaining_usd)}</dd>
      </dl>
      {pay > 0 && !fits && (
        <p className="mt-2 text-[13px] text-warn">
          Exceeds the remaining quota by {usd(c.excess_usd)} → documented route with the bank (Q-002). Never split across relatives (T4-003).
        </p>
      )}
    </Shell>
  );
}

function FxQuote({ c, delay }: P) {
  return (
    <Shell testid="card-fx-quote" eyebrow="FX quote · 汇率" delay={delay} right={<Chip tone="neutral">simulated rate</Chip>}>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="num font-display text-[24px]">{money(c.amount, c.currency)}</span>
        <span className="text-ink-mute">→</span>
        <span className="num font-display text-[24px]">{money(c.cny_amount, "CNY")}</span>
      </div>
      <dl className="kv mt-2">
        <dt>Rate</dt><dd>1 {c.currency} = CNY {c.rate_cny}</dd>
        <dt>Transfer fee</dt><dd>{money(c.fee_cny, "CNY")}</dd>
        <dt>Total debit</dt><dd className="font-semibold">{money(c.total_cny_debit, "CNY")}</dd>
        <dt>Quota counts</dt><dd>{usd(c.usd_equivalent)} (at USD/CNY {c.usd_cny_rate})</dd>
      </dl>
    </Shell>
  );
}

function Refusal({ c, delay }: P) {
  return (
    <Shell testid="card-refusal" eyebrow={`Refused · ${c.rule_id}`} tone="block" delay={delay}
      right={<Chip tone="block">{c.source_of_refusal === "request_guard" ? "request guard" : "policy engine"}</Chip>}>
      <div className="font-display text-[19px] leading-tight text-block">{c.title}</div>
      <p className="mt-1.5 text-[14px] leading-relaxed">{c.explanation}</p>
      {c.reason && <p className="mt-1 text-[13px] text-ink-soft">Why here: {c.reason}</p>}
      {c.lawful_alternative && (
        <div className="mt-3 rounded-md border border-pass-line bg-pass-bg px-3 py-2.5">
          <div className="eyebrow !text-pass">Lawful alternative · 合法做法</div>
          <p className="mt-1 text-[14px] leading-relaxed">{c.lawful_alternative}</p>
        </div>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11.5px] text-ink-mute">
        <SourceText text={c.source} /> <StatusBadge status={c.status} />
      </div>
    </Shell>
  );
}

function Checklist({ c, delay }: P) {
  const within = c.route === "within_quota";
  return (
    <Shell testid="card-checklist" eyebrow="Documents · 所需材料" tone={within ? undefined : "warn"} delay={delay}
      right={<Chip tone={within ? "pass" : "warn"}>{within ? "within quota" : "documented route"}</Chip>}>
      <ul className="space-y-1.5">
        {c.items.map((it: string) => (
          <li key={it} className="flex items-start gap-2 text-[14px]">
            <span className="mt-[3px] inline-block h-3.5 w-3.5 shrink-0 rounded-sm border border-ink-faint" />
            {it}
          </li>
        ))}
      </ul>
      <p className="mt-2.5 text-[13px] leading-relaxed text-ink-soft">{c.note}</p>
      {!within && (
        <p className="mt-1 text-[12.5px] text-ink-mute">
          {c.bank_verified ? "✅ Bank officer verified the documents (simulated)." : "Next: bank officer verification (simulated) in the Evidence Center → Controls."}
        </p>
      )}
    </Shell>
  );
}

function EmailDraft({ c, delay }: P) {
  const [copied, setCopied] = useState(false);
  return (
    <Shell testid="card-email-draft" eyebrow="Verification email draft" delay={delay} right={<Chip tone="neutral">not sent</Chip>}>
      <dl className="kv">
        <dt>To</dt>
        <dd><span className="font-mono">{c.to}</span> <Chip tone="pass">from verified registry</Chip></dd>
        <dt>Subject</dt><dd>{c.subject}</dd>
      </dl>
      <pre className="mt-3 max-h-56 overflow-auto whitespace-pre-wrap rounded-md bg-paper-sunk p-3 font-sans text-[13px] leading-relaxed">{c.body}</pre>
      <div className="mt-2 flex items-center justify-between">
        <span className="text-[12px] italic text-ink-mute">{c.label} · AI-generated · AI生成</span>
        <button className="btn-ghost !py-1 text-[12.5px]" onClick={() => { navigator.clipboard?.writeText(c.body); setCopied(true); }}>
          {copied ? "Copied" : "Copy text"}
        </button>
      </div>
    </Shell>
  );
}

function Receipt({ c, delay }: P) {
  return (
    <Shell testid="card-receipt" eyebrow={`Receipt · ${c.tier === "T2" ? "autonomous (T2)" : "approved (T3)"}`} tone="pass" delay={delay}
      right={<Chip tone="pass">Paid in sandbox</Chip>}>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="num font-display text-[26px] leading-none">{money(c.amount, c.currency)}</div>
          <div className="mt-1 text-[13px] text-ink-soft">
            Debited {money(c.total_cny, "CNY")} (incl. fee {money(c.fee_cny, "CNY")}) · rate {c.fx_rate} · bank ref{" "}
            <span className="font-mono">{c.bank_reference}</span>
          </div>
        </div>
        <Seal value={c.fingerprint} />
      </div>
      <div className="mt-3 flex items-center justify-between border-t border-rule pt-2.5">
        <span className="text-[12px] text-ink-mute">{c.watermark}</span>
        <a data-testid="receipt-pdf" className="btn-ghost !py-1 text-[12.5px]" href={c.pdf_url} target="_blank" rel="noreferrer">
          Receipt PDF ↗
        </a>
      </div>
    </Shell>
  );
}

function Clarify({ c, delay }: P) {
  return (
    <Shell testid="card-clarify" eyebrow="Question · 需要确认" delay={delay}>
      <p className="font-display text-[18px] leading-snug">{c.question}</p>
    </Shell>
  );
}

function Explanation({ c, delay }: P) {
  return (
    <Shell testid="card-explanation" eyebrow="Explanation" delay={delay}>
      <div className="font-medium">{c.title}</div>
      {c.text && <p className="mt-1 text-[13.5px] text-ink-soft">{c.text}</p>}
      {c.checks && <div className="mt-2"><RuleChecks checks={c.checks} compact /></div>}
    </Shell>
  );
}

function ApprovalStatus({ c: snap, delay }: P) {
  const { intents } = useStore();
  const live = intents[snap.intent_id]?.approvals;
  const c = live ? { ...snap, ...live } : snap;
  return (
    <Shell testid="card-approval-status" eyebrow="Approvals · T3" delay={delay} right={<span className="font-mono text-[12.5px]">{c.fingerprint}</span>}>
      <ul className="flex flex-wrap gap-2">
        {c.required.map((p: string) => (
          <li key={p}>
            <Chip tone={c.approved?.[p] ? "pass" : "warn"}>
              {c.approved?.[p] ? "✓" : "…"} {snap.names?.[p] ?? p}
            </Chip>
          </li>
        ))}
      </ul>
    </Shell>
  );
}
