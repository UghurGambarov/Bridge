/* eslint-disable @typescript-eslint/no-explicit-any */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Chip, SourceText, StatusBadge } from "../cards/common";
import { api, ApiError } from "../lib/api";
import { money, shortTime } from "../lib/format";
import { useStore } from "../lib/store";

const TABS = [
  ["audit", "Audit log"],
  ["receipts", "Receipts"],
  ["scenarios", "Scenario results"],
  ["security", "Security"],
  ["rules", "Rules"],
  ["controls", "Controls"],
  ["export", "Export"],
] as const;
type Tab = (typeof TABS)[number][0];

export function EvidenceCenter() {
  const [tab, setTab] = useState<Tab>(() => (new URLSearchParams(window.location.search).get("tab") as Tab) || "audit");
  return (
    <div className="mx-auto max-w-[1520px] px-6 py-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="eyebrow">Evidence Center · 证据中心</div>
          <h1 className="font-display text-[34px] leading-tight">Verifiable execution</h1>
          <p className="mt-1 max-w-3xl text-[14px] text-ink-soft">
            Every step is written to a hash-chained log, every receipt carries the transaction fingerprint, and every rule has a source. Judges can check all of it here.
          </p>
        </div>
        <Summary />
      </div>
      <nav className="mt-6 flex flex-wrap gap-1 border-b border-rule">
        {TABS.map(([id, label]) => (
          <button key={id} data-testid={`tab-${id}`} onClick={() => setTab(id)}
            className={`-mb-px border-b-2 px-4 py-2.5 text-[14px] font-medium ${tab === id ? "border-ink text-ink" : "border-transparent text-ink-mute hover:text-ink"}`}>
            {label}
          </button>
        ))}
      </nav>
      <div className="pt-5">
        {tab === "audit" && <AuditTab />}
        {tab === "receipts" && <ReceiptsTab />}
        {tab === "scenarios" && <ScenariosTab />}
        {tab === "security" && <SecurityTab />}
        {tab === "rules" && <RulesTab />}
        {tab === "controls" && <ControlsTab />}
        {tab === "export" && <ExportTab />}
      </div>
    </div>
  );
}

function Summary() {
  const [s, setS] = useState<any>(null);
  useEffect(() => { api.evidenceSummary().then(setS).catch(() => undefined); }, []);
  if (!s) return null;
  return (
    <div className="flex gap-6 text-right">
      <Kpi label="Audit entries" value={s.chain.entries} />
      <Kpi label="Receipts" value={s.receipts} />
      <Kpi label="Scenario pass rate" value={s.scenarios ? `${s.scenarios.pass_rate}%` : "—"} />
    </div>
  );
}

function Kpi({ label, value }: { label: string; value: any }) {
  return (
    <div>
      <div className="num font-display text-[28px] leading-none">{value}</div>
      <div className="eyebrow mt-1">{label}</div>
    </div>
  );
}

