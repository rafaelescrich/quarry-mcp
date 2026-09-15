"""Integration tests using the existing extracted Lean fixture, never modifying it."""
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from quarry_mcp.web import Workspace, Server, trust

FIXTURE = Path(__file__).resolve().parents[1] / 'fixtures/quarry-fixture.sqlite'


class WebTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()

    @classmethod
    def tearDownClass(cls):
        assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == cls.original

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'state.sqlite'
        self.w = Workspace(FIXTURE, self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_search_filters_pagination_literal_input(self):
        result = self.w.search('Poisson', kind='theorem')
        self.assertGreater(len(result['items']), 0)
        self.assertTrue(all(d['kind'] == 'theorem' for d in result['items']))
        corpus = result['items'][0]['corpus']
        self.assertTrue(all(d['corpus'] == corpus for d in self.w.search('Poisson', corpus)['items']))
        self.assertFalse(set(x['id'] for x in self.w.search()['items']) & set(x['id'] for x in self.w.search(offset=30)['items']))
        self.assertEqual(self.w.search('" OR definitely_missing_abc123')['items'], [])
        with self.assertRaises(ValueError):
            self.w.search(offset=-1)

    def test_details_dependency_and_provenance(self):
        item = self.w.search('Poisson')['items'][0]
        d = self.w.get(item['id'])
        self.assertIn('dependencies', d)
        self.assertIn('corpus_info', d)
        self.assertIn('axioms', d)
        self.assertIn(d['trust'], ['recorded-sorry-free', 'contains-sorry', 'custom-axioms', 'unknown'])
        with self.assertRaises(KeyError):
            self.w.get('absent')

    def test_save_notes_persist_and_remove(self):
        ident = self.w.search()['items'][0]['id']
        self.w.save(ident, 'Unicode ∀ and <script> stay text')
        other = Workspace(FIXTURE, self.path)
        self.assertEqual(other.saved()[0]['notes'], 'Unicode ∀ and <script> stay text')
        other.save(ident, 'updated')
        self.assertEqual(len(other.saved()), 1)
        other.remove(ident)
        self.assertEqual(other.saved(), [])

    def test_registration_is_unverified_and_durable(self):
        d = self.w.register({'name':'Demo.test','module':'Demo','lean':'4.34.0-rc2','statement':'True','proof_source':'by trivial','notes':'Check this'})
        self.assertEqual(d['trust'], 'unverified')
        self.assertIsNone(d['sorry_free'])
        self.assertEqual(Workspace(FIXTURE, self.path).get(d['id'])['proof_source'], 'by trivial')
        self.assertEqual(self.w.saved()[0]['notes'], 'Check this')
        self.assertTrue(self.w.export()['review_required'])
        with self.assertRaises(ValueError):
            self.w.register({'name':'Incomplete'})

    def test_mixed_toolchain_export(self):
        for corpus in self.w.corpora:
            self.w.save(self.w.search(corpus=corpus['id'])['items'][0]['id'], 'review')
        result = self.w.export()
        self.assertFalse(result['compatible_toolchains'])
        self.assertIn('Mixed Lean/Mathlib', result['review_required'][0])
        self.assertEqual(len(result['proofs']), len(self.w.corpora))

    def test_missing_and_custom_axioms_never_imply_verified(self):
        self.assertEqual(trust({'sorry_free':1,'axioms':None}), 'unknown')
        self.assertEqual(trust({'sorry_free':1,'axioms':['myAxiom']}), 'custom-axioms')
        self.assertEqual(trust({'sorry_free':1,'axioms':['sorryAx']}), 'contains-sorry')
        self.assertEqual(trust({'sorry_free':1,'axioms':[]}), 'recorded-sorry-free')

    def test_read_only_corpus(self):
        import sqlite3
        c = self.w.corpus()
        try:
            with self.assertRaises(sqlite3.OperationalError):
                c.execute('DELETE FROM corpus')
        finally:
            c.close()

    def test_http_roundtrip_security_and_assets(self):
        server = Server(('127.0.0.1', 0), self.w)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = 'http://127.0.0.1:' + str(server.server_port)
        def request(path, body=None, headers=None):
            req = Request(base+path, data=json.dumps(body).encode() if body is not None else None, headers=headers or {})
            with urlopen(req, timeout=20) as r:
                return r.status, r.read(), r.headers
        try:
            _, body, headers = request('/')
            self.assertIn(b'Proof registry', body)
            self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
            self.assertEqual(request('/app.js')[0], 200)
            bootstrap = json.loads(request('/api/bootstrap')[1])
            with self.assertRaises(HTTPError) as err:
                request('/api/register', {'name':'bad'})
            self.assertEqual(err.exception.code, 403)
            with self.assertRaises(HTTPError) as err:
                request('/api/bootstrap', headers={'Host':'attacker.example'})
            self.assertEqual(err.exception.code, 403)
            token = {'X-Quarry-Token':bootstrap['csrf']}
            result = json.loads(request('/api/register', {'name':'Test.web','module':'Test','lean':'4.34.0-rc2','statement':'True'}, token)[1])
            self.assertEqual(result['trust'], 'unverified')
            exported = json.loads(request('/api/export')[1])
            self.assertEqual(exported['proofs'][0]['name'], 'Test.web')
            self.assertGreater(len(json.loads(request('/api/search?q=Poisson')[1])['items']),0)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
