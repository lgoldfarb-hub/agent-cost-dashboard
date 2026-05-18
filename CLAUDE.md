# Agent Cost Dashboard — Claude Instructions

## Session startup checklist

At the start of every session:
1. Read `docs/agent-cost-dashboard-session-log.md` for a summary of recent changes, deferred decisions, and open questions.

At the end of every session, always append a new entry to `docs/agent-cost-dashboard-session-log.md` when the user says "save log". Each entry should cover: what was done, problems encountered, decisions deferred, and open questions for next time.

## Project overview

**Goal:** A self-hosted web dashboard that visualizes AI agent cost and usage across all Albato automation agents.

**What it does:**
- Receives job records (JSON) pushed by agents via GitHub Actions (tracker.py)
- Stores records in a SQLite DB (`data/jobs.db`)
- Serves a single-page HTML dashboard with cost charts, per-agent breakdowns, and agent documentation

**Architecture:**
- `app.py` — Flask app, serves the dashboard and receives job records
- `tracker.py` — slim script bundled with each agent; pushes job records to this repo via GitHub API
- `templates/index.html` — the full dashboard UI (single file, vanilla JS + Chart.js)
- `static/style.css` — styles
- `data/jobs.db` — SQLite DB (gitignored)

**Hosting:** Railway (lgoldfarb-hub/agent-cost-dashboard repo, auto-deploys on push to main)

## Key rules

- Always push commits to remote immediately after committing (`git push origin main`). Railway auto-deploys from main.
- All dashboard UI is in `templates/index.html` — no separate JS files.
- The Documentation tab contains one card per agent with scoring/config details — keep these in sync when agent logic changes.

## Secrets (stored as Railway env vars)

- `TRACKER_SECRET` — shared secret for authenticating job record pushes
