#!/usr/bin/env python3
"""Summarize David's log for a time window: LLM calls, latency, tokens, tool calls."""
import re, sys
start, end = sys.argv[1], sys.argv[2]
calls = tools = pt = ct = ms = 0; tool_names = {}
for line in open(sys.argv[3] if len(sys.argv) > 3 else __import__("os").path.expanduser("~/.david/logs/david.log")):
    ts = line[:27]
    if not (start <= ts <= end): continue
    m = re.search(r"llm request done .*llm_ms=(\d+) tool_calls=(\d+).*prompt_tokens=(\d+) completion_tokens=(\d+)", line)
    if m: calls += 1; ms += int(m[1]); pt += int(m[3]); ct += int(m[4])
    m = re.search(r"tool call tool=(\w+)", line)
    if m: tools += 1; tool_names[m[1]] = tool_names.get(m[1], 0) + 1
    if "ERROR" in line or "error" in line.lower() and "llm" in line: pass
print(f"llm_calls={calls} avg_llm_ms={ms//max(calls,1)} prompt_tokens={pt} completion_tokens={ct} tool_calls={tools} tools={tool_names}")
print(f"promo_cost_usd={pt*0.04/1e6 + ct*0.15/1e6:.5f}  list_cost_usd={pt*0.20/1e6 + ct*0.75/1e6:.5f}")
