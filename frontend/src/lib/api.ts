// Thin client for the Bridge API (/api). Every number shown in the UI comes from these responses.

/* eslint-disable @typescript-eslint/no-explicit-any */
export type Card = { type: string; [k: string]: any };
export type AgentMessage = { text: string; ai_generated: boolean; label: string };
export type Turn = {
  user: { persona: string | null; text: string | null; doc_ids: string[] } | null;
  messages: AgentMessage[];
  cards: Card[];
  tools_called?: string[];
};

export class ApiError extends Error {
  constructor(public status: number, public ruleId: string | null, public reason: string) {
    super(ruleId ? `${ruleId}: ${reason}` : reason);
  }
}

async function request<T>(method: string, path: string, body?: unknown, form?: FormData): Promise<T> {
  const init: RequestInit = { method, headers: {} };
  if (form) init.body = form;
  else if (body !== undefined) {
    init.body = JSON.stringify(body);
    (init.headers as Record<string, string>)["Content-Type"] = "application/json";
  }
  const res = await fetch(`/api${path}`, init);
  const ct = res.headers.get("content-type") || "";
  const data = ct.includes("application/json") ? await res.json() : await res.text();
  if (!res.ok) {
    const d = (data as any)?.detail;
    throw new ApiError(res.status, d?.rule_id ?? null, d?.reason ?? (typeof d === "string" ? d : res.statusText));
  }
  return data as T;
}

export const api = {
  health: () => request<any>("GET", "/health"),
  start: (persona: string) => request<any>("POST", "/session/start", { persona }),
  enroll: (person_id: string, label: string) =>
    request<{ device_id: string; device_secret: string }>("POST", "/devices/enroll", { person_id, label }),
  consent: (person_id: string) => request<any>("POST", "/consent", { person_id }),
  consentStatus: (person_id: string) => request<{ consented: boolean }>("GET", `/consent/${person_id}`),
  switchPersona: (session_id: string, person_id: string) => request<any>("POST", "/session/persona", { session_id, person_id }),
  deleteData: (person_id: string) => request<any>("DELETE", `/persons/${person_id}/data`),
  history: (session_id: string) => request<{ turns: Turn[] }>("GET", `/chat/${session_id}`),
  chat: (session_id: string, person_id: string, message: string, doc_ids: string[]) =>
    request<Turn & { model_label: string }>("POST", "/chat", { session_id, person_id, message, doc_ids }),
  upload: (person_id: string, file: File) => {
    const f = new FormData();
    f.append("person_id", person_id);
    f.append("file", file);
    return request<any>("POST", "/documents", undefined, f);
  },
  intents: () => request<{ intents: Card[] }>("GET", "/intents"),
  intent: (id: string) => request<Card>("GET", `/intents/${id}`),
  why: (id: string) => request<Card>("GET", `/intents/${id}/why`),
  challenge: (id: string, person_id: string, device_id: string) =>
    request<any>("POST", `/intents/${id}/challenge`, { person_id, device_id }),
  approve: (id: string, body: { person_id: string; device_id: string; nonce: string; mac: string; session_id: string }) =>
    request<any>("POST", `/intents/${id}/approve`, body),
  reject: (id: string, person_id: string, reason: string) => request<Card>("POST", `/intents/${id}/reject`, { person_id, reason }),
  bankVerify: (id: string, session_id: string) => request<Card>("POST", `/intents/${id}/bank-verify`, { session_id }),
  quota: (person_id: string) => request<Card>("GET", `/quota/${person_id}`),
  receipts: () => request<{ receipts: Card[] }>("GET", "/receipts"),
  audit: () => request<{ entries: any[]; head_seq: number }>("GET", "/audit?limit=5000"),
  verify: () => request<{ valid: boolean; broken_at_seq: number | null; entries: number; head_hash: string | null }>("GET", "/audit/verify"),
  tamper: () => request<any>("POST", "/audit/tamper-simulation", {}),
  rules: () => request<{ rules: any[] }>("GET", "/rules"),
  knownRisks: () => request<{ risks: any[] }>("GET", "/known-risks"),
  scenariosLatest: () => request<any>("GET", "/scenarios/latest"),
  scenariosRun: () => request<any>("POST", "/scenarios/run"),
  evidenceSummary: () => request<any>("GET", "/evidence/summary"),
  freeze: (frozen: boolean) => request<{ frozen: boolean }>("POST", "/admin/freeze", { frozen }),
  adminState: () => request<{ frozen: boolean; now: string; model_label: string }>("GET", "/admin/state"),
  advanceClock: (session_id: string, months = 1) => request<any>("POST", "/admin/advance-clock", { months, session_id }),
  reset: () => request<any>("POST", "/demo/reset"),
  samples: () => request<{ samples: string[] }>("GET", "/samples"),
  sampleFile: async (name: string): Promise<File> => {
    const res = await fetch(`/api/samples/${encodeURIComponent(name)}`);
    if (!res.ok) throw new ApiError(res.status, null, "Sample not found");
    return new File([await res.blob()], name);
  },
};
