#!/usr/bin/env python3
"""Offline tests for media download retries and recovery (local HTTP server)."""

from __future__ import annotations

import http.server
import socketserver
import sys
import threading
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import _common as common  # noqa: E402


class _FlakyHandler(http.server.BaseHTTPRequestHandler):
    hits = 0

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def do_GET(self) -> None:  # noqa: N802
        type(self).hits += 1
        if type(self).hits < 3:
            self.send_response(503)
            self.end_headers()
            self.wfile.write(b"busy")
            return
        body = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 32
        self.send_response(200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class DownloadRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        _FlakyHandler.hits = 0
        self.httpd = socketserver.TCPServer(("127.0.0.1", 0), _FlakyHandler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.out = Path(__file__).resolve().parents[1] / "output" / "test_dl.mp4"
        if self.out.exists():
            self.out.unlink()

    def tearDown(self) -> None:
        self.httpd.shutdown()
        if self.out.exists():
            self.out.unlink()

    def test_download_retries_then_succeeds(self) -> None:
        url = f"http://127.0.0.1:{self.port}/v.mp4"
        path = common.download_url(url, self.out, timeout=5, max_attempts=4)
        self.assertTrue(path.exists())
        self.assertGreater(path.stat().st_size, 0)
        self.assertGreaterEqual(_FlakyHandler.hits, 3)

    def test_recover_media_url_get_only(self) -> None:
        _FlakyHandler.hits = 2  # next hit succeeds
        url = f"http://127.0.0.1:{self.port}/v.mp4"
        # force output under project
        dest = str(Path(__file__).resolve().parents[1] / "output" / "recovered.mp4")
        result = common.recover_media_url(url, dest, kind="video", timeout=5)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result.get("saved_to"))
        self.assertIn("markdown_media", result)
        Path(result["saved_to"]).unlink(missing_ok=True)

    def test_remove_partial_on_permanent_failure(self) -> None:
        class AlwaysFail(http.server.BaseHTTPRequestHandler):
            def log_message(self, format: str, *args) -> None:  # noqa: A003
                return

            def do_GET(self) -> None:  # noqa: N802
                self.send_response(404)
                self.end_headers()

        httpd = socketserver.TCPServer(("127.0.0.1", 0), AlwaysFail)
        port = httpd.server_address[1]
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        try:
            bad = Path(__file__).resolve().parents[1] / "output" / "partial.mp4"
            with self.assertRaises(Exception):
                common.download_url(f"http://127.0.0.1:{port}/x", bad, timeout=3, max_attempts=2)
            self.assertFalse(bad.exists())
        finally:
            httpd.shutdown()


if __name__ == "__main__":
    unittest.main()
