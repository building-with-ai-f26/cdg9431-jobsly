# AGENTS.md: Jobsly

Jobsly is a personalized AI career coach. The user chats with **Scout** (Claude) for six short questions, and Jobsly turns the conversation into a **Career Plan** dashboard: guiding principle, profile, stretch goal, three options with pay estimates, questions to ask, how to get the meeting, a pitch, next steps, and a closing note.

## Project structure

```
.
├── server.py          Local server: serves docs/, holds the API key, calls Claude
├── .env               Your Anthropic API key (created on first run; never committed)
├── .env.example       Template for .env
├── .gitignore         Keeps .env out of Git
├── AGENTS.md          This file
└── docs/              Everything the browser loads (also published by GitHub Pages)
    ├── index.html     Product Page: pitch, screenshots, PRD v2, build log
    ├── app.html       The app: sign-in, coaching chat, Career Plan dashboard
    ├── config.js      Public browser settings (PostHog project key; no secrets)
    ├── analytics.js   Loads PostHog: pageviews, clicks, session replay
    └── ai-demo.png    Screenshot of a real AI run, shown on the Product Page
```

## Setup and run (macOS)

Requirements: Python 3 (no packages to install) and an Anthropic API key.

1. Open Terminal and go to the project folder, for example:
   `cd ~/Downloads/jobsly`
2. Start the server:
   `python3 server.py`
3. The first time, paste your Anthropic API key when asked. It is saved to `.env` in this folder only.
4. Open **http://localhost:8000/app.html** in your browser.
5. Leave Terminal open while using the app. Press **Control+C** to stop.

If macOS asks to install "command line developer tools" when you run `python3`, click Install, then run the command again.

## How it works

1. `app.html` collects answers and sends the conversation to `POST /api/chat` on the local server.
2. `server.py` adds the coaching instructions (kept server-side) and calls the Claude Messages API.
   - `mode: "chat"`: Scout asks one tailored question (5 in total). The app adds a final "anything else?" question.
   - `mode: "plan"`: Claude returns the Career Plan as JSON in a fixed shape, which `app.html` renders.
3. The server prints the token usage and cost of every call in Terminal.

On GitHub Pages there is no server, so the app shows a notice that live AI runs locally in this build.

## Configuration

| Setting | Where | Default |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | `.env` | required |
| `CLAUDE_MODEL` | `.env` | `claude-sonnet-5-5` |
| `PORT` | `.env` or environment | `8000` |
| PostHog key and host | `docs/config.js` | empty (analytics off) |

## Rules for anyone (human or agent) working on this repo

- Never commit `.env` or put an API key in any file under `docs/`. GitHub Pages makes `docs/` public.
- Keep the coaching prompts in `server.py`, not in the browser.
- The plan JSON shape in `PLAN_PROMPT` and `renderPlan()` in `app.html` must stay in sync.
- Escape all AI text before inserting it into the page (`esc()` in `app.html`).
- Keep answers short and label pay as estimates; never present deadlines as fact.
