import { ReactNode } from "react";

export function Shell(props: {
  testid: string;
  eyebrow: string;
  right?: ReactNode;
  tone?: "pass" | "warn" | "block";
  children: ReactNode;
  delay?: number;
  onClick?: () => void;
}) {
  const edge =
    props.tone === "pass" ? "border-l-pass" : props.tone === "warn" ? "border-l-warn" : props.tone === "block" ? "border-l-block" : "";
  return (
    <section
      data-testid={props.testid}
      onClick={props.onClick}
      className={`card rise overflow-hidden ${edge ? `border-l-[3px] ${edge}` : ""} ${props.onClick ? "cursor-pointer" : ""}`}
      style={{ animationDelay: `${props.delay ?? 0}ms` }}
    >
      <header className="flex items-center justify-between gap-3 border-b border-rule px-4 py-2.5">
        <span className="eyebrow">{props.eyebrow}</span>
        {props.right}
      </header>
      <div className="px-4 py-3.5">{props.children}</div>
    </section>
  );
}

// Literal class names so Tailwind's content scan keeps them.
const CHIP = { pass: "chip-pass", warn: "chip-warn", block: "chip-block", neutral: "chip-neutral" } as const;

export function Chip({ tone, children, title }: { tone: "pass" | "warn" | "block" | "neutral"; children: ReactNode; title?: string }) {
  return (
    <span title={title} className={CHIP[tone]}>
      {children}
    </span>
  );
}

export function StatusBadge({ status }: { status?: string }) {
  if (status === "verified") return <Chip tone="neutral">✅ verified source</Chip>;
  return <Chip tone="neutral">🔎 to verify</Chip>;
}

export function ResultMark({ result }: { result: string }) {
  if (result === "pass") return <span className="text-pass" title="pass">✅</span>;
  if (result === "needs_approval") return <span className="text-warn" title="needs approval">⏸</span>;
  if (result === "block") return <span className="text-block" title="blocked">⛔</span>;
  return <span className="text-ink-mute" title="info">ℹ️</span>;
}

/* eslint-disable @typescript-eslint/no-explicit-any */
export function RuleChecks({ checks, compact }: { checks: any[]; compact?: boolean }) {
  if (!checks?.length) return <p className="text-sm text-ink-mute">No rule checks recorded.</p>;
  return (
    <ul className="divide-y divide-rule">
      {checks.map((c, i) => (
        <li key={`${c.rule_id}-${i}`} className="grid grid-cols-[22px_74px_1fr] items-start gap-2 py-2">
          <ResultMark result={c.result} />
          <code className="font-mono text-[12.5px] font-medium text-ink">{c.rule_id}</code>
          <div className="min-w-0">
            <div className="text-[13.5px] font-medium leading-snug">{c.title}</div>
            {c.detail && <div className="mt-0.5 text-[12.5px] leading-snug text-ink-soft">{c.detail}</div>}
            {!compact && c.source && (
              <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11.5px] text-ink-mute">
                <SourceText text={c.source} />
                <StatusBadge status={c.status} />
              </div>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}

export function SourceText({ text }: { text: string }) {
  const parts = text.split(/(https?:\/\/[^\s;)]+)/g);
  return (
    <span className="break-words">
      {parts.map((p, i) =>
        /^https?:\/\//.test(p) ? (
          <a key={i} href={p} target="_blank" rel="noreferrer" className="underline decoration-rule-strong underline-offset-2 hover:text-ink">
            {new URL(p).hostname}
          </a>
        ) : (
          <span key={i}>{p}</span>
        ),
      )}
    </span>
  );
}

export function Seal({ value, label = "Transaction fingerprint" }: { value?: string; label?: string }) {
  if (!value) return null;
  return (
    <div className="flex flex-col gap-1">
      <span className="eyebrow">{label}</span>
      <span className="seal" data-testid="fingerprint">
        {value}
      </span>
    </div>
  );
}
