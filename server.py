import os
import json
import base64
from datetime import datetime, timezone, timedelta
from flask import Flask, render_template, jsonify, request, Response
import anthropic

sys_path = os.path.dirname(__file__)
import sys
sys.path.insert(0, sys_path)

from tracker.db import get_conn, init_db, import_json_jobs, DB_PATH
import subprocess

app = Flask(__name__)
init_db()

DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")

@app.before_request
def require_auth():
    if not DASHBOARD_PASSWORD:
        return
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth[6:]).decode("utf-8")
            _, password = decoded.split(":", 1)
            if password == DASHBOARD_PASSWORD:
                return
        except Exception:
            pass
    return Response(
        "Unauthorized",
        401,
        {"WWW-Authenticate": 'Basic realm="Agent Dashboard"'},
    )

def _pull_and_import():
    try:
        result = subprocess.run(["git", "pull"], cwd=os.path.dirname(__file__), capture_output=True, text=True, timeout=15)
    except Exception as e:
        print(f"[db] git pull failed: {e}", file=sys.stderr)
    try:
        n = import_json_jobs()
        if n:
            print(f"[db] Imported {n} job(s) from data/jobs/")
    except Exception as e:
        print(f"[db] import failed: {e}", file=sys.stderr)

_pull_and_import()

AGENTS = [
    "discovery_brief",
    "brief_impact_analysis",
    "signal_research",
    "action_plan",
    "nps",
    "pipeline_agent",
    "followup_tracker",
    "second_brain",
    "daily_todo_agent",
]

