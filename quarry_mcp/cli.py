"""CLI module."""

import argparse
import json
import sys
from quarry_mcp import db, protocol, server


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    subparsers = parser.add_subparsers(dest="command")
    serve_parser = subparsers.add_parser("serve")
    call_parser = subparsers.add_parser("call")
    call_parser.add_argument("tool")
    call_parser.add_argument("json_args")

    args = parser.parse_args(argv)
    registry = db.Registry(args.db)

    if args.command == "serve":
        server.serve(registry, sys.stdin, sys.stdout)
    elif args.command == "call":
        try:
            request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": args.tool, "arguments": json.loads(args.json_args)}
            }
        except json.JSONDecodeError:
            print(json.dumps({"error": "Invalid JSON args"}), file=sys.stderr)
            sys.exit(2)

        response = protocol.handle(request, registry)
        print(json.dumps(response, indent=2))

        # Exit code 1 on tool error (isError true in result)
        if "result" in response and response["result"].get("isError"):
            sys.exit(1)
    else:
        parser.print_help()
        sys.exit(2)
