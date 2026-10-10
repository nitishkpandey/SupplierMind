from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BENCHMARK = ROOT / "thesis" / "benchmark" / "supplierbench24_10k.json"
ABSTENTION = ROOT / "thesis" / "benchmark" / "abstention5_10k.json"


class BenchmarkIntegrityTests(unittest.TestCase):
    def test_supplierbench_contains_24_unique_queries(self) -> None:
        queries = json.loads(BENCHMARK.read_text())

        self.assertEqual(len(queries), 24)
        self.assertEqual([query["query_number"] for query in queries], list(range(1, 25)))
        self.assertEqual(len({query["id"] for query in queries}), 24)
        self.assertEqual(len({query["raw_query"].casefold() for query in queries}), 24)
        self.assertTrue(all(query["ground_truth_count"] >= 3 for query in queries))

    def test_abstention_queries_have_no_ground_truth_matches(self) -> None:
        queries = json.loads(ABSTENTION.read_text())

        self.assertEqual(len(queries), 5)
        self.assertTrue(all(query["ground_truth_count"] == 0 for query in queries))
        self.assertTrue(all(query["ground_truth_supplier_ids"] == [] for query in queries))


if __name__ == "__main__":
    unittest.main()
