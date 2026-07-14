#!/usr/bin/env python3
"""Sub2API / xAI relay contract: image field names + official-host preflight scope."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import _common as common  # noqa: E402


class Sub2ApiContractTests(unittest.TestCase):
    def test_official_xai_host_only_api_x_ai(self) -> None:
        self.assertTrue(common.is_official_xai_host("https://api.x.ai"))
        self.assertTrue(common.is_official_xai_host("https://api.x.ai/v1"))
        self.assertFalse(common.is_official_xai_host("https://ai.llmx.cloud/v1"))
        self.assertFalse(common.is_official_xai_host("https://sub2api.example.com/v1"))

    def test_api_format_xai_is_xai_like_but_not_official(self) -> None:
        ch = {
            "api_format": "xai",
            "base_url": "https://ai.llmx.cloud/v1",
        }
        self.assertTrue(common.is_xai_like_channel(ch))
        self.assertFalse(
            common.is_official_xai_host(ch["base_url"])
        )

    def test_video_image_url_field_sub2api(self) -> None:
        ch = {"api_format": "xai", "base_url": "https://relay.example/v1"}
        self.assertEqual(common.video_image_url_field(ch["base_url"], ch), "image_url")

    def test_video_image_url_field_official(self) -> None:
        ch = {"api_format": "xai", "base_url": "https://api.x.ai"}
        self.assertEqual(common.video_image_url_field(ch["base_url"], ch), "url")

    def test_video_image_url_field_override(self) -> None:
        ch = {
            "api_format": "xai",
            "base_url": "https://relay.example/v1",
            "video_image_url_field": "url",
        }
        self.assertEqual(common.video_image_url_field("", ch), "url")

    def test_browser_user_agent_default(self) -> None:
        ua = common.resolve_media_user_agent()
        self.assertIn("Mozilla", ua)
        self.assertNotIn("hellomedia/", ua)


if __name__ == "__main__":
    unittest.main()
