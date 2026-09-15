import unittest
import json
import subprocess
import time
import signal
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestE2E(unittest.TestCase):
    def setUp(self):
        """Start the quarry_mcp server as a subprocess."""
        self.process = subprocess.Popen(
            [sys.executable, "-m", "quarry_mcp", "--db", "fixtures/quarry-fixture.sqlite", "serve"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
        # Give server time to start
        time.sleep(0.5)

    def tearDown(self):
        """Kill the server process."""
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()

    def send_request(self, data):
        """Send a JSON-RPC request and return the response line."""
        request_line = json.dumps(data) + "\n"
        self.process.stdin.write(request_line)
        self.process.stdin.flush()
        return self.process.stdout.readline()

    def test_full_handshake_and_tools(self):
        """Test initialize, tools/list, and one tools/call."""
        # Test initialize
        init_response = json.loads(self.send_request({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize"
        }))
        self.assertEqual(init_response["jsonrpc"], "2.0")
        self.assertEqual(init_response["result"]["serverInfo"]["name"], "quarry-mcp")

        # Test tools/list
        tools_response = json.loads(self.send_request({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list"
        }))
        self.assertEqual(tools_response["jsonrpc"], "2.0")
        self.assertEqual(len(tools_response["result"]["tools"]), 5)
        tool_names = [t["name"] for t in tools_response["result"]["tools"]]
        self.assertIn("quarry.search", tool_names)
        self.assertIn("quarry.get", tool_names)
        self.assertIn("quarry.closure", tool_names)
        self.assertIn("quarry.similar", tool_names)
        self.assertIn("quarry.stats", tool_names)

        # Test tools/call with quarry.stats
        stats_response = json.loads(self.send_request({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "quarry.stats", "arguments": {}}
        }))
        self.assertEqual(stats_response["jsonrpc"], "2.0")
        self.assertEqual(stats_response["result"]["content"][0]["type"], "text")
        stats_data = json.loads(stats_response["result"]["content"][0]["text"])
        self.assertIn("corpora", stats_data)

    def test_invalid_json_handling(self):
        """Test that invalid JSON lines are handled gracefully."""
        # Send invalid JSON
        invalid_response = self.send_request("not valid json\n")
        invalid_data = json.loads(invalid_response)
        self.assertEqual(invalid_data["error"]["code"], -32700)

        # Server should still respond to valid requests
        valid_response = json.loads(self.send_request({
            "jsonrpc": "2.0",
            "id": 4,
            "method": "initialize"
        }))
        self.assertEqual(valid_response["result"]["serverInfo"]["name"], "quarry-mcp")


if __name__ == "__main__":
    unittest.main()
