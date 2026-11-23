# AGENTS.md: JobsDoctor

JobsDoctor ("Resuscitate your job search") is an AI career clinic. The user clicks **Get Started**, checks in with a first name, and does a short intake with **Nurse Ruby**, one question per message: a tap-to-choose status menu (plus a graduation-date menu for students), the scripted "What brings you in today?" rundown, then seven AI steps (Claude), including two reflective questions and a step where the nurse reflects back the criterion behind the job title for the user to confirm or correct, plus a closing "anything else?" question. An animated waiting room (nurse taking notes, career-vitals monitor, Rx pad) runs for at least 20 seconds while the doctor (Claude) writes the **job prescription**: diagnosis and guiding principle, profile, stretch goal, areas to target with roles and pay estimates, questions to ask employers (the first tests the guiding principle), how to get the meeting, a pitch, next steps, and a closing note.

## Project structure

```
.
├── server.py          The server: serves docs/, holds the API key, calls Claude, rate-limits AI calls
├── requirements.txt   Empty on purpose: standard library only (Render installs from it)
├── security_check.py  Press Run: checks the live site for exposed keys and a working rate limit
├── SECURITY.md        Security audit results
├── .vscode/launch.json  The Run button configuration for VS Code
├── .env.example       Template for .env (placeholders only)
├── .gitignore         Keeps .env out of Git
├── AGENTS.md          This file
└── docs/              Everything the browser loads (also published by GitHub Pages)
    ├── index.html     Product Page: pitch, screenshots, PRD v3, build log
    ├── app.html       The app: landing, check-in, intake chat, waiting room, prescription
    ├── config.js      Public browser settings (PostHog project key; no secrets)
    ├── analytics.js   Loads PostHog: pageviews, clicks, session replay
    └── ai-demo.png    Screenshot of a real AI run, shown on the Product Page
```

## Setup and run (macOS)

Requirements: Python 3 (no packages to install) and an Anthropic API key.

**In VS Code (easiest):** open the project folder, then press **Run** (F5) and choose **Run JobsDoctor**. The app opens in your browser.

**In Terminal:** `cd` into the project folder and run `python3 server.py`.

The first time, paste your Anthropic API key when asked. It is saved once in `~/.jobsdoctor/.env` (your home folder, outside every project), so new builds use it automatically. A `.env` file in the project folder still works and takes priority.

If port 8000 is busy (for example, an older build is still running), the server uses the next free port and prints the address. Add `--no-browser` to skip opening the browser. Press **Control+C** to stop.

## How it works

1. `app.html` collects answers and sends the conversation to `POST /api/chat` on the local server.
2. `server.py` adds the coaching instructions (kept server-side) and calls the Claude Messages API.
   - `mode: "chat"`: the nurse asks one question for intake step `turn` (3 to 9). Steps 1 and 2, the graduation menu and the closing question are scripted in `app.html`. Each step's job is defined in `STAGES` in `server.py`; step 6 is the reflection. The app adds a final "anything else?" question.
   - `mode: "plan"`: Claude returns the prescription as JSON in a fixed shape (`PLAN_PROMPT`), which `renderPlan()` in `app.html` renders. The waiting room runs at least `MIN_WAIT_MS` (20 s) and until the prescription arrives.
3. The server prints the token usage and cost of every call in Terminal.

On GitHub Pages there is no server, so the app there shows a notice and points to the live Render app.

## Shipping (deploy to Render)

The live app runs on Render as a Python web service. GitHub stores the code; Render pulls it and runs `server.py`.

**First deploy (one time):**
1. Sign up at render.com.
2. Click **New → Web Service**, choose **Public Git Repository**, and paste `https://github.com/building-with-ai-f26/cdg9431-jobsly`.
3. Settings: **Name** `jobsdoctor` · **Language** Python 3 · **Branch** `main` · **Root directory** blank · **Build command** `pip install -r requirements.txt` · **Start command** `python server.py` · **Instance type** Free.
4. Under **Environment Variables**, add `ANTHROPIC_API_KEY` = your key. Never put it anywhere else.
5. Click **Deploy Web Service**. When the log says "JobsDoctor is live on Render", open the address Render shows (like `https://jobsdoctor.onrender.com`) and add `/app.html`.
6. Put that address in `docs/config.js` (`liveAppUrl`) so the Product Page and the GitHub Pages copy link to it.

**Every later deploy:**
1. Upload the new build to GitHub (one commit).
2. In Render, open the service and click **Manual Deploy → Deploy latest commit**. (A public-repo service does not redeploy on its own.)
3. Check the live site: open `/app.html`, finish one intake, and confirm the prescription appears.
4. Run `security_check.py` against the live address and confirm **PASS**.

**Roll back a bad deploy:** in Render, open **Events**, find the last good deploy, and click **Rollback**.

**Server limits (environment variables on Render, optional):** `RATE_LIMIT_PER_10_MIN` (default 20), `DAILY_AI_CALL_CAP` (default 300), `CLAUDE_MODEL`.

## Ask me first

Stop and ask the owner before doing any of these:
- Deleting files, folders, or deploys; changing or deleting stored data.
- Anything involving keys, secrets, or permissions: creating, rotating, moving or displaying the API key; changing Render environment variables; changing who can access the repo or Render service.
- Anything that costs money: changing the AI model, raising `max_tokens`, raising the rate limits or daily cap, upgrading the Render plan, or turning on paid add-ons (such as web search).
- Transferring, renaming or making the repo private, or changing GitHub Pages settings (the live URLs would break).
- Removing or loosening any security check (rate limits, request validation, escaping AI text).

## Configuration

| Setting | Where | Default |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | `~/.jobsdoctor/.env` (or project `.env`) | required |
| `CLAUDE_MODEL` | `.env` | `claude-sonnet-5-5` |
| `PORT` | environment (Render sets it) | `8000` locally |
| `RATE_LIMIT_PER_10_MIN` | environment | `20` AI calls per visitor |
| `DAILY_AI_CALL_CAP` | environment | `300` AI calls per day, whole site |
| PostHog key and host | `docs/config.js` | empty (analytics off) |

## Rules for anyone (human or agent) working on this repo

- Never commit `.env` or put an API key in any file under `docs/`. GitHub Pages makes `docs/` public.
- Keep the coaching prompts in `server.py`, not in the browser.
- The plan JSON shape in `PLAN_PROMPT` and `renderPlan()` in `app.html` must stay in sync.
- Escape all AI text before inserting it into the page (`esc()` in `app.html`).
- Keep answers short and label pay as estimates; never present deadlines as fact.
- Every route that calls Claude must go through `check_rate()`.

### Rules learned from real mistakes

- **Never set `max_tokens` below 4,000 on a Claude call, and always check for an empty reply.** On Nov 16 the agent set it to 300; the model spent its budget thinking and returned blank chat bubbles during a live test. Fixed with 4,000 for chat and 16,000 for the prescription, plus an empty-reply check.
- **Confirm where the course wants things before creating them.** The agent said a personal repo was fine; the professor required the class organization, which cost a grade point and a repo transfer.
- **Preview fonts with real text before choosing one.** The agent picked a logo font whose italic capital J had a decorative swash; it only showed up when the name changed to "JobsDoctor".
- **Don't turn one tester's story into everyone's script.** The agent built the intake's backup question and examples around one teammate's realization (hands-on tech versus management), so unrelated users got an off-topic question. Prompts must build on each user's own words; examples must cover different kinds of people.
- **When testing, stop old servers before starting new ones.** Leftover test servers kept answering on port 8000, so a re-test hit old code and looked like the fixes failed.
