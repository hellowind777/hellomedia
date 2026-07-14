#!/usr/bin/env python3
"""Offline tests for HTTP(S) proxy resolution (no network)."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import _common as common  # noqa: E402


class ProxyResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._env = os.environ.copy()
        for k in list(os.environ):
            if k.lower() in {
                "hellomedia_proxy",
                "http_proxy",
                "https_proxy",
                "all_proxy",
                "no_proxy",
            }:
                del os.environ[k]
        common._PROXY_INSTALLED = None

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._env)
        common._PROXY_INSTALLED = None
        common.install_opener(common.build_opener())

    def test_explicit_hellomedia_proxy_enables_http_https(self) -> None:
        os.environ["HELLOMEDIA_PROXY"] = "http://user:s3cret@127.0.0.1:18080"
        proxies, summary = common.resolve_proxy_settings()
        self.assertTrue(summary["enabled"])
        self.assertEqual(summary["source"], "explicit")
        self.assertIn("http", proxies)
        self.assertIn("https", proxies)
        # public summary must not embed password
        blob = str(summary)
        self.assertNotIn("s3cret", blob)
        self.assertNotIn("user:s3cret", blob)

    def test_socks_proxy_is_unsupported(self) -> None:
        os.environ["HELLOMEDIA_PROXY"] = "socks5://127.0.0.1:1080"
        proxies, summary = common.resolve_proxy_settings()
        self.assertFalse(summary["enabled"])
        self.assertEqual(proxies, {})
        self.assertIn("socks5", summary.get("unsupported_schemes") or [])

    def test_http_proxy_env(self) -> None:
        os.environ["HTTP_PROXY"] = "http://127.0.0.1:9"
        os.environ["HTTPS_PROXY"] = "http://127.0.0.1:9"
        proxies, summary = common.resolve_proxy_settings()
        self.assertTrue(summary["enabled"])
        self.assertEqual(summary["source"], "environment")
        self.assertTrue(proxies)

    def test_configure_proxy_opener_returns_summary(self) -> None:
        os.environ["HELLOMEDIA_PROXY"] = "http://127.0.0.1:9"
        summary = common.configure_proxy_opener()
        self.assertTrue(summary.get("enabled"))
        self.assertEqual(common.proxy_summary().get("enabled"), True)

    def test_no_proxy_disabled(self) -> None:
        with mock.patch.object(common, "getproxies", return_value={}):
            proxies, summary = common.resolve_proxy_settings()
        self.assertFalse(summary["enabled"])
        self.assertEqual(proxies, {})


if __name__ == "__main__":
    unittest.main()