AGENT_LABELS = {
    "discovery_brief":      "Discovery Brief",
    "brief_impact_analysis": "Brief Impact Analysis",
    "signal_research":      "Signal Research",
    "action_plan":          "Action Plan",
    "nps":                  "NPS Agent",
    "pipeline_agent":       "Pipeline Agent",
    "followup_tracker":     "Follow-up Tracker",
    "second_brain":         "Second Brain",
    "daily_todo_agent":     "Daily Todo Agent",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_utc():
    return datetime.now(timezone.utc)


def _mtd_start():
    n = _now_utc()
    return n.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()


def _days_elapsed():
    n = _now_utc()
    return max(n.day, 1)


def _parse_date_range():
    """Return (start_iso, end_iso, days) from query params or MTD defaults."""
    from_str = request.args.get("from")
    to_str = request.args.get("to")
    try:
        start = datetime.fromisoformat(from_str).replace(tzinfo=timezone.utc) if from_str else _now_utc().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = datetime.fromisoformat(to_str).replace(hour=23, minute=59, second=59, tzinfo=timezone.utc) if to_str else _now_utc()
    except ValueError:
        start = _now_utc().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = _now_utc()
    days = max((end - start).days + 1, 1)
    return start.isoformat(), end.isoformat(), days


def _30d_start():
    return (_now_utc() - timedelta(days=30)).isoformat()


def _7d_start():
    return (_now_utc() - timedelta(days=7)).isoformat()


def _agent_mtd(conn, agent_name, start=None, end=None):
    start = start or _mtd_start()
    end = end or _now_utc().isoformat()
    row = conn.execute("""
        SELECT
            COALESCE(SUM(cost_total),0) as spend,
            COALESCE(SUM(input_tokens),0) as input_tokens,
            COALESCE(SUM(output_tokens),0) as output_tokens,
            COALESCE(SUM(web_searches),0) as web_searches,
            COUNT(*) as jobs,
            COALESCE(SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END),0) as failed
        FROM jobs WHERE agent_name=? AND started_at>=? AND started_at<=?
    """, (agent_name, start, end)).fetchone()
    return dict(row)


def _budget(conn, agent_name):
    row = conn.execute("SELECT monthly_budget_usd FROM agent_budgets WHERE agent_name=?", (agent_name,)).fetchone()
    return row["monthly_budget_usd"] if row else None


def _budget_status(spend, budget, days_elapsed):
    if budget is None:
        return None
    projected = spend / days_elapsed * 30 if days_elapsed > 0 else 0
    if spend >= budget:
        return "critical"
    if projected >= budget:
        return "warning"
    return "ok"


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html", agents=AGENTS, agent_labels=AGENT_LABELS)


@app.route("/agent/<agent_name>")
def agent_page(agent_name):
    label = AGENT_LABELS.get(agent_name, agent_name)
    return render_template("agent.html", agent_name=agent_name, agent_label=label)


# ---------------------------------------------------------------------------
# API — Global summary
# ---------------------------------------------------------------------------

@app.route("/api/summary")
def api_summary():
    _pull_and_import()
    conn = get_conn()
    start, end, days = _parse_date_range()

    agents_data = []
    total_spend = total_in = total_out = total_searches = total_jobs = total_failed = 0

    for agent in AGENTS:
        mtd = _agent_mtd(conn, agent, start, end)
        budget = _budget(conn, agent)
        status = _budget_status(mtd["spend"], budget, days)
        projected = mtd["spend"] / days * 30 if days > 0 else 0
        agents_data.append({
            "name": agent,
            "label": AGENT_LABELS[agent],
            "spend": mtd["spend"],
            "input_tokens": mtd["input_tokens"],
            "output_tokens": mtd["output_tokens"],
            "web_searches": mtd["web_searches"],
            "jobs": mtd["jobs"],
            "failed": mtd["failed"],
            "budget": budget,
            "projected": projected,
            "budget_status": status,
        })
        total_spend   += mtd["spend"]
        total_in      += mtd["input_tokens"]
        total_out     += mtd["output_tokens"]
        total_searches += mtd["web_searches"]
        total_jobs    += mtd["jobs"]
        total_failed  += mtd["failed"]

    # Daily spend within selected range
    daily = conn.execute("""
        SELECT DATE(started_at) as day, SUM(cost_total) as spend
        FROM jobs WHERE started_at>=? AND started_at<=?
        GROUP BY day ORDER BY day
    """, (start, end)).fetchall()

    # Run frequency: jobs per day per agent, within selected range
    freq = conn.execute("""
        SELECT agent_name, COUNT(*) as jobs
        FROM jobs WHERE started_at>=? AND started_at<=?
        GROUP BY agent_name
    """, (start, end)).fetchall()
    freq_map = {r["agent_name"]: round(r["jobs"] / max(days, 1), 2) for r in freq}

    conn.close()
    return jsonify({
        "total_spend": total_spend,
        "total_input_tokens": total_in,
        "total_output_tokens": total_out,
        "total_web_searches": total_searches,
        "total_jobs": total_jobs,
        "total_failed": total_failed,
        "agents": agents_data,
        "daily_spend": [{"day": r["day"], "spend": r["spend"]} for r in daily],
        "run_frequency": freq_map,
    })


# ---------------------------------------------------------------------------
# API — Agent drilldown
# ---------------------------------------------------------------------------

@app.route("/api/agent/<agent_name>")
def api_agent(agent_name):
    conn = get_conn()
    days = _days_elapsed()
    mtd = _agent_mtd(conn, agent_name)
    budget = _budget(conn, agent_name)
    projected = mtd["spend"] / days * 30 if days > 0 else 0

    # Aggregate stats
    agg = conn.execute("""
        SELECT
            COALESCE(AVG(cost_total),0)       as avg_cost,
            COALESCE(AVG(duration_seconds),0)  as avg_duration,
            COALESCE(AVG(web_searches),0)      as avg_searches,
            COALESCE(AVG(CASE WHEN input_tokens>0
                THEN CAST(cache_read_tokens AS REAL)/input_tokens
                ELSE 0 END),0)                  as cache_hit_rate,
            COALESCE(SUM(CASE WHEN status='success' THEN 1 ELSE 0 END)*1.0/NULLIF(COUNT(*),0),0) as success_rate,
            COUNT(*) as total_jobs
        FROM jobs WHERE agent_name=?
    """, (agent_name,)).fetchone()

    today_start = _now_utc().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    week_start  = (_now_utc() - timedelta(days=7)).isoformat()

    runs_today = conn.execute("SELECT COUNT(*) FROM jobs WHERE agent_name=? AND started_at>=?", (agent_name, today_start)).fetchone()[0]
    runs_week  = conn.execute("SELECT COUNT(*) FROM jobs WHERE agent_name=? AND started_at>=?", (agent_name, week_start)).fetchone()[0]
    runs_month = mtd["jobs"]

    # Cost-per-job trend: daily avg cost last 30 days
    cost_trend = conn.execute("""
        SELECT DATE(started_at) as day, AVG(cost_total) as avg_cost, COUNT(*) as jobs
        FROM jobs WHERE agent_name=? AND started_at>=?
        GROUP BY day ORDER BY day
    """, (agent_name, _30d_start())).fetchall()

    # Prompt bloat: compare avg cost/job last 7d vs prior 7d
    prior_14d = (_now_utc() - timedelta(days=14)).isoformat()
    cost_last7  = conn.execute("SELECT AVG(cost_total) FROM jobs WHERE agent_name=? AND started_at>=?", (agent_name, week_start)).fetchone()[0] or 0
    cost_prior7 = conn.execute("SELECT AVG(cost_total) FROM jobs WHERE agent_name=? AND started_at>=? AND started_at<?", (agent_name, prior_14d, week_start)).fetchone()[0] or 0
    bloat_flag = (cost_last7 > cost_prior7 * 1.20) if cost_prior7 > 0 else False

    # Token source breakdown: avg across last 30 jobs
    token_breakdown = conn.execute("""
        SELECT
            AVG(system_prompt_tokens) as sys,
            AVG(tool_result_tokens)   as tool,
            AVG(conversation_tokens)  as conv,
            AVG(input_tokens)         as total_in
        FROM (SELECT * FROM jobs WHERE agent_name=? ORDER BY started_at DESC LIMIT 30)
    """, (agent_name,)).fetchone()

    # Run frequency: jobs per day last 30 days
    run_freq = conn.execute("""
        SELECT DATE(started_at) as day, COUNT(*) as jobs
        FROM jobs WHERE agent_name=? AND started_at>=?
        GROUP BY day ORDER BY day
    """, (agent_name, _30d_start())).fetchall()

    # Jobs table: last 100
    jobs = conn.execute("""
        SELECT id, job_name, started_at, duration_seconds, status,
               input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
               web_searches, cost_total, system_prompt_tokens, tool_result_tokens, conversation_tokens
        FROM jobs WHERE agent_name=?
        ORDER BY started_at DESC LIMIT 100
    """, (agent_name,)).fetchall()

    conn.close()
    return jsonify({
        "agent_name": agent_name,
        "label": AGENT_LABELS.get(agent_name, agent_name),
        "budget": budget,
        "projected": projected,
        "budget_status": _budget_status(mtd["spend"], budget, days),
        "mtd": dict(mtd),
        "agg": dict(agg),
        "runs_today": runs_today,
        "runs_week": runs_week,
        "runs_month": runs_month,
        "cost_trend": [{"day": r["day"], "avg_cost": r["avg_cost"], "jobs": r["jobs"]} for r in cost_trend],
        "bloat_flag": bloat_flag,
        "token_breakdown": dict(token_breakdown) if token_breakdown else {},
        "run_freq": [{"day": r["day"], "jobs": r["jobs"]} for r in run_freq],
        "jobs": [dict(j) for j in jobs],
    })


# ---------------------------------------------------------------------------
# API — Budget
# ---------------------------------------------------------------------------

@app.route("/api/agent/<agent_name>/budget", methods=["POST"])
def api_set_budget(agent_name):
    data = request.get_json()
    budget = float(data.get("budget", 0))
    conn = get_conn()
    conn.execute("""
        INSERT INTO agent_budgets (agent_name, monthly_budget_usd, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(agent_name) DO UPDATE SET monthly_budget_usd=excluded.monthly_budget_usd, updated_at=excluded.updated_at
    """, (agent_name, budget, _now_utc().isoformat()))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "budget": budget})


