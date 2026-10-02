export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public offline = false,
    public reasonCategory?: string,
  ) {
    super(message);
  }
}

export function apiErrorFromBody(status: number, body: unknown, offline: boolean): ApiError {
  let detail = "";
  let category: string | undefined;
  if (body && typeof body === "object" && "detail" in body) {
    const raw = (body as { detail: unknown }).detail;
    if (typeof raw === "string") {
      detail = raw;
    } else if (raw && typeof raw === "object") {
      const obj = raw as { message?: string; reason_category?: string };
      detail = typeof obj.message === "string" ? obj.message : JSON.stringify(raw);
      category = typeof obj.reason_category === "string" ? obj.reason_category : undefined;
    }
  }
  return new ApiError(status, detail || "error", offline, category);
}

export const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
export const API_FALLBACK = (import.meta.env.VITE_API_FALLBACK_URL ?? "").replace(/\/$/, "");

let activeBaseUrl = API_BASE;

export function getActiveApiBase(): string {
  return activeBaseUrl;
}

export function setActiveApiBase(url: string) {
  activeBaseUrl = url.replace(/\/$/, "");
}

export function resolveApiUrl(path: string, base: string = activeBaseUrl): string {
  if (!path || path.startsWith("http://") || path.startsWith("https://") || path.startsWith("blob:") || path.startsWith("data:")) {
    return path;
  }
  return `${base}${path.startsWith("/") ? "" : "/"}${path}`;
}

/**
 * navigator.onLine only knows about the local network. Requests report whether the archive server itself
 * answered (not the service worker's offline copy, not a gateway error) so the offline banner stays honest.
 */
export const REACHABILITY_EVENT = "archive-reachability";
let lastReachable = true;
export function reportReachable(res: Response | null): void {
  const reachable = res !== null && res.headers.get("x-archive-offline") !== "1" && ![502, 503, 504].includes(res.status);
  if (reachable === lastReachable) return;
  lastReachable = reachable;
  window.dispatchEvent(new CustomEvent(REACHABILITY_EVENT, { detail: reachable }));
}

async function request<T>(path: string, init: RequestInit = {}, token?: string | null): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let res: Response | null = null;
  try {
    res = await fetch(resolveApiUrl(path, activeBaseUrl), { ...init, headers });
  } catch (e) {
    if (init.signal?.aborted) throw e; // the caller cancelled it: not a lost connection
    // If primary network fetch failed and we have a fallback, try the fallback
    if (API_FALLBACK && activeBaseUrl !== API_FALLBACK) {
      try {
        const fallbackRes = await fetch(resolveApiUrl(path, API_FALLBACK), { ...init, headers });
        if (fallbackRes.ok || fallbackRes.status < 500) {
          activeBaseUrl = API_FALLBACK;
          res = fallbackRes;
        }
      } catch {
        // Fallback failed too
      }
    }
  }

  // Also check if primary returned a server gateway error (502, 503, 504)
  if (res && res.status >= 502 && API_FALLBACK && activeBaseUrl !== API_FALLBACK) {
    try {
      const fallbackRes = await fetch(resolveApiUrl(path, API_FALLBACK), { ...init, headers });
      if (fallbackRes.ok || fallbackRes.status < 500) {
        activeBaseUrl = API_FALLBACK;
        res = fallbackRes;
      }
    } catch {
      // Keep original response
    }
  }

  if (!res) {
    reportReachable(null);
    throw new ApiError(0, "offline", true);
  }
  reportReachable(res);

  if (!res.ok) {
    try {
      throw apiErrorFromBody(res.status, await res.json(), res.headers.get("x-archive-offline") === "1");
    } catch (e) {
      if (e instanceof ApiError) throw e;
      throw new ApiError(res.status, res.statusText, res.headers.get("x-archive-offline") === "1");
    }
  }
  const type = res.headers.get("content-type") ?? "";
  return (type.includes("json") ? res.json() : res.text()) as Promise<T>;
}

export const api = {
  get: <T>(path: string, token?: string | null) => request<T>(path, {}, token),
  post: <T>(path: string, body: unknown, token?: string | null, signal?: AbortSignal) =>
    request<T>(path, { method: "POST", body: body instanceof FormData ? body : JSON.stringify(body), signal }, token),
  put: <T>(path: string, body: unknown, token?: string | null) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(body) }, token),
};

export const fileUrl = (id: number) => resolveApiUrl(`/api/visitor/files/${id}`);

export interface ArticleRef {
  number: string;
  title: string;
}

export interface ItemCard {
  id: number;
  title: string;
  item_type: string;
  collection: string;
  date_text: string | null;
  date_certainty: string;
  creator: string | null;
  languages: string[];
  edition: string | null;
  volume: string | null;
  is_fixture: boolean;
  online_only: boolean;
  subjects: string[];
  people: string[];
  places: string[];
  /** Only for photographs with an approved caption. */
  photo: { caption: string; credit: string | null; image_file_id: number | null } | null;
}

