#!/usr/bin/env python3
"""
JobsDoctor live security check. Press Run in VS Code (or: python3 security_check.py).

It asks for your live Render address, then:
  1. Downloads the live site's code and searches it for secret API keys.
  2. Searches this project folder for secret API keys.
  3. Calls the AI route 30 times in a row and checks that the rate limit
     kicks in and starts returning 429.

Paste the printed results into SECURITY.md under "Live-site results".
Cost: up to about 20 real AI calls before the limit kicks in, roughly 5 to 10 cents.
"""
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

KEY_PATTERNS = ["sb_secret_", "service_role", "sk-or-", "sk-ant-", "sk-proj-", "sk_live_"]
PLACEHOLDERS = ["sk-or-v1-replace-with-your-key"]  # the class template's example value, not a real key
PAGES = ["/", "/app.html", "/config.js", "/analytics.js"]


def fetch(url, data=None):
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                 headers={"Content-Type": "application/json", "User-Agent": "jobsdoctor-security-check"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, r.read().decode(errors="ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="ignore")


def find_keys(text):
    hits = []
    for p in KEY_PATTERNS:
        for m in re.finditer(re.escape(p) + r"[A-Za-z0-9_\-]{8,}", text):
            if m.group(0) not in PLACEHOLDERS:
                hits.append(m.group(0)[:12] + "…")
    return hits


def main():
    base = (sys.argv[1] if len(sys.argv) > 1 else input("Live site address (e.g. https://jobsdoctor.onrender.com): ")).strip().rstrip("/")
    if not base.startswith("http"):
        base = "https://" + base
    results, ok = [], True

    print(f"\n1) Searching the live site's code at {base} for secret keys…")
    for path in PAGES:
        status, body = fetch(base + path)
        hits = find_keys(body)
        line = f"   {path}: HTTP {status}, " + ("NO secret keys found" if not hits else f"FOUND {hits}")
        print(line); results.append(line)
        ok &= not hits

    print("\n2) Searching this project folder for secret keys…")
    here = Path(__file__).resolve().parent
    found = []
    for f in here.rglob("*"):
        if f.is_file() and ".git" not in f.parts and f.name != ".env" and f.suffix in {".py", ".html", ".js", ".md", ".json", ".txt", ".example", ""}:
            hits = find_keys(f.read_text(errors="ignore")) if f.name != Path(__file__).name else []
            if hits:
                found.append(f"{f.relative_to(here)}: {hits}")
    line = "   NO secret keys in project files" if not found else "   FOUND: " + "; ".join(found)
    print(line); results.append(line)
    ok &= not found

    print("\n3) Calling the AI route 30 times in a row (the rate limit should return 429)…")
    body = json.dumps({"mode": "chat", "turn": 1, "messages": [{"role": "user", "content": "Hi"}]}).encode()
    codes = []
    for i in range(30):
        status, _ = fetch(base + "/api/chat", body)
        codes.append(status)
        print(f"   call {i + 1:2}: {status}")
    first = codes.index(429) + 1 if 429 in codes else None
    line = f"   30 calls -> {codes.count(200)} succeeded, {codes.count(429)} returned 429" + (f" (limit kicked in at call {first})" if first else " (NO rate limit!)")
    print(line); results.append(line)
    ok &= bool(first)

    print("\n" + ("PASS: no exposed keys, and the rate limit works." if ok else "FAIL: see the lines above."))
    print("\nCopy this into SECURITY.md:\n")
    print("\n".join(results))


if __name__ == "__main__":
    main()
