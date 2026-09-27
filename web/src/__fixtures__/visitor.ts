// Visitor API responses for the rendered accessibility tests. Shapes follow web/src/api.ts.
import type { AskResult, ConstitutionArticle, ConstitutionDetail, Facets, Hit, ItemCard, ItemDetail, TimelineEvent, VisitorConfig } from "../api";

export const config: VisitorConfig = {
  languages: ["en", "hi", "mr"],
  ask_model_connected: true,
  machine_translation: { available: true, collections: { writings: true } },
  narration_live_available: false,
  fixture_items_visible: 0,
  index_version: 1,
  session_idle_seconds: 120,
  lease_hours: 72,
};

export const card = (id: number, title: string, extra: Partial<ItemCard> = {}): ItemCard => ({
  id,
  title,
  item_type: "text",
  collection: "writings",
  date_text: "1936",
  date_certainty: "exact",
  creator: "B. R. Ambedkar",
  languages: ["en"],
  edition: null,
  volume: "Volume 1",
  is_fixture: false,
  online_only: false,
  subjects: ["Caste"],
  people: [],
  places: ["Lahore"],
  photo: null,
  ...extra,
});

export const hit = (id: number, extra: Partial<Hit> = {}): Hit => ({
  passage_id: id,
  item_id: 1,
  text: "Caste is a notion; it is a state of the mind.",
  language: "en",
  kind: "source_text",
  kind_label: "Source text",
  quote_verified: true,
  title: "Annihilation of Caste",
  collection: "writings",
  citation: "Annihilation of Caste, 1936, p. 3",
  deep_link: `/item/1?page=1&passage=${id}`,
  page_sequence: 1,
  start_ms: null,
  keyword_rank: 1,
  semantic_rank: 1,
  extra: { articles: [{ number: "17", title: "Abolition of Untouchability" }] },
  ...extra,
});

const home = {
  collections: [
    { key: "writings", count: 12 },
    { key: "speeches", count: 4 },
    { key: "debates", count: 0 },
    { key: "manuscripts", count: 2 },
    { key: "photographs", count: 5 },
    { key: "audio_video", count: 1 },
  ],
  stories: [{ slug: "mahad", titles: { en: "The Mahad Satyagraha", hi: "महाड सत्याग्रह" } }],
};

const facets: Facets = { subjects: ["Caste", "Education"], people: ["B. R. Ambedkar"], places: ["Mahad"] };

const ask: AskResult = {
  outcome: "answered",
  language: "en",
  label: "AI-generated answer from archive sources",
  message: null,
  sentences: [
    { text: "Ambedkar described caste as a state of mind.", citations: [11] },
    { text: "He argued that it had to be destroyed at its religious root.", citations: [11, 12] },
  ],
  citations: [
    { passage_id: 11, item_id: 1, label: "Annihilation of Caste, 1936, p. 3", deep_link: "/item/1?page=1&passage=11", kind_label: "Source text", quote_verified: true, title: "Annihilation of Caste", excerpt: "Caste is a notion; it is a state of the mind.", quoted_spans: [] },
    { passage_id: 12, item_id: 2, label: "जाति का विनाश, p. 4", deep_link: "/item/2?page=1&passage=12", kind_label: "Reviewed translation", quote_verified: false, title: "जाति का विनाश", excerpt: "जाति एक धारणा है।", quoted_spans: [] },
  ],
  paraphrase_only: false,
  retried_retrieval: false,
};

const item: ItemDetail = {
  ...card(1, "Annihilation of Caste"),
  collection: "speeches",
  languages: ["en"],
  source_institution: "Government of Maharashtra",
  publisher: "Education Department",
  rights_line: "Public domain",
  rights_holder: "Government of Maharashtra",
  version: 2,
  provenance: {},
  pages: [
    {
      id: 101,
      sequence: 1,
      label: "3",
      image_file_id: null,
      iiif: null,
      derivative_label: "Source text",
      quote_verified: true,
      citation: "Annihilation of Caste, 1936, p. 3",
      passages: [
        { id: 11, text: "Caste is a notion; it is a state of the mind.", language: "en", kind: "source_text", kind_label: "Source text", quote_verified: true, char_start: 0, bboxes: [], translations: { hi: { passage_id: 21, text: "जाति एक धारणा है; यह मन की एक अवस्था है।" } } },
      ],
      articles: [{ number: "17", title: "Abolition of Untouchability" }],
    },
    { id: 102, sequence: 2, label: "4", image_file_id: null, iiif: null, derivative_label: "Source text", quote_verified: false, citation: "p. 4", passages: [], articles: [] },
  ],
  media: {
    file_id: 7,
    format: "video/mp4",
    captions: "/api/visitor/files/8",
    label: "Reviewed transcript",
    segments: [
      { id: 1, start_ms: 0, end_ms: 9000, speaker: "B. R. Ambedkar", text: "I measure the progress of a community by the degree of progress which women have achieved.", quote_verified: true, passages: [{ id: 31, text: "I measure…", language: "en", kind: "transcript", kind_label: "Reviewed transcript", quote_verified: true, char_start: 0, bboxes: [], translations: {} }], articles: [] },
      { id: 2, start_ms: 9000, end_ms: 20000, speaker: null, text: "Educate, agitate, organise.", quote_verified: false, passages: [], articles: [] },
    ],
  },
  photo: null,
  summaries: [{ language: "en", text: "A speech prepared for the Jat-Pat-Todak Mandal.", label: "Reviewed summary" }],
  narrations: [{ language: "en", file_id: 9, source_ids: [11], label: "Synthetic narration" }],
  related: [card(2, "जाति का विनाश", { languages: ["hi"] })],
  machine_translation_enabled: true,
};