# ---------------------------------------------------------------------------
# API — AI Insights
# ---------------------------------------------------------------------------

INSIGHTS_PROMPT = """You are an AI cost optimization advisor analyzing usage data for an Anthropic API agent.

Agent: {agent_name}

Aggregate stats (all time):
{stats}

Last 50 jobs (most recent first):
{jobs}

Return exactly 3-5 specific, actionable optimization recommendations based on the data above.
Focus on: cache hit rate, web search costs, input token growth trends, failure rates, cost variance, duration trends, tool result token dominance.

Format each recommendation as JSON in this exact structure:
[
  {{"severity": "optimization"|"warning"|"critical", "title": "short title", "detail": "specific actionable recommendation referencing actual numbers from the data"}},
  ...
]

Return only the JSON array, no other text."""


@app.route("/api/agent/<agent_name>/insights", methods=["POST"])
def api_insights(agent_name):
    conn = get_conn()
    agg = conn.execute("""
        SELECT
            COUNT(*) as total_jobs,
            AVG(cost_total) as avg_cost,
            AVG(duration_seconds) as avg_duration,
            AVG(web_searches) as avg_searches,
            AVG(CASE WHEN input_tokens>0 THEN CAST(cache_read_tokens AS REAL)/input_tokens ELSE 0 END) as cache_hit_rate,
            SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END)*1.0/NULLIF(COUNT(*),0) as failure_rate,
            AVG(system_prompt_tokens) as avg_sys_tokens,
            AVG(tool_result_tokens) as avg_tool_tokens,
            AVG(conversation_tokens) as avg_conv_tokens
        FROM jobs WHERE agent_name=?
    """, (agent_name,)).fetchone()

    jobs = conn.execute("""
        SELECT job_name, started_at, duration_seconds, status,
               input_tokens, output_tokens, cache_read_tokens, web_searches, cost_total
        FROM jobs WHERE agent_name=? ORDER BY started_at DESC LIMIT 50
    """, (agent_name,)).fetchall()
    conn.close()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return jsonify({"error": "ANTHROPIC_API_KEY not set"}), 500

    client = anthropic.Anthropic(api_key=api_key)
    prompt = INSIGHTS_PROMPT.format(
        agent_name=AGENT_LABELS.get(agent_name, agent_name),
        stats=json.dumps(dict(agg), indent=2),
        jobs=json.dumps([dict(j) for j in jobs], indent=2),
    )
    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        insights = json.loads(raw)
        return jsonify({"insights": insights})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# API — Amy Performance
