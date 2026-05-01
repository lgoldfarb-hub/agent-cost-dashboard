"""
Lightweight job tracker for Anthropic API usage.

Usage:
    import sys, os
    sys.path.insert(0, os.path.expanduser("~/agent-cost-dashboard"))
    from tracker.tracker import start_job

    job = start_job("discovery_brief", f"Brief: {deal_name}", model="claude-sonnet-4-6")
    job.add_usage(response.usage)
    job.add_web_searches(n)          # pass count of web_search tool_use blocks
    job.set_system_prompt(prompt_str)  # call once with the system prompt text
    job.add_tool_result(result_str)    # call for each tool result content block
    job.complete()                     # status="success" by default
    job.fail()                         # status="failed"
    job.complete(status="partial")

Local runs: writes to SQLite when ~/agent-cost-dashboard/data/ exists.
GitHub Actions runs: pushes a JSON file to lgoldfarb-hub/agent-cost-dashboard
  when TRACKER_GITHUB_TOKEN env var is set.
"""

import base64
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

_ENABLED = None  # lazy-evaluated
_GITHUB_ENABLED = None


def _is_enabled() -> bool:
    global _ENABLED
    if _ENABLED is None:
        if os.environ.get("TRACKER_DB_PATH"):
            _ENABLED = True
        else:
            default_data = os.path.join(os.path.dirname(__file__), "..", "data")
            _ENABLED = os.path.isdir(os.path.abspath(default_data))
    return _ENABLED


def _is_github_enabled() -> bool:
    global _GITHUB_ENABLED
    if _GITHUB_ENABLED is None:
        _GITHUB_ENABLED = bool(os.environ.get("TRACKER_GITHUB_TOKEN"))
    return _GITHUB_ENABLED


def _push_to_github(record: dict) -> None:
    token = os.environ["TRACKER_GITHUB_TOKEN"]
    ts = record["started_at"].replace(":", "-").replace("+", "").replace(".", "-")[:19]
    filename = f"data/jobs/{ts}-{record['agent_name']}.json"
    content = base64.b64encode(json.dumps(record, indent=2).encode()).decode()
    payload = json.dumps({
        "message": f"[tracker] {record['agent_name']}: {record['job_name'][:60]}",
        "content": content,
    }).encode()
    req = urllib.request.Request(
        f"https://api.github.com/repos/lgoldfarb-hub/agent-cost-dashboard/contents/{filename}",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            print(f"[tracker] pushed {filename} (HTTP {resp.status})")
    except Exception as e:
        print(f"[tracker] WARNING: GitHub push failed: {e}", file=sys.stderr)


class _NoopJob:
    def add_usage(self, usage): pass
    def add_web_searches(self, n=1): pass
    def set_system_prompt(self, text): pass
    def add_tool_result(self, text): pass
    def complete(self, status="success"): pass
    def fail(self): self.complete(status="failed")


class Job:
    def __init__(self, agent_name: str, job_name: str, model: str):
        self.agent_name = agent_name
        self.job_name = job_name
        self.model = model
        self.started_at = datetime.now(timezone.utc).isoformat()
        self._input_tokens = 0
        self._output_tokens = 0
        self._cache_read_tokens = 0
        self._cache_write_tokens = 0
        self._web_searches = 0
        self._system_prompt_tokens = 0
        self._tool_result_chars = 0
        self._first_call = True

    def add_usage(self, usage):
        self._input_tokens  += getattr(usage, "input_tokens", 0) or 0
        self._output_tokens += getattr(usage, "output_tokens", 0) or 0
        self._cache_read_tokens  += getattr(usage, "cache_read_input_tokens", 0) or 0
        self._cache_write_tokens += getattr(usage, "cache_creation_input_tokens", 0) or 0
        self._first_call = False

    def add_web_searches(self, n: int = 1):
        self._web_searches += n

    def set_system_prompt(self, text: str):
        if text:
            self._system_prompt_tokens = len(text) // 4

    def add_tool_result(self, text: str):
        if text:
            self._tool_result_chars += len(text)

    def complete(self, status: str = "success"):
        try:
            pricing = self._get_pricing()
            completed_at = datetime.now(timezone.utc).isoformat()
            started = datetime.fromisoformat(self.started_at)
            completed = datetime.fromisoformat(completed_at)
            duration = (completed - started).total_seconds()

            tool_result_tokens = self._tool_result_chars // 4
            conversation_tokens = max(0, self._input_tokens - self._system_prompt_tokens - tool_result_tokens)

            cost_input       = self._input_tokens       / 1_000_000 * pricing["input_per_m"]
            cost_output      = self._output_tokens      / 1_000_000 * pricing["output_per_m"]
            cost_cache_read  = self._cache_read_tokens  / 1_000_000 * pricing["cache_read_per_m"]
            cost_cache_write = self._cache_write_tokens / 1_000_000 * pricing["cache_write_per_m"]
            cost_web_search  = self._web_searches * 0.01
            cost_total       = cost_input + cost_output + cost_cache_read + cost_cache_write + cost_web_search

            record = {
                "agent_name":           self.agent_name,
                "job_name":             self.job_name,
                "model":                self.model,
                "started_at":           self.started_at,
                "completed_at":         completed_at,
                "duration_seconds":     duration,
                "input_tokens":         self._input_tokens,
                "output_tokens":        self._output_tokens,
                "cache_read_tokens":    self._cache_read_tokens,
                "cache_write_tokens":   self._cache_write_tokens,
                "system_prompt_tokens": self._system_prompt_tokens,
                "tool_result_tokens":   tool_result_tokens,
                "conversation_tokens":  conversation_tokens,
                "web_searches":         self._web_searches,
                "status":               status,
                "cost_input":           cost_input,
                "cost_output":          cost_output,
                "cost_cache_read":      cost_cache_read,
                "cost_cache_write":     cost_cache_write,
                "cost_web_search":      cost_web_search,
                "cost_total":           cost_total,
            }

            if _is_enabled():
                from tracker.db import insert_job, init_db
                init_db()
                insert_job(record)

            if _is_github_enabled():
                _push_to_github(record)

            print(f"[tracker] {self.agent_name} / {self.job_name} → {status} | "
                  f"{self._input_tokens:,}in {self._output_tokens:,}out "
                  f"searches={self._web_searches} cost=${cost_total:.4f}")
        except Exception as e:
            print(f"[tracker] WARNING: failed to log job: {e}", file=sys.stderr)

    def _get_pricing(self) -> dict:
        if _is_enabled():
            try:
                from tracker.db import get_pricing
                return get_pricing(self.model)
            except Exception:
                pass
        # Fallback pricing when DB not available
        _PRICING = {
            "claude-sonnet-4-6": {"input_per_m": 3.00, "output_per_m": 15.00, "cache_read_per_m": 0.30, "cache_write_per_m": 3.75},
            "claude-opus-4-6":   {"input_per_m": 15.00, "output_per_m": 75.00, "cache_read_per_m": 1.50, "cache_write_per_m": 18.75},
        }
        return _PRICING.get(self.model, _PRICING["claude-sonnet-4-6"])

    def fail(self):
        self.complete(status="failed")


def start_job(agent_name: str, job_name: str, model: str = "claude-sonnet-4-6") -> Job:
    if not _is_enabled() and not _is_github_enabled():
        return _NoopJob()
    return Job(agent_name, job_name, model)
