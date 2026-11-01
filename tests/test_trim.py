"""Trim validation and project-timeline offsets."""

import json
from pathlib import Path
import tempfile
import unittest

from unweave.audio.pipeline import parse_trim
from unweave.cli import parser
from unweave.projects.store import describe_project


def project(root: Path, separation: dict, names=("vocals", "guitar", "lead", "rhythm")) -> Path:
    path = root / "Song"
    path.mkdir()
    (path / "original.wav").write_bytes(b"RIFF")
    (path / "metadata.json").write_text(json.dumps({"title": "Song", "original_file": "original.wav"}))
    stems = path / "stems"
    stems.mkdir()
    for name in names:
        (stems / f"{name}.wav").write_bytes(b"RIFF")
    (stems / "separation.json").write_text(json.dumps(separation))
    return path


class ParseTrimTests(unittest.TestCase):
    def test_accepts_mapping_and_pair(self):
        self.assertEqual(parse_trim({"start": 1.23456, "end": 2.34567}, 10), (1.235, 2.346))
        self.assertEqual(parse_trim([0, 5], 10), (0.0, 5.0))
        self.assertIsNone(parse_trim(None, 10))

    def test_rejects_invalid_values(self):
        for value in ({"start": "1", "end": 2}, {"start": 1, "end": float("nan")},
                      {"start": -1, "end": 2}, {"start": 5, "end": 5}, "full",
                      {"start": 0, "end": 10.1}, {"start": 0, "end": 0.5}):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_trim(value, 10)

    def test_guitar_minimum(self):
        with self.assertRaises(ValueError):
            parse_trim({"start": 1, "end": 2.5}, 10, 2.0)
        self.assertEqual(parse_trim({"start": 1, "end": 3}, 10, 2.0), (1.0, 3.0))


class CliTrimTests(unittest.TestCase):
    def test_separate_range(self):
        args = parser().parse_args(["separate", "--file", "song.wav", "--start", "1.5", "--end", "9"])
        self.assertEqual((args.start, args.end), (1.5, 9.0))

    def test_split_range(self):
        args = parser().parse_args(["split-guitar", "--file", "guitar.wav", "--output", "out",
                                    "--start", "2", "--end", "8"])
        self.assertEqual((args.start, args.end), (2.0, 8.0))


class ProjectOffsetTests(unittest.TestCase):
    def test_offsets_follow_trim(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = project(Path(temporary), {
                "stems": ["vocals", "guitar"],
                "trim": {"start": 90, "end": 120},
                "lead_rhythm_split": {"model": "listra92", "trim": {"start": 95, "end": 110}},
            })
            info = describe_project(path)
            offsets = {item["file"]: item["offset"] for item in info["stems"]}
            names = {item["file"]: item["name"] for item in info["stems"]}
            self.assertEqual(names["vocals.wav"], "Vocals")
            self.assertEqual(names["lead.wav"], "Lead")
            self.assertEqual(offsets["vocals.wav"], 90.0)
            self.assertEqual(offsets["lead.wav"], 95.0)
            self.assertEqual(offsets["rhythm.wav"], 95.0)
            self.assertNotIn("guitar.wav", offsets)
            self.assertEqual(info["separation"]["trim"], {"start": 90, "end": 120})

    def test_legacy_guitar_targets_use_split_offset(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = project(Path(temporary), {
                "trim": {"start": 10, "end": 40},
                "lead_rhythm_split": {"model": "listra92", "trim": {"start": 15, "end": 25}},
            }, names=("vocals", "guitar-target-1", "guitar-remainder"))
            offsets = {item["file"]: item["offset"] for item in describe_project(path)["stems"]}
            self.assertEqual(offsets["vocals.wav"], 10.0)
            self.assertEqual(offsets["guitar-target-1.wav"], 15.0)
            self.assertEqual(offsets["guitar-remainder.wav"], 15.0)

    def test_invalid_trim_is_dropped_with_warning(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = project(Path(temporary), {
                "trim": {"start": "bad", "end": 30},
                "lead_rhythm_split": {"model": "listra92", "trim": {"start": 40, "end": 20}},
            })
            info = describe_project(path)
            self.assertNotIn("trim", info["separation"])
            self.assertNotIn("trim", info["separation"]["lead_rhythm_split"])
            self.assertIn("Separation settings: invalid trim range.", info["warnings"])
            self.assertTrue(all(item["offset"] == 0 for item in info["stems"]))

    def test_untouched_projects_keep_zero_offsets(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = project(Path(temporary), {"stems": ["vocals"]}, names=("vocals",))
            info = describe_project(path)
            self.assertEqual(info["stems"][0]["offset"], 0.0)
            self.assertNotIn("trim", info["separation"])


if __name__ == "__main__":
    unittest.main()