# ---------------------------------------------------------------------------

_local_bdr = os.path.join(os.path.dirname(__file__), "..", "bdr-agent")
_repo_bdr  = os.path.join(os.path.dirname(__file__), "bdr-agent")
BDR_AGENT_PATH = _local_bdr if os.path.isdir(_local_bdr) else _repo_bdr

@app.route("/api/amy")
def api_amy():
    import re

    # 1. Draft + respond runs from SQLite
    conn = get_conn()
    draft_runs = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE agent_name='bdr-agent' AND job_name LIKE 'draft:%'"
    ).fetchone()[0]
    respond_runs = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE agent_name='bdr-agent' AND job_name LIKE 'respond:%'"
    ).fetchone()[0]
    mtd_cost = conn.execute(
        "SELECT COALESCE(SUM(cost_total),0) FROM jobs WHERE agent_name='bdr-agent' AND started_at>=?",
        (_mtd_start(),)
    ).fetchone()[0]

    # 2. Scores from respond job names: "respond: 8" or "respond: 8/10"
    score_jobs = conn.execute(
        "SELECT job_name, started_at FROM jobs WHERE agent_name='bdr-agent' AND job_name LIKE 'respond:%' ORDER BY started_at DESC"
    ).fetchall()
    conn.close()

    score_log = []
    for row in score_jobs:
        m = re.match(r"respond:\s*(\d+)(/10)?$", row["job_name"].strip())
        if m:
            score_log.append({
                "score": int(m.group(1)),
                "date": row["started_at"][:10],
                "job_name": row["job_name"],
            })

    avg_score = round(sum(s["score"] for s in score_log) / len(score_log), 1) if score_log else None

    # Scores by date (avg per day)
    from collections import defaultdict
    by_date = defaultdict(list)
    for s in score_log:
        by_date[s["date"]].append(s["score"])
    scores_by_date = sorted([
        {"date": d, "avg_score": round(sum(v)/len(v), 1)}
        for d, v in by_date.items()
    ], key=lambda x: x["date"])

    # 3. Meetings booked — count bdr-learn job runs from SQLite
    conn2 = get_conn()
    learn_jobs = conn2.execute(
        "SELECT job_name, started_at FROM jobs WHERE agent_name='bdr-agent' AND job_name LIKE 'learn:%' ORDER BY started_at DESC"
    ).fetchall()
    conn2.close()
    meetings = [
        {
            "date": row["started_at"][:10],
            "deal_name": row["job_name"].replace("learn:", "").strip(),
            "contact": "",
        }
        for row in learn_jobs
    ]

    # 4. Guidelines from kb_guidelines.md — parse ## headings
    guidelines = []
    guidelines_path = os.path.join(BDR_AGENT_PATH, "kb", "kb_guidelines.md")
    if os.path.exists(guidelines_path):
        try:
            with open(guidelines_path) as f:
                for line in f:
                    if line.startswith("## "):
                        guidelines.append({"title": line[3:].strip(), "date": ""})
        except Exception:
            pass

    return jsonify({
        "total_drafts":       draft_runs,
        "total_respond_runs": respond_runs,
        "total_meetings":     len(meetings),
        "avg_score":          avg_score,
        "total_guidelines":   len(guidelines),
        "mtd_cost":           mtd_cost,
        "scores_by_date":     scores_by_date,
        "score_log":          score_log[:50],
        "meetings":           meetings,
        "guidelines":         guidelines,
    })


