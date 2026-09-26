import { describe, expect, it } from "vitest";
import { STRINGS, translate } from "./i18n";

describe("interface strings", () => {
  const keys = Object.keys(STRINGS.en).sort();

  it.each(["hi", "mr"] as const)("%s has every English key and no empty strings", (lang) => {
    expect(Object.keys(STRINGS[lang]).sort()).toEqual(keys);
    for (const k of keys) expect(STRINGS[lang][k as keyof typeof STRINGS.en].trim(), `${lang}.${k}`).not.toBe("");
  });

  it.each(["en", "hi", "mr"] as const)("%s keeps every {placeholder} used in English", (lang) => {
    for (const k of keys) {
      const want = (STRINGS.en[k as keyof typeof STRINGS.en].match(/\{\w+\}/g) ?? []).sort();
      const got = (STRINGS[lang][k as keyof typeof STRINGS.en].match(/\{\w+\}/g) ?? []).sort();
      expect(got, `${lang}.${k}`).toEqual(want);
    }
  });

  it("fills placeholders and formats numbers", () => {
    expect(translate("en", "results", { n: 1200 })).toBe("1,200 results");
    expect(translate("en", "noResults", { q: "tank" })).toContain("“tank”");
  });

  it("labels synthetic narration and machine translation honestly in every language", () => {
    for (const lang of ["en", "hi", "mr"] as const) {
      expect(STRINGS[lang].synthNarration.length).toBeGreaterThan(10);
      expect(STRINGS[lang].mtLabel.length).toBeGreaterThan(10);
      expect(STRINGS[lang].fixtureBanner.length).toBeGreaterThan(20);
    }
  });
});
