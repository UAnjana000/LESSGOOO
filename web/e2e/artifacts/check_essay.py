import json
import ssl
import urllib.request
from pathlib import Path

ctx = ssl._create_unverified_context()
base = "https://localhost:9443"


def req(method: str, path: str, data=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = None if data is None else json.dumps(data).encode()
    r = urllib.request.Request(base + path, data=body, headers=headers, method=method)
    with urllib.request.urlopen(r, context=ctx) as resp:
        return json.load(resp)


login = req("POST", "/api/staff/login", {"email": "admin@archive.local", "password": "e2e-admin-password"})
token = login["token"]
items = req("GET", "/api/staff/items?limit=50", token=token)
out = []
for it in items if isinstance(items, list) else items.get("items", items.get("results", [])):
    title = it.get("title") or ""
    if "essay" in title.lower() or "reading rooms" in title.lower() or it.get("id") == 1:
        detail = req("GET", f"/api/staff/items/{it['id']}", token=token)
        out.append({
            "id": it.get("id"),
            "title": title,
            "state": detail.get("state") or detail.get("publication_state"),
            "item_type": detail.get("item_type"),
            "pages": len(detail.get("pages") or []),
            "page_statuses": [p.get("status") for p in (detail.get("pages") or [])],
            "keys": list(detail.keys())[:20],
        })

Path(__file__).with_name("essay-state.json").write_text(json.dumps({"staff_list_type": type(items).__name__, "preview": items if isinstance(items, dict) else "list", "matches": out, "list_len": len(items) if isinstance(items, list) else None}, default=str, indent=2)[:8000], encoding="utf-8")
print("matches", len(out), "list_kind", type(items).__name__)
