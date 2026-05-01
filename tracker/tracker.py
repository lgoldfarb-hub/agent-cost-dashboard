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

No-op when TRACKER_DB_PATH is unset and ~/agent-cost-dashboard/data/ does not exist.
"""

import os
import sys
from datetime import datetime, timezone

_ENABLED = None  # lazy-evaluated


def _is_enabled() -> bool:
    global _ENABLED
    if _ENABLED is None:
        if os.environ.get("TRACKER_DB_PATH"):
            _ENABLED = True
        else:
            default_data = os.path.join(os.path.dirname(__file__), "..", "data")
            _ENABLED = os.path.isdir(os.path.abspath(default_data))
    return _ENABLED


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
        from tracker.db import get_pricing, insert_job, init_db
        try:
            init_db()
            pricing = get_pricing(self.model)
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

            insert_job({
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
            })
            print(f"[tracker] {self.agent_name} / {self.job_name} → {status} | "
                  f"{self._input_tokens:,}in {self._output_tokens:,}out "
                  f"searches={self._web_searches} cost=${cost_total:.4f}")
        except Exception as e:
            print(f"[tracker] WARNING: failed to log job: {e}", file=sys.stderr)

    def fail(self):
        self.complete(status="failed")


def start_job(agent_name: str, job_name: str, model: str = "claude-sonnet-4-6") -> Job:
    if not _is_enabled():
        return _NoopJob()
    return Job(agent_name, job_name, model)
