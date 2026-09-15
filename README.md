# quarry-mcp

An MCP (Model Context Protocol) server for querying a Lean 4 proof corpus registry.

## Installation

```bash
pip install -e .
```

## Usage

### Server

Run the MCP server over stdio:

```bash
quarry-mcp --db PATH/to/quarry-fixture.sqlite serve
```

Or via Python module:

```bash
python -m quarry_mcp --db PATH/to/quarry-fixture.sqlite serve
```

### CLI Tool

One-shot tool invocation:

```bash
quarry-mcp --db PATH/to/quarry-fixture.sqlite call quarry.search '{"query": "Poisson"}'
```

## Tools

- `quarry.search` — Full-text or hash search
- `quarry.get` — Get declaration by ID
- `quarry.closure` — Compute dependency/dependent closure
- `quarry.similar` — Find similar declarations
- `quarry.stats` — Get corpus statistics

## License

MIT

## Proof management web interface

The web workspace adds a browser UI over the same Quarry schema. It has no additional dependencies.

```bash
python3 -m quarry_mcp.web --db fixtures/quarry-fixture.sqlite --state ./quarry-workspace.sqlite --port 8791
```

Open `http://127.0.0.1:8791`. On Solimoes the production corpus is at
`/home/rafael/Projects/lean/quarry-out/quarry.sqlite`; the installed web app is
`/home/rafael/Projects/lean/quarry-web`. Connect with:

```bash
ssh -N -L 8791:127.0.0.1:8791 solimoes
```

- Search real declarations by name or statement; filter by source package and declaration kind, with pagination.
- Inspect full statements, source revision links, recorded axioms, module names, authorship, and direct dependencies/dependents (up to 100 in each direction). Missing external declarations are explicitly labelled.
- Save declarations, maintain notes, and register local proofs with statement, source, module, and toolchain metadata.
- Export a JSON selection manifest including pinned corpus IDs, source revisions encoded in IDs, toolchains, statement hashes, notes, and review blockers. This is not a Lake lockfile and does not install packages. Mixed Lean/Mathlib selections require porting and re-verification.

The corpus is opened with SQLite `mode=ro`; management data lives in the separate `--state` SQLite file. Back up that file to preserve registrations and notes. New registrations always remain **unverified**. “Recorded sorry-free” means only that the extractor recorded no `sorryAx` and no nonstandard axioms; the app does not run Lean, execute submitted source, audit transitive dependencies, or independently validate corpus-level verification claims. The importer currently attaches a Navier–Stokes comparator claim to Mathlib too, so the UI deliberately labels those as source-provided claims.

The server listens only on loopback and is intended for a private SSH workspace. It checks Host and requires a same-origin token on mutations. It is not a public multi-user service. Local drafts stay registered when removed from the selection; find them in Registrations and save them again at any time.

Run the integration tests (requires permission to bind a temporary localhost port):

```bash
python3 -m unittest tests.test_web -v
node --check quarry_mcp/static/app.js
```
