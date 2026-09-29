import { describe, expect, it } from "vitest";
import { detailText, fileNotes, metadataBody, metadataForm, parseList, rightsBody, rightsDowngrades } from "./forms";

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

describe("detailText", () => {
  it("names the field of a validation error by its last loc element", () => {
    expect(detailText([{ type: "string_too_short", loc: ["body", "reason"], msg: "String should have at least 3 characters" }, "rights.title missing"]))
      .toBe("reason: String should have at least 3 characters; rights.title missing");
  });

  it("spells out publish problems and per-file intake notes", () => {
    expect(detailText({ message: "Item is not ready to publish.", problems: ["page 2 not approved", "no rights"] }))
      .toBe("Item is not ready to publish. page 2 not approved; no rights");
    expect(detailText({ message: "No file was stored.", files: [{ name: "a.pdf", status: "duplicate", detail: "already stored" }, { name: "b.bin", status: "rejected" }] }))
      .toBe("No file was stored. a.pdf: duplicate (already stored); b.bin: rejected");
  });

  it("falls back to JSON for an unknown shape", () => {
    expect(detailText({ code: 7 })).toBe('{"code":7}');
    expect(fileNotes(undefined)).toBe("");
  });
});

describe("rights register", () => {
  it("sends blank optional text as null and keeps the other fields", () => {
    expect(rightsBody({ source_key: "k", edition: " ", pages: "12-14", notes: "", is_fixture: true, discovery_only: false }))
      .toEqual({ source_key: "k", source_url: null, edition: null, volume: null, pages: "12-14", training_basis: null, notes: null, is_fixture: true, discovery_only: false });
  });

  it("reports only permissions that move away from allowed on an existing entry", () => {
    const before = { display_permission: "allowed", training_permission: "allowed" };
    expect(rightsDowngrades(before, { display_permission: "not_allowed", training_permission: "allowed" })).toEqual(["display_permission"]);
    expect(rightsDowngrades(before, { display_permission: "allowed", training_permission: "unknown" })).toEqual(["training_permission"]);
    expect(rightsDowngrades({ display_permission: "unknown" }, { display_permission: "not_allowed" })).toEqual([]);
    expect(rightsDowngrades(undefined, { display_permission: "not_allowed" })).toEqual([]);
  });
});
