import { describe, expect, it } from "vitest";
import vector from "./__fixtures__/python-signed-manifest.json";
import {
  canonical,
  fileItemIndex,
  importPublicKey,
  leaseValid,
  offlineShellAllowed,
  servable,
  verifyManifest,
  type SignedManifest,
} from "./exhibitVerify";

const signed = vector.manifest as unknown as SignedManifest;

describe("exhibit manifest verification (cross-language with archive/exhibit.py)", () => {
  it("accepts the signature produced by the Python edge server", async () => {
    const key = await importPublicKey(vector.spki_b64);
    expect(await verifyManifest(signed, key)).toBe(true);
  });

  it("rejects a manifest whose payload was altered after signing", async () => {
    const key = await importPublicKey(vector.spki_b64);
    const tampered = structuredClone(signed);
    tampered.payload.withdrawn_item_ids = [];
    expect(await verifyManifest(tampered, key)).toBe(false);
  });

  it("rejects an unexpected algorithm label", async () => {
    const key = await importPublicKey(vector.spki_b64);
    expect(await verifyManifest({ ...signed, alg: "none" }, key)).toBe(false);
  });

  it("serialises like json.dumps(sort_keys=True, separators=(',', ':'), ensure_ascii=False)", () => {
    expect(canonical({ b: 1, a: [true, null, "é"], c: { z: 1, y: "x" } })).toBe('{"a":[true,null,"é"],"b":1,"c":{"y":"x","z":1}}');
  });
});

describe("offline serving rules", () => {
  const p = signed.payload;
  const idx = fileItemIndex(p);
  const beforeExpiry = Date.parse(p.lease_expires_at) - 1000;
  const afterExpiry = Date.parse(p.lease_expires_at) + 1000;

  it("serves cached items and their files within the lease", () => {
    expect(servable(p, "/api/visitor/items/3", idx, beforeExpiry)).toBe(true);
    expect(servable(p, "/api/visitor/files/9", idx, beforeExpiry)).toBe(true);
    expect(servable(p, "/api/visitor/home", idx, beforeExpiry)).toBe(true);
  });

  it("stops serving everything once the lease expires", () => {
    expect(leaseValid(p, afterExpiry)).toBe(false);
    expect(servable(p, "/api/visitor/items/3", idx, afterExpiry)).toBe(false);
    expect(servable(p, "/api/visitor/home", idx, afterExpiry)).toBe(false);
  });

  it("never serves a withdrawn item even if it is still in the cache", () => {
    const withWithdrawn = { ...p, items: [...p.items, { item_id: 5, version: 1, bytes: 1, urls: ["/api/visitor/items/5"], sha256: [] }] };
    expect(servable(withWithdrawn, "/api/visitor/items/5", fileItemIndex(withWithdrawn), beforeExpiry)).toBe(false);
  });

  it("does not serve items that were not in the manifest (e.g. online-only)", () => {
    expect(servable(p, "/api/visitor/items/42", idx, beforeExpiry)).toBe(false);
    expect(servable(p, "/api/visitor/search", idx, beforeExpiry)).toBe(false);
  });

  it("applies the same rules to IIIF images of a delivery file", () => {
    expect(servable(p, "/iiif/9/info.json", idx, beforeExpiry)).toBe(true);
    expect(servable(p, "/iiif/9/full/max/0/default.jpg", idx, afterExpiry)).toBe(false);
    expect(servable(p, "/iiif/77/info.json", idx, beforeExpiry)).toBe(false);
  });
});

describe("offline navigation fallback", () => {
  it("reopens visitor pages, including item addresses, from the precached app shell", () => {
    for (const path of ["/", "/item/3", "/timeline", "/search", "/stories/samarpur", "/c/abc123", "/display"]) {
      expect(offlineShellAllowed(path), path).toBe(true);
    }
  });

  it("never falls back for staff pages or server paths", () => {
    for (const path of ["/staff", "/staff/items/3", "/api/visitor/items/3", "/iiif/3/info.json"]) {
      expect(offlineShellAllowed(path), path).toBe(false);
    }
  });
});
