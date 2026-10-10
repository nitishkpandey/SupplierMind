from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from prepare_reproduction import deduplicate_benchmark, sanitize_run  # noqa: E402


class PrepareReproductionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.duplicate_id = "duplicate"
        self.benchmark = [
            {
                "id": "first",
                "query_number": 1,
                "raw_query": "first query",
                "difficulty": "simple",
            },
            {
                "id": self.duplicate_id,
                "query_number": 2,
                "raw_query": "first query",
                "difficulty": "hard",
            },
            {
                "id": "third",
                "query_number": 3,
                "raw_query": "third query",
                "difficulty": "hard",
            },
        ]

    def test_deduplicate_benchmark_removes_duplicate_and_renumbers(self) -> None:
        corrected, query_numbers = deduplicate_benchmark(
            self.benchmark,
            excluded_query_id=self.duplicate_id,
        )

        self.assertEqual([query["id"] for query in corrected], ["first", "third"])
        self.assertEqual([query["query_number"] for query in corrected], [1, 2])
        self.assertEqual(corrected[1]["source_query_number"], 3)
        self.assertEqual(query_numbers, {"first": 1, "third": 2})

    def test_sanitize_run_removes_duplicate_and_free_text_reasoning(self) -> None:
        run = {
            "query_count": 3,
            "aggregated": {"stale": True},
            "per_query_metrics": {
                "keyword_sql": [],
                "suppliermind": [
                    {
                        "query_id": "first",
                        "query_number": 1,
                        "precision_at_5": 1.0,
                        "reasoning": "remove this",
                        "compliance_data": [{"reason": "retain evidence reason"}],
                    },
                    {
                        "query_id": self.duplicate_id,
                        "query_number": 2,
                        "precision_at_5": 0.0,
                        "reasoning": "remove this too",
                    },
                    {
                        "query_id": "third",
                        "query_number": 3,
                        "precision_at_5": 0.5,
                        "reasoning": "remove this as well",
                    },
                ]
            },
        }

        sanitized = sanitize_run(
            run,
            excluded_query_id=self.duplicate_id,
            query_numbers={"first": 1, "third": 2},
        )

        records = sanitized["per_query_metrics"]["suppliermind"]
        self.assertEqual(sanitized["query_count"], 2)
        self.assertNotIn("aggregated", sanitized)
        self.assertEqual(sanitized["per_query_metrics"]["keyword_sql"], [])
        self.assertEqual([record["query_number"] for record in records], [1, 2])
        self.assertNotIn("reasoning", records[0])
        self.assertEqual(records[0]["compliance_data"][0]["reason"], "retain evidence reason")


if __name__ == "__main__":
    unittest.main()
