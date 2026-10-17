// Formatting helpers. Values arrive as decimal strings from the API; we only format them.

const SYM: Record<string, string> = { GBP: "£", USD: "US$", HKD: "HK$", EUR: "€", CNY: "¥" };

export function money(amount: string | number | null | undefined, currency?: string): string {
  if (amount === null || amount === undefined || amount === "") return "—";
  const n = Number(amount);
  const s = n.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return currency ? `${SYM[currency] ?? currency + " "}${s}` : s;
}

export function usd(amount: string | number | null | undefined): string {
  return amount === null || amount === undefined ? "—" : `USD ${money(amount)}`;
}

export function shortTime(iso?: string | null): string {
  if (!iso) return "";
  return iso.replace("T", " ").slice(0, 16);
}

export const PERSONA = {
  mother: "p_zhang_min",
  student: "p_li_wei",
} as const;

export function personaName(id?: string | null): string {
  if (id === PERSONA.mother) return "Zhang Min · 妈妈";
  if (id === PERSONA.student) return "Li Wei";
  return id || "";
}

export const STATUS_LABEL: Record<string, string> = {
  draft: "Draft",
  awaiting_documents: "Awaiting documents",
  pending_approval: "Awaiting approval",
  approved: "Approved",
  executed: "Paid",
  held: "Held for approval",
  blocked: "Blocked",
  refused: "Refused",
  expired: "Expired",
  rejected: "Rejected",
};

export function statusTone(status: string): "pass" | "warn" | "block" | "neutral" {
  if (status === "executed" || status === "approved") return "pass";
  if (status === "blocked" || status === "refused" || status === "rejected") return "block";
  if (status === "held" || status === "awaiting_documents" || status === "pending_approval") return "warn";
  return "neutral";
}
