# Quarry MCP server — brief

Quarry is an index format for Lean 4 proof corpora. A registry is one SQLite database with these tables
(schema is authoritative, inspect it with `sqlite3`-free Python: `sqlite3.connect(...).execute("SELECT sql FROM sqlite_master")`):

- corpus(id, repo, commit_sha, lean, mathlib_rev, license, tier, manifest_json)
- decl(id, corpus, name, kind, module, file, line, line_end, statement, stmt_hash, expr_hash, context_json, docstring,
  proof_source, proof_file, axioms_json, sorry_free, arity_json, attrs_json, visibility, authorship, authorship_model,
  tags_json, proof_size, extra_json)            -- id = "<corpus>/<Lean name>"
- edge(src, dst, kind, count)                   -- kind: "uses" (in proof) | "mentions" (in statement); dst may be a decl id of another corpus
- informal(decl, title, statement_nl, concepts_json, refs_json, origin, origin_model, confidence, lang)
- ledger(src, dst, relation, verified_json, agent_json, notes, at)
- metric(decl, in_degree, out_degree, closure_size, pagerank, generality)
- decl_fts: FTS5 virtual table (id UNINDEXED, name, statement, title) for full-text search

The fixture `fixtures/quarry-fixture.sqlite` holds a real subset (thousands of declarations from two corpora + Mathlib).

## The product: `quarry_mcp`, a Python 3.12 package, standard library only

An MCP (Model Context Protocol) server over stdio, JSON-RPC 2.0, newline-delimited: one JSON object per line on stdin,
one per line on stdout, nothing else on stdout (logs go to stderr). Methods to support exactly:

1. `initialize` -> {"protocolVersion":"2025-06-18","capabilities":{"tools":{}},"serverInfo":{"name":"quarry-mcp","version":"0.1.0"}}
2. `notifications/initialized` (a notification, no id: do not reply)
3. `tools/list` -> {"tools":[{name, description, inputSchema}, ...]} for the five tools below
4. `tools/call` with params {"name": <tool>, "arguments": {...}} -> {"content":[{"type":"text","text":<JSON string of the result>}],"isError":false}
   Unknown method -> JSON-RPC error -32601; bad params -> -32602; tool failure -> result with isError true and the message in content.

Tools:
- `quarry.search` {query: str, mode: "text"|"hash", corpus?: str, kind?: str, limit?: int=10, exclude_tags?: [str]}
  text: FTS5 MATCH on decl_fts, joined to decl and metric, ordered by in_degree DESC then FTS rank; hash: exact stmt_hash match.
  Returns [{id, corpus, name, kind, statement (truncated to 300 chars), title, in_degree}].
- `quarry.get` {id: str, with?: ["informal","edges","metric"]} -> the decl row as an object (json columns decoded) plus requested attachments:
  informal (list), edges {uses:[dst...], mentions:[dst...], dependents:[src...]}, metric (object). Unknown id -> isError.
- `quarry.closure` {id: str, direction: "deps"|"dependents", depth?: int=50, stop_at_corpus?: str, kind?: "uses"}
  BFS over edge; returns {root, count, by_corpus: {corpus: n}, by_module: {module: n}, ids: [...] (capped at 2000)}.
  With stop_at_corpus set, nodes of that corpus are counted but not expanded.
- `quarry.similar` {id?: str, statement?: str, limit?: int=10}: first exact stmt_hash matches in OTHER corpora, then FTS on the
  statement's identifier tokens (split on non-identifier chars, keep tokens with a dot or length>=4, quote them for FTS5), labelled
  {match: "hash"|"text"}.
- `quarry.stats` {} -> per-corpus decl counts, edge count, fts row count.

Also a CLI `python -m quarry_mcp --db PATH serve` (runs the server) and `python -m quarry_mcp --db PATH call <tool> '<json args>'` (one-shot, prints JSON).
Tests with unittest against the fixture: protocol handshake, tools/list, each tool with a known-good query
(e.g. search "Poisson" returns SchwartzMap.tsum_eq_tsum_fourier_euclideanSpace; closure of that id with direction deps has count>0;
similar on it returns text matches), error paths (unknown id, unknown method, invalid JSON line -> -32700 error and keep serving).
