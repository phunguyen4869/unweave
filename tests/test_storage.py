"""Settings storage cleanup (spec 07 / 12): clear models and per-project exports."""

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from unweave.fsutil import dir_bytes, is_link_like
from unweave.webui.library import Library


class DirBytesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_sums_files_and_skips_symlinks(self):
        folder = self.root / "cache"
        folder.mkdir()
        (folder / "a.bin").write_bytes(b"12345")
        nested = folder / "nested"
        nested.mkdir()
        (nested / "b.bin").write_bytes(b"abcdef")
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "secret.bin").write_bytes(b"xxxxxxxx")
        link = folder / "link-out"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        self.assertTrue(is_link_like(link))
        self.assertEqual(dir_bytes(folder), 11)

    def test_skips_reparse_point_entries(self):
        folder = self.root / "cache"
        folder.mkdir()
        (folder / "kept.bin").write_bytes(b"abc")
        linked = folder / "linked"
        with mock.patch("unweave.fsutil.is_link_like", side_effect=lambda path: path == linked or path.is_symlink()):
            # Pretend linked is a junction; dir_bytes must not require it to exist.
            linked.mkdir()
            (linked / "secret.bin").write_bytes(b"xxxxxxxx")
            self.assertEqual(dir_bytes(folder), 3)


class StorageCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        base = Path(self.temporary.name)
        self.projects = base / "projects"
        self.projects.mkdir()
        self.cache = base / "models"
        self.cache.mkdir()
        self.config = base / "ui.json"
        self.library = Library(self.projects, self.config, self.cache, default_root=self.projects)

    def tearDown(self):
        self.temporary.cleanup()

    def _make_project(self, name="Song One", *, with_exports=True):
        project = self.projects / name
        project.mkdir()
        (project / "original.wav").write_bytes(b"original-audio")
        stems = project / "stems"
        stems.mkdir()
        (stems / "vocals.flac").write_bytes(b"vocals-stem-data")
        (project / "metadata.json").write_text(
            json.dumps({"title": name, "original_file": "original.wav"}), encoding="utf-8"
        )
        exports_bytes = 0
        if with_exports:
            exports = project / "exports"
            exports.mkdir()
            (exports / "vocals.mp3").write_bytes(b"export-copy-bytes")
            (exports / "manifest.json").write_text("{}", encoding="utf-8")
            exports_bytes = (exports / "vocals.mp3").stat().st_size + (exports / "manifest.json").stat().st_size
        return project, exports_bytes

    def test_storage_info_reports_models_and_projects(self):
        (self.cache / "model.ckpt").write_bytes(b"x" * 100)
        project, exports_bytes = self._make_project()
        info = self.library.storage_info()
        self.assertEqual(info["models_bytes"], 100)
        self.assertEqual(info["models_path"], str(self.cache.resolve()))
        self.assertEqual(len(info["projects"]), 1)
        entry = info["projects"][0]
        self.assertEqual(entry["id"], project.name)
        self.assertEqual(entry["exports_bytes"], exports_bytes)
        self.assertGreater(entry["bytes"], exports_bytes)
        self.assertEqual(info["projects_bytes"], entry["bytes"])

    def test_storage_info_releases_lock_while_sizing(self):
        (self.cache / "model.ckpt").write_bytes(b"x" * 20)
        self._make_project()
        seen = {"free": False}

        def checking_dir_bytes(path):
            acquired = self.library.lock.acquire(blocking=False)
            if acquired:
                seen["free"] = True
                self.library.lock.release()
            return 7

        with mock.patch("unweave.webui.settings.dir_bytes", side_effect=checking_dir_bytes), \
             mock.patch("unweave.fsutil.dir_bytes", side_effect=checking_dir_bytes):
            info = self.library.storage_info()
        self.assertTrue(seen["free"])
        self.assertEqual(info["models_bytes"], 7)
        self.assertEqual(info["projects"][0]["bytes"], 7)

    def test_clear_models_removes_cache_only(self):
        (self.cache / "model.ckpt").write_bytes(b"x" * 50)
        nested = self.cache / "subdir"
        nested.mkdir()
        (nested / "other.bin").write_bytes(b"yyyy")
        project, _ = self._make_project()
        result = self.library.clear_models()
        self.assertTrue(result["ok"])
        self.assertEqual(result["models_bytes"], 0)
        self.assertGreater(result["freed_bytes"], 0)
        self.assertTrue(self.cache.is_dir())
        self.assertEqual(list(self.cache.iterdir()), [])
        self.assertTrue((project / "original.wav").is_file())
        self.assertTrue((project / "stems" / "vocals.flac").is_file())

    def test_clear_models_refuses_while_job_runs(self):
        (self.cache / "model.ckpt").write_bytes(b"model")
        release = threading.Event()

        def fake_separate(_library, job, *args, **kwargs):
            try:
                with self.library.lock:
                    job["progress"] = 50
                release.wait(5)
                with self.library.lock:
                    job.update(status="succeeded", progress=100)
            finally:
                with self.library.lock:
                    self.library._finish(job)

        with mock.patch.object(Library, "_separate", fake_separate):
            job = {
                "id": "busy-job", "kind": "separate", "project": "Song",
                "status": "queued", "started": time.time(), "finished": None,
                "error": None, "progress": 0,
                "_project": self.projects / "Song", "_original": "original.wav",
                "_stems": ["vocals"], "_guitar_split": False, "_trim": None,
            }
            with self.library.lock:
                self.library._enqueue(job)
            deadline = time.time() + 5
            while time.time() < deadline and "busy-job" not in self.library.active:
                time.sleep(0.01)
            with self.assertRaisesRegex(ValueError, "Wait for the current job"):
                self.library.clear_models()
            release.set()
            deadline = time.time() + 5
            while self.library.running() and time.time() < deadline:
                time.sleep(0.01)
        self.assertTrue((self.cache / "model.ckpt").is_file())

    def test_clear_exports_removes_only_exports(self):
        project, exports_bytes = self._make_project()
        result = self.library.clear_exports(project.name, str(self.library.root))
        self.assertTrue(result["ok"])
        self.assertEqual(result["freed_bytes"], exports_bytes)
        self.assertFalse((project / "exports").exists())
        self.assertTrue((project / "original.wav").is_file())
        self.assertTrue((project / "stems" / "vocals.flac").is_file())
        self.assertTrue((project / "metadata.json").is_file())

    def test_clear_exports_refuses_while_project_job_runs(self):
        project, _ = self._make_project()
        release = threading.Event()

        def fake_export(_library, job, *args, **kwargs):
            try:
                release.wait(5)
                with self.library.lock:
                    job.update(status="succeeded", progress=100)
            finally:
                with self.library.lock:
                    self.library._finish(job)

        with mock.patch.object(Library, "_export", fake_export):
            job = {
                "id": "export-job", "kind": "export", "project": project.name,
                "status": "queued", "started": time.time(), "finished": None,
                "error": None, "progress": 0,
                "_project": project, "_formats": ["mp3"], "_stems": ["vocals.flac"],
                "_prevent_clipping": True,
            }
            with self.library.lock:
                self.library._enqueue(job)
            deadline = time.time() + 5
            while time.time() < deadline and "export-job" not in self.library.active:
                time.sleep(0.01)
            with self.assertRaisesRegex(ValueError, "Wait for this song"):
                self.library.clear_exports(project.name, str(self.library.root))
            release.set()
            deadline = time.time() + 5
            while self.library.running() and time.time() < deadline:
                time.sleep(0.01)
        self.assertTrue((project / "exports").is_dir())


if __name__ == "__main__":
    unittest.main()
