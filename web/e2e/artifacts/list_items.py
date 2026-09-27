import json
import ssl
import urllib.request
from pathlib import Path

ctx = ssl._create_unverified_context()
items = json.load(urllib.request.urlopen("https://localhost:9443/api/visitor/items", context=ctx))
out = Path(__file__).with_name("items-titles.txt")
needles = [
    "On Public Reading Rooms",
    "Lecture on Education and Work",
    "Proceedings of the Samarpur Civic Assembly",
    "Handwritten note on the library board",
    "Readers at the Samarpur reading room",
    "Talk on the reading room",
    "Synthetic test-pattern video",
]
lines = [f"{i['id']}\t{i['item_type']}\t{i['title']}" for i in items]
missing = [n for n in needles if not any(n in (i.get("title") or "") for i in items)]
out.write_text("\n".join(lines) + f"\n\ncount={len(items)}\nmissing={missing}\n", encoding="utf-8")
print(f"count={len(items)} missing={missing}")
