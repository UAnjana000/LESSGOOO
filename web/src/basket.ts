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
