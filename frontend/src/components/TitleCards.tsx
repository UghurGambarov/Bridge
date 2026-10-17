// /intro and /outro: the demo video's title cards.
import { SandboxStrip } from "./Header";

export function Intro() {
  return (
    <div className="min-h-full">
      <SandboxStrip />
      <div data-testid="intro" className="mx-auto grid min-h-[calc(100vh-28px)] max-w-[1600px] grid-cols-1 content-center gap-14 px-14 py-12 lg:grid-cols-[1.25fr_1fr]">
        <div className="rise">
          <div className="eyebrow">2026 Shenzhen FinTechathon · Topic C · Cross-border & student finance</div>
          <h1 className="mt-4 font-display text-[64px] font-semibold leading-[1.02] tracking-tight">Bridge</h1>
          <p className="mt-6 font-display text-[28px] leading-snug text-ink-soft">
            Chinese families struggle to pay tuition abroad safely and legally because of scams and foreign-exchange quota rules.
          </p>
          <p className="mt-4 text-[18px] leading-relaxed text-ink-soft">
            Existing tools only compare fees and do not check the payee or the rules. Our agent verifies the payee, enforces the limits, and completes the payment under human approval.
          </p>
          <ul className="mt-8 space-y-3 text-[16px]">
            <li className="flex gap-3"><span className="font-display text-ink-faint">01</span>“Real admission, fake fee payment” (真录取+假代缴): an agent collected tuition into a personal account — about 10 students lost their places, over RMB 1 million involved.</li>
            <li className="flex gap-3"><span className="font-display text-ink-faint">02</span>Each person may buy USD 50,000 of foreign currency per calendar year; above that the bank needs documents.</li>
            <li className="flex gap-3"><span className="font-display text-ink-faint">03</span>Splitting one payment across relatives' quotas (分拆购汇) is prohibited and fined by SAFE.</li>
          </ul>
        </div>
        <div className="rise space-y-4" style={{ animationDelay: "200ms" }}>
          {[
            ["李伟 Li Wei, 19", "Undergraduate at Northbridge University (UK). Can check his fees on the university portal."],
            ["张敏 Zhang Min", "His mother in Hangzhou. She pays — and cannot comfortably read English invoices."],
            ["张强 Zhang Qiang", "The uncle. Appears only when the mother asks to use his FX quota."],
          ].map(([n, d]) => (
            <div key={n} className="card px-6 py-5">
              <div className="font-display text-[26px]">{n}</div>
              <div className="mt-1 text-[15px] text-ink-soft">{d}</div>
            </div>
          ))}
          <p className="pt-2 text-[13px] text-ink-mute">All people, institutions and accounts are fictional. Simulated money only.</p>
        </div>
      </div>
    </div>
  );
}

const BOX_BASE = "rounded-md border-2 border-ink px-4 py-3 text-center text-[18px] font-medium leading-tight";
const BOX = `${BOX_BASE} bg-paper-raised`;

export function Outro() {
  return (
    <div className="min-h-full">
      <SandboxStrip />
      <div data-testid="outro" className="mx-auto flex min-h-[calc(100vh-28px)] max-w-[1720px] flex-col justify-center px-14 py-12">
        <div className="eyebrow">Architecture</div>
        <h1 className="mt-2 font-display text-[56px] leading-tight">The AI proposes. The policy engine decides. Humans approve.</h1>
        <div className="mt-10 grid grid-cols-[1fr_auto_1fr_auto_1.2fr_auto_1fr] items-center gap-3">
          <div className="space-y-3">
            <div className={BOX}>Web UI<div className="text-[14px] font-normal text-ink-mute">persona toggle Mother / Li Wei</div></div>
            <div className={BOX}>Evidence Center</div>
          </div>
          <Arrow />
          <div className="space-y-3">
            <div className={BOX}>Request guard<div className="text-[14px] font-normal text-ink-mute">deterministic</div></div>
            <div className={BOX}>Document ingestion<div className="text-[14px] font-normal text-ink-mute">hidden text · injection · invisible unicode · lookalike domains</div></div>
            <div className={`${BOX} border-dashed`}>Quarantined extractor LLM<div className="text-[14px] font-normal text-ink-mute">no tools · JSON schema only</div></div>
          </div>
          <Arrow />
          <div className="space-y-3">
            <div className={BOX}>Agent orchestrator<div className="text-[14px] font-normal text-ink-mute">planner LLM · sees checked fields only</div></div>
            <div className="text-center text-[15px] text-ink-mute">↓ every tool call</div>
            <div className={`${BOX_BASE} bg-ink text-paper`}>Policy engine T0–T4<div className="text-[14px] font-normal text-paper/70">single choke point · digest-bound approvals</div></div>
          </div>
          <Arrow />
          <div className="space-y-3">
            <div className={BOX}>Tools<div className="text-[14px] font-normal text-ink-mute">payee check · quota · FX · intents · sandbox bank</div></div>
            <div className={BOX}>Registry · quota ledger · sandbox bank</div>
            <div className={BOX}>Hash-chained audit log</div>
          </div>
        </div>
        <div className="mt-14 grid grid-cols-5 gap-4 text-[18px]">
          {["Dual-LLM quarantine", "Single choke point", "Capability restriction", "Digest-bound human approval", "Tamper-evident audit"].map((p, i) => (
            <div key={p} className="card px-4 py-3"><span className="font-display text-ink-faint">0{i + 1}</span> {p}</div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Arrow() {
  return <div className="font-display text-[36px] text-ink-faint">→</div>;
}
