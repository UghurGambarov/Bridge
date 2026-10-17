import { useState } from "react";
import { navigate } from "../lib/demo";
import { PERSONA } from "../lib/format";
import { useStore } from "../lib/store";

export function SandboxStrip() {
  return (
    <div className="sandbox-strip flex h-7 items-center justify-center text-[11.5px] font-medium tracking-[0.12em] text-paper">
      SANDBOX — fictional institutions, simulated accounts and FX rates
    </div>
  );
}

export function Wordmark() {
  return (
    <button onClick={() => navigate("/")} className="flex items-baseline gap-3 text-left">
      <span className="font-display text-[26px] font-semibold leading-none tracking-tight">Bridge</span>
      <span className="hidden text-[12.5px] text-ink-mute md:inline">Safe tuition payments abroad · 安心付学费</span>
    </button>
  );
}

export function ModelBadge() {
  const { modelLabel } = useStore();
  const mock = modelLabel.startsWith("MOCK");
  return (
    <span data-testid="model-badge" title="Active LLM provider and model"
      className={`rounded border px-2 py-1 font-mono text-[11.5px] ${mock ? "border-warn-line bg-warn-bg text-warn" : "border-rule-strong bg-paper-raised text-ink-soft"}`}>
      model: {modelLabel || "…"}
    </span>
  );
}

export function Header({ evidence }: { evidence?: boolean }) {
  const { persona, setPersona, deleteMyData } = useStore();
  const [menu, setMenu] = useState(false);
  const seg = (id: string, label: string, testid: string) => (
    <button data-testid={testid} onClick={() => setPersona(id)}
      className={`px-3.5 py-1.5 text-[13.5px] font-medium transition-colors ${persona === id ? "bg-ink text-paper" : "text-ink-soft hover:bg-paper-sunk"}`}>
      {label}
    </button>
  );
  return (
    <header className="sticky top-0 z-30 border-b border-rule bg-paper/95 backdrop-blur">
      <SandboxStrip />
      <div className="mx-auto flex h-14 max-w-[1720px] items-center justify-between gap-4 px-5">
        <Wordmark />
        {!evidence && (
          <div className="flex items-center gap-2">
            <span className="eyebrow hidden lg:inline">Acting as</span>
            <div className="flex overflow-hidden rounded-md border border-ink">
              {seg(PERSONA.mother, "Mother 妈妈", "persona-mother")}
              {seg(PERSONA.student, "Li Wei", "persona-student")}
            </div>
            <div className="relative">
              <button data-testid="persona-menu" className="btn-ghost !px-2 !py-1.5" onClick={() => setMenu((m) => !m)} aria-label="Persona menu">⋯</button>
              {menu && (
                <div className="absolute right-0 top-10 z-40 w-64 rounded-md border border-rule bg-paper-raised p-1 shadow-card">
                  <button data-testid="delete-data" className="w-full rounded px-3 py-2 text-left text-[13.5px] hover:bg-paper-sunk"
                    onClick={async () => {
                      setMenu(false);
                      if (window.confirm("Delete this persona's documents, devices and consent? Masked audit entries are kept (PIPL P-003).")) await deleteMyData();
                    }}>
                    Delete my data · 删除我的数据
                    <div className="text-[11.5px] text-ink-mute">PIPL P-003 — masked audit kept</div>
                  </button>
                </div>
              )}
            </div>
          </div>
        )}
        <div className="flex items-center gap-3">
          <ModelBadge />
          {evidence ? (
            <button data-testid="nav-chat" className="btn-ghost" onClick={() => navigate("/")}>← Back to chat</button>
          ) : (
            <button data-testid="nav-evidence" className="btn-ghost" onClick={() => navigate("/evidence")}>Evidence Center</button>
          )}
        </div>
      </div>
    </header>
  );
}
