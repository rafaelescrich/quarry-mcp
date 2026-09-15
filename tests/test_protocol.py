import unittest
import json
import sys
from io import StringIO
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from quarry_mcp.protocol import handle
from quarry_mcp.db import Registry
from tests.conftest_fixture import FIXTURE


class TestProtocol(unittest.TestCase):
    def setUp(self):
        self.registry = Registry(FIXTURE)

    def test_initialize(self):
        result = handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"}, self.registry)
        self.assertEqual(result["jsonrpc"], "2.0")
        self.assertIn("result", result)
        self.assertEqual(result["result"]["serverInfo"]["name"], "quarry-mcp")

    def test_initialized_notification(self):
        result = handle({"jsonrpc": "2.0", "method": "notifications/initialized"}, self.registry)
        self.assertIsNone(result)

    def test_tools_list(self):
        result = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, self.registry)
        self.assertIn("result", result)
        self.assertIn("tools", result["result"])
        self.assertEqual(len(result["result"]["tools"]), 5)
        tool_names = {t["name"] for t in result["result"]["tools"]}
        expected = {"quarry.search", "quarry.get", "quarry.closure", "quarry.similar", "quarry.stats"}
        self.assertEqual(tool_names, expected)

    def test_tools_call_stats(self):
        result = handle({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "quarry.stats", "arguments": {}}
        }, self.registry)
        self.assertIn("result", result)
        self.assertIn("content", result["result"])
        self.assertEqual(result["result"]["content"][0]["type"], "text")
        data = json.loads(result["result"]["content"][0]["text"])
        self.assertIn("corpora", data)

    def test_method_not_found(self):
        result = handle({"jsonrpc": "2.0", "id": 1, "method": "unknown/method"}, self.registry)
        self.assertIn("error", result)
        self.assertEqual(result["error"]["code"], -32601)

    def test_invalid_params(self):
        result = handle({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "quarry.search"}
        }, self.registry)
        self.assertIn("error", result)
        self.assertEqual(result["error"]["code"], -32602)


if __name__ == "__main__":
    unittest.main()
