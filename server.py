#!/usr/bin/env python3
"""
JobsDoctor local server.

Runs the JobsDoctor app on your own computer and talks to Claude for you.
Your Anthropic API key is saved once in ~/.jobsdoctor/.env on your computer.
It is never sent to the browser and never uploaded to GitHub.

Start it with:   python3 server.py   (or the Run button in VS Code)
It opens the app in your browser automatically.
"""
import getpass
import threading
import time
from collections import deque
import webbrowser
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
# The key is saved once in your home folder, so every new build finds it automatically.
HOME_ENV = Path.home() / ".jobsdoctor" / ".env"
LEGACY_ENVS = [Path.home() / "Downloads" / "jobsly" / ".env", Path.home() / "jobsly" / ".env"]
PORT = int(os.environ.get("PORT", "8000"))
ON_RENDER = bool(os.environ.get("RENDER"))  # Render sets this automatically on its servers

# ---- Cost protection (per-visitor and daily limits on AI calls) ----
# One full visit uses 8 AI calls (AI intake steps 3-9 + 1 prescription; the first steps are scripted), so 20 per 10 minutes
# allows about two visits per person and stops anyone hammering the AI.
RATE_LIMIT = int(os.environ.get("RATE_LIMIT_PER_10_MIN", "20"))
RATE_WINDOW = 600  # seconds
DAILY_CAP = int(os.environ.get("DAILY_AI_CALL_CAP", "300"))  # whole site, about 33 visits a day
MAX_BODY = 100_000  # bytes

# Price per million tokens (USD) for the default model, used to report cost per run.
PRICES = {
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-opus-5-5": (4.00, 20.00),
}

# ---------------------------------------------------------------------------
# Key handling: read .env, or ask once in the Terminal and save it.
# ---------------------------------------------------------------------------
def read_env(path):
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

def save_home_env(text):
    HOME_ENV.parent.mkdir(parents=True, exist_ok=True)
    HOME_ENV.write_text(text)
    try:
        os.chmod(HOME_ENV, 0o600)
    except OSError:
        pass

def load_env():
    read_env(ENV_FILE)   # a project-specific .env still works and wins
    read_env(HOME_ENV)   # the shared key for every build
    if not os.environ.get("ANTHROPIC_API_KEY"):
        for old in LEGACY_ENVS:  # pick up a key saved by an earlier build, and move it to the shared spot
            if old.exists():
                read_env(old)
                if os.environ.get("ANTHROPIC_API_KEY"):
                    save_home_env(old.read_text())
                    print(f"Found your saved API key from an earlier build. Every build will use it from now on.")
                    break

def ensure_key():
    load_env()
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    if ON_RENDER or not sys.stdin.isatty():
        sys.exit("ANTHROPIC_API_KEY is not set. On Render: open your service > Environment > add ANTHROPIC_API_KEY, then redeploy.")
    print("\nNo API key found yet. Paste your Anthropic API key below.")
    print("(It won't show as you paste. That's normal. Press Enter when done.)\n")
    key = getpass.getpass("API key: ").strip()
    if not key:
        sys.exit("No key entered. Run  python3 server.py  again when you have it.")
    save_home_env(f"ANTHROPIC_API_KEY={key}\n")
    os.environ["ANTHROPIC_API_KEY"] = key
    print("Saved privately on this computer (not in the project, not on GitHub). Every build will use it.\n")

# ---------------------------------------------------------------------------
# The coaching playbook. It stays on the server, so it is not visible in the browser.
# ---------------------------------------------------------------------------
INTAKE_STEPS = 9  # steps 1-2 are scripted in the app (status menu, short rundown); the AI asks steps 3-9

# What the intake nurse asks at each AI step. One question per step, never two.
# The reflective steps (4-6) help people say out loud what they actually want, not just which title fits.
STAGES = {
    3: "Ask ONE follow-up question about the most important thing missing from their rundown, usually what they have actually done so far or what they are strongest at.",
    4: "Ask ONE reflective question: a specific moment at work or school when they felt most engaged or most like themselves, and what they were doing.",
    5: ("Ask ONE follow-up that digs beneath the most telling thing they have said so far: a frustration they vented, a pattern that keeps repeating, or something that clearly energizes them. "
        "Build on their own words to find out what really matters to them underneath it. Never ask a generic or stock question."),
    6: ("Reflect back what you are hearing. In one or two warm sentences, name the criterion behind the job title that their answers point to, "
        "using their own words where you can. It must come from this person's answers, not from a template. Examples of the kind of sentence, for very different people: "
        "'It sounds like you want to see your work through, not build something and hand it off.' / "
        "'It sounds like steady hours and a team you trust matter more to you than a bigger title.' / "
        "'It sounds like you want to use your business training but stay hands-on with the technology itself.' "
        "Then ask only: does that ring true? This message may be up to 70 words."),
    7: "Briefly acknowledge their answer; if they corrected your reflection, adopt their version. Then ask ONE question: where do they want to work, which cities or remote?",
    8: "Ask ONE question: the minimum yearly pay they would accept.",
    9: "Ask ONE question: do they have any interviews, meetings or leads already in motion?",
}

