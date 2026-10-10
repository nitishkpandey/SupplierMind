from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VERIFY = ROOT / "thesis" / "scripts" / "verify_reproduction.py"


class VerificationTests(unittest.TestCase):
    def test_verifier_accepts_published_package(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(VERIFY)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("24 unique satisfiable queries", completed.stdout)
        self.assertIn("9 sanitized archived runs", completed.stdout)
        self.assertIn("all provenance checksums match", completed.stdout)


if __name__ == "__main__":
    unittest.main()
