"""Private HTTP workspace over a read-only Quarry corpus and a separate writable DB."""
from contextlib import closing
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit, quote
import argparse
import hashlib
import json
import secrets
import sqlite3
import time
import uuid

STATIC = Path(__file__).with_name('static')
STANDARD_AXIOMS = {'propext', 'Classical.choice', 'Quot.sound'}


def decode(row):
    obj = dict(row)
    for key in list(obj):
        if key.endswith('_json') and obj[key] is not None:
            try:
                obj[key[:-5]] = json.loads(obj.pop(key))
            except (ValueError, TypeError):
                obj[key[:-5]] = None
    return obj


def trust(d):
    axioms = d.get('axioms')
    if d.get('local'):
        return 'unverified'
    if axioms is not None and 'sorryAx' in axioms or d.get('sorry_free') == 0:
        return 'contains-sorry'
    if axioms is None or d.get('sorry_free') is None:
        return 'unknown'
    if set(axioms) - STANDARD_AXIOMS:
        return 'custom-axioms'
    return 'recorded-sorry-free'


class Workspace:
    def __init__(self, corpus, state):
        self.corpus_path = Path(corpus).resolve(strict=True)
        self.state_path = Path(state).resolve()
        if self.corpus_path == self.state_path:
            raise ValueError('Workspace database must differ from corpus database')
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.state()) as c, c:
            c.executescript('''
                CREATE TABLE IF NOT EXISTS saved(id TEXT PRIMARY KEY, notes TEXT NOT NULL DEFAULT '', added_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS drafts(id TEXT PRIMARY KEY, data TEXT NOT NULL);
            ''')
        with closing(self.corpus()) as c:
            self.corpora = [decode(r) for r in c.execute('SELECT * FROM corpus')]
            counts = dict(c.execute('SELECT corpus, count(*) FROM decl GROUP BY corpus'))
            for item in self.corpora:
                item['declarations'] = counts.get(item['id'], 0)
        self.by_corpus = {x['id']: x for x in self.corpora}

    def corpus(self):
        c = sqlite3.connect(self.corpus_path.as_uri() + '?mode=ro', uri=True)
        c.row_factory = sqlite3.Row
        deadline = time.monotonic() + 15
        c.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
        return c

    def state(self):
        c = sqlite3.connect(self.state_path, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    def decorate(self, d):
        d['trust'] = trust(d)
        corpus = self.by_corpus.get(d.get('corpus'), {})
        d['lean'] = d.get('lean') or corpus.get('lean')
        d['mathlib_rev'] = d.get('mathlib_rev') or corpus.get('mathlib_rev')
        return d

    def saved(self):
        with closing(self.state()) as c:
            return [dict(r) for r in c.execute('SELECT * FROM saved ORDER BY added_at DESC')]

    def drafts(self):
        with closing(self.state()) as c:
            return [self.decorate(json.loads(r[0])) for r in c.execute('SELECT data FROM drafts')]

    def search(self, q='', corpus='', kind='', offset=0):
        if len(q) > 300 or offset < 0 or offset > 10000:
            raise ValueError('Search is too long or page is out of range')
        args, conditions = [], []
        join = ''
        if q.strip():
            # Quote literal words: UI search cannot accidentally become an FTS expression.
            terms = q.split()[:12]
            expression = ' AND '.join('"' + t.replace('"', '""') + '"*' for t in terms)
            join = 'JOIN decl_fts f ON f.id=d.id'
            conditions.append('decl_fts MATCH ?')
            args.append(expression)
        if corpus:
            conditions.append('d.corpus=?')
            args.append(corpus)
        if kind:
            conditions.append('d.kind=?')
            args.append(kind)
        where = 'WHERE ' + ' AND '.join(conditions) if conditions else ''
        order = 'rank' if join else 'd.name'
        sql = f'''SELECT d.id,d.name,d.corpus,d.kind,d.module,substr(d.statement,1,340) statement,
            d.sorry_free,d.axioms_json,d.tags_json,m.in_degree,m.out_degree
            FROM decl d {join} LEFT JOIN metric m ON m.decl=d.id
            {where} ORDER BY {order} LIMIT 31 OFFSET ?'''
        with closing(self.corpus()) as c:
            rows = [self.decorate(decode(r)) for r in c.execute(sql, args + [offset])]
        return {'items': rows[:30], 'has_more': len(rows) > 30, 'offset': offset}

    def get(self, ident):
        with closing(self.state()) as c:
            row = c.execute('SELECT data FROM drafts WHERE id=?', (ident,)).fetchone()
        if row:
            return self.decorate(json.loads(row[0]))
        with closing(self.corpus()) as c:
            row = c.execute('SELECT * FROM decl WHERE id=?', (ident,)).fetchone()
            if row is None:
                raise KeyError('Declaration not found in this registry')
            d = decode(row)
            for label, field, target in [('dependencies', 'src', 'dst'), ('dependents', 'dst', 'src')]:
                edges = c.execute(f'''SELECT e.{target} id, d.name, d.corpus, d.module
                    FROM edge e LEFT JOIN decl d ON d.id=e.{target}
                    WHERE e.{field}=? AND e.kind='uses' LIMIT 101''', (ident,)).fetchall()
                d[label] = [dict(r) for r in edges[:100]]
                d[label + '_truncated'] = len(edges) > 100
            row = c.execute('SELECT * FROM metric WHERE decl=?', (ident,)).fetchone()
            d['metric'] = dict(row) if row else {}
            d['informal'] = [decode(r) for r in c.execute('SELECT * FROM informal WHERE decl=? LIMIT 10', (ident,))]
        corpus = self.by_corpus.get(d['corpus'], {})
        d['corpus_info'] = corpus
        repo = corpus.get('repo', '')
        if repo.startswith('https://github.com/') and d.get('file') and '..' not in Path(d['file']).parts and not d['file'].startswith('/'):
            d['source_url'] = repo.removesuffix('.git') + '/blob/' + quote(corpus.get('commit_sha') or '', safe='') + '/' + quote(d['file'], safe='/')
            if d.get('line'):
                d['source_url'] += '#L' + str(d['line'])
        return self.decorate(d)

    def save(self, ident, notes):
        if not isinstance(ident, str) or not isinstance(notes, str) or len(notes) > 10000:
            raise ValueError('Invalid declaration or notes (maximum 10,000 characters)')
        self.get(ident)
        with closing(self.state()) as c, c:
            c.execute('INSERT INTO saved VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET notes=excluded.notes',
                      (ident, notes, datetime.now(timezone.utc).isoformat()))
        return {'saved': True}

    def remove(self, ident):
        with closing(self.state()) as c, c:
            c.execute('DELETE FROM saved WHERE id=?', (ident,))
        return {'saved': False}

    def register(self, data):
        fields = {}
        for key, maximum in [('name', 300), ('statement', 100000), ('module', 300), ('lean', 100), ('mathlib_rev', 100), ('proof_source', 200000), ('notes', 10000)]:
            value = data.get(key, '')
            if not isinstance(value, str) or len(value) > maximum:
                raise ValueError(f'Invalid {key}')
            fields[key] = value.strip()
        if not all(fields[k] for k in ['name', 'statement', 'module', 'lean']):
            raise ValueError('Name, statement, module, and Lean version are required')
        ident = 'workspace/' + str(uuid.uuid4())
        fields.update(id=ident, corpus='workspace', kind='theorem', local=True, sorry_free=None,
                      axioms=None, created_at=datetime.now(timezone.utc).isoformat(),
                      stmt_hash=hashlib.sha256(fields['statement'].encode()).hexdigest())
        with closing(self.state()) as c, c:
            c.execute('INSERT INTO drafts VALUES (?,?)', (ident, json.dumps(fields)))
            c.execute('INSERT INTO saved VALUES (?,?,?)', (ident, fields.pop('notes'), fields['created_at']))
        return self.decorate(fields)

    def export(self):
        entries, versions, blockers = [], set(), []
        for s in self.saved():
            d = self.get(s['id'])
            versions.add((d.get('lean'), d.get('mathlib_rev')))
            if d['trust'] != 'recorded-sorry-free':
                blockers.append(d['name'] + ': ' + d['trust'])
            entries.append({k: d.get(k) for k in ['id', 'name', 'corpus', 'module', 'lean', 'mathlib_rev', 'stmt_hash', 'trust', 'statement', 'proof_source'] } | {'notes': s['notes']})
        if len(versions) > 1:
            blockers.insert(0, 'Mixed Lean/Mathlib versions require porting and re-verification.')
        if any(not a or not b for a, b in versions):
            blockers.append('Toolchain metadata is incomplete.')
        return {'format': 'quarry-workspace-v1', 'exported_at': datetime.now(timezone.utc).isoformat(),
                'notice': 'Selection manifest only; not a Lake lockfile or a new verification result. Importing declarations requires their source packages.',
                'compatible_toolchains': len(versions) <= 1, 'review_required': blockers, 'proofs': entries}


class Server(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, workspace, allowed_hosts=()):
        self.workspace = workspace
        self.allowed_hosts = {'localhost', '127.0.0.1', '::1', *allowed_hosts}
        self.csrf = secrets.token_urlsafe(32)
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Avoid logging proof statements or arbitrary query strings.
        pass

    def send(self, data, code=200, content_type='application/json; charset=utf-8'):
        body = json.dumps(data, ensure_ascii=False).encode() if content_type.startswith('application/json') else data
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.route(False)

    def do_POST(self):
        self.route(True)

    def route(self, write):
        try:
            # Loopback-only server, also prevent DNS rebinding against the local workspace.
            host = urlsplit('http://' + self.headers.get('Host', '')).hostname
            if host not in self.server.allowed_hosts:
                return self.send({'error': 'Use a localhost SSH tunnel to open this workspace'}, 403)
            url = urlsplit(self.path)
            params = {k: v[0] for k, v in parse_qs(url.query).items()}
            w = self.server.workspace
            if write:
                if self.headers.get('X-Quarry-Token') != self.server.csrf:
                    return self.send({'error': 'Invalid workspace token; refresh the page'}, 403)
                size = int(self.headers.get('Content-Length', 0))
                if not 0 < size <= 400000:
                    raise ValueError('Request body must be between 1 and 400,000 bytes')
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict):
                    raise ValueError('Expected a JSON object')
                if url.path == '/api/save':
                    return self.send(w.save(data.get('id'), data.get('notes', '')))
                if url.path == '/api/remove':
                    return self.send(w.remove(data['id']))
                if url.path == '/api/register':
                    return self.send(w.register(data), 201)
                return self.send({'error': 'Not found'}, 404)
            if url.path == '/api/bootstrap':
                return self.send({'corpora': w.corpora, 'saved': w.saved(), 'drafts': w.drafts(), 'csrf': self.server.csrf})
            if url.path == '/api/search':
                return self.send(w.search(params.get('q', ''), params.get('corpus', ''), params.get('kind', ''), int(params.get('offset', '0'))))
            if url.path == '/api/proof':
                return self.send(w.get(params['id']))
            if url.path == '/api/export':
                return self.send(w.export())
            files = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'), '/style.css': ('style.css', 'text/css')}
            if url.path in files:
                name, mime = files[url.path]
                return self.send((STATIC / name).read_bytes(), content_type=mime + '; charset=utf-8')
            return self.send({'error': 'Not found'}, 404)
        except KeyError as e:
            self.send({'error': str(e)}, 404)
        except (ValueError, TypeError) as e:
            self.send({'error': str(e)}, 400)
        except sqlite3.OperationalError:
            self.send({'error': 'Registry query unavailable or exceeded 15 seconds. Try a more specific search.'}, 503)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self.send({'error': 'An unexpected workspace error occurred'}, 500)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db', required=True)
    p.add_argument('--state', default='quarry-workspace.sqlite')
    p.add_argument('--port', type=int, default=8791)
    p.add_argument('--allowed-host', action='append', default=[])
    args = p.parse_args()
    w = Workspace(args.db, args.state)
    server = Server(('127.0.0.1', args.port), w, args.allowed_host)
    print(f'Quarry workspace ready at http://127.0.0.1:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == '__main__':
    main()
