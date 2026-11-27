import urllib.request, json, time
UA = "confluence-engine/0.1 (research; public endpoints only)"
def get(url, timeout=15, as_json=True, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    raw = urllib.request.urlopen(req, timeout=timeout).read()
    return json.loads(raw) if as_json else raw.decode("utf-8", "replace")
def post_json(url, payload, timeout=15):
    req = urllib.request.Request(url, json.dumps(payload).encode(), {"Content-Type": "application/json", "User-Agent": UA})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())
