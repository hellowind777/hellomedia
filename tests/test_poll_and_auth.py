#!/usr/bin/env python3
"""video poll_timeout defaults, doctor version, auth post_json presence."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
VIDEO = SCRIPTS / "video.py"
DOCTOR = SCRIPTS / "doctor.py"
PY = sys.executable

sys.path.insert(0, str(SCRIPTS))


def run_json(args: list[str], env: dict | None = None) -> tuple[int, dict]:
    e = os.environ.copy()
    if env:
        e.update(env)
    proc = subprocess.run(
        [PY, *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=e,
    )
    # Prefer stdout: doctor/video progress may land on stderr
    for blob in ((proc.stdout or "").strip(), (proc.stderr or "").strip()):
        if not blob:
            continue
        try:
            return proc.returncode, json.loads(blob)
        except json.JSONDecodeError:
            pass
        # Multi-line JSON object starting at first '{'
        start = blob.find("{")
        if start >= 0:
            try:
                return proc.returncode, json.loads(blob[start:])
            except json.JSONDecodeError:
                pass
        for line in reversed(blob.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return proc.returncode, json.loads(line)
                except json.JSONDecodeError:
                    continue
    return proc.returncode, {"_raw": ((proc.stdout or "") + (proc.stderr or ""))[:500]}


class PollTimeoutTests(unittest.TestCase):
    def test_poll_timeout_none_default_loads_config_or_600(self) -> None:
        # dry-run does not require poll, but argparse default must be None so config can apply.
        # Smoke: CLI still works without explicit --poll-timeout
        code, data = run_json([str(VIDEO), "--prompt", "t", "--dry-run"])
        self.assertEqual(code, 0, data)
        self.assertTrue(data.get("ok"))


class DoctorVersionTests(unittest.TestCase):
    def test_doctor_dry_run_has_version(self) -> None:
        code, data = run_json([str(DOCTOR), "--dry-run"])
        self.assertEqual(code, 0, data)
        self.assertIn("version", data)
        self.assertTrue(str(data.get("version")))
        self.assertIn("overall_status", data)
        dumped = json.dumps(data)
        self.assertNotIn('"api_key":', dumped)


class AuthHelpersTests(unittest.TestCase):
    def test_post_json_and_request_failure_exist(self) -> None:
        import _auth_discovery as auth

        self.assertTrue(callable(auth.post_json))
        self.assertTrue(issubclass(auth.RequestFailure, Exception))

    def test_refresh_nameerror_gone(self) -> None:
        import _auth_discovery as auth

        with self.assertRaises(auth.RequestFailure):
            # Missing tokens → returns record early without post; force call path with empty refresh
            auth.refresh_codex_chatgpt_tokens(
                {"refresh_token": "rt", "payload": {}, "store": {}},
                Path("."),
            )


class PollVideoPermanentTests(unittest.TestCase):
    def test_poll_fails_fast_on_401(self) -> None:
        import video as video_mod

        def fake_http_json(*_a, **_k):
            return False, {"error": "HTTP 401: unauthorized", "status": 401}

        with mock.patch.object(video_mod, "http_json", side_effect=fake_http_json):
            out = video_mod.poll_video(
                "https://example.com", "key", "rid", timeout=30, interval=0.01
            )
        self.assertEqual(out.get("status"), "failed")
        self.assertEqual(out.get("http_status"), 401)


if __name__ == "__main__":
    unittest.main()
