import json
import sqlite3
import os

DB_PATH = os.environ.get("TRACKER_DB_PATH", os.path.join(os.path.dirname(__file__), "..", "data", "jobs.db"))


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_name            TEXT NOT NULL,
            job_name              TEXT NOT NULL,
            model                 TEXT NOT NULL,
            started_at            TEXT NOT NULL,
            completed_at          TEXT,
            duration_seconds      REAL,
            input_tokens          INTEGER DEFAULT 0,
            output_tokens         INTEGER DEFAULT 0,
            cache_read_tokens     INTEGER DEFAULT 0,
            cache_write_tokens    INTEGER DEFAULT 0,
            system_prompt_tokens  INTEGER DEFAULT 0,
            tool_result_tokens    INTEGER DEFAULT 0,
            conversation_tokens   INTEGER DEFAULT 0,
            web_searches          INTEGER DEFAULT 0,
            status                TEXT NOT NULL DEFAULT 'running',
            cost_input            REAL DEFAULT 0,
            cost_output           REAL DEFAULT 0,
            cost_cache_read       REAL DEFAULT 0,
            cost_cache_write      REAL DEFAULT 0,
            cost_web_search       REAL DEFAULT 0,
            cost_total            REAL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS agent_budgets (
            agent_name          TEXT PRIMARY KEY,
            monthly_budget_usd  REAL NOT NULL,
            updated_at          TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS model_pricing (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            model            TEXT NOT NULL,
            input_per_m      REAL NOT NULL,
            output_per_m     REAL NOT NULL,
            cache_read_per_m REAL NOT NULL,
            cache_write_per_m REAL NOT NULL,
            effective_from   TEXT NOT NULL
        );
    """)
    # Seed pricing if empty
    count = c.execute("SELECT COUNT(*) FROM model_pricing").fetchone()[0]
    if count == 0:
        c.executemany(
            "INSERT INTO model_pricing (model, input_per_m, output_per_m, cache_read_per_m, cache_write_per_m, effective_from) VALUES (?,?,?,?,?,?)",
            [
                ("claude-sonnet-4-6", 3.00, 15.00, 0.30, 3.75, "2025-01-01"),
                ("claude-opus-4-6",  15.00, 75.00, 1.50, 18.75, "2025-01-01"),
            ]
        )
    conn.commit()
    conn.close()


def get_pricing(model: str) -> dict:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM model_pricing WHERE model=? ORDER BY effective_from DESC LIMIT 1",
        (model,)
    ).fetchone()
    conn.close()
    if row:
        return dict(row)
    # fallback to sonnet pricing
    return {"input_per_m": 3.00, "output_per_m": 15.00, "cache_read_per_m": 0.30, "cache_write_per_m": 3.75}


def insert_job(job: dict) -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO jobs (
            agent_name, job_name, model,
            started_at, completed_at, duration_seconds,
            input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
            system_prompt_tokens, tool_result_tokens, conversation_tokens,
            web_searches, status,
            cost_input, cost_output, cost_cache_read, cost_cache_write, cost_web_search, cost_total
        ) VALUES (
            :agent_name, :job_name, :model,
            :started_at, :completed_at, :duration_seconds,
            :input_tokens, :output_tokens, :cache_read_tokens, :cache_write_tokens,
            :system_prompt_tokens, :tool_result_tokens, :conversation_tokens,
            :web_searches, :status,
            :cost_input, :cost_output, :cost_cache_read, :cost_cache_write, :cost_web_search, :cost_total
        )
    """, job)
    row_id = c.lastrowid
    conn.commit()
    conn.close()
    return row_id


def import_json_jobs() -> int:
    """Import any JSON job files from data/jobs/ that aren't already in the DB. Returns count imported."""
    jobs_dir = os.path.join(os.path.dirname(__file__), "..", "data", "jobs")
    if not os.path.isdir(jobs_dir):
        return 0
    conn = get_conn()
    imported = 0
    for fname in sorted(os.listdir(jobs_dir)):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(jobs_dir, fname)
        try:
            with open(fpath) as f:
                job = json.load(f)
        except Exception:
            continue
        exists = conn.execute(
            "SELECT 1 FROM jobs WHERE agent_name=? AND started_at=?",
            (job.get("agent_name"), job.get("started_at"))
        ).fetchone()
        if not exists:
            try:
                conn.execute("""
                    INSERT INTO jobs (
                        agent_name, job_name, model,
                        started_at, completed_at, duration_seconds,
                        input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
                        system_prompt_tokens, tool_result_tokens, conversation_tokens,
                        web_searches, status,
                        cost_input, cost_output, cost_cache_read, cost_cache_write, cost_web_search, cost_total
                    ) VALUES (
                        :agent_name, :job_name, :model,
                        :started_at, :completed_at, :duration_seconds,
                        :input_tokens, :output_tokens, :cache_read_tokens, :cache_write_tokens,
                        :system_prompt_tokens, :tool_result_tokens, :conversation_tokens,
                        :web_searches, :status,
                        :cost_input, :cost_output, :cost_cache_read, :cost_cache_write, :cost_web_search, :cost_total
                    )
                """, job)
                imported += 1
            except Exception:
                continue
    conn.commit()
    conn.close()
    return imported


if __name__ == "__main__":
    init_db()
    print(f"DB initialised at {DB_PATH}")
