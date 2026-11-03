"""Copy-only diagnostics bundle (spec 15)."""

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from unweave.diagnostics import (LOG_BYTE_CAP, LOG_LINE_CAP, build_diagnostics_text,
                                 redact_text, trim_log_lines)
from unweave.webui.library import Library


class RedactTests(unittest.TestCase):
    def test_redacts_projects_prefix(self):
        root = Path("/home/user/Music/Unweave Projects")
        line = f"Writing {root / 'Show Me Love' / 'original.wav'}"
        self.assertEqual(
            redact_text(line, root),
            "Writing <projects>/Show Me Love/original.wav",
        )

    def test_redacts_windows_style_prefix(self):
        # Forward-slash Windows path survives as a PosixPath string on Linux tests.
        root = Path("C:/Users/sam/Unweave/Projects")
        win_path = r"C:\Users\sam\Unweave\Projects\song\original.wav"
        mixed = "C:/Users/sam/Unweave/Projects/song/original.wav"
        for line in (win_path, mixed):
            with self.subTest(line=line):
                redacted = redact_text(line, root)
                self.assertIn("<projects>", redacted)
                self.assertNotIn(r"C:\Users\sam\Unweave\Projects", redacted)
                self.assertNotIn("C:/Users/sam/Unweave/Projects", redacted)

    def test_noop_without_root(self):
        self.assertEqual(redact_text("/tmp/x", None), "/tmp/x")


class TrimLogTests(unittest.TestCase):
    def test_keeps_tail_by_line_count(self):
        lines = [f"line-{i}" for i in range(200)]
        trimmed = trim_log_lines(lines, max_lines=10, max_bytes=10_000)
        self.assertEqual(trimmed, lines[-10:])

    def test_keeps_tail_by_byte_cap(self):
        lines = ["x" * 100 for _ in range(20)]
        trimmed = trim_log_lines(lines, max_lines=80, max_bytes=250)
        self.assertLessEqual(sum(len(line) + 1 for line in trimmed), 250)
        self.assertEqual(trimmed[-1], lines[-1])
        self.assertLess(len(trimmed), len(lines))

    def test_defaults_match_spec_caps(self):
        self.assertEqual(LOG_LINE_CAP, 80)
        self.assertEqual(LOG_BYTE_CAP, 32 * 1024)


class BuildTextTests(unittest.TestCase):
    def test_bundle_shape_and_redaction(self):
        root = Path("/data/projects")
        text = build_diagnostics_text(
            version="1.5.5",
            platform_name="windows",
            arch="AMD64",
            python_version="3.11.9",
            utc_now=datetime(2026, 11, 3, 10, 0, tzinfo=timezone.utc),
            setup_stages=[
                {"id": "runtime", "done": True, "missing": False},
                {"id": "ffmpeg", "done": False, "missing": True},
                {"id": "separation", "done": True, "missing": False},
                {"id": "youtube", "done": True, "missing": False},
            ],
            job={"kind": "setup", "status": "failed",
                 "error": f"urlopen failed for {root / 'tmp'}"},
            log_lines=[f"Downloading into {root / 'cache'}", "SSL expired"],
            projects_root=root,
        )
        self.assertIn("=== Unweave diagnostics ===", text)
        self.assertIn("App version: 1.5.5", text)
        self.assertIn("Platform: windows", text)
        self.assertIn("Setup: runtime=ok ffmpeg=missing separation=ok youtube=ok", text)
        self.assertIn("Last job: kind=setup status=failed error=", text)
        self.assertIn("<projects>", text)
        self.assertNotIn("/data/projects", text)
        self.assertIn("SSL expired", text)
        self.assertTrue(text.endswith("=== end ===\n"))


class LibraryDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        base = Path(self.temporary.name)
        self.root = base / "projects"
        self.root.mkdir()
        self.library = Library(self.root, base / "ui.json", base / "cache",
                               default_root=self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def test_diagnostics_endpoint_payload(self):
        job = {
            "id": "abc123", "kind": "separation", "status": "failed",
            "error": f"boom at {self.root / 'song'}", "project": "song",
        }
        self.library.finished_jobs.append(job)
        self.library._job_logs("abc123").extend([
            f"path {self.root / 'song' / 'original.wav'}",
            "Separation CLI exited with code 3221225477",
        ])
        payload = self.library.diagnostics()
        self.assertIn("text", payload)
        text = payload["text"]
        self.assertIn("kind=separation", text)
        self.assertIn("3221225477", text)
        self.assertIn("<projects>", text)
        self.assertNotIn(str(self.root), text)

    def test_diagnostics_by_job_id(self):
        older = {"id": "old", "kind": "setup", "status": "failed", "error": "old"}
        newer = {"id": "new", "kind": "export", "status": "failed", "error": "new"}
        self.library.finished_jobs.append(older)
        self.library.finished_jobs.append(newer)
        text = self.library.diagnostics(job_id="old")["text"]
        self.assertIn("kind=setup", text)
        self.assertIn("error=old", text)


if __name__ == "__main__":
    unittest.main()
