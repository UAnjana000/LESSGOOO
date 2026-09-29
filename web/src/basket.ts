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