export interface PassageView {
  id: number;
  text: string;
  language: string;
  kind: string;
  kind_label: string;
  quote_verified: boolean;
  char_start: number;
  bboxes: number[][];
  translations: Record<string, { passage_id: number; text: string }>;
}

export interface PageView {
  id: number;
  sequence: number;
  label: string;
  image_file_id: number | null;
  iiif: string | null;
  derivative_label: string;
  quote_verified: boolean;
  citation: string;
  passages: PassageView[];
  articles: ArticleRef[];
}

export interface Segment {
  id: number;
  start_ms: number;
  end_ms: number;
  speaker: string | null;
  text: string;
  quote_verified: boolean;
  passages: PassageView[];
  articles: ArticleRef[];
}

export interface PhotoDetail {
  caption: string;
  credit: string | null;
  photographer: string | null;
  source_reference: string | null;
  place: string | null;
  event: string | null;
  date_text: string | null;
  people: string[];
}

export interface ItemDetail extends Omit<ItemCard, "photo"> {
  source_institution: string;
  publisher: string | null;
  rights_line: string;
  rights_holder: string;
  version: number;
  provenance: Record<string, unknown>;
  pages: PageView[];
  /** `format` is a MIME type: video/* gets a video player with captions, audio/* an audio player. */
  media: { file_id: number; format: string; captions: string; segments: Segment[]; label: string } | null;
  photo: PhotoDetail | null;
  /** Approved summaries only; drafts never reach visitors. A summary is never a quotation. */
  summaries: { language: string; text: string; label: string; quote_verified: false }[];
  narrations: { language: string; file_id: number; source_ids: number[]; label: string }[];
  related: ItemCard[];
  machine_translation_enabled: boolean;
}

export interface Hit {
  passage_id: number;
  item_id: number;
  text: string;
  language: string;
  kind: string;
  kind_label: string;
  quote_verified: boolean;
  title: string;
  collection: string;
  citation: string;
  deep_link: string;
  page_sequence: number | null;
  start_ms: number | null;
  keyword_rank: number | null;
  semantic_rank: number | null;
  extra: {
    is_fixture?: boolean;
    edition?: string | null;
    volume?: string | null;
    rights_line?: string;
    credit?: string | null;
    item_type?: string;
    creator?: string | null;
    date_text?: string | null;
    subjects?: string[];
    people?: string[];
    places?: string[];
    articles?: ArticleRef[];
  };
}

export interface Facets {
  subjects: string[];
  people: string[];
  places: string[];
}

export interface ConstitutionArticle {
  number: string;
  titles: Record<string, string>;
  part: string | null;
  debates: number;
}

export interface ConstitutionEntry {
  link_id: number;
  note: string | null;
  item: ItemCard;
  passage: Hit | null;
  citation: string;
  deep_link: string;
}

export interface ConstitutionDetail extends Omit<ConstitutionArticle, "debates"> {
  note: string;
  entries: ConstitutionEntry[];
}

export interface AskCitation {
  passage_id: number;
  item_id: number;
  label: string;
  deep_link: string;
  kind_label: string;
  quote_verified: boolean;
  title: string;
  excerpt: string;
  is_fixture?: boolean;
  quoted_spans: string[];
}

export interface AskResult {
  outcome: "answered" | "extractive" | "insufficient" | "refused" | "rejected_input" | "error" | "offline";
  language: string;
  label: string | null;
  message: string | null;
  sentences: { text: string; citations: number[] }[];
  citations: AskCitation[];
  paraphrase_only: boolean;
  retried_retrieval: boolean;
  /** Why a question was not accepted, e.g. "too_long". */
  reason?: string | null;
  /** What the server's validator checked for an answer; absent or null means no check to report. */
  checks?: { citations_ok: boolean; quotes: number; quotes_verified: number } | null;
  claim_support_note?: string;
  cache_hit?: boolean;
  latency_ms?: number;
}

export interface VisitorConfig {
  languages: string[];
  ask_model_connected: boolean;
  /** Spoken questions: transcribed by the answer provider's Whisper through the API, never in the browser. */
  ask_voice_available: boolean;
  ask_voice_max_seconds: number;
  machine_translation: { available: boolean; collections: Record<string, boolean> };
  narration_live_available: boolean;
  fixture_items_visible: number;
  index_version: number;
  session_idle_seconds: number;
  lease_hours: number;
}

export interface TimelineEvent {
  id: number;
  date_text: string;
  sort_date: string;
  date_certainty: string;
  titles: Record<string, string>;
  descriptions: Record<string, string>;
  items: ItemCard[];
}
