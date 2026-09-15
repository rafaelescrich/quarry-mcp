"""Protocol module."""

import json
from quarry_mcp import tools
from quarry_mcp.db import NotFound, BadArgument


def handle(request: dict, registry) -> dict | None:
    if "id" not in request:
        return None  # Notification
    method = request.get("method")
    params = request.get("params", {})
    resp_id = request["id"]

    try:
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": resp_id,
                "result": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "quarry-mcp", "version": "0.1.0"}
                }
            }
        elif method == "notifications/initialized":
            return None
        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": resp_id,
                "result": {"tools": tools.TOOL_SPECS}
            }
        elif method == "tools/call":
            try:
                result = tools.dispatch(registry, params["name"], params["arguments"])
                return {
                    "jsonrpc": "2.0",
                    "id": resp_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(result)}],
                        "isError": False
                    }
                }
            except (BadArgument, NotFound) as e:
                return {
                    "jsonrpc": "2.0",
                    "id": resp_id,
                    "result": {
                        "content": [{"type": "text", "text": str(e)}],
                        "isError": True
                    }
                }
            except (KeyError, TypeError, ValueError) as e:
                return {
                    "jsonrpc": "2.0",
                    "id": resp_id,
                    "error": {"code": -32602, "message": str(e)}
                }
        else:
            return {
                "jsonrpc": "2.0",
                "id": resp_id,
                "error": {"code": -32601, "message": "Method not found"}
            }
    except Exception as e:
        return {
            "jsonrpc": "2.0",
            "id": resp_id,
            "error": {"code": -32600, "message": str(e)}
        }
