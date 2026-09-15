#!/bin/bash
# Smoke test for quarry_mcp

set -e

# Ensure logs directory exists
mkdir -p logs

# Start server as subprocess and communicate via Python driver
python3 << 'EOF'
import json
import subprocess
import sys
import time

KNOWN_ID = "github.com/anthropics/fermats-last-theorem@aa2d8b34/SchwartzMap.tsum_eq_tsum_fourier_euclideanSpace"

steps = []

def send_request(proc, msg):
    """Send a request and return (latency_ms, response_dict)."""
    start = time.time() * 1000
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    latency = time.time() * 1000 - start
    if line:
        return latency, json.loads(line)
    return latency, None

# Start server
proc = subprocess.Popen(
    ["python3", "-m", "quarry_mcp", "--db", "fixtures/quarry-fixture.sqlite", "serve"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True
)

try:
    # 1. Initialize
    lat, resp = send_request(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    steps.append({"step": "initialize", "latency_ms": round(lat, 2), "pass": resp is not None and resp.get("result") is not None})

    # 2. Notifications/initialized (no response expected)
    start = time.time() * 1000
    proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
    proc.stdin.flush()
    lat = time.time() * 1000 - start
    # Should not read anything (notification has no reply)
    steps.append({"step": "notifications/initialized", "latency_ms": round(lat, 2), "pass": True})

    # 3. Tools/list
    lat, resp = send_request(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    steps.append({"step": "tools/list", "latency_ms": round(lat, 2), "pass": resp is not None and "tools" in resp.get("result", {})})

    # 4. quarry.stats
    lat, resp = send_request(proc, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "quarry.stats", "arguments": {}}})
    steps.append({"step": "quarry.stats", "latency_ms": round(lat, 2), "pass": resp is not None and not resp.get("result", {}).get("isError")})

    # 5. quarry.search {"query":"Poisson"}
    lat, resp = send_request(proc, {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "quarry.search", "arguments": {"query": "Poisson"}}})
    steps.append({"step": "quarry.search", "latency_ms": round(lat, 2), "pass": resp is not None and not resp.get("result", {}).get("isError")})

    # 6. quarry.get with KNOWN_ID
    lat, resp = send_request(proc, {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "quarry.get", "arguments": {"id": KNOWN_ID}}})
    steps.append({"step": "quarry.get", "latency_ms": round(lat, 2), "pass": resp is not None and not resp.get("result", {}).get("isError")})

    # 7. quarry.get with ["informal","edges","metric"]
    lat, resp = send_request(proc, {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "quarry.get", "arguments": {"id": KNOWN_ID, "with": ["informal", "edges", "metric"]}}})
    steps.append({"step": "quarry.get (full)", "latency_ms": round(lat, 2), "pass": resp is not None and not resp.get("result", {}).get("isError")})

    # 8. quarry.closure on KNOWN_ID
    lat, resp = send_request(proc, {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "quarry.closure", "arguments": {"id": KNOWN_ID}}})
    steps.append({"step": "quarry.closure", "latency_ms": round(lat, 2), "pass": resp is not None and not resp.get("result", {}).get("isError")})

    # 9. quarry.similar on KNOWN_ID
    lat, resp = send_request(proc, {"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {"name": "quarry.similar", "arguments": {"id": KNOWN_ID}}})
    steps.append({"step": "quarry.similar", "latency_ms": round(lat, 2), "pass": resp is not None and not resp.get("result", {}).get("isError")})

    # 10. Invalid JSON line
    start = time.time() * 1000
    proc.stdin.write("not valid json\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    lat = time.time() * 1000 - start
    resp = json.loads(line) if line else None
    steps.append({"step": "invalid_json", "latency_ms": round(lat, 2), "pass": resp is not None and resp.get("error", {}).get("code") == -32700})

finally:
    proc.terminate()
    proc.wait(timeout=5)

# Write results to logs/smoke.json
with open("logs/smoke.json", "w") as f:
    json.dump(steps, f, indent=2)

# Print table
print(f"{'Step':<30} {'Latency (ms)':<15} {'Pass'}")
print("-" * 60)
for s in steps:
    print(f"{s['step']:<30} {s['latency_ms']:<15.2f} {'✓' if s['pass'] else '✗'}")

all_passed = all(s["pass"] for s in steps)
sys.exit(0 if all_passed else 1)
EOF
