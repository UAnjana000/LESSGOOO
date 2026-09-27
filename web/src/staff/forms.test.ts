import { describe, expect, it } from "vitest";
import { metadataBody, metadataForm, parseList } from "./forms";

describe("parseList", () => {
  it("splits on commas, trims and drops blanks", () => {
    expect(parseList(" Education, Caste ,, Mahad ")).toEqual(["Education", "Caste", "Mahad"]);
    expect(parseList("   ")).toEqual([]);
  });
});

describe("metadataForm", () => {
  it("fills the form from the staff item metadata, joining lists", () => {
    const f = metadataForm({ subjects: ["Education", "Caste"], people: [], places: ["Mahad"], date_text: "c. 1927", date_start: "1927-03-01", date_end: null, date_certainty: "approximate", languages: ["en"], edition: null, volume: "Vol. 1", publisher: null, creator: "B. R. Ambedkar" });
    expect(f).toMatchObject({ subjects: "Education, Caste", people: "", places: "Mahad", date_text: "c. 1927", date_start: "1927-03-01", date_end: "", date_certainty: "approximate", languages: "en", edition: "", volume: "Vol. 1", creator: "B. R. Ambedkar", reason: "" });
  });

  it("defaults certainty to unknown when metadata is missing", () => {
    expect(metadataForm(undefined).date_certainty).toBe("unknown");
  });
});

describe("metadataBody", () => {
  it("sends lists as arrays, blank text as null and the trimmed reason", () => {
    const body = metadataBody({ ...metadataForm(undefined), subjects: "Education, Caste", places: "", date_text: " ", date_start: "1927-03-01", date_certainty: "exact", languages: "en, mr", volume: "Vol. 1", reason: "  catalogue check  " });
    expect(body).toEqual({
      subjects: ["Education", "Caste"], people: [], places: [], date_text: null, date_start: "1927-03-01", date_end: null,
      date_certainty: "exact", languages: ["en", "mr"], edition: null, volume: "Vol. 1", publisher: null, creator: null, reason: "catalogue check",
    });
  });
});
