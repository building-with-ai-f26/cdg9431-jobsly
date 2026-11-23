# AGENTS.md: JobsDoctor

JobsDoctor ("Resuscitate your job search") is an AI career clinic. The user clicks **Get Started**, checks in with a first name, and does a short intake with **Nurse Ruby** (Claude): eight AI steps, including two reflective questions and a step where the nurse reflects back the criterion behind the job title for the user to confirm or correct, plus a closing "anything else?" question. An animated waiting room (nurse taking notes, career-vitals monitor, Rx pad) runs for at least 20 seconds while the doctor (Claude) writes the **job prescription**: diagnosis and guiding principle, profile, stretch goal, areas to target with roles and pay estimates, questions to ask employers (the first tests the guiding principle), how to get the meeting, a pitch, next steps, and a closing note.

## Project structure

```
.
├── server.py          Local server: serves docs/, holds the API key, calls Claude
├── .vscode/launch.json  The Run button configuration for VS Code
├── .env.example       Template for .env
├── .gitignore         Keeps .env out of Git
├── AGENTS.md          This file
└── docs/              Everything the browser loads (also published by GitHub Pages)
    ├── index.html     Product Page: pitch, screenshots, PRD v2, build log
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
   - `mode: "chat"`: the nurse asks one question for intake step `turn` (1 to 8). Each step's job is defined in `STAGES` in `server.py`; step 6 is the reflection. The app adds a final "anything else?" question.
   - `mode: "plan"`: Claude returns the prescription as JSON in a fixed shape (`PLAN_PROMPT`), which `renderPlan()` in `app.html` renders. The waiting room runs at least `MIN_WAIT_MS` (20 s) and until the prescription arrives.
3. The server prints the token usage and cost of every call in Terminal.

On GitHub Pages there is no server, so the app shows a notice that live AI runs locally in this build.

## Configuration

| Setting | Where | Default |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | `~/.jobsdoctor/.env` (or project `.env`) | required |
| `CLAUDE_MODEL` | `.env` | `claude-sonnet-5-5` |
| `PORT` | `.env` or environment | `8000` |
| PostHog key and host | `docs/config.js` | empty (analytics off) |

## Rules for anyone (human or agent) working on this repo

- Never commit `.env` or put an API key in any file under `docs/`. GitHub Pages makes `docs/` public.
- Keep the coaching prompts in `server.py`, not in the browser.
- The plan JSON shape in `PLAN_PROMPT` and `renderPlan()` in `app.html` must stay in sync.
- Escape all AI text before inserting it into the page (`esc()` in `app.html`).
- Keep answers short and label pay as estimates; never present deadlines as fact.
