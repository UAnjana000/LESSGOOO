import { describe, expect, it } from "vitest";
import { DERIVATIVE_LABELS, derivativeLabel, LANGS, STRINGS, textLang, TRANSLATION_REVIEW, translate, type Key, type Lang } from "./i18n";
import { staffEn } from "./i18n.staff";
import { ITEM_TYPES } from "./filters";

const LANG_CODES: Lang[] = ["en", "hi", "mr"];
const DEVANAGARI = /[\u0900-\u097F]/;

describe("interface strings", () => {
  const keys = Object.keys(STRINGS.en).sort();

  it("offers exactly English, Hindi and Marathi", () => {
    expect(LANGS.map((l) => l.code)).toEqual(LANG_CODES);
    expect(Object.keys(STRINGS).sort()).toEqual([...LANG_CODES].sort());
  });

  it.each(LANG_CODES)("%s has the same keys as every other language and no empty strings", (lang) => {
    for (const other of LANG_CODES) {
      const mine = Object.keys(STRINGS[lang]).sort();
      const theirs = Object.keys(STRINGS[other]).sort();
      expect(mine.filter((k) => !theirs.includes(k)), `${lang} keys missing from ${other}`).toEqual([]);
      expect(theirs.filter((k) => !mine.includes(k)), `${other} keys missing from ${lang}`).toEqual([]);
    }
    for (const k of keys) expect(STRINGS[lang][k as Key].trim(), `${lang}.${k}`).not.toBe("");
  });

  it.each(LANG_CODES)("%s keeps every {placeholder} used in English", (lang) => {
    for (const k of keys) {
      const want = (STRINGS.en[k as Key].match(/\{\w+\}/g) ?? []).sort();
      const got = (STRINGS[lang][k as Key].match(/\{\w+\}/g) ?? []).sort();
      expect(got, `${lang}.${k}`).toEqual(want);
    }
  });

  it.each(["hi", "mr"] as const)("%s strings are written in Devanagari, not left in English", (lang) => {
    // Short tokens that are deliberately the same in every language.
    const sameEverywhere = new Set<Key>(["captions"]);
    const untranslated = keys.filter((k) => {
      const s = STRINGS[lang][k as Key];
      return !sameEverywhere.has(k as Key) && !DEVANAGARI.test(s);
    });
    expect(untranslated, `${lang} strings without Devanagari`).toEqual([]);
  });

  it("has a label for every collection, item type and map node type the API can send", () => {
    const dynamic = [
      ...["writings", "speeches", "debates", "manuscripts", "photographs", "audio_video"].map((c) => `col_${c}`),
      ...ITEM_TYPES.map((t) => `type_${t}`),
      ...["person", "organisation", "place", "event", "concept", "document"].map((n) => `node_${n}`),
    ];
    for (const lang of LANG_CODES) for (const k of dynamic) expect(STRINGS[lang], `${lang}.${k}`).toHaveProperty(k);
  });

  it("fills placeholders and formats numbers", () => {
    expect(translate("en", "results", { n: 1200 })).toBe("1,200 results");
    expect(translate("en", "noResults", { q: "tank" })).toContain("“tank”");
  });

  it("labels synthetic narration and machine translation honestly in every language", () => {
    for (const lang of LANG_CODES) {
      expect(STRINGS[lang].synthNarration.length).toBeGreaterThan(10);
      expect(STRINGS[lang].mtLabel.length).toBeGreaterThan(10);
      expect(STRINGS[lang].fixtureBanner.length).toBeGreaterThan(20);
    }
  });

  it("says in every language that Constitution links are curated by staff, not AI", () => {
    for (const lang of LANG_CODES) expect(STRINGS[lang].constitutionCurated).toContain("AI");
  });

  it("uses the spec wording for the Ask answer label", () => {
    expect(STRINGS.en.askLabel).toBe("AI-generated answer from archive sources");
  });
});

