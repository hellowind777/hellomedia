#!/usr/bin/env python3
"""Offline tests for media capabilities validation."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from media_caps import (  # noqa: E402
    ValidationError,
    capabilities_dict,
    closest_aspect_ratios,
    default_video_model,
    validate_video_request,
)


class MediaCapsTests(unittest.TestCase):
    def test_capabilities_has_video_modes(self) -> None:
        caps = capabilities_dict()
        self.assertEqual(caps["operation"], "capabilities")
        self.assertIn("image_to_video", caps["video"]["modes"])
        self.assertIn("reference_to_video", caps["video"]["modes"])

    def test_closest_aspect_for_four_by_five(self) -> None:
        sugg = closest_aspect_ratios("4:5", ("1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"))
        self.assertTrue(sugg)
        self.assertIn(sugg[0], {"3:4", "2:3", "1:1"})

    def test_reject_unsupported_video_aspect(self) -> None:
        with self.assertRaises(ValidationError) as ctx:
            validate_video_request(
                tool_mode="text_to_video",
                duration=6,
                resolution="480p",
                aspect_ratio="4:5",
                model="grok-imagine-video",
                prompt="hello",
            )
        err = ctx.exception
        self.assertTrue(err.suggestions)
        d = err.to_dict()
        self.assertFalse(d["ok"])
        self.assertIn("suggestions", d)

    def test_reject_duration_over_max(self) -> None:
        with self.assertRaises(ValidationError):
            validate_video_request(
                tool_mode="text_to_video",
                duration=99,
                resolution="480p",
                aspect_ratio="16:9",
                model="grok-imagine-video",
                prompt="hello",
            )

    def test_reference_duration_max_10(self) -> None:
        with self.assertRaises(ValidationError):
            validate_video_request(
                tool_mode="reference_to_video",
                duration=12,
                resolution="720p",
                aspect_ratio="16:9",
                model="grok-imagine-video",
                n_refs=2,
                prompt="hello",
            )

    def test_1080p_only_i2v_15(self) -> None:
        with self.assertRaises(ValidationError):
            validate_video_request(
                tool_mode="text_to_video",
                duration=6,
                resolution="1080p",
                aspect_ratio="16:9",
                model="grok-imagine-video",
                prompt="hello",
            )
        ok = validate_video_request(
            tool_mode="image_to_video",
            duration=6,
            resolution="1080p",
            aspect_ratio=None,
            model="grok-imagine-video-1.5",
            has_image=True,
            prompt="move",
            aspect_explicit=False,
        )
        self.assertTrue(ok["omit_aspect_ratio"])

    def test_reference_rejects_model_15(self) -> None:
        with self.assertRaises(ValidationError):
            validate_video_request(
                tool_mode="reference_to_video",
                duration=8,
                resolution="720p",
                aspect_ratio="16:9",
                model="grok-imagine-video-1.5",
                n_refs=1,
                prompt="hello",
            )

    def test_video_edit_gated(self) -> None:
        with self.assertRaises(ValidationError) as ctx:
            validate_video_request(
                tool_mode="edit",
                duration=6,
                resolution="480p",
                aspect_ratio=None,
                model="grok-imagine-video",
                has_video=True,
                prompt="add jacket",
                video_edit=False,
            )
        self.assertEqual(ctx.exception.code, "video_edit_disabled")

    def test_default_models(self) -> None:
        self.assertIn("1.5", default_video_model("image_to_video"))
        self.assertNotIn("1.5", default_video_model("text_to_video"))
        self.assertEqual(default_video_model("text_to_video", explicit="custom"), "custom")
        # Generic channel T2V model must not override I2V 1.5 default
        self.assertIn(
            "1.5",
            default_video_model("image_to_video", channel_model="grok-imagine-video"),
        )
        # Intentional channel pin of 1.5 is kept
        self.assertEqual(
            default_video_model("image_to_video", channel_model="grok-imagine-video-1.5"),
            "grok-imagine-video-1.5",
        )
        # Explicit CLI wins over everything
        self.assertEqual(
            default_video_model(
                "image_to_video",
                channel_model="grok-imagine-video",
                explicit="custom-i2v",
            ),
            "custom-i2v",
        )


if __name__ == "__main__":
    unittest.main()