// ------------------------------------------------------------------ audit
function AuditTab() {
  const [rows, setRows] = useState<any[]>([]);
  const [verify, setVerify] = useState<any>(null);
  const [tamper, setTamper] = useState<any>(null);
  useEffect(() => { api.audit().then((r) => setRows(r.entries)); }, []);
  return (
    <div>
      <div className="flex flex-wrap items-center gap-3">
        <button data-testid="verify-chain" className="btn-primary" onClick={async () => { setTamper(null); setVerify(await api.verify()); }}>
          Verify chain
        </button>
        <button data-testid="tamper-sim" className="btn-ghost" onClick={async () => setTamper(await api.tamper())}>
          Simulate tampering (on a copy)
        </button>
        {verify && !tamper && (
          <div data-testid="verify-result" className={verify.valid ? "chip-pass !text-[14px] !py-1.5 !px-3" : "chip-block !text-[14px] !py-1.5 !px-3"}>
            {verify.valid ? `✅ Chain valid — ${verify.entries} entries, head ${verify.head_hash?.slice(0, 16)}…` : `⛔ Chain broken at #${verify.broken_at_seq}`}
          </div>
        )}
        {tamper && (
          <div data-testid="tamper-result" className="chip-block !text-[14px] !py-1.5 !px-3">
            ⛔ Copy with entry #{tamper.tampered_seq} edited → verification breaks at #{tamper.broken_at_seq}. Real log still {tamper.original_valid ? "valid ✅" : "invalid"}.
          </div>
        )}
      </div>
      <p className="mt-2 text-[12.5px] text-ink-mute">hash = sha256(prev_hash + canonical_json(entry)). Editing or deleting any entry breaks every later link. Payloads are masked (P-002).</p>
      <div className="card mt-4 overflow-hidden">
        <div className="max-h-[62vh] overflow-auto">
          <table className="w-full text-[12.5px]">
            <thead className="sticky top-0 bg-paper-sunk text-left">
              <tr>{["#", "Time (sandbox)", "Actor / persona", "Event", "Rule", "Decision", "Reason", "Hash"].map((h) => <th key={h} className="px-3 py-2 font-medium text-ink-soft">{h}</th>)}</tr>
            </thead>
            <tbody className="divide-y divide-rule">
              {rows.map((e) => {
                const broken = tamper && e.seq >= tamper.broken_at_seq;
                const tone = e.decision === "deny" ? "text-block" : e.decision === "require_approval" ? "text-warn" : e.decision === "allow" ? "text-pass" : "";
                return (
                  <tr key={e.seq} className={broken ? "bg-block-bg" : ""}>
                    <td className="num px-3 py-1.5 text-ink-mute">{e.seq}</td>
                    <td className="num whitespace-nowrap px-3 py-1.5">{shortTime(e.ts)}</td>
                    <td className="px-3 py-1.5">{e.actor}{e.persona ? <span className="text-ink-mute"> / {e.persona}</span> : null}</td>
                    <td className="px-3 py-1.5 font-mono text-[11.5px]">{e.event}{e.payload_masked?.tool ? `: ${e.payload_masked.tool}` : ""}</td>
                    <td className="px-3 py-1.5 font-mono text-[11.5px]">{e.rule_id ?? ""}</td>
                    <td className={`px-3 py-1.5 ${tone}`}>{e.decision ?? ""}</td>
                    <td className="max-w-[420px] truncate px-3 py-1.5 text-ink-soft" title={e.reason}>{e.reason}</td>
                    <td className="px-3 py-1.5 font-mono text-[11px] text-ink-mute">{e.hash.slice(0, 10)}<span className="text-ink-faint"> ← {e.prev_hash.slice(0, 6)}</span></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ receipts
function ReceiptsTab() {
  const [rows, setRows] = useState<any[] | null>(null);
  useEffect(() => { api.receipts().then((r) => setRows(r.receipts)); }, []);
  if (!rows) return null;
  if (!rows.length) return <p className="text-ink-mute">No sandbox transfers yet.</p>;
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
      {rows.map((r) => (
        <div key={r.transfer_id} className="card px-4 py-3.5">
          <div className="flex items-center justify-between">
            <span className="font-mono text-[13px]">{r.bank_reference}</span>
            <Chip tone="pass">{r.tier === "T2" ? "autonomous T2" : "approved T3"}</Chip>
          </div>
          <div className="num mt-2 font-display text-[24px]">{money(r.amount, r.currency)}</div>
          <div className="text-[12.5px] text-ink-mute">CNY {money(r.total_cny)} debited · {shortTime(r.executed_at)}</div>
          <div className="mt-2 flex items-center justify-between">
            <span className="seal !text-[12.5px]">{r.fingerprint}</span>
            <a className="btn-ghost !py-1 text-[12.5px]" href={r.pdf_url} target="_blank" rel="noreferrer">PDF ↗</a>
          </div>
        </div>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ scenarios
function ScenariosTab() {
  const [rep, setRep] = useState<any>(null);
  const [running, setRunning] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api.scenariosLatest().then(setRep).catch(() => setRep(null)); }, []);
  const run = async () => {
    setRunning(true);
    setErr(null);
    try { setRep(await api.scenariosRun()); } catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); } finally { setRunning(false); }
  };
  return (
    <div>
      <div className="flex flex-wrap items-center gap-4">
        <button data-testid="scenario-run" className="btn-primary" disabled={running} onClick={run}>{running ? "Running 39 cases…" : "Run suite"}</button>
        <span className="text-[12.5px] text-ink-mute">Each case runs on an isolated temporary database — the demo state is never touched.</span>
        {err && <span className="text-block">{err}</span>}
      </div>
      {rep && (
        <>
          <div data-testid="scenario-summary" className="mt-5 flex flex-wrap items-end gap-8">
            <div>
              <div className={`num font-display text-[56px] leading-none ${rep.summary.failed ? "text-block" : "text-pass"}`}>{rep.summary.pass_rate}%</div>
              <div className="eyebrow mt-1">pass rate · {rep.summary.passed}/{rep.summary.total} · {rep.model_label}</div>
            </div>
            {Object.entries(rep.summary.by_category).map(([cat, c]: any) => (
              <div key={cat}>
                <div className="num font-display text-[28px] leading-none">{c.passed}/{c.total}</div>
                <div className="eyebrow mt-1">{cat}</div>
              </div>
            ))}
            <div className="text-[12px] text-ink-mute">generated {shortTime(rep.generated_at)}</div>
          </div>
          <div className="card mt-5 overflow-hidden">
            <div className="max-h-[56vh] overflow-auto">
              <table className="w-full text-[12.5px]">
                <thead className="sticky top-0 bg-paper-sunk text-left">
                  <tr>{["ID", "Category", "Case", "Expected", "Actual", "", "OWASP", "STRIDE"].map((h) => <th key={h} className="px-3 py-2 font-medium text-ink-soft">{h}</th>)}</tr>
                </thead>
                <tbody className="divide-y divide-rule">
                  {rep.cases.map((c: any) => (
                    <tr key={c.id}>
                      <td className="px-3 py-1.5 font-mono">{c.id}</td>
                      <td className="px-3 py-1.5">{c.category}</td>
                      <td className="px-3 py-1.5">{c.title}<div className="text-[11.5px] text-ink-mute">{c.input}</div></td>
                      <td className="px-3 py-1.5 text-ink-soft">{c.expected}</td>
                      <td className="px-3 py-1.5 font-mono text-[11px] text-ink-soft">{c.actual}{c.failures?.length ? <div className="text-block">{c.failures.join("; ")}</div> : null}</td>
                      <td className="px-3 py-1.5">{c.passed ? "✅" : "❌"}</td>
                      <td className="px-3 py-1.5 font-mono">{c.owasp}</td>
                      <td className="px-3 py-1.5">{c.stride}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ security
const OWASP: Record<string, string> = {
  LLM01: "Prompt Injection", LLM02: "Sensitive Information Disclosure", LLM05: "Improper Output Handling",
  LLM06: "Excessive Agency", LLM09: "Misinformation", LLM10: "Unbounded Consumption",
};
const PATTERNS = [
  ["Dual-LLM / quarantine", "The planner never sees raw document text — only schema-validated fields and detector findings."],
  ["Single choke point", "No tool runs without policy.authorize(): the AI proposes, the policy engine decides."],
  ["Capability restriction", "Payments accept only a registry payee_channel_id; the model cannot type an account number."],
  ["Digest-bound human approval", "Single-use, expiring, device-bound approvals over the transaction digest. The agent has no approval tool."],
  ["Tamper-evident audit", "Hash-chained log, verifiable from this page."],
];

function SecurityTab() {
  const [rules, setRules] = useState<any[]>([]);
  const [risks, setRisks] = useState<any[]>([]);
  const [rep, setRep] = useState<any>(null);
  useEffect(() => {
    api.rules().then((r) => setRules(r.rules));
    api.knownRisks().then((r) => setRisks(r.risks));
    api.scenariosLatest().then(setRep).catch(() => undefined);
  }, []);
  const byTier = useMemo(() => {
    const m: Record<string, any[]> = {};
    for (const r of rules) (m[r.tier] ??= []).push(r);
    return m;
  }, [rules]);
  const owaspMap = useMemo(() => {
    const m: Record<string, string[]> = {};
    for (const c of rep?.cases ?? []) if (c.owasp && c.owasp !== "-") (m[c.owasp] ??= []).push(c.id);
    return m;
  }, [rep]);
  const strideMap = useMemo(() => {
    const m: Record<string, string[]> = {};
    for (const c of rep?.cases ?? []) if (c.stride && c.stride !== "-") (m[c.stride] ??= []).push(c.id);
    return m;
  }, [rep]);
  const TIERS: [string, string][] = [["T4", "Forbidden — never, even if asked"], ["T3", "Act with approval"], ["T2", "Act within limits (autonomous)"], ["policy", "Quota policy"], ["privacy", "Personal data (PIPL)"], ["system", "System"]];
  return (
    <div className="grid grid-cols-1 gap-6 xl:grid-cols-[1.3fr_1fr]">
      <div className="space-y-6">
        <section>
          <h2 className="font-display text-[22px]">Five security patterns</h2>
          <ol className="mt-2 grid grid-cols-1 gap-2 md:grid-cols-2">
            {PATTERNS.map(([t, d], i) => (
              <li key={t} className="card px-4 py-3"><div className="font-medium">{i + 1}. {t}</div><div className="mt-0.5 text-[13px] text-ink-soft">{d}</div></li>
            ))}
          </ol>
        </section>
        <section>
          <h2 className="font-display text-[22px]">Permission tiers (from rules.yaml)</h2>
          <div className="card mt-2 divide-y divide-rule">
            <div className="grid grid-cols-[90px_1fr] gap-3 px-4 py-2.5 text-[13px]"><b>T0</b><span>Read and explain — always allowed.</span></div>
            <div className="grid grid-cols-[90px_1fr] gap-3 px-4 py-2.5 text-[13px]"><b>T1</b><span>Prepare (drafts, document lists, verification emails) — never executes.</span></div>
            {TIERS.map(([tier, label]) => (
              <div key={tier} className="grid grid-cols-[90px_1fr] gap-3 px-4 py-2.5 text-[13px]">
                <b>{tier}</b>
                <div><div className="text-ink-soft">{label}</div>
                  <div className="mt-1 flex flex-wrap gap-1">{(byTier[tier] ?? []).map((r) => <span key={r.id} className="chip-neutral" title={r.title}>{r.id}</span>)}</div>
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>
      <div className="space-y-6">
        <section>
          <h2 className="font-display text-[22px]">OWASP LLM Top 10 (2025) → cases</h2>
          <ul className="card mt-2 divide-y divide-rule text-[13px]">
            {Object.entries(owaspMap).map(([k, ids]) => (
              <li key={k} className="px-4 py-2"><b className="font-mono">{k}</b> {OWASP[k] ?? ""}<div className="text-[12px] text-ink-mute">{ids.join(", ")}</div></li>
            ))}
          </ul>
          <h3 className="mt-4 font-display text-[18px]">STRIDE → cases</h3>
          <ul className="card mt-2 divide-y divide-rule text-[13px]">
            {Object.entries(strideMap).map(([k, ids]) => (
              <li key={k} className="px-4 py-2"><b>{k}</b><div className="text-[12px] text-ink-mute">{ids.join(", ")}</div></li>
            ))}
          </ul>
        </section>
        <section>
          <h2 className="font-display text-[22px]">Known risks</h2>
          <ol className="card mt-2 divide-y divide-rule text-[13px]">
            {risks.map((r) => (
              <li key={r.id} className="px-4 py-2"><b className="font-mono text-[12px]">{r.id}</b> {r.risk}<div className="text-[12px] text-ink-mute">Mitigation: {r.mitigation}</div></li>
            ))}
          </ol>
        </section>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ rules
function RulesTab() {
  const [rules, setRules] = useState<any[]>([]);
  useEffect(() => { api.rules().then((r) => setRules(r.rules)); }, []);
  return (
    <div data-testid="rules-table" className="card overflow-hidden">
      <table className="w-full text-[13px]">
        <thead className="bg-paper-sunk text-left">
          <tr>{["Rule", "Tier", "Rule text", "Source", "Checked", "Status"].map((h) => <th key={h} className="px-3 py-2 font-medium text-ink-soft">{h}</th>)}</tr>
        </thead>
        <tbody className="divide-y divide-rule align-top">
          {rules.map((r) => (
            <tr key={r.id}>
              <td className="px-3 py-2 font-mono font-medium">{r.id}</td>
              <td className="px-3 py-2">{r.tier}</td>
              <td className="px-3 py-2"><div className="font-medium">{r.title}</div><div className="text-[12.5px] text-ink-soft">{r.text}</div>
                {Object.keys(r.params ?? {}).length > 0 && <div className="mt-1 font-mono text-[11.5px] text-ink-mute">{JSON.stringify(r.params)}</div>}</td>
              <td className="max-w-[360px] px-3 py-2 text-[12px] text-ink-soft"><SourceText text={r.source} /></td>
              <td className="num whitespace-nowrap px-3 py-2 text-[12px]">{r.last_checked}</td>
              <td className="px-3 py-2"><StatusBadge status={r.status} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ------------------------------------------------------------------ controls
function ControlsTab() {
  const { sessionId, intents, refreshIntents, appendTurn, resetSession, notify } = useStore();
  const [state, setState] = useState<{ frozen: boolean; now: string } | null>(null);
  const [last, setLast] = useState<string | null>(null);
  const load = useCallback(async () => setState(await api.adminState()), []);
  useEffect(() => { load(); refreshIntents(); }, [load, refreshIntents]);
  const awaiting = Object.values(intents).filter((i) => i.status === "awaiting_documents");
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
      <div className="card px-5 py-4">
        <div className="eyebrow">SYS-001 · kill switch</div>
        <div className="mt-1 font-display text-[20px]">Global freeze</div>
        <p className="mt-1 text-[13px] text-ink-soft">When frozen, no payment can be created, approved for execution, or executed.</p>
        <button data-testid="freeze-toggle" className={state?.frozen ? "btn-primary mt-3 !bg-block !border-block" : "btn-ghost mt-3"}
          onClick={async () => { await api.freeze(!state?.frozen); await load(); }}>
          {state?.frozen ? "Frozen — click to unfreeze" : "Freeze all payments"}
        </button>
      </div>
      <div className="card px-5 py-4">
        <div className="eyebrow">Sandbox clock · {state ? shortTime(state.now) : ""}</div>
        <div className="mt-1 font-display text-[20px]">Advance clock 1 month</div>
        <p className="mt-1 text-[13px] text-ink-soft">Runs due allowance schedules through the T2 path; anything above the caps is held for approval.</p>
        <button data-testid="advance-clock" className="btn-primary mt-3" onClick={async () => {
          const r = await api.advanceClock(sessionId, 1);
          appendTurn({ user: null, messages: r.messages, cards: r.cards });
          await Promise.all([load(), refreshIntents()]);
          setLast(r.messages?.[0]?.text ?? "No schedules were due.");
        }}>Advance 1 month</button>
        {last && <p data-testid="advance-result" className="mt-2 text-[13px] text-pass">{last}</p>}
      </div>
      <div className="card px-5 py-4">
        <div className="eyebrow">Q-002 · documented route</div>
        <div className="mt-1 font-display text-[20px]">Bank officer verification (simulated)</div>
        <p className="mt-1 text-[13px] text-ink-soft">For payments above the payer's remaining quota: the bank checks the admission letter, invoice, IDs and relationship proof. Then the normal T3 approval follows.</p>
        {awaiting.length === 0 && <p className="mt-3 text-[13px] text-ink-mute">No intent is awaiting documents.</p>}
        {awaiting.map((i) => (
          <div key={i.intent_id} className="mt-3 flex items-center justify-between gap-3 rounded-md border border-rule px-3 py-2">
            <span className="text-[13px]">{money(i.amount, i.currency)} · {i.purpose} · <span className="font-mono">{i.fingerprint}</span></span>
            <button data-testid={`bank-verify-${i.intent_id}`} className="btn-primary !py-1.5" onClick={async () => {
              await api.bankVerify(i.intent_id, sessionId);
              await refreshIntents();
              notify("Bank officer verified the documents (simulated). Request approval from the chat.");
            }}>Verify documents</button>
          </div>
        ))}
      </div>
      <div className="card px-5 py-4">
        <div className="eyebrow">Demo</div>
        <div className="mt-1 font-display text-[20px]">Reset demo</div>
        <p className="mt-1 text-[13px] text-ink-soft">Wipes the sandbox database and receipts and re-seeds the fictional family (quota used: USD 25,000).</p>
        <button data-testid="reset-demo" className="btn-ghost mt-3 !border-block-line !text-block" onClick={async () => {
          if (!window.confirm("Reset the sandbox to the seed state?")) return;
          await api.reset();
          await resetSession();
          await load();
          notify("Sandbox reset.");
        }}>Reset sandbox</button>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ export
function ExportTab() {
  return (
    <div className="card max-w-3xl px-6 py-5">
      <div className="font-display text-[22px]">Evidence pack</div>
      <p className="mt-1 text-[14px] text-ink-soft">One zip with everything needed to check this sandbox run independently.</p>
      <ul className="mt-3 grid grid-cols-1 gap-1 text-[13px] md:grid-cols-2">
        {["metadata.json — commit, time, model", "audit_log.jsonl + audit_log.html", "chain_verification.json", "receipts/*.pdf + *.json",
          "scenario_report.html / .md / .json", "rules.md with source badges", "screenshots/ and video/ (from the autopilot)", "README.txt — how to verify the chain"].map((x) => (
          <li key={x} className="font-mono text-[12px] text-ink-soft">• {x}</li>
        ))}
      </ul>
      <a data-testid="export-pack" className="btn-primary mt-4" href="/api/evidence/export">Export evidence pack (.zip)</a>
    </div>
  );
}
