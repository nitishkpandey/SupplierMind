from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REPRODUCE = ROOT / "thesis" / "scripts" / "reproduce.py"
METRICS = ROOT / "thesis" / "results" / "METRICS.json"
FIGURES = ROOT / "thesis" / "figures"


class OfflineReproductionTests(unittest.TestCase):
    def test_single_command_reproduces_expected_metrics_and_figures(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(REPRODUCE)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("SupplierBench-24 reproduction verified", completed.stdout)

        metrics = json.loads(METRICS.read_text())
        self.assertEqual(metrics["n_runs"], 5)
        self.assertAlmostEqual(metrics["systems"]["suppliermind"]["p5"]["mean"], 0.7467, places=4)
        self.assertAlmostEqual(metrics["systems"]["p2_rag"]["p5"]["mean"], 0.5167, places=4)
        self.assertAlmostEqual(
            metrics["systems"]["suppliermind"]["p5_by_tier"]["hard"],
            0.6133,
            places=4,
        )

        expected = {
            "figure_5_1_precision_by_paradigm.png",
            "figure_5_2_precision_by_tier.png",
            "figure_5_3_auditability_rubric.png",
            "figure_5_4_abstention.png",
            "figure_5_5_ablation_ladder.png",
            "figure_5_6_cost_latency.png",
        }
        self.assertTrue(expected.issubset({path.name for path in FIGURES.glob("*.png")}))


if __name__ == "__main__":
    unittest.main()