INTAKE_PROMPT = """You are the intake nurse at JobsDoctor, an AI career clinic whose tagline is "Resuscitate your job search".
You are taking a short intake before the doctor writes this person's job prescription.

Rules:
- Ask exactly ONE short question per message, never two questions in one, and never "and also". Two sentences at most, under 35 words, warm and plain.
- No lists, no markdown, no parentheses, and never spell out a menu of options inside the sentence.
- Start with a few words reacting to their last answer, then ask your question.
- A light clinic touch is welcome now and then, but never more than one medical pun in the whole intake.
- Do not give advice yet. Listen closely: the goal is to help them notice what they really want, not just collect facts.
- If they're unsure, help them narrow it with a simple either/or question.

This is step {turn} of {total}. Your task for this message: {stage}"""

PLAN_PROMPT = """You are the doctor at JobsDoctor, an AI career clinic. Using the intake notes (the conversation), write this person's job prescription.

Coaching rules:
- Be specific to this person. Use what they told you; do not invent facts about them.
- Build everything around the realization from the intake: the criterion behind the job title that they confirmed or corrected. If they corrected the nurse, use their version.
- Present tradeoffs, not verdicts. Never steer them away from a live opportunity or meeting they mentioned.
- Pay: give a realistic range for someone with their profile, marked as an estimate.
- Never state application deadlines or dates as fact. Tell them to verify current deadlines.
- Respect their location limits and deal-breakers.
- Keep every item short and plain. One steady, encouraging tone. No medical advice; the clinic theme is only a metaphor.

Return ONLY valid JSON, no other text, in exactly this shape:
{
  "headline": "one sentence naming the direction that fits them",
  "realization": "two or three sentences written to them about what they discovered in the intake, using their own words where possible, e.g. 'You told me you light up when... What that tells me is...'",
  "guiding_principle": "the single criterion behind the job title that should guide every decision, one sentence",
  "profile": {"status": "", "target": "", "timeline": "", "location": "", "pay_floor": "", "deal_breakers": ""},
  "areas": [
    {
      "name": "a broad area or field to target, e.g. 'Consulting tech arms' or 'AI engineering'",
      "what_it_is": "",
      "why_it_fits": "why this area fits this person specifically, tied to their guiding principle",
      "where_to_look": "the industries and kinds of employers where this area lives",
      "roles": [
        {"title": "a specific role within this area", "what_you_do": "one short sentence", "typical_pay": "estimate range"}
      ],
      "watch_for": ""
    }
  ],
  "questions_to_ask": ["question to ask employers that separates real opportunities from buzzwords"],
  "get_the_meeting": ["concrete way to land a conversation"],
  "pitch": {"fifteen_second": "a ready-to-say answer to 'tell me about yourself'", "tailoring_tip": "how to adjust it per role"},
  "stretch_goal": {"name": "a short memorable nickname for their long-shot goal", "description": "one sentence"},
  "next_steps": ["checkbox-style action for this week"],
  "closing_note": "a short, personal word of encouragement from the doctor"
}
Include as many areas as genuinely fit this person (usually 2 to 4), ordered best fit first, each with 2 to 4 specific roles.
Give 4 questions_to_ask. The FIRST must directly test this person's own guiding principle with an employer, written for them, not copied from an example. For instance, someone who wants to see work through might ask "How long do people in this role usually own a product or account?", while someone who wants to stay technical might ask "How much of this role is hands-on with the technology versus managing it?"
Give 4 get_the_meeting items and 5 next_steps. Use "Not shared" for any profile field they didn't give."""

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
        if not isinstance(m, dict):
            continue
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
# Rate limiting
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_hits = {}                      # visitor -> deque of request times
_day = {"date": None, "count": 0}

def check_rate(visitor):
    """Returns None if allowed, or a message explaining the limit."""
    now = time.time()
    today = time.strftime("%Y-%m-%d", time.gmtime(now))
    with _lock:
        if _day["date"] != today:
            _day["date"], _day["count"] = today, 0
        if _day["count"] >= DAILY_CAP:
            return "JobsDoctor has reached today's visit limit. Please come back tomorrow."
        q = _hits.setdefault(visitor, deque())
        while q and now - q[0] > RATE_WINDOW:
            q.popleft()
        if len(q) >= RATE_LIMIT:
            return "You're going a little fast. Please wait a few minutes and try again."
        q.append(now)
        _day["count"] += 1
        if len(_hits) > 5000:  # keep memory small
            for k in [k for k, v in _hits.items() if not v or now - v[-1] > RATE_WINDOW]:
                _hits.pop(k, None)
    return None

