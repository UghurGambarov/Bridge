/* eslint-disable @typescript-eslint/no-explicit-any */
import { useEffect, useState } from "react";
import { Chip, Seal } from "../cards/common";
import { canApprove } from "../cards/IntentCard";
import { api, ApiError } from "../lib/api";
import { money, personaName, PERSONA, usd } from "../lib/format";
import { useStore } from "../lib/store";

function Backdrop({ children, testid }: { children: React.ReactNode; testid: string }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-6 backdrop-blur-[2px]">
      <div data-testid={testid} role="dialog" aria-modal="true" className="card rise max-h-[92vh] w-full max-w-[640px] overflow-y-auto !bg-paper-raised">
        {children}
      </div>
    </div>
  );
}

export function ApprovalModal() {
  const { approvalFor, openApproval, intents, persona, approve, reject, notify } = useStore();
  const [detail, setDetail] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const live = approvalFor ? intents[approvalFor] : undefined;

  useEffect(() => {
    setError(null);
    if (approvalFor) api.intent(approvalFor).then(setDetail).catch(() => setDetail(null));
    else setDetail(null);
  }, [approvalFor, live?.status, live?.approvals?.waiting_for?.length]);

  if (!approvalFor || !detail) return null;
  const d = { ...detail, ...(live ?? {}) };
  const student = persona === PERSONA.student;
  const mine = canApprove(d, persona);
  const waiting: string[] = d.approvals?.waiting_for ?? [];
  const checks: any[] = d.rule_checks ?? [];
  const c = (r: string) => checks.filter((x) => x.result === r).length;

  const doApprove = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await approve(approvalFor);
      if (r.complete) {
        openApproval(null);
        notify("Both approvals received — the agent is executing through the policy engine.");
      }
    } catch (e) {
      setError(e instanceof ApiError ? `${e.ruleId ?? ""} ${e.reason}` : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Backdrop testid="approval-modal">
      <div className="border-b border-rule px-6 py-4">
        <div className="eyebrow">{student ? "Confirm on Li Wei's device" : "Approve on your device · 在您的设备上审批"}</div>
        <div className="mt-1 font-display text-[24px] leading-tight">
          {student ? "Does this match your Northbridge student portal?" : "What you see is what you sign"}
        </div>
      </div>
      <div className="space-y-4 px-6 py-5">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <div className="num font-display text-[34px] leading-none">{money(d.amount, d.currency)}</div>
            <div className="mt-1 text-[13px] text-ink-soft">{d.purpose} · {d.route === "within_quota" ? "within quota" : "documented route (bank-verified)"} · tier {d.tier}</div>
          </div>
          <Seal value={d.fingerprint} />
        </div>
        <dl className="kv rounded-md border border-rule bg-paper px-4 py-3">
          <dt>Payee</dt>
          <dd>{d.payee.beneficiary_name} <span className="font-mono text-[12.5px]">{d.payee.account_masked}</span> {d.payee.verified && <Chip tone="pass">✓ registry-verified</Chip>}</dd>
          <dt>Reference</dt><dd className="font-mono">{d.reference ?? "—"}</dd>
          <dt>Due date</dt><dd>{d.due_date ?? "—"}</dd>
          <dt>FX rate</dt><dd>1 {d.currency} = CNY {d.fx_rate} <span className="text-ink-mute">(simulated)</span></dd>
          <dt>CNY debit</dt><dd>{money(d.cny_equivalent, "CNY")}</dd>
          <dt>Fee</dt><dd>{money(d.fee_cny, "CNY")}</dd>
          <dt>Total</dt><dd className="font-semibold">{money(d.total_cny, "CNY")}</dd>
          <dt>Quota after</dt><dd>{usd(d.quota_after_usd)} left of the payer's USD 50,000</dd>
        </dl>
        <div className="flex flex-wrap items-center gap-2 text-[12.5px]">
          <span className="eyebrow mr-1">Rule checks</span>
          <Chip tone="pass">✅ {c("pass")}</Chip>
          <Chip tone="warn">⏸ {c("needs_approval")}</Chip>
          <Chip tone="block">⛔ {c("block")}</Chip>
          <span className="text-ink-mute">full trace in the Why panel</span>
        </div>
        <div className="rounded-md bg-paper-sunk px-4 py-3 text-[13.5px]">
          {d.approvals?.required.map((p: string) => (
            <div key={p} className="flex items-center justify-between py-0.5">
              <span>{personaName(p)}</span>
              {d.approvals.approved?.[p] ? <Chip tone="pass">✓ approved {d.approvals.approved[p].slice(11, 16)}</Chip> : <Chip tone="warn">waiting</Chip>}
            </div>
          ))}
          {!mine && waiting.length > 0 && (
            <div data-testid="approval-waiting" className="mt-2 font-medium text-warn">
              Waiting for {waiting.map((p) => (p === PERSONA.student ? "Li Wei's confirmation" : `${personaName(p)}'s approval`)).join(" and ")}.
            </div>
          )}
        </div>
        {student && mine && (
          <p className="text-[13px] text-ink-soft">Check that the amount and reference match your student portal. This second check is what stops fake "agency" invoices.</p>
        )}
        {error && <p className="text-[13px] text-block">⛔ {error}</p>}
      </div>
      <div className="flex items-center justify-between gap-2 border-t border-rule px-6 py-4">
        <button className="btn-ghost" data-testid="approval-close" onClick={() => openApproval(null)}>Close</button>
        <div className="flex gap-2">
          {mine && (
            <button data-testid="reject-button" className="btn-ghost !border-block-line !text-block" disabled={busy}
              onClick={async () => { await reject(approvalFor, student ? "Amount does not match the student portal" : "Rejected by payer"); openApproval(null); }}>
              Reject
            </button>
          )}
          <button data-testid="approve-button" className="btn-primary" disabled={!mine || busy} onClick={doApprove}>
            {busy ? "Signing…" : student ? "Confirm — matches my portal" : "Approve · 批准"}
          </button>
        </div>
      </div>
    </Backdrop>
  );
}

