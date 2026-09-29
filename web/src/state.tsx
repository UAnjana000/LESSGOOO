import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, REACHABILITY_EVENT, type VisitorConfig } from "./api";
import { translate, type Key, type Lang } from "./i18n";

export interface BasketEntry {
  item_id: number;
  title: string;
  passage_id?: number;
  page?: number;
  start_ms?: number;
  citation: string;
}

export interface AskTurn {
  q: string;
  a: string;
}

interface Session {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (key: Key, vars?: Record<string, string | number>) => string;
  textScale: number;
  cycleTextScale: () => void;
  contrast: boolean;
  toggleContrast: () => void;
  basket: BasketEntry[];
  addToBasket: (e: BasketEntry) => void;
  removeFromBasket: (e: BasketEntry) => void;
  inBasket: (e: Partial<BasketEntry>) => boolean;
  askHistory: AskTurn[];
  pushAsk: (turn: AskTurn) => void;
  sessionId: string;
  finish: () => void;
  config: VisitorConfig | null;
  online: boolean;
}

const Ctx = createContext<Session | null>(null);
const SCALES = [1, 1.15, 1.3];
const KEY = "archive-visit";

function newSessionId(): string {
  return crypto.randomUUID ? crypto.randomUUID() : `s-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function load(): { lang: Lang; textScale: number; contrast: boolean; basket: BasketEntry[]; askHistory: AskTurn[]; sessionId: string } {
  try {
    const raw = sessionStorage.getItem(KEY);
    if (raw) return JSON.parse(raw);
  } catch {
    /* storage unavailable */
  }
  return { lang: "en", textScale: 1, contrast: false, basket: [], askHistory: [], sessionId: newSessionId() };
}

const same = (a: Partial<BasketEntry>, b: Partial<BasketEntry>) =>
  a.item_id === b.item_id && a.passage_id === b.passage_id && a.page === b.page && a.start_ms === b.start_ms;

export function SessionProvider({ children }: { children: ReactNode }) {
  const initial = useMemo(load, []);
  const [lang, setLang] = useState<Lang>(initial.lang);
  const [textScale, setTextScale] = useState(initial.textScale);
  const [contrast, setContrast] = useState(initial.contrast);
  const [basket, setBasket] = useState<BasketEntry[]>(initial.basket);
  const [askHistory, setAskHistory] = useState<AskTurn[]>(initial.askHistory);
  const [sessionId, setSessionId] = useState(initial.sessionId);
  const [config, setConfig] = useState<VisitorConfig | null>(null);
  const [online, setOnline] = useState(navigator.onLine);
  const [reachable, setReachable] = useState(true);

  useEffect(() => {
    sessionStorage.setItem(KEY, JSON.stringify({ lang, textScale, contrast, basket, askHistory, sessionId }));
  }, [lang, textScale, contrast, basket, askHistory, sessionId]);

  useEffect(() => {
    document.documentElement.lang = lang;
    document.documentElement.style.setProperty("--scale", String(textScale));
    document.documentElement.dataset.contrast = contrast ? "high" : "normal";
  }, [lang, textScale, contrast]);

  useEffect(() => {
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    const server = (e: Event) => setReachable((e as CustomEvent<boolean>).detail);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    window.addEventListener(REACHABILITY_EVENT, server);
    api.get<VisitorConfig>("/api/visitor/config").then(setConfig).catch(() => setConfig(null));
    return () => {
      window.removeEventListener("online", up);
      window.removeEventListener("offline", down);
      window.removeEventListener(REACHABILITY_EVENT, server);
    };
  }, []);

  const finish = useCallback(() => {
    setBasket([]);
    setAskHistory([]);
    setTextScale(1);
    setContrast(false);
    setLang("en");
    setSessionId(newSessionId());
  }, []);

  const value: Session = {
    lang,
    setLang,
    t: (key, vars) => translate(lang, key, vars),
    textScale,
    cycleTextScale: () => setTextScale((s) => SCALES[(SCALES.indexOf(s) + 1) % SCALES.length]),
    contrast,
    toggleContrast: () => setContrast((c) => !c),
    basket,
    addToBasket: (e) => setBasket((b) => (b.some((x) => same(x, e)) ? b : [...b, e].slice(-30))),
    removeFromBasket: (e) => setBasket((b) => b.filter((x) => !same(x, e))),
    inBasket: (e) => basket.some((x) => same(x, e)),
    askHistory,
    pushAsk: (turn) => setAskHistory((h) => [...h, turn].slice(-3)),
    sessionId,
    finish,
    config,
    online: online && reachable,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSession(): Session {
  const s = useContext(Ctx);
  if (!s) throw new Error("SessionProvider missing");
  return s;
}