const articles: ConstitutionArticle[] = [
  { number: "17", titles: { en: "Abolition of Untouchability", hi: "अस्पृश्यता का अंत" }, part: "Part III — Fundamental Rights", debates: 2 },
  { number: "41", titles: { en: "Right to work, to education and to public assistance" }, part: "Part IV", debates: 1 },
];

const article: ConstitutionDetail = {
  number: "17",
  titles: { en: "Abolition of Untouchability", hi: "अस्पृश्यता का अंत" },
  part: "Part III — Fundamental Rights",
  note: "Links chosen by archive staff.",
  entries: [
    { link_id: 1, note: "Ambedkar moves the draft article.", item: card(3, "Constituent Assembly Debates, 29 November 1948", { collection: "debates" }), passage: hit(41, { kind_label: "Reviewed transcription" }), citation: "CAD Vol. 7, p. 665", deep_link: "/item/3?page=1&passage=41" },
  ],
};

const timeline: TimelineEvent[] = [
  { id: 1, date_text: "1927", sort_date: "1927-03-20", date_certainty: "exact", titles: { en: "Mahad Satyagraha", mr: "महाड सत्याग्रह" }, descriptions: { en: "Marchers drink from the Chavdar tank." }, items: [card(4, "Mahad speech")] },
  { id: 2, date_text: "c. 1935", sort_date: "1935-01-01", date_certainty: "approximate", titles: { en: "Yeola declaration" }, descriptions: { en: "A public declaration." }, items: [] },
];

const stories = [{ slug: "mahad", titles: { en: "The Mahad Satyagraha" }, blocks: 2 }];

const story = {
  slug: "mahad",
  titles: { en: "The Mahad Satyagraha" },
  blocks: [{ item: card(5, "Photograph of the Chavdar tank", { item_type: "photograph", collection: "photographs" }), captions: { en: "The Chavdar tank at Mahad." }, image_file_id: 12, passage: hit(51), citation: "Photo archive, 1927", deep_link: "/item/5" }],
  narration_file_ids: { en: 13 },
  narration_label: "Synthetic narration",
};

const map = {
  nodes: [
    { id: 1, type: "person", labels: { en: "B. R. Ambedkar", hi: "बी. आर. आंबेडकर" }, description: "Chairman of the Drafting Committee.", item_ids: [1] },
    { id: 2, type: "place", labels: { en: "Mahad" }, description: null, item_ids: [4] },
    { id: 3, type: "event", labels: { en: "Mahad Satyagraha" }, description: null, item_ids: [] },
  ],
  edges: [
    { id: 1, from: 1, to: 3, relation: "led" },
    { id: 2, from: 3, to: 2, relation: "took_place_in" },
  ],
};

const shared = {
  expires_at: "2026-10-01T12:00:00Z",
  entries: [{ item: card(1, "Annihilation of Caste"), rights_line: "Public domain", passage: hit(11), citation: "Annihilation of Caste, 1936, p. 3", deep_link: "/item/1?page=1&passage=11", start_ms: null }],
  removed_count: 1,
};

const signage = { timeline, story: { titles: story.titles, blocks: story.blocks }, slide_seconds: 12 };

type Route = [RegExp, unknown];
const GET: Route[] = [
  [/^\/api\/visitor\/config$/, config],
  [/^\/api\/visitor\/home$/, home],
  [/^\/api\/visitor\/facets$/, facets],
  [/^\/api\/visitor\/search\?/, { results: [hit(11), hit(12, { title: "जाति का विनाश", language: "hi", text: "जाति एक धारणा है।", kind_label: "Reviewed translation", quote_verified: false })] }],
  [/^\/api\/visitor\/items(\?.*)?$/, [card(1, "Annihilation of Caste"), card(5, "Chavdar tank", { item_type: "photograph", collection: "photographs", photo: { caption: "The Chavdar tank at Mahad.", credit: "Archive", image_file_id: 12 } })]],
  [/^\/api\/visitor\/items\/1\?/, item],
  [/^\/api\/visitor\/constitution$/, articles],
  [/^\/api\/visitor\/constitution\/17$/, article],
  [/^\/api\/visitor\/timeline$/, timeline],
  [/^\/api\/visitor\/stories$/, stories],
  [/^\/api\/visitor\/stories\/mahad$/, story],
  [/^\/api\/visitor\/map$/, map],
  [/^\/api\/visitor\/collections\/abc$/, shared],
  [/^\/api\/visitor\/signage$/, signage],
];

function respond(status: number, body: unknown) {
  return {
    ok: status < 400,
    status,
    statusText: status < 400 ? "OK" : "Not Found",
    headers: new Headers({ "content-type": "application/json" }),
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

/** A fetch stand-in serving the fixtures above; unknown paths get a 404 like the real API. */
export async function fakeFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const url = typeof input === "string" ? input : input instanceof URL ? input.pathname + input.search : input.url;
  const path = url.replace(/^https?:\/\/[^/]+/, "");
  if (init?.method === "POST" && path === "/api/visitor/ask") return respond(200, ask);
  if (init?.method === "POST" && path === "/api/visitor/collections") {
    return respond(200, { token: "abc", url: "https://example.test/c/abc", expires_at: "2026-10-01T12:00:00Z", qr_svg: "<svg viewBox='0 0 1 1'></svg>", count: 1 });
  }
  const route = GET.find(([re]) => re.test(path));
  return route ? respond(200, route[1]) : respond(404, { detail: "Item not found" });
}
