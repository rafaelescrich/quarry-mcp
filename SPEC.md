# Quarry MCP Server Specification

## Overview

Quarry is an MCP (Model Context Protocol) server over stdio using JSON-RPC 2.0 with newline-delimited messages. It provides search and analysis tools for Lean 4 proof corpora stored in a SQLite registry.

## Package Layout

```
quarry_mcp/
├── __init__.py
├── db.py
├── tools.py
├── protocol.py
├── server.py
├── cli.py
└── __main__.py
tests/
├── __init__.py
├── test_db.py
├── test_protocol.py
└── test_e2e.py
```

## Public API

### db module

```python
class Registry:
    def __init__(self, path: str) -> None
    def search(query: str, mode: str = "text", corpus: str | None = None, kind: str | None = None, limit: int = 10, exclude_tags: list[str] | None = None) -> list[dict]
    def get(id: str, with_: tuple[str, ...] = ()) -> dict
    def closure(id: str, direction: str = "deps", depth: int = 50, stop_at_corpus: str | None = None, kind: str = "uses") -> dict
    def similar(id: str | None = None, statement: str | None = None, limit: int = 10) -> list[dict]
    def stats() -> dict
```

Exceptions:
- `db.NotFound(id)` - raised for unknown ids
- `db.BadArgument(msg)` - raised for invalid arguments

### tools module

```python
TOOL_SPECS: list[dict]  # List of MCP tool descriptors with JSON Schema inputSchema
def dispatch(registry: Registry, name: str, arguments: dict) -> dict
```

### protocol module

```python
def handle(request: dict, registry: Registry) -> dict | None
```

Implements:
- `initialize` - returns protocol info
- `notifications/initialized` - returns None (no reply)
- `tools/list` - returns list of available tools
- `tools/call` - calls a tool with arguments

JSON-RPC error objects:
- `-32700` - parse error
- `-32600` - invalid request
- `-32601` - method not found
- `-32602` - invalid params

### server module

```python
def serve(registry: Registry, stdin, stdout) -> None
```

Reads newline-delimited JSON from stdin, writes one JSON line per response to stdout. Logs to stderr. Survives invalid JSON lines by emitting a -32700 error.

### cli module

```python
def main(argv: list[str]) -> None
```

Subcommands:
- `serve` - runs the server with `--db PATH`
- `call <tool> <json-args>` - one-shot tool invocation

## Tool Specifications

### quarry.search

Input: `{query: str, mode: "text"|"hash", corpus?: str, kind?: str, limit?: int=10, exclude_tags?: [str]}`

- text: FTS5 MATCH on decl_fts, joined to decl and metric, ordered by in_degree DESC then FTS rank
- hash: exact stmt_hash match

Output: `[{id, corpus, name, kind, statement (truncated to 300 chars), title, in_degree}]`

### quarry.get

Input: `{id: str, with?: ["informal","edges","metric"]}`

Output: decl row as object (json columns decoded) plus requested attachments:
- informal: list
- edges: {uses:[dst...], mentions:[dst...], dependents:[src...]}
- metric: object

### quarry.closure

Input: `{id: str, direction: "deps"|"dependents", depth?: int=50, stop_at_corpus?: str, kind?: "uses"}`

Output: `{root, count, by_corpus: {corpus: n}, by_module: {module: n}, ids: [...] (capped at 2000)}`

With stop_at_corpus set, nodes of that corpus are counted but not expanded.

### quarry.similar

Input: `{id?: str, statement?: str, limit?: int=10}`

First exact stmt_hash matches in OTHER corpora, then FTS on the statement's identifier tokens (split on non-identifier chars, keep tokens with a dot or length>=4, quote them for FTS5), labelled `{match: "hash"|"text"}`.

### quarry.stats

Input: `{}`

Output: per-corpus decl counts, edge count, fts row count.

## CLI Usage

```bash
# Run server
python -m quarry_mcp --db PATH serve

# One-shot tool call
python -m quarry_mcp --db PATH call quarry.search '{"query": "Poisson"}'
```
