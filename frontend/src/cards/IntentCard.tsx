/* eslint-disable @typescript-eslint/no-explicit-any */
import { useStore } from "../lib/store";
import { money, personaName, STATUS_LABEL, statusTone, usd } from "../lib/format";
import { Chip, Seal, Shell } from "./common";

const STEP_LABEL: Record<string, string> = {
  created: "Prepared",
  bank_documents_verified: "Bank verified documents",
  approval_requested: "Approval requested",
  payer_approved: "Mother approved",
  student_confirmed: "Li Wei confirmed",
  executed: "Paid",
};

export function canApprove(intent: any, persona: string): boolean {
  if (!intent || !["pending_approval", "held"].includes(intent.status)) return false;
  const a = intent.approvals;
  if (!a) return false;
  return a.required.includes(persona) && !a.approved?.[persona];
}

export function IntentCard({ c, delay }: { c: any; delay: number }) {
  const { intents, persona, openApproval, selectIntent, selectedIntent } = useStore();
  const live = intents[c.intent_id] ?? c; // the card snapshot, refreshed with the live state
  const tone = statusTone(live.status);
  const purpose = live.purpose === "allowance" ? "Allowance to Li Wei" : `${live.purpose[0].toUpperCase()}${live.purpose.slice(1)}`;
  const selected = selectedIntent === live.intent_id;
  return (
    <Shell testid="card-intent" eyebrow={`Payment intent · ${live.tier}`} tone={tone === "neutral" ? undefined : tone} delay={delay}
      onClick={() => selectIntent(live.intent_id)}
      right={<Chip tone={tone}>{STATUS_LABEL[live.status] ?? live.status}</Chip>}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="text-[13px] text-ink-mute">{purpose} · {live.route === "within_quota" ? "within quota" : "documented route"}</div>
          <div className="num font-display text-[28px] leading-tight">{money(live.amount, live.currency)}</div>
          <div className="text-[13px] text-ink-soft num">
            ≈ {money(live.cny_equivalent, "CNY")} + fee {money(live.fee_cny, "CNY")} · counts {usd(live.usd_equivalent)} of quota
          </div>
          <div className="mt-2 text-[13.5px]">
            To <span className="font-medium">{live.payee.beneficiary_name}</span>{" "}
            <span className="font-mono text-[12.5px] text-ink-soft">{live.payee.account_masked}</span>{" "}
            {live.payee.verified && <Chip tone="pass">✓ registry-verified</Chip>}
          </div>
          {(live.reference || live.due_date) && (
            <div className="mt-1 text-[12.5px] text-ink-mute">
              {live.reference && <>Ref <span className="font-mono">{live.reference}</span></>}
              {live.due_date && <> · due {live.due_date}</>}
            </div>
          )}
        </div>
        <Seal value={live.fingerprint} />
      </div>

      <ol className="mt-3.5 flex flex-wrap items-center gap-x-1 gap-y-1 text-[12px]">
        {live.timeline.filter((s: any) => s.applies !== false).map((s: any, i: number, arr: any[]) => (
          <li key={s.step} className="flex items-center gap-1">
            <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 ${s.done ? "border-ink bg-ink text-paper" : "border-rule-strong text-ink-mute"}`}>
              {s.done ? "✓" : "○"} {STEP_LABEL[s.step] ?? s.step}
            </span>
            {i < arr.length - 1 && <span className="text-ink-faint">—</span>}
          </li>
        ))}
      </ol>

      {live.status_reason && ["held", "blocked", "rejected"].includes(live.status) && (
        <p className={`mt-2.5 text-[13px] ${live.status === "held" ? "text-warn" : "text-block"}`}>{live.status_reason}</p>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-rule pt-3" onClick={(e) => e.stopPropagation()}>
        {canApprove(live, persona) && (
          <button data-testid="intent-review" className="btn-primary" onClick={() => openApproval(live.intent_id)}>
            {persona === "p_li_wei" ? "Review & confirm" : "Review & approve"}
          </button>
        )}
        {live.approvals && !canApprove(live, persona) && ["pending_approval", "held"].includes(live.status) && (
          <span className="text-[13px] text-ink-soft">
            Waiting for {live.approvals.waiting_for.map((p: string) => personaName(p)).join(", ")}
          </span>
        )}
        <button className={`btn-ghost ${selected ? "!border-ink" : ""}`} onClick={() => selectIntent(live.intent_id)}>
          Why? · 为什么
        </button>
      </div>
    </Shell>
  );
}
