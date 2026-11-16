#!/usr/bin/env python3
"""
Jobsly local server.

Runs the Jobsly app on your own computer and talks to Claude for you.
Your Anthropic API key lives only in the .env file next to this script.
It is never sent to the browser and never uploaded to GitHub.

Start it with:   python3 server.py
Then open:       http://localhost:8000/app.html
"""
import getpass
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
ENV_FILE = ROOT / ".env"
PORT = int(os.environ.get("PORT", "8000"))

# Price per million tokens (USD) for the default model, used to report cost per run.
PRICES = {
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-opus-5-5": (4.00, 20.00),
}

# ---------------------------------------------------------------------------
# Key handling: read .env, or ask once in the Terminal and save it.
# ---------------------------------------------------------------------------
def load_env():
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

def ensure_key():
    load_env()
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    print("\nNo API key found yet. Paste your Anthropic API key below.")
    print("(It won't show as you paste. That's normal. Press Enter when done.)\n")
    key = getpass.getpass("API key: ").strip()
    if not key:
        sys.exit("No key entered. Run  python3 server.py  again when you have it.")
    ENV_FILE.write_text(f"ANTHROPIC_API_KEY={key}\n")
    try:
        os.chmod(ENV_FILE, 0o600)
    except OSError:
        pass
    os.environ["ANTHROPIC_API_KEY"] = key
    print("Saved to .env on this computer only. You won't be asked again.\n")

# ---------------------------------------------------------------------------
# The coaching playbook. It stays on the server, so it is not visible in the browser.
# ---------------------------------------------------------------------------
INTAKE_PROMPT = """You are Scout, the career coach inside Jobsly, a personalized career-coaching app.
You are running a short intake interview before building the user's career plan.

Rules:
- Ask exactly ONE question per message. Keep it under 40 words, warm and plain. No lists, no markdown.
- Start with a few words reacting to their last answer, then ask your question.
- Do not give advice yet. You are only gathering what you need for the plan.
- Cover these, in order of importance, adapting to what they've already told you:
  1. Where they are now: current student (and graduation date), recent graduate, working and looking to advance, or working and looking to pivot.
  2. The field, roles or industries they're drawn to, or their background if they're unsure.
  3. Their experience level and strengths.
  4. Location limits and the minimum pay they'd accept.
  5. Deal-breakers, plus any meetings, leads or applications already in motion.
- If they say they're unsure, help them narrow it with a simple either/or question.
This is question {turn} of 5."""

PLAN_PROMPT = """You are Scout, the career coach inside Jobsly. Using the intake conversation, build this person's career plan.

Coaching rules:
- Be specific to this person. Use what they told you; do not invent facts about them.
- Present tradeoffs, not verdicts. Never steer them away from a live opportunity or meeting they mentioned.
- Pay: give a realistic range for someone with their profile, marked as an estimate.
- Never state application deadlines or dates as fact. Tell them to verify current deadlines.
- Respect their location limits and deal-breakers.
- Keep every item short and plain. One steady, encouraging tone.

Return ONLY valid JSON, no other text, in exactly this shape:
{
  "headline": "one sentence naming the direction that fits them",
  "guiding_principle": "the single criterion behind the job title that should guide every decision, one sentence",
  "profile": {"status": "", "target": "", "timeline": "", "location": "", "pay_floor": "", "deal_breakers": ""},
  "areas": [
    {
      "name": "a broad area or field to target, e.g. 'Consulting tech arms' or 'AI engineering'",
      "what_it_is": "",
      "why_it_fits": "why this area fits this person specifically",
      "where_to_look": "the industries and kinds of employers where this area lives",
      "roles": [
        {"title": "a specific role within this area", "what_you_do": "one short sentence", "typical_pay": "estimate range"}
      ],
      "watch_for": ""
    }
  ],
  "questions_to_ask": ["question that separates real opportunities from buzzwords"],
  "get_the_meeting": ["concrete way to land a conversation"],
  "pitch": {"fifteen_second": "a ready-to-say answer to 'tell me about yourself'", "tailoring_tip": "how to adjust it per role"},
  "stretch_goal": {"name": "a short memorable nickname for their long-shot goal", "description": "one sentence"},
  "next_steps": ["checkbox-style action for this week"],
  "closing_note": "a short, personal word of encouragement from Scout"
}
Include as many areas as genuinely fit this person (usually 2 to 4), ordered best fit first, each with 2 to 4 specific roles. Give 4 questions_to_ask, 4 get_the_meeting items and 5 next_steps. Use "Not shared" for any profile field they didn't give."""

# ---------------------------------------------------------------------------
# Calling Claude
# ---------------------------------------------------------------------------
TOTALS = {"input": 0, "output": 0}

