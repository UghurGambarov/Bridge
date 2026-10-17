/* eslint-disable @typescript-eslint/no-explicit-any */
import { useEffect, useState } from "react";
import { Chip, RuleChecks } from "../cards/common";
import { api } from "../lib/api";
import { money, STATUS_LABEL, statusTone } from "../lib/format";
import { useStore } from "../lib/store";

export function WhyPanel() {
  const { intents, selectedIntent, selectIntent } = useStore();
  const intent = selectedIntent ? intents[selectedIntent] : undefined;
  const [why, setWhy] = useState<any>(null);
  const list = Object.values(intents);

  useEffect(() => {
    if (!selectedIntent) return setWhy(null);
    api.why(selectedIntent).then(setWhy).catch(() => setWhy(null));
  }, [selectedIntent, intent?.status, intent?.rule_checks?.length]);

  const counts = (why?.checks ?? []).reduce((acc: Record<string, number>, c: any) => ({ ...acc, [c.result]: (acc[c.result] ?? 0) + 1 }), {});
  return (
    <aside data-testid="why-panel" className="flex h-full flex-col border-l border-rule bg-paper-raised/60">
      <div className="border-b border-rule px-5 py-3.5">
        <div className="eyebrow">Why panel · 为什么</div>
        <div className="mt-0.5 font-display text-[20px] leading-tight">Every rule check, with its source</div>
        <p className="mt-1 text-[12.5px] text-ink-mute">The AI proposes; the policy engine decides. Results come from code, not from the model.</p>
      </div>
      {list.length > 1 && (
        <div className="flex gap-1.5 overflow-x-auto border-b border-rule px-5 py-2">
          {list.map((i) => (
            <button key={i.intent_id} onClick={() => selectIntent(i.intent_id)}
              className={`whitespace-nowrap rounded-full border px-2.5 py-1 font-mono text-[11.5px] ${i.intent_id === selectedIntent ? "border-ink bg-ink text-paper" : "border-rule-strong text-ink-soft"}`}>
              {i.fingerprint}
            </button>
          ))}
        </div>
      )}
      <div className="flex-1 overflow-y-auto px-5 py-4">
        {!intent || !why ? (
          <p className="text-[13.5px] leading-relaxed text-ink-mute">
            When Bridge prepares a payment, every check the policy engine ran appears here: ✅ pass, ⏸ needs approval, ⛔ block — with the rule ID and its source.
          </p>
        ) : (
          <>
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="num font-display text-[22px] leading-tight">{money(intent.amount, intent.currency)}</div>
                <div className="text-[12.5px] text-ink-mute">{intent.purpose} · {intent.payee.beneficiary_name} · tier {intent.tier}</div>
              </div>
              <Chip tone={statusTone(intent.status)}>{STATUS_LABEL[intent.status] ?? intent.status}</Chip>
            </div>
            <div className="mt-2 font-mono text-[13px] tracking-[0.1em]">{intent.fingerprint}</div>
            <div className="mt-3 flex gap-2 text-[12px]">
              <Chip tone="pass">✅ {counts.pass ?? 0} pass</Chip>
              <Chip tone="warn">⏸ {counts.needs_approval ?? 0} needs approval</Chip>
              <Chip tone="block">⛔ {counts.block ?? 0} block</Chip>
            </div>
            {intent.risk?.signals?.length > 0 && (
              <div className="mt-3 text-[12.5px] text-ink-soft">Risk {intent.risk.level} ({intent.risk.score}): {intent.risk.signals.join(", ")}</div>
            )}
            <div className="mt-3"><RuleChecks checks={why.checks} /></div>
          </>
        )}
      </div>
    </aside>
  );
}