describe("derivative labels sent by the API", () => {
  // Spec §1.1 and backend KIND_LABELS / PAGE_LABELS / label_shown / the MT label.
  const backendLabels = [
    "Original scan",
    "Source text",
    "Reviewed transcription",
    "Reviewed transcript",
    "Reviewed caption",
    "Reviewed translation",
    "Reviewed summary",
    "Synthetic narration",
    "Machine translation — not reviewed",
    "AI-generated answer from archive sources",
  ];

  it("maps every backend label to an interface string", () => {
    for (const label of backendLabels) expect(DERIVATIVE_LABELS, label).toHaveProperty([label]);
  });

  it.each(["hi", "mr"] as const)("shows every backend label in %s", (lang) => {
    for (const label of backendLabels) {
      const d = derivativeLabel(lang, label);
      expect(d.lang, label).toBeUndefined();
      expect(DEVANAGARI.test(d.text), `${lang}: ${label} → ${d.text}`).toBe(true);
    }
  });

  it("keeps the English meaning of each label in English", () => {
    for (const label of backendLabels) expect(derivativeLabel("en", label).text, label).toBe(label);
  });

  it("shows an unknown label as sent, marked as English for screen readers", () => {
    expect(derivativeLabel("hi", "Something new")).toEqual({ text: "Something new", lang: "en" });
  });
});

describe("textLang", () => {
  it("marks Latin-script archive text as English and Devanagari as the Indian UI language", () => {
    expect(textLang("Annihilation of Caste", "hi")).toBe("en");
    expect(textLang("जातीचे निर्मूलन", "mr")).toBe("mr");
    expect(textLang("जाति का विनाश", "en")).toBe("hi");
    expect(textLang("1936", "hi")).toBeUndefined();
    expect(textLang(null, "en")).toBeUndefined();
  });
});

describe("translation review flag", () => {
  it("covers every language", () => {
    expect(Object.keys(TRANSLATION_REVIEW).sort()).toEqual([...LANG_CODES].sort());
  });

  it("marks a language native-reviewed only with a named reviewer and date", () => {
    for (const lang of LANG_CODES) {
      const r = TRANSLATION_REVIEW[lang];
      if (r.status === "native_reviewed") {
        expect(r.reviewer?.trim(), lang).toBeTruthy();
        expect(r.date, lang).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      }
    }
    expect(TRANSLATION_REVIEW.en.status).toBe("source");
  });

  it("covers the archivist workspace strings in every language", () => {
    for (const lang of LANG_CODES) for (const k of Object.keys(staffEn)) expect(STRINGS[lang], `${lang}.${k}`).toHaveProperty(k);
  });
});

describe("visitor and staff screens take every string from i18n", () => {
  const sources = import.meta.glob(["./pages/*.tsx", "./components/*.tsx", "./staff/*.tsx"], { query: "?raw", import: "default", eager: true }) as Record<string, string>;

  it("found the visitor and staff source files", () => {
    expect(Object.keys(sources).length).toBeGreaterThanOrEqual(10);
    expect(Object.keys(sources)).toContain("./staff/Staff.tsx");
  });

  it.each(Object.keys(sources))("%s has no hard-coded English text or accessible names", (file) => {
    const src = sources[file].replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
    const problems: string[] = [];
    // JSX text on one line between tags, e.g. <p>Loading…</p>.
    // TypeScript generics (`=> Promise<unknown>`) look like JSX text to this pattern.
    const generic = /^(Promise|Record|Array|Map|Set|Partial|ReturnType)$/;
    for (const m of src.matchAll(/>\s*([^<>{}()=;\n]*[A-Za-z]{3,}[^<>{}()=;\n]*)\s*</g)) if (!generic.test(m[1].trim())) problems.push(m[1].trim());
    // JSX text on its own line.
    for (const m of src.matchAll(/^\s+([A-Za-z][A-Za-z']+(?: [A-Za-z',]+)+[.?!…]?)\s*$/gm)) problems.push(m[1].trim());
    // Literal accessible names and visible attributes.
    for (const m of src.matchAll(/\b(?:aria-label|alt|placeholder|title)="([^"]*[A-Za-z]{3,}[^"]*)"/g)) problems.push(m[1]);
    expect(problems).toEqual([]);
  });
});
