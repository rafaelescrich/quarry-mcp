import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from quarry_mcp.db import Registry, NotFound, BadArgument
from tests.conftest_fixture import FIXTURE, KNOWN_ID


class TestRegistry(unittest.TestCase):
    def setUp(self):
        self.registry = Registry(FIXTURE)

    def test_stats_three_corpora(self):
        """stats has three corpora"""
        stats = self.registry.stats()
        self.assertIn("corpora", stats)
        self.assertEqual(len(stats["corpora"]), 3)

    def test_search_poisson_in_first_10(self):
        """search 'Poisson' (text) includes KNOWN_ID within the first 10 results"""
        results = self.registry.search("Poisson", mode="text", limit=10)
        self.assertTrue(len(results) > 0)
        ids = [r["id"] for r in results]
        self.assertIn(KNOWN_ID, ids)

    def test_search_corpus_filter(self):
        """search with corpus filter only returns that corpus"""
        corpus_id = "github.com/anthropics/fermats-last-theorem@aa2d8b34"
        results = self.registry.search("Poisson", mode="text", corpus=corpus_id)
        for r in results:
            self.assertTrue(r["id"].startswith(corpus_id))

    def test_get_with_edges_informal_metric(self):
        """get(KNOWN_ID, with_=("edges","informal","metric")) has non-empty edges.uses"""
        decl = self.registry.get(KNOWN_ID, with_=("edges", "informal", "metric"))
        self.assertIn("edges", decl)
        self.assertIn("uses", decl["edges"])
        self.assertTrue(len(decl["edges"]["uses"]) > 0)

    def test_get_unknown_id_raises_not_found(self):
        """get unknown id raises NotFound"""
        with self.assertRaises(NotFound):
            self.registry.get("unknown/id/that/does/not/exist")

    def test_closure_deps_count_and_by_corpus(self):
        """closure(KNOWN_ID, "deps") has count > 0 and by_corpus keys"""
        closure = self.registry.closure(KNOWN_ID, direction="deps")
        self.assertIn("root", closure)
        self.assertIn("count", closure)
        self.assertIn("by_corpus", closure)
        self.assertGreater(closure["count"], 0)

    def test_closure_stop_at_corpus(self):
        """closure with stop_at_corpus set to Mathlib corpus id does not expand Mathlib nodes"""
        # First get the unbounded closure
        unbounded = self.registry.closure(KNOWN_ID, direction="deps")
        
        # Find Mathlib corpus id from stats
        stats = self.registry.stats()
        mathlib_corpus = None
        for c in stats["corpora"]:
            if "mathlib" in c.lower():
                mathlib_corpus = c
                break
        
        self.assertIsNotNone(mathlib_corpus, "Mathlib corpus not found in fixture")
        
        # Get closure with stop_at_corpus
        bounded = self.registry.closure(
            KNOWN_ID, 
            direction="deps", 
            stop_at_corpus=mathlib_corpus
        )
        
        # Count should be <= unbounded
        self.assertLessEqual(bounded["count"], unbounded["count"])
        
        # No Mathlib ids should appear as sources of further expansion
        # Check that all ids in bounded are not from mathlib
        for id in bounded.get("ids", []):
            self.assertFalse(id.startswith(mathlib_corpus))

    def test_similar_returns_match_keys(self):
        """similar(id=KNOWN_ID) returns a list whose items have a 'match' key"""
        similar = self.registry.similar(id=KNOWN_ID)
        self.assertIsInstance(similar, list)
        for item in similar:
            self.assertIn("match", item)

    def test_bad_argument_invalid_mode(self):
        """BadArgument on an invalid mode"""
        with self.assertRaises(BadArgument):
            self.registry.search("test", mode="invalid_mode")


if __name__ == "__main__":
    unittest.main()
