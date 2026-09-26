export class ApiError extends Error {
  constructor(public status: number, message: string, public offline = false) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}, token?: string | null): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let res: Response;
  try {
    res = await fetch(path, { ...init, headers });
  } catch {
    throw new ApiError(0, "offline", true);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail, res.headers.get("x-archive-offline") === "1");
  }
  const type = res.headers.get("content-type") ?? "";
  return (type.includes("json") ? res.json() : res.text()) as Promise<T>;
}

export const api = {
  get: <T>(path: string, token?: string | null) => request<T>(path, {}, token),
  post: <T>(path: string, body: unknown, token?: string | null) =>
    request<T>(path, { method: "POST", body: body instanceof FormData ? body : JSON.stringify(body) }, token),
  put: <T>(path: string, body: unknown, token?: string | null) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(body) }, token),
};

export const fileUrl = (id: number) => `/api/visitor/files/${id}`;

export interface ItemCard {
  id: number;
  title: string;
  item_type: string;
  collection: string;
  date_text: string | null;
  creator: string | null;
  languages: string[];
  edition: string | null;
  volume: string | null;
  is_fixture: boolean;
  online_only: boolean;
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
}

export interface Segment {
  id: number;
  start_ms: number;
  end_ms: number;
  speaker: string | null;
  text: string;
  quote_verified: boolean;
  passages: PassageView[];
}

export interface ItemDetail extends ItemCard {
  source_institution: string;
  publisher: string | null;
  date_certainty: string;
  rights_line: string;
  rights_holder: string;
  version: number;
  provenance: Record<string, unknown>;
  pages: PageView[];
  media: { file_id: number; format: string; captions: string; segments: Segment[]; label: string } | null;
  photo: { caption: string; place: string | null; event: string | null; date_text: string | null; photographer: string | null } | null;
  summaries: { language: string; text: string; label: string }[];
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
  extra: { is_fixture?: boolean };
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
  claim_support_note?: string;
  cache_hit?: boolean;
  latency_ms?: number;
}

export interface VisitorConfig {
  languages: string[];
  ask_model_connected: boolean;
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