# ---------------------------------------------------------------------------
# API — Amy KB viewer
# ---------------------------------------------------------------------------

@app.route("/api/amy/kb")
def api_amy_kb():
    import re

    result = {}

    # Guidelines — parse into sections
    guidelines_path = os.path.join(BDR_AGENT_PATH, "kb", "kb_guidelines.md")
    if os.path.exists(guidelines_path):
        with open(guidelines_path) as f:
            raw = f.read()
        sections = []
        current = None
        for line in raw.splitlines():
            if line.startswith("## "):
                if current:
                    sections.append(current)
                current = {"title": line[3:].strip(), "body": []}
            elif current:
                current["body"].append(line)
        if current:
            sections.append(current)
        for s in sections:
            # trim trailing blank lines
            while s["body"] and not s["body"][-1].strip():
                s["body"].pop()
            s["body"] = "\n".join(s["body"])
        result["guidelines"] = sections

    # Tone of voice — parse into sections
    tov_path = os.path.join(BDR_AGENT_PATH, "kb", "kb_tone_of_voice.md")
    if os.path.exists(tov_path):
        with open(tov_path) as f:
            raw = f.read()
        sections = []
        current = None
        for line in raw.splitlines():
            if line.startswith("## "):
                if current:
                    sections.append(current)
                current = {"title": line[3:].strip(), "body": []}
            elif current:
                current["body"].append(line)
        if current:
            sections.append(current)
        for s in sections:
            while s["body"] and not s["body"][-1].strip():
                s["body"].pop()
            s["body"] = "\n".join(s["body"])
        result["tov"] = sections

    # Sources — group by unique title, one chunk per title
    sources_path = os.path.join(BDR_AGENT_PATH, "kb", "kb_sources.json")
    if os.path.exists(sources_path):
        with open(sources_path) as f:
            chunks = json.load(f)
        seen = {}
        for c in chunks:
            title = c.get("title", "Untitled")
            if title not in seen:
                seen[title] = {"title": title, "url": c.get("url", ""), "text": c.get("text", "")[:600]}
        result["sources"] = list(seen.values())

    # Winning threads — summary view
    threads_path = os.path.join(BDR_AGENT_PATH, "kb", "kb_winning_threads.json")
    if os.path.exists(threads_path):
        with open(threads_path) as f:
            threads = json.load(f)
        result["threads"] = [
            {
                "deal_name": t.get("deal_name", ""),
                "contact": t.get("contact_name", ""),
                "date": t.get("meeting_date") or t.get("booked_at") or t.get("added_at", ""),
                "source": t.get("source", "albato_learn"),
                "message_count": len(t.get("messages", [])),
                "messages": t.get("messages", []),
            }
            for t in threads
        ]

    return jsonify(result)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    print(f"Dashboard running at http://localhost:{port}")
    print(f"DB: {DB_PATH}")
    app.run(debug=False, host="0.0.0.0", port=port)
