#!/usr/bin/env python3
"""generate.py --count bounds and dry-run contracts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERATE = ROOT / "scripts" / "generate.py"
PY = sys.executable


def run_json(args: list[str]) -> tuple[int, dict]:
    proc = subprocess.run(
        [PY, *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=os.environ.copy(),
    )
    blob = ((proc.stderr or "") + "\n" + (proc.stdout or "")).strip()
    data: dict = {}
    for line in reversed(blob.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                data = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
    if not data:
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            data = {"_raw": blob[:500]}
    return proc.returncode, data


class GenerateCountTests(unittest.TestCase):
    def test_count_zero_rejected(self) -> None:
        code, data = run_json(
            [
                str(GENERATE),
                "--prompt",
                "x",
                "--count",
                "0",
                "--output",
                "./output/z.png",
                "--dry-run",
                "--quiet",
            ]
        )
        self.assertNotEqual(code, 0)
        self.assertFalse(data.get("ok", True))
        self.assertEqual(data.get("code"), "invalid_count")

    def test_count_99_rejected(self) -> None:
        code, data = run_json(
            [
                str(GENERATE),
                "--prompt",
                "x",
                "--count",
                "99",
                "--output",
                "./output/z.png",
                "--dry-run",
                "--quiet",
            ]
        )
        self.assertNotEqual(code, 0)
        self.assertFalse(data.get("ok", True))

    def test_count_one_dry_run_ok(self) -> None:
        code, data = run_json(
            [
                str(GENERATE),
                "--prompt",
                "x",
                "--count",
                "1",
                "--output",
                "./output/z.png",
                "--dry-run",
                "--quiet",
            ]
        )
        self.assertEqual(code, 0, data)
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("count"), 1)
        # Must never echo the raw secret field (has_api_key boolean is OK)
        dumped = json.dumps(data)
        self.assertNotRegex(dumped, r'"api_key"\s*:')
        self.assertIn("has_api_key", data)


if __name__ == "__main__":
    unittest.main()
