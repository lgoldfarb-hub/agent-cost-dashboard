# Agent Cost Dashboard — Session Log

Log of working sessions with Claude. Updated at the end of each session.

Each entry covers:
- **Done** — what was changed, added, or removed (files, logic, UI)
- **Problems** — issues and errors encountered
- **Deferred** — decisions postponed and why
- **Open questions** — open questions for next session

---

## 2026-06-14

### Done
- **Added HTTP Basic Auth** — `server.py` now checks `DASHBOARD_PASSWORD` env var via `@app.before_request`. Any username, correct password grants access. If env var is not set, dashboard stays open (safe for local dev).
- **Added Procfile** — `web: python server.py` so Railway knows the start command.
- **Fixed port binding** — `server.py` now reads `$PORT` env var (Railway requirement) and binds to `0.0.0.0`.
- **Deployed to Railway** — connected `lgoldfarb-hub/agent-cost-dashboard` repo to existing Railway service (previously running second-brain Telegram bot). Set custom start command to `python server.py` in Railway settings.
- **Dashboard live** at `https://web-production-0e7481.up.railway.app` — password-protected, shareable with teammates.
- **Fixed import on Railway** — `_pull_and_import()` was only calling `import_json_jobs()` when git pull returned "Fast-forward". Fixed to always run import regardless of git pull result.
- **Swapped Documentation and Amy Performance tab order** — Documentation is now second, Amy Performance third.
- **Second Brain decommissioned** — Railway service now runs the dashboard. Second brain repo left dormant.

### Problems
- Railway was auto-detecting `telegram_bot.py` as the start command from the previous repo — overridden via Railway custom start command setting.
- Procfile was present but ignored due to cached build config from the old repo.
- Railway DB started empty — fixed by always running import on startup.
- Local vs Railway data discrepancy: historical Second Brain jobs were tracked locally only, not via GitHub Actions, so they don't appear on Railway. Gap is permanent but acceptable.

### Deferred
- None.

### Open questions / next session
- None.

---

## 2026-06-14 (continued 2)

### Done
- **Fixed KB sync for large files** — moved sync logic from inline shell to `.github/scripts/sync_kb.py`. Fixes "argument list too long" on `kb_sources.json` (289KB) and YAML heredoc syntax error. All 4 KB files now sync correctly.

### Problems
- Shell `base64 | curl -d` fails on files >~100KB due to OS arg limit.
- YAML heredoc syntax incompatible with GitHub Actions `run:` block.

### Deferred
- None.

### Open questions / next session
- None.

---

## 2026-06-14 (continued)

### Done
- **KB sync from bdr-agent** — `server.py` now looks for KB files in `bdr-agent/kb/` inside the repo (Railway path) when `../bdr-agent/` doesn't exist. `sync-kb.yml` in bdr-agent repo copies all 4 KB files on every `kb/**` push. Amy Performance KB viewer now populates on Railway automatically.

### Problems
- `kb_sources.json` and `kb_winning_threads.json` weren't synced on first run — only changed files trigger the workflow. Fixed by manually touching both files.

### Deferred
- None.

### Open questions / next session
- None.

---

## 2026-05-16

### Done
- **Updated Second Brain documentation** — expanded the Second Brain entry in `templates/index.html` with full description: two interfaces (Telegram bot + web dashboard at localhost:5055), Railway hosting, digest classification logic, all connectors with exact lookback windows, available bot actions table, secrets table (names only). Fixed workflow diagram to show 2 triggers (30-min poller + Telegram message) and 2 outputs (Telegram bot + web dashboard).

### Problems
- None.

### Deferred
- None.

### Open questions / next session
- None.

---

## 2026-05-14

### Done
- **Sorted agents table by MTD spend descending** — `static/app.js` `renderAgentsTable()`: added `.sort((a, b) => b.spend - a.spend)` on a spread copy of `d.agents` before mapping to rows. No backend change needed; sort is client-side.
- **Created `docs/session-log.md`** — this file.

### Problems
- None.

### Deferred
- None.

### Open questions / next session
- None.

---

## 2026-07-03

### Done
- **Registered the new Runtime Custdev Brief agent** (from sibling repo `discovery-brief-agent-runtime`) — added `runtime_custdev_brief` to `AGENTS` and `AGENT_LABELS` in `server.py` (displays as "Runtime Custdev Brief" in cost charts). Its `tracker.py` job records were already flowing into the DB (confirmed via a live dry-run test against Duda), but had no display label until now.
- **Added a Documentation tab entry** — new `data-agent="runtime-custdev-brief"` doc-card in `templates/index.html` plus a matching filter button, following the same structure as the other per-agent cards (workflow diagram, rules, output-section table, input data sources, secrets, file structure).

### Problems
- Found an unrelated, pre-existing uncommitted diff in this repo's working tree (the 2026-06-14 session-log entries above, plus a stray `jobs.db`) that predates this session — left untouched and uncommitted per user's choice, since it wasn't part of this change and isn't mine to bundle in.
- A `git push` was rejected because `discovery-brief-agent-runtime`'s own `tracker.py` had pushed a job-record commit to this repo in the meantime — resolved with a stash + rebase + push + stash-pop to avoid losing the untouched session-log diff.

### Deferred
- The pre-existing uncommitted session-log/jobs.db diff — still sitting in the working tree, not committed.

### Open questions / next session
- None specific to this change.
