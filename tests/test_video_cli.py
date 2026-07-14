#!/usr/bin/env python3
"""Drive shipped video.py entrypoint for validation and dry-run contracts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIDEO = ROOT / "scripts" / "video.py"
DOCTOR = ROOT / "scripts" / "doctor.py"
GENERATE = ROOT / "scripts" / "generate.py"
AUDIO = ROOT / "scripts" / "audio.py"
PY = sys.executable


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
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    blob = out or err
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        # last JSON object in mixed output
        data = {}
        for line in reversed(blob.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    data = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
        if not data and blob.startswith("{"):
            # multi-line json
            try:
                data = json.loads(blob)
            except json.JSONDecodeError:
                data = {"_raw": blob[:500]}
    return proc.returncode, data


class VideoCliTests(unittest.TestCase):
    def test_reject_aspect_4_5_before_post(self) -> None:
        code, data = run_json(
            [str(VIDEO), "--prompt", "x", "--aspect-ratio", "4:5", "--dry-run"]
        )
        self.assertNotEqual(code, 0)
        self.assertFalse(data.get("ok", True))
        self.assertIn("suggestions", data)

    def test_reject_duration_99(self) -> None:
        code, data = run_json(
            [str(VIDEO), "--prompt", "x", "--duration", "99", "--dry-run"]
        )
        self.assertNotEqual(code, 0)
        self.assertFalse(data.get("ok", True))

    def test_text_to_video_dry_run_ok(self) -> None:
        code, data = run_json([str(VIDEO), "--prompt", "t", "--dry-run"])
        self.assertEqual(code, 0)
        self.assertTrue(data.get("ok"))
        self.assertTrue(data.get("dry_run"))
        self.assertEqual(data.get("tool"), "text_to_video")

    def _ensure_swatch(self) -> Path:
        img = ROOT / "output" / "test_swatch.png"
        img.parent.mkdir(parents=True, exist_ok=True)
        if not img.exists():
            img.write_bytes(
                bytes.fromhex(
                    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
                    "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
                )
            )
        return img

    def test_i2v_omits_aspect_when_unset(self) -> None:
        img = self._ensure_swatch()
        code, data = run_json(
            [
                str(VIDEO),
                "--mode",
                "image_to_video",
                "--image",
                str(img),
                "--prompt",
                "gentle motion",
                "--dry-run",
            ]
        )
        self.assertEqual(code, 0, data)
        preview = data.get("payload_preview") or {}
        self.assertTrue(
            preview.get("aspect_ratio_omitted") or preview.get("aspect_ratio") is None,
            preview,
        )

    def test_i2v_dry_run_uses_model_15_despite_channel_video_model(self) -> None:
        """Shipped path: channel video_model is usually grok-imagine-video; I2V must still pick 1.5."""
        img = self._ensure_swatch()
        code, data = run_json(
            [
                str(VIDEO),
                "--mode",
                "image_to_video",
                "--image",
                str(img),
                "--prompt",
                "gentle motion",
                "--dry-run",
            ]
        )
        self.assertEqual(code, 0, data)
        model = data.get("model") or ""
        self.assertIn("1.5", model, data)
        # 1080p must be accepted on this model without explicit --model
        code2, data2 = run_json(
            [
                str(VIDEO),
                "--mode",
                "image_to_video",
                "--image",
                str(img),
                "--prompt",
                "gentle motion",
                "--resolution",
                "1080p",
                "--dry-run",
            ]
        )
        self.assertEqual(code2, 0, data2)
        self.assertIn("1.5", data2.get("model") or "", data2)
        self.assertEqual((data2.get("payload_preview") or {}).get("resolution"), "1080p")

    def test_doctor_capabilities_no_key(self) -> None:
        code, data = run_json([str(DOCTOR), "--capabilities"])
        self.assertEqual(code, 0)
        self.assertEqual(data.get("operation"), "capabilities")
        self.assertIn("video", data)

    def test_doctor_dry_run_has_proxy(self) -> None:
        code, data = run_json([str(DOCTOR), "--dry-run"])
        self.assertEqual(code, 0)
        self.assertTrue(data.get("ok"))
        self.assertIn("proxy", data)

    def test_generate_dry_run(self) -> None:
        code, data = run_json(
            [str(GENERATE), "--prompt", "t", "--dry-run", "--quiet"]
        )
        self.assertEqual(code, 0)
        self.assertTrue(data.get("ok"))

    def test_audio_dry_run(self) -> None:
        code, data = run_json([str(AUDIO), "tts", "--text", "t", "--dry-run"])
        self.assertEqual(code, 0)
        self.assertTrue(data.get("ok"))


if __name__ == "__main__":
    unittest.main()
