"""Export format table, staging, and manifest."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from unweave.audio.exports import FORMATS, export_stems


def make_project(root: Path) -> Path:
    path = root / "Song"
    path.mkdir()
    (path / "original.wav").write_bytes(b"RIFF")
    (path / "metadata.json").write_text(json.dumps({
        "title": "Song", "artist": "Artist", "album": "Album", "year": "2026",
        "original_file": "original.wav",
    }))
    stems = path / "stems"
    stems.mkdir()
    for name in ("vocals", "guitar"):
        (stems / f"{name}.wav").write_bytes(f"{name}-data".encode())
    (stems / "separation.json").write_text(json.dumps({
        "stems": ["vocals", "guitar"], "trim": {"start": 90, "end": 120},
    }))
    return path


def fake_convert(source, destination, format_id, metadata, prevent_clipping,
                 duration, report=None, set_process=None):
    destination.write_bytes(source.read_bytes())
    if report:
        report(1.0)


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.ffmpeg = patch("unweave.audio.exports.ensure_ffmpeg_on_path", return_value=True)
        self.ffmpeg.start()
        self.addCleanup(self.ffmpeg.stop)

    def test_format_table(self):
        self.assertEqual(set(FORMATS), {"flac", "mp3", "opus", "m4a", "wav16", "aiff"})
        for format_id, spec in FORMATS.items():
            with self.subTest(format=format_id):
                self.assertTrue(spec["extension"].startswith("."))
                self.assertIn("-c:a", spec["args"])

    def test_staging_replaces_only_requested_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = make_project(Path(temporary))
            exports = project / "exports"
            exports.mkdir()
            (exports / "guitar.mp3").write_bytes(b"keep me")
            with patch("unweave.audio.exports.convert", side_effect=fake_convert), \
                 patch("unweave.audio.exports.probe_duration", return_value=30.0):
                result = export_stems(project, ["vocals.wav"], ["flac", "mp3"], True)
            self.assertEqual({path.name for path in result}, {"vocals.flac", "vocals.mp3"})
            self.assertEqual((exports / "vocals.flac").read_bytes(), b"vocals-data")
            self.assertEqual((exports / "vocals.mp3").read_bytes(), b"vocals-data")
            self.assertEqual((exports / "guitar.mp3").read_bytes(), b"keep me")
            manifest = json.loads((exports / "manifest.json").read_text())
            self.assertEqual(manifest["formats"], ["flac", "mp3"])
            self.assertTrue(manifest["prevent_clipping"])
            self.assertEqual(manifest["files"], [
                {"stem": "vocals.wav", "label": "Vocals", "output": "vocals.flac", "offset": 90.0},
                {"stem": "vocals.wav", "label": "Vocals", "output": "vocals.mp3", "offset": 90.0},
            ])

    def test_rejects_unknown_stem_and_format(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = make_project(Path(temporary))
            with self.assertRaises(ValueError):
                export_stems(project, ["missing.wav"], ["flac"], True)
            with self.assertRaises(ValueError):
                export_stems(project, ["vocals.wav"], ["wav"], True)


if __name__ == "__main__":
    unittest.main()
