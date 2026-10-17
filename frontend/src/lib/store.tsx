// App state: chat session, persona, live intents, consent, approval modal.
import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, Card, Turn } from "./api";
import { approveIntent, ensureDevice, forgetDevices } from "./device";
import { PERSONA } from "./format";

type PendingTurn = Turn & { pending?: boolean; error?: string; key: string };

type Store = {
  ready: boolean;
  sessionId: string;
  persona: string;
  modelLabel: string;
  turns: PendingTurn[];
  intents: Record<string, Card>;
  selectedIntent: string | null;
  consent: Record<string, boolean>;
  busy: boolean;
  toast: string | null;
  approvalFor: string | null;
  setPersona: (p: string) => void;
  send: (text: string, docIds?: string[]) => Promise<void>;
  upload: (file: File, text: string) => Promise<void>;
  selectIntent: (id: string | null) => void;
  openApproval: (id: string | null) => void;
  approve: (id: string) => Promise<{ complete: boolean }>;
  reject: (id: string, reason: string) => Promise<void>;
  giveConsent: () => Promise<void>;
  deleteMyData: () => Promise<void>;
  refreshIntents: () => Promise<void>;
  appendTurn: (t: Turn) => void;
  resetSession: () => Promise<void>;
  notify: (msg: string) => void;
};

const Ctx = createContext<Store | null>(null);
const SESSION_KEY = "bridge.session.v1";
let turnSeq = 0;
const key = () => `t${++turnSeq}`;

function storageGet(k: string): string | null {
  try {
    return localStorage.getItem(k);
  } catch {
    return null;
  }
}
function storageSet(k: string, v: string) {
  try {
    localStorage.setItem(k, v);
  } catch {
    /* ignore */
  }
}