def ssl_context():
    try:
        import certifi  # present on many Macs; fixes certificate errors if so
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()

def call_claude(system, messages, max_tokens):
    model = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")
    base = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")
    body = json.dumps({"model": model, "max_tokens": max_tokens,
                       "system": system, "messages": messages}).encode()
    req = urllib.request.Request(base + "/v1/messages", data=body, method="POST", headers={
        "x-api-key": os.environ["ANTHROPIC_API_KEY"],
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=180, context=ssl_context()) as r:
        data = json.loads(r.read())
    text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    if not text.strip():
        kinds = [b.get("type") for b in data.get("content", [])]
        print(f"  Claude sent no text (stop_reason={data.get('stop_reason')}, blocks={kinds}).")
    u = data.get("usage", {})
    tin, tout = u.get("input_tokens", 0), u.get("output_tokens", 0)
    TOTALS["input"] += tin
    TOTALS["output"] += tout
    pin, pout = PRICES.get(model, PRICES["claude-sonnet-5-5"])
    cost = tin / 1e6 * pin + tout / 1e6 * pout
    return text, {"model": model, "input_tokens": tin, "output_tokens": tout, "cost_usd": round(cost, 5)}

def clean_messages(raw):
    msgs = []
    for m in raw if isinstance(raw, list) else []:
        role = m.get("role")
        content = str(m.get("content", ""))[:2000]
        if role in ("user", "assistant") and content.strip():
            msgs.append({"role": role, "content": content})
    if not msgs or msgs[0]["role"] != "user":
        msgs.insert(0, {"role": "user", "content": "Hi!"})
    return msgs[-20:]

def parse_plan(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("The plan came back in an unexpected format.")
    return json.loads(m.group(0))

# ---------------------------------------------------------------------------
# Web server: serves the docs/ folder and answers /api/chat
# ---------------------------------------------------------------------------
class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(DOCS), **kw)

    def log_message(self, fmt, *args):
        pass  # keep the Terminal quiet

    def send_json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/api/chat":
            return self.send_json(404, {"error": "Not found"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            req = json.loads(self.rfile.read(min(length, 100_000)) or b"{}")
            msgs = clean_messages(req.get("messages"))
            if req.get("mode") == "plan":
                text, usage = call_claude(PLAN_PROMPT, msgs + [{"role": "user", "content": "Please build my career plan now."}] if msgs[-1]["role"] == "assistant" else msgs, 16000)
                plan = parse_plan(text)
                print(f"  Career plan built. Cost of this step: ${usage['cost_usd']:.4f}")
                run_cost = TOTALS["input"] / 1e6 * PRICES.get(usage["model"], PRICES["claude-sonnet-5-5"])[0] + TOTALS["output"] / 1e6 * PRICES.get(usage["model"], PRICES["claude-sonnet-5-5"])[1]
                print(f"  Total since server started: {TOTALS['input']} input + {TOTALS['output']} output tokens, about ${run_cost:.4f}")
                return self.send_json(200, {"plan": plan, "usage": usage})
            turn = max(1, min(5, int(req.get("turn", 1))))
            text, usage = call_claude(INTAKE_PROMPT.format(turn=turn), msgs, 4000)
            if not text.strip():
                return self.send_json(502, {"error": "Scout didn't finish that answer. Please tap Try again."})
            print(f"  Scout asked question {turn}. Cost: ${usage['cost_usd']:.4f}")
            return self.send_json(200, {"reply": text.strip(), "usage": usage})
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="ignore")[:300]
            msg = "Your API key was rejected. Delete the .env file and run the server again to re-enter it." if e.code == 401 else f"Claude returned an error ({e.code})."
            print(f"  Error from Claude ({e.code}): {detail}")
            return self.send_json(502, {"error": msg})
        except urllib.error.URLError as e:
            print(f"  Connection problem: {e}")
            hint = " On a Mac with Python from python.org, run 'Install Certificates.command' in your Python folder." if "CERTIFICATE" in str(e).upper() else ""
            return self.send_json(502, {"error": "Couldn't reach Claude. Check your internet connection." + hint})
        except Exception as e:
            print(f"  Problem: {e}")
            return self.send_json(500, {"error": "Something went wrong building your answer. Please try again."})

def main():
    if not DOCS.exists():
        sys.exit("Couldn't find the docs folder. Run this from the project folder.")
    ensure_key()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print("Jobsly is running on your computer.")
    print(f"  App:          http://localhost:{PORT}/app.html")
    print(f"  Product Page: http://localhost:{PORT}/")
    print("Leave this window open while you use the app. Press Control+C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")

if __name__ == "__main__":
    main()
