import type { ItemDetail } from "./api";
import type { BasketEntry } from "./state";

/** Reader deep link for a saved entry; `t` makes the recording player seek to the saved segment. */
export function basketLink(e: BasketEntry): string {
  const qs = new URLSearchParams();
  if (e.page != null) qs.set("page", String(e.page));
  if (e.start_ms != null) qs.set("t", String(e.start_ms));
  if (e.passage_id != null) qs.set("passage", String(e.passage_id));
  const s = qs.toString();
  return s ? `/item/${e.item_id}?${s}` : `/item/${e.item_id}`;
}

/** Citation for a whole item: a page citation without its trailing ", p. …", else title, edition and volume. */
export function itemCitation(item: Pick<ItemDetail, "title" | "edition" | "volume" | "pages">): string {
  const first = item.pages[0]?.citation;
  if (first) return first.replace(/, p\. [^,]*$/, "");
  return [item.title, item.edition, item.volume && `Vol. ${item.volume}`].filter(Boolean).join(", ");
}

/** A short one-line excerpt (<=160 chars) for a saved passage; collapses whitespace and cuts at a word. */
export function clipSnippet(text: string, max = 160): string {
  const flat = text.replace(/\s+/g, " ").trim();
  if (flat.length <= max) return flat;
  const cut = flat.slice(0, max - 1);
  const sp = cut.lastIndexOf(" ");
  return `${(sp > max * 0.6 ? cut.slice(0, sp) : cut).trimEnd()}…`;
}

/** The citation without a leading repeat of the title ("Title, 1936, p. 3" under the title "Title" becomes "1936, p. 3"). */
export function citationTail(title: string, citation: string): string {
  const c = citation.trim();
  const t = title.trim();
  if (!c || c === t) return "";
  if (t && c.startsWith(t)) return c.slice(t.length).replace(/^[\s,;:.\u2013\u2014-]+/, "").trim();
  return c;
}
