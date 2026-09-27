import json
import ssl
import urllib.error
import urllib.parse
import urllib.request

ctx = ssl._create_unverified_context()
base = "https://localhost:9443"


def get(path: str):
    try:
        with urllib.request.urlopen(base + path, context=ctx) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        return e.code, body


print("unfiltered", get("/api/visitor/search?" + urllib.parse.urlencode({"q": "library board"}))[0])
code, body = get("/api/visitor/search?" + urllib.parse.urlencode({"q": "library board", "date_from": "1927-01-01", "date_to": "1927-12-31"}))
print("filtered", code)
print(body if isinstance(body, str) else json.dumps(body, indent=2)[:2000])
