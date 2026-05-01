"""Insert a synthetic job to verify the tracker works end-to-end."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tracker.tracker import start_job

job = start_job("discovery_brief", "Brief: Test Company (synthetic)")
job.set_system_prompt("A" * 4000)  # ~1000 tokens

class FakeUsage:
    input_tokens = 12500
    output_tokens = 3200
    cache_read_input_tokens = 4000
    cache_creation_input_tokens = 800

job.add_usage(FakeUsage())
job.add_web_searches(7)
job.add_tool_result("B" * 8000)  # ~2000 tokens of tool results
job.complete()
print("Test job inserted successfully.")
