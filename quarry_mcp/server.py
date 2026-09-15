"""Server module."""

import json
import sys
import logging
from quarry_mcp import protocol

logging.basicConfig(stream=sys.stderr, level=logging.ERROR)


def serve(registry, stdin, stdout):
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            response = protocol.handle(request, registry)
            if response is not None:
                print(json.dumps(response), file=stdout)
                stdout.flush()
        except json.JSONDecodeError:
            error = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"}
            }
            print(json.dumps(error), file=stdout)
            stdout.flush()
        except Exception as e:
            logging.error("Server error: %s", e)