class BadRequest(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message

# ---------------------------------------------------------------------------
# Web server: serves the docs/ folder and answers /api/chat
# ---------------------------------------------------------------------------
class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(DOCS), **kw)

    def log_message(self, fmt, *args):
        pass  # keep the Terminal quiet

    def end_headers(self):
        # Basic browser protections on every response
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        super().end_headers()

    def list_directory(self, path):
        self.send_error(404, "File not found")  # never show folder listings
        return None

    def visitor(self):
        # Render sits behind a proxy, so the visitor's address comes from a header there.
        for h in ("True-Client-IP", "CF-Connecting-IP"):
            if self.headers.get(h):
                return self.headers[h].strip()
        xff = self.headers.get("X-Forwarded-For")
        if xff:
            return xff.split(",")[0].strip()
        return self.client_address[0]

    def read_json(self):
        if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
            raise BadRequest(415, "Requests must be sent as JSON.")
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            raise BadRequest(411, "Missing request size.")
        if length <= 0 or length > MAX_BODY:
            raise BadRequest(413, "That request is too large.")
        try:
            req = json.loads(self.rfile.read(length))
        except ValueError:
            raise BadRequest(400, "That request wasn't valid JSON.")
        if not isinstance(req, dict):
            raise BadRequest(400, "That request wasn't in the expected format.")
        return req

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
            req = self.read_json()
        except BadRequest as e:
            self.close_connection = True
            return self.send_json(e.status, {"error": e.message})
        limited = check_rate(self.visitor())
        if limited:
            print(f"  Rate limit: refused a request ({limited[:40]}...)")
            return self.send_json(429, {"error": limited})
        try:
            if req.get("mode") not in ("chat", "plan"):
                return self.send_json(400, {"error": "Unknown request type."})
            msgs = clean_messages(req.get("messages"))
            if req.get("mode") == "plan":
                text, usage = call_claude(PLAN_PROMPT, msgs + [{"role": "user", "content": "Please write my job prescription now."}] if msgs[-1]["role"] == "assistant" else msgs, 16000)
                plan = parse_plan(text)
                print(f"  Prescription written. Cost of this step: ${usage['cost_usd']:.4f}")
                run_cost = TOTALS["input"] / 1e6 * PRICES.get(usage["model"], PRICES["claude-sonnet-5-5"])[0] + TOTALS["output"] / 1e6 * PRICES.get(usage["model"], PRICES["claude-sonnet-5-5"])[1]
                print(f"  Total since server started: {TOTALS['input']} input + {TOTALS['output']} output tokens, about ${run_cost:.4f}")
                return self.send_json(200, {"plan": plan, "usage": usage})
            try:
                turn = max(min(STAGES), min(INTAKE_STEPS, int(req.get("turn", 3))))
            except (TypeError, ValueError):
                return self.send_json(400, {"error": "That request wasn't in the expected format."})
            system = INTAKE_PROMPT.format(turn=turn, total=INTAKE_STEPS, stage=STAGES[turn])
            text, usage = call_claude(system, msgs, 4000)
            if not text.strip():
                return self.send_json(502, {"error": "The nurse didn't finish that answer. Please tap Try again."})
            print(f"  Nurse asked question {turn} of {INTAKE_STEPS}. Cost: ${usage['cost_usd']:.4f}")
            return self.send_json(200, {"reply": text.strip(), "usage": usage})
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="ignore")[:300]
            if e.code == 401:
                msg = "The clinic's AI key isn't working right now. Please try again later." if ON_RENDER else "Your API key was rejected. Delete ~/.jobsdoctor/.env and run the server again to re-enter it."
            else:
                msg = "The AI service had a problem. Please try again in a moment."
            print(f"  Error from Claude ({e.code}): {detail}")
            return self.send_json(502, {"error": msg})
        except urllib.error.URLError as e:
            print(f"  Connection problem: {e}")
            hint = " On a Mac with Python from python.org, run 'Install Certificates.command' in your Python folder." if "CERTIFICATE" in str(e).upper() else ""
            return self.send_json(502, {"error": "Couldn't reach Claude. Check your internet connection." + hint})
        except Exception as e:
            print(f"  Problem: {e}")
            return self.send_json(500, {"error": "Something went wrong building your answer. Please try again."})

def start_server():
    if ON_RENDER:  # in the cloud: listen on Render's port, on all interfaces
        return ThreadingHTTPServer(("0.0.0.0", PORT), Handler), PORT
    # On your computer: use 8000, or the next free port if an older build is still running.
    for port in range(PORT, PORT + 20):
        try:
            return ThreadingHTTPServer(("127.0.0.1", port), Handler), port
        except OSError:
            continue
    sys.exit("Couldn't find a free port. Close other JobsDoctor windows and try again.")

def main():
    if not DOCS.exists():
        sys.exit("Couldn't find the docs folder. Run this from the project folder.")
    ensure_key()
    server, port = start_server()
    if ON_RENDER:
        print(f"JobsDoctor is live on Render (port {port}). Limits: {RATE_LIMIT} AI calls per visitor per 10 min, {DAILY_CAP} per day.")
        server.serve_forever()
        return
    url = f"http://localhost:{port}/app.html"
    print("JobsDoctor is running on your computer.")
    print(f"  App:          {url}")
    print(f"  Product Page: http://localhost:{port}/")
    if port != PORT:
        print(f"  (Port {PORT} was busy, probably an older build still running, so this one uses {port}.)")
    print("Leave this window open while you use the app. Press Control+C to stop.\n")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")

if __name__ == "__main__":
    main()