export function ConsentModal() {
  const { ready, consent, persona, giveConsent } = useStore();
  if (!ready || consent[persona] !== false) return null;
  return (
    <Backdrop testid="consent-modal">
      <div className="px-6 py-5">
        <div className="eyebrow">Consent · 个人信息处理同意 (PIPL P-001)</div>
        <div className="mt-1 font-display text-[24px] leading-tight">Before Bridge reads your documents</div>
        <p className="mt-2 text-[14px] leading-relaxed text-ink-soft">
          {personaName(persona)}: Bridge will process your documents and payment details only to verify payees, check your FX quota and prepare payments for your approval.
        </p>
        <ul className="mt-3 space-y-1.5 text-[14px]">
          <li>• Document processing — hashes and checked fields only; raw files are not kept (P-004).</li>
          <li>• Payment processing — sandbox bank, simulated money.</li>
          <li>• Audit logging — masked, hash-chained; you can delete your data at any time (P-003).</li>
        </ul>
        <p className="mt-3 text-[13px] text-ink-mute">我同意 Bridge 为核验收款方、检查购汇额度和准备付款而处理我的信息。</p>
      </div>
      <div className="flex justify-end border-t border-rule px-6 py-4">
        <button data-testid="consent-accept" className="btn-primary" onClick={giveConsent}>I agree · 同意</button>
      </div>
    </Backdrop>
  );
}

export function Toast() {
  const { toast } = useStore();
  if (!toast) return null;
  return (
    <div className="fixed bottom-6 left-1/2 z-[60] -translate-x-1/2 rise rounded-md bg-ink px-4 py-2.5 text-[13.5px] text-paper shadow-card">
      {toast}
    </div>
  );
}

export function CaptionBar({ text }: { text: string }) {
  if (!text) return null;
  return (
    <div data-testid="demo-caption" className="pointer-events-none fixed inset-x-0 bottom-0 z-[70] flex justify-center pb-6">
      <div key={text} className="rise max-w-[1280px] rounded-lg bg-ink/95 px-7 py-3.5 text-center font-display text-[26px] leading-snug text-paper shadow-2xl">
        {text}
      </div>
    </div>
  );
}