export function StoreProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [sessionId, setSessionId] = useState("");
  const [persona, setPersonaState] = useState<string>(PERSONA.mother);
  const [modelLabel, setModelLabel] = useState("");
  const [turns, setTurns] = useState<PendingTurn[]>([]);
  const [intents, setIntents] = useState<Record<string, Card>>({});
  const [selectedIntent, setSelectedIntent] = useState<string | null>(null);
  const [consent, setConsent] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [approvalFor, setApprovalFor] = useState<string | null>(null);
  const toastTimer = useRef<number>();

  const notify = useCallback((msg: string) => {
    setToast(msg);
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 5200);
  }, []);

  const refreshIntents = useCallback(async () => {
    const { intents: list } = await api.intents();
    const map: Record<string, Card> = {};
    for (const c of list) map[c.intent_id] = c;
    setIntents(map);
    setSelectedIntent((cur) => cur ?? list[0]?.intent_id ?? null);
  }, []);

  const startNewSession = useCallback(async (p: string) => {
    const s = await api.start(p);
    storageSet(SESSION_KEY, s.session_id);
    setSessionId(s.session_id);
    setModelLabel(s.model_label);
    setConsent(s.consent);
    setTurns([]);
    return s;
  }, []);

  // Boot: resume the chat session if the server still knows it, else start a new one.
  useEffect(() => {
    (async () => {
      const health = await api.health();
      setModelLabel(health.model_label);
      const saved = storageGet(SESSION_KEY);
      let resumed = false;
      if (saved) {
        try {
          const h = await api.history(saved);
          setSessionId(saved);
          setTurns(h.turns.map((t) => ({ ...t, key: key() })));
          resumed = true;
        } catch {
          resumed = false;
        }
      }
      if (!resumed) await startNewSession(PERSONA.mother);
      const [m, s] = await Promise.all([api.consentStatus(PERSONA.mother), api.consentStatus(PERSONA.student)]);
      setConsent({ [PERSONA.mother]: m.consented, [PERSONA.student]: s.consented });
      await Promise.all([ensureDevice(PERSONA.mother), ensureDevice(PERSONA.student)]).catch(() => undefined);
      await refreshIntents();
      setReady(true);
    })().catch((e) => notify(`Backend unavailable: ${e.message}`));
  }, [notify, refreshIntents, startNewSession]);

  const appendTurn = useCallback((t: Turn) => {
    if (!t || (!t.messages?.length && !t.cards?.length)) return;
    setTurns((prev) => [...prev, { ...t, key: key() }]);
  }, []);

  const absorbCards = useCallback((cards: Card[]) => {
    const latest = [...cards].reverse().find((c) => c.type === "intent" || c.type === "receipt");
    if (latest?.intent_id) setSelectedIntent(latest.intent_id);
  }, []);

  const setPersona = useCallback(
    (p: string) => {
      setPersonaState(p);
      if (sessionId) api.switchPersona(sessionId, p).catch(() => undefined);
    },
    [sessionId],
  );

  const send = useCallback(
    async (text: string, docIds: string[] = []) => {
      const k = key();
      setTurns((prev) => [...prev, { key: k, user: { persona, text, doc_ids: docIds }, messages: [], cards: [], pending: true }]);
      setBusy(true);
      try {
        const out = await api.chat(sessionId, persona, text, docIds);
        setTurns((prev) => prev.map((t) => (t.key === k ? { ...out, user: { persona, text, doc_ids: docIds }, key: k } : t)));
        absorbCards(out.cards);
        await refreshIntents();
      } catch (e) {
        const msg = e instanceof ApiError ? e.message : String(e);
        setTurns((prev) => prev.map((t) => (t.key === k ? { ...t, pending: false, error: msg } : t)));
      } finally {
        setBusy(false);
      }
    },
    [absorbCards, persona, refreshIntents, sessionId],
  );

  const upload = useCallback(
    async (file: File, text: string) => {
      setBusy(true);
      let docId: string;
      try {
        docId = (await api.upload(persona, file)).doc_id;
      } catch (e) {
        setBusy(false);
        if (e instanceof ApiError && e.ruleId === "P-001") {
          setConsent((c) => ({ ...c, [persona]: false }));
          notify("Consent is needed before Bridge can read documents (P-001).");
        } else notify(e instanceof Error ? e.message : String(e));
        return;
      }
      setBusy(false);
      const zh = persona === PERSONA.mother;
      await send(text.trim() || (zh ? `请帮我看看这份文件：${file.name}` : `Please check this document: ${file.name}`), [docId]);
    },
    [notify, persona, send],
  );

  const approve = useCallback(
    async (id: string) => {
      const out = await approveIntent(id, persona, sessionId);
      if (out.agent) {
        appendTurn(out.agent);
        absorbCards(out.agent.cards || []);
      }
      await refreshIntents();
      return { complete: !!out.approval_status?.complete };
    },
    [absorbCards, appendTurn, persona, refreshIntents, sessionId],
  );

  const reject = useCallback(
    async (id: string, reason: string) => {
      await api.reject(id, persona, reason);
      await refreshIntents();
    },
    [persona, refreshIntents],
  );

  const giveConsent = useCallback(async () => {
    await api.consent(persona);
    setConsent((c) => ({ ...c, [persona]: true }));
  }, [persona]);

  const deleteMyData = useCallback(async () => {
    const r = await api.deleteData(persona);
    notify(`Deleted ${r.documents} document(s), ${r.devices} device(s) and consent. Masked audit entries kept.`);
    forgetDevices();
    setConsent((c) => ({ ...c, [persona]: false }));
  }, [notify, persona]);

  const resetSession = useCallback(async () => {
    forgetDevices();
    await startNewSession(PERSONA.mother);
    setPersonaState(PERSONA.mother);
    setIntents({});
    setSelectedIntent(null);
    setApprovalFor(null);
    await Promise.all([ensureDevice(PERSONA.mother), ensureDevice(PERSONA.student)]).catch(() => undefined);
    await refreshIntents();
  }, [refreshIntents, startNewSession]);

  const value = useMemo<Store>(
    () => ({
      ready, sessionId, persona, modelLabel, turns, intents, selectedIntent, consent, busy, toast, approvalFor,
      setPersona, send, upload, selectIntent: setSelectedIntent, openApproval: setApprovalFor, approve, reject,
      giveConsent, deleteMyData, refreshIntents, appendTurn, resetSession, notify,
    }),
    [ready, sessionId, persona, modelLabel, turns, intents, selectedIntent, consent, busy, toast, approvalFor, setPersona,
      send, upload, approve, reject, giveConsent, deleteMyData, refreshIntents, appendTurn, resetSession, notify],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useStore(): Store {
  const s = useContext(Ctx);
  if (!s) throw new Error("StoreProvider missing");
  return s;
}
