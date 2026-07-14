#!/usr/bin/env python3
"""Output path safety and download URL scheme rules (no network)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import _common as common  # noqa: E402


class SafePathTests(unittest.TestCase):
    def test_skill_output_allowed(self) -> None:
        skill = common.SKILL_DIR.resolve()
        ok, p = common.safe_output_path(str(skill / "output" / "a.png"))
        self.assertTrue(ok)
        self.assertIsNotNone(p)

    def test_prefix_sibling_not_allowed(self) -> None:
        """hellomedia_evil must not pass as under hellomedia (startswith bug)."""
        skill = common.SKILL_DIR.resolve()
        evil = skill.parent / f"{skill.name}_evil" / "out.mp4"
        ok, _ = common.safe_output_path(str(evil))
        self.assertFalse(ok)

    def test_cwd_relative_output_allowed(self) -> None:
        ok, p = common.safe_output_path("./output/local.png")
        self.assertTrue(ok)
        self.assertIsNotNone(p)

    def test_stdout_dash_allowed(self) -> None:
        ok, p = common.safe_output_path("-")
        self.assertTrue(ok)
        self.assertIsNone(p)


class DownloadUrlSchemeTests(unittest.TestCase):
    def test_http_loopback_allowed(self) -> None:
        # Local proxy / test servers must remain first-class
        self.assertEqual(
            common.validate_download_url("http://127.0.0.1:9/v.mp4"),
            "http://127.0.0.1:9/v.mp4",
        )
        self.assertEqual(
            common.validate_download_url("http://localhost:8080/x"),
            "http://localhost:8080/x",
        )

    def test_https_allowed(self) -> None:
        common.validate_download_url("https://cdn.example.com/v.mp4")

    def test_file_scheme_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            common.validate_download_url("file:///C:/Windows/x.mp4")
        self.assertIn("scheme", str(ctx.exception).lower())

    def test_empty_rejected(self) -> None:
        with self.assertRaises(ValueError):
            common.validate_download_url("")

    def test_recover_rejects_file_scheme(self) -> None:
        dest = str(common.SKILL_DIR / "output" / "no_file_scheme.mp4")
        result = common.recover_media_url("file:///tmp/x.mp4", dest, kind="video")
        self.assertFalse(result.get("ok"))
        self.assertIn("scheme", (result.get("error") or "").lower())


if __name__ == "__main__":
    unittest.main()
