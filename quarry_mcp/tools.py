"""Tools module with MCP tool specifications."""

from typing import Any
from quarry_mcp.db import NotFound, BadArgument


TOOL_SPECS: list[dict] = [
    {
        "name": "quarry.search",
        "description": "Search Lean declarations by text or hash.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query string."},
                "mode": {"type": "string", "enum": ["text", "hash"], "default": "text", "description": "Search mode: text (FTS) or hash (exact stmt_hash)."},
                "corpus": {"type": "string", "description": "Filter by corpus id."},
                "kind": {"type": "string", "description": "Filter by declaration kind."},
                "limit": {"type": "integer", "default": 10, "description": "Maximum results to return."},
                "exclude_tags": {"type": "array", "items": {"type": "string"}, "description": "Exclude declarations with these tags."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "quarry.get",
        "description": "Get a declaration by id with optional attachments.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Declaration id."},
                "with": {"type": "array", "items": {"type": "string", "enum": ["informal", "edges", "metric"]}, "description": "Attachments to include."},
            },
            "required": ["id"],
        },
    },
    {
        "name": "quarry.closure",
        "description": "Compute BFS closure of a declaration.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Root declaration id."},
                "direction": {"type": "string", "enum": ["deps", "dependents"], "default": "deps", "description": "Traversal direction."},
                "depth": {"type": "integer", "default": 50, "description": "Maximum BFS depth."},
                "stop_at_corpus": {"type": "string", "description": "Stop expanding nodes from this corpus."},
                "kind": {"type": "string", "default": "uses", "description": "Edge kind to follow."},
            },
            "required": ["id"],
        },
    },
    {
        "name": "quarry.similar",
        "description": "Find similar declarations by hash or statement.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Declaration id to find similar for."},
                "statement": {"type": "string", "description": "Statement text to find similar for."},
                "limit": {"type": "integer", "default": 10, "description": "Maximum results to return."},
            },
            "required": [],
        },
    },
    {
        "name": "quarry.stats",
        "description": "Get registry statistics.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]


def _validate_required(arguments: dict[str, Any], required: list[str]) -> None:
    """Validate that required arguments are present."""
    for key in required:
        if key not in arguments:
            raise BadArgument(f"Missing required argument: {key}")


def _validate_type(arguments: dict[str, Any], name: str, expected_type: type) -> None:
    """Validate that an argument has the expected type."""
    if name in arguments and not isinstance(arguments[name], expected_type):
        raise BadArgument(f"Argument {name} must be of type {expected_type.__name__}")


def dispatch(registry, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Dispatch a tool call to the registry."""
    try:
        if name == "quarry.search":
            _validate_required(arguments, ["query"])
            _validate_type(arguments, "limit", int)
            _validate_type(arguments, "exclude_tags", list)
            result = registry.search(
                arguments["query"],
                mode=arguments.get("mode", "text"),
                corpus=arguments.get("corpus"),
                kind=arguments.get("kind"),
                limit=arguments.get("limit", 10),
                exclude_tags=arguments.get("exclude_tags"),
            )
            return {"results": result}
        elif name == "quarry.get":
            _validate_required(arguments, ["id"])
            _validate_type(arguments, "with", list)
            result = registry.get(
                arguments["id"],
                with_=tuple(arguments.get("with", [])),
            )
            return {"result": result}
        elif name == "quarry.closure":
            _validate_required(arguments, ["id"])
            _validate_type(arguments, "depth", int)
            result = registry.closure(
                arguments["id"],
                direction=arguments.get("direction", "deps"),
                depth=arguments.get("depth", 50),
                stop_at_corpus=arguments.get("stop_at_corpus"),
                kind=arguments.get("kind", "uses"),
            )
            return {"result": result}
        elif name == "quarry.similar":
            _validate_type(arguments, "limit", int)
            result = registry.similar(
                id=arguments.get("id"),
                statement=arguments.get("statement"),
                limit=arguments.get("limit", 10),
            )
            return {"results": result}
        elif name == "quarry.stats":
            result = registry.stats()
            return result
        else:
            raise BadArgument(f"Unknown tool: {name}")
    except (NotFound, BadArgument):
        raise
    except Exception as e:
        raise BadArgument(str(e))
