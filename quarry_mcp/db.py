"""Database registry module for quarry_mcp.

This module provides the Registry class for querying Lean declarations
from a SQLite database following the quarry format.
"""

import sqlite3
import json
import re
from typing import Any


class NotFound(Exception):
    """Raised when an id is not found in the registry."""
    pass


class BadArgument(Exception):
    """Raised when arguments are invalid."""
    pass


class Registry:
    """SQLite registry for Lean declarations."""

    def __init__(self, path: str):
        self._path = path
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        """Convert a sqlite3.Row to a dict, decoding JSON columns."""
        result = dict(row)
        json_cols = ['manifest_json', 'context_json', 'attrs_json', 'tags_json', 'extra_json',
                     'axioms_json', 'arity_json', 'authorship_model']
        for col in json_cols:
            if col in result and result[col] is not None:
                try:
                    result[col] = json.loads(result[col])
                except (json.JSONDecodeError, TypeError):
                    result[col] = None
        return result

    def search(self, query: str, mode: str = "text", corpus: str | None = None,
               kind: str | None = None, limit: int = 10,
               exclude_tags: list[str] | None = None) -> list[dict]:
        if mode not in ("text", "hash"):
            raise BadArgument(f"Invalid mode: {mode}. Must be 'text' or 'hash'.")
        """Search declarations in the registry.
        
        Args:
            query: Search query string
            mode: "text" for FTS5 search, "hash" for exact stmt_hash match
            corpus: Filter by corpus id
            kind: Filter by declaration kind
            limit: Maximum results to return
            exclude_tags: Tags to exclude from results
            
        Returns:
            List of declaration dicts with id, corpus, name, kind, statement, title, in_degree
        """
        if mode == "hash":
            # Exact stmt_hash match
            sql = """
                SELECT d.id, d.corpus, d.name, d.kind, d.statement, 
                       i.title, m.in_degree
                FROM decl d
                LEFT JOIN metric m ON d.id = m.decl
                LEFT JOIN informal i ON d.id = i.decl
                WHERE d.stmt_hash = ?
            """
            params = [query]
        else:
            # FTS5 MATCH on decl_fts (no rank column in FTS5)
            sql = """
                SELECT d.id, d.corpus, d.name, d.kind, d.statement, 
                       i.title, m.in_degree
                FROM decl_fts
                JOIN decl d ON decl_fts.id = d.id
                LEFT JOIN metric m ON d.id = m.decl
                LEFT JOIN informal i ON d.id = i.decl
                WHERE decl_fts MATCH ?
            """
            params = [query]

        if corpus:
            sql += " AND d.corpus = ?"
            params.append(corpus)
        if kind:
            sql += " AND d.kind = ?"
            params.append(kind)
        if exclude_tags:
            # Check that tags_json doesn't contain any excluded tags
            for tag in exclude_tags:
                sql += " AND (d.tags_json IS NULL OR d.tags_json NOT LIKE ?)"
                params.append(f'%{tag}%')
        
        if mode == "text":
            sql += " ORDER BY m.in_degree DESC, rank LIMIT ?"
        else:
            sql += " LIMIT ?"
        params.append(limit)

        cur = self._conn.execute(sql, params)
        rows = cur.fetchall()
        results = []
        for row in rows:
            item = {
                'id': row['id'],
                'corpus': row['corpus'],
                'name': row['name'],
                'kind': row['kind'],
                'statement': (row['statement'] or '')[:300],
                'title': row['title'],
                'in_degree': row['in_degree'] or 0
            }
            results.append(item)
        return results

    def get(self, id: str, with_: tuple[str, ...] = ()) -> dict:
        """Get a declaration by id.
        
        Args:
            id: Declaration id
            with_: Tuple of attachments to include: "informal", "edges", "metric"
            
        Returns:
            Declaration dict with requested attachments
        """
        cur = self._conn.execute(
            "SELECT * FROM decl WHERE id = ?", [id]
        )
        row = cur.fetchone()
        if row is None:
            raise NotFound(id)
        
        result = self._row_to_dict(row)
        
        if "informal" in with_:
            cur = self._conn.execute(
                "SELECT * FROM informal WHERE decl = ?", [id]
            )
            result['informal'] = [self._row_to_dict(r) for r in cur.fetchall()]
        
        if "edges" in with_:
            cur = self._conn.execute(
                "SELECT dst FROM edge WHERE src = ? AND kind = 'uses'", [id]
            )
            uses = [r['dst'] for r in cur.fetchall()]
            cur = self._conn.execute(
                "SELECT dst FROM edge WHERE src = ? AND kind = 'mentions'", [id]
            )
            mentions = [r['dst'] for r in cur.fetchall()]
            cur = self._conn.execute(
                "SELECT src FROM edge WHERE dst = ? AND kind = 'uses'", [id]
            )
            dependents = [r['src'] for r in cur.fetchall()]
            result['edges'] = {'uses': uses, 'mentions': mentions, 'dependents': dependents}
        
        if "metric" in with_:
            cur = self._conn.execute(
                "SELECT * FROM metric WHERE decl = ?", [id]
            )
            row = cur.fetchone()
            result['metric'] = self._row_to_dict(row) if row else {}
        
        return result

    def closure(self, id: str, direction: str = "deps", depth: int = 50,
                stop_at_corpus: str | None = None, kind: str = "uses") -> dict:
        """Compute the closure of a declaration.
        
        Args:
            id: Starting declaration id
            direction: "deps" to traverse outgoing edges, "dependents" for incoming
            depth: Maximum traversal depth
            stop_at_corpus: If set, nodes of this corpus are counted but not expanded
            kind: Edge kind to traverse ("uses" or "mentions")
            
        Returns:
            Dict with root, count, by_corpus, by_module, ids
        """
        if direction == "deps":
            edge_clause = "src = ?"
        else:
            edge_clause = "dst = ?"
        
        visited = set()
        queue = [(id, 0)]
        by_corpus: dict[str, int] = {}
        by_module: dict[str, int] = {}
        all_ids: list[str] = []
        
        cur = self._conn.execute(
            "SELECT corpus, module FROM decl WHERE id = ?", [id]
        )
        row = cur.fetchone()
        if row is None:
            raise NotFound(id)
        
        root_corpus = row['corpus']
        root_module = row['module']
        
        while queue:
            current_id, current_depth = queue.pop(0)
            if current_id in visited:
                continue
            visited.add(current_id)
            
            if len(all_ids) < 2000:
                all_ids.append(current_id)
            
            cur = self._conn.execute(
                "SELECT corpus, module FROM decl WHERE id = ?", [current_id]
            )
            row = cur.fetchone()
            if row:
                corpus = row['corpus']
                module = row['module']
                by_corpus[corpus] = by_corpus.get(corpus, 0) + 1
                by_module[module] = by_module.get(module, 0) + 1
            
            if stop_at_corpus and corpus == stop_at_corpus:
                continue
            
            if current_depth >= depth:
                continue
            
            if direction == "deps":
                cur = self._conn.execute(
                    "SELECT dst FROM edge WHERE src = ? AND kind = ?",
                    [current_id, kind]
                )
            else:
                cur = self._conn.execute(
                    "SELECT src FROM edge WHERE dst = ? AND kind = ?",
                    [current_id, kind]
                )
            
            for row in cur.fetchall():
                next_id = row['dst'] if direction == "deps" else row['src']
                if next_id not in visited:
                    queue.append((next_id, current_depth + 1))
        
        return {
            'root': id,
            'count': len(visited),
            'by_corpus': by_corpus,
            'by_module': by_module,
            'ids': all_ids
        }

    def similar(self, id: str | None = None, statement: str | None = None,
                limit: int = 10) -> list[dict]:
        """Find similar declarations.
        
        Args:
            id: Declaration id to find similar to
            statement: Statement text to find similar to
            limit: Maximum results to return
            
        Returns:
            List of similar declarations with match type ("hash" or "text")
        """
        results = []
        stmt_hash = None
        
        if id:
            cur = self._conn.execute(
                "SELECT stmt_hash, corpus, statement FROM decl WHERE id = ?", [id]
            )
            row = cur.fetchone()
            if row is None:
                raise NotFound(id)
            stmt_hash = row['stmt_hash']
            statement = row['statement']
        
        if not statement:
            return results
        
        # First: exact stmt_hash matches in OTHER corpora
        if stmt_hash:
            # Get the corpus of the source declaration if we have an id
            source_corpus = None
            if id:
                cur_src = self._conn.execute(
                    "SELECT corpus FROM decl WHERE id = ?", [id]
                )
                src_row = cur_src.fetchone()
                if src_row:
                    source_corpus = src_row['corpus']

            cur = self._conn.execute(
                "SELECT d.id, d.corpus, d.name, d.kind, d.statement, m.in_degree FROM decl d "
                "JOIN metric m ON d.id = m.decl WHERE d.stmt_hash = ?", [stmt_hash]
            )
            for row in cur.fetchall():
                if row['corpus'] != source_corpus:
                    results.append({
                        'id': row['id'],
                        'corpus': row['corpus'],
                        'name': row['name'],
                        'kind': row['kind'],
                        'statement': (row['statement'] or '')[:300],
                        'title': row['title'],
                        'in_degree': row['in_degree'] or 0,
                        'match': 'hash'
                    })
        
        # Second: FTS on identifier tokens
        tokens = re.findall(r'[a-zA-Z_][a-zA-Z0-9_.]*', statement)
        tokens = [t for t in tokens if '.' in t or len(t) >= 4]
        
        if tokens:
            fts_query = ' '.join(f'"{t}"' for t in tokens)
            cur = self._conn.execute(
                "SELECT d.id, d.corpus, d.name, d.kind, d.statement, "
                "i.title, m.in_degree FROM decl_fts "
                "JOIN decl d ON decl_fts.id = d.id "
                "LEFT JOIN metric m ON d.id = m.decl "
                "LEFT JOIN informal i ON d.id = i.decl "
                "WHERE decl_fts MATCH ?", [fts_query]
            )
            for row in cur.fetchall():
                if row['id'] not in [r['id'] for r in results]:
                    results.append({
                        'id': row['id'],
                        'corpus': row['corpus'],
                        'name': row['name'],
                        'kind': row['kind'],
                        'statement': (row['statement'] or '')[:300],
                        'title': row['title'],
                        'in_degree': row['in_degree'] or 0,
                        'match': 'text'
                    })
        
        return results[:limit]

    def stats(self) -> dict:
        """Get registry statistics.
        
        Returns:
            Dict with per-corpus decl counts, edge count, fts row count
        """
        cur = self._conn.execute(
            "SELECT corpus, COUNT(*) as cnt FROM decl GROUP BY corpus"
        )
        decl_by_corpus = {row['corpus']: row['cnt'] for row in cur.fetchall()}
        
        cur = self._conn.execute("SELECT COUNT(*) as cnt FROM edge")
        edge_count = cur.fetchone()['cnt']
        
        cur = self._conn.execute("SELECT COUNT(*) as cnt FROM decl_fts")
        fts_count = cur.fetchone()['cnt']
        
        return {
            'corpora': decl_by_corpus,
            'edge_count': edge_count,
            'fts_row_count': fts_count
        }
