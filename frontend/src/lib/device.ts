// Per-persona "device": the persona toggle simulates two phones, each with its own secret.
// The secret is returned once by the server and kept only in this browser (localStorage).
// Approval MAC = HMAC-SHA256(key = SHA-256(device_secret), digest + ":" + nonce), computed with Web Crypto.
// Production would use WebAuthn / passkeys instead (see docs/DECISIONS.md).
import { api, ApiError } from "./api";

type Device = { device_id: string; device_secret: string };
const KEY = "bridge.devices.v1";

function load(): Record<string, Device> {
  try {
    return JSON.parse(localStorage.getItem(KEY) || "{}");
  } catch {
    return {};
  }
}

function save(all: Record<string, Device>) {
  try {
    localStorage.setItem(KEY, JSON.stringify(all));
  } catch {
    /* storage unavailable: devices live for this page only */
  }
}

const memory: Record<string, Device> = load();

export async function ensureDevice(personId: string, force = false): Promise<Device> {
  if (!force && memory[personId]) return memory[personId];
  const label = personId === "p_li_wei" ? "Li Wei's phone (simulated)" : "Mother's phone (simulated)";
  const d = await api.enroll(personId, label);
  memory[personId] = d;
  save(memory);
  return d;
}

export function forgetDevices() {
  for (const k of Object.keys(memory)) delete memory[k];
  save(memory);
}

const hex = (buf: ArrayBuffer) => Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, "0")).join("");

export async function macFor(secret: string, digest: string, nonce: string): Promise<string> {
  const enc = new TextEncoder();
  const keyBytes = await crypto.subtle.digest("SHA-256", enc.encode(secret));
  const key = await crypto.subtle.importKey("raw", keyBytes, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return hex(await crypto.subtle.sign("HMAC", key, enc.encode(`${digest}:${nonce}`)));
}

/** Challenge + sign + approve. Re-enrols once if the server no longer knows this device (e.g. after a demo reset). */
export async function approveIntent(intentId: string, personId: string, sessionId: string) {
  for (let attempt = 0; attempt < 2; attempt++) {
    const dev = await ensureDevice(personId, attempt > 0);
    try {
      const ch = await api.challenge(intentId, personId, dev.device_id);
      const mac = await macFor(dev.device_secret, ch.digest, ch.nonce);
      return await api.approve(intentId, { person_id: personId, device_id: dev.device_id, nonce: ch.nonce, mac, session_id: sessionId });
    } catch (e) {
      const enrolledProblem = e instanceof ApiError && e.ruleId === "T3-004" && /not enrolled/i.test(e.reason);
      if (!enrolledProblem || attempt > 0) throw e;
    }
  }
  throw new Error("unreachable");
}
