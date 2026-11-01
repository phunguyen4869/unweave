"""Leftover clean-up scanner (spec 13)."""

import os
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from unweave import cleanup
from unweave.fsutil import dir_bytes, is_link_like
from unweave.webui.library import Library


def _age(path: Path, hours: float):
    when = time.time() - hours * 3600
    os.utime(path, (when, when))


class FsutilTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_dir_bytes_counts_regular_files(self):
        folder = self.root / "cache"
        folder.mkdir()
        (folder / "a.bin").write_bytes(b"12345")
        self.assertEqual(dir_bytes(folder), 5)

    def test_cloud_reparse_tag_is_not_a_link(self):
        path = self.root / "onedrive-file"
        path.write_bytes(b"cloud")
        fake = SimpleNamespace(
            st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT,
            st_reparse_tag=0x9000001A,  # IO_REPARSE_TAG_CLOUD-ish
            st_size=5,
        )
        with mock.patch("os.name", "nt"), \
             mock.patch.object(Path, "is_symlink", return_value=False), \
             mock.patch("os.path.isjunction", return_value=False, create=True), \
             mock.patch("os.stat", return_value=fake):
            self.assertFalse(is_link_like(path))

    @unittest.skipUnless(sys.platform == "win32", "Windows junctions")
    def test_real_junction_is_link_like(self):
        target = self.root / "real"
        target.mkdir()
        (target / "secret.bin").write_bytes(b"xxxxxxxx")
        link = self.root / "junction"
        code = os.system(f'cmd /c mklink /J "{link}" "{target}" >nul')
        if code != 0:
            self.skipTest("mklink /J unavailable")
        self.assertTrue(is_link_like(link))
        folder = self.root / "wrap"
        folder.mkdir()
        (folder / "kept.bin").write_bytes(b"abc")
        # Junction as child must not be sized.
        os.system(f'cmd /c mklink /J "{folder / "linked"}" "{target}" >nul')
        self.assertEqual(dir_bytes(folder), 3)


class CleanupScanTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        base = Path(self.temporary.name)
        self.temp = base / "temp"
        self.projects = base / "projects"
        self.cache = base / "models"
        self.temp.mkdir()
        self.projects.mkdir()
        self.cache.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def _old_dir(self, root: Path, name: str, payload=b"x" * 100):
        path = root / name
        path.mkdir()
        (path / "blob.bin").write_bytes(payload)
        _age(path, 30)
        return path

    def test_finds_each_pattern_location(self):
        self._old_dir(self.temp, "unweave-abc")
        self._old_dir(self.temp, "sound-razor-ffmpeg-1")
        self._old_dir(self.projects, ".separation-root")
        project = self.projects / "Song"
        project.mkdir()
        self._old_dir(project, ".exports-1")
        cover = project / ".cover-tmp.jpg"
        cover.write_bytes(b"cover-bytes")
        _age(cover, 30)
        self._old_dir(self.cache, ".model-download-1")
        result = cleanup.scan(
            projects_root=self.projects, model_cache=self.cache, temp_dir=self.temp,
            min_age_hours=24,
        )
        names = {Path(item["path"]).name for item in result["items"]}
        self.assertTrue({"unweave-abc", "sound-razor-ffmpeg-1", ".separation-root",
                         ".exports-1", ".cover-tmp.jpg", ".model-download-1"} <= names)
        self.assertGreater(result["bytes"], 0)

    def test_skips_young_items_and_nested_matches(self):
        young = self.temp / "unweave-young"
        young.mkdir()
        (young / "a").write_bytes(b"young")
        nested = self.projects / "Song" / "stems" / ".separation-deep"
        nested.mkdir(parents=True)
        (nested / "a").write_bytes(b"nested")
        _age(nested, 40)
        result = cleanup.scan(
            projects_root=self.projects, model_cache=self.cache, temp_dir=self.temp,
            min_age_hours=24,
        )
        paths = [item["path"] for item in result["items"]]
        self.assertFalse(any("unweave-young" in path for path in paths))
        self.assertFalse(any(".separation-deep" in path for path in paths))

    def test_skips_symlink_and_busy_jobs(self):
        real = self.projects / "Song"
        real.mkdir()
        (real / "original.wav").write_bytes(b"song")
        link = self.temp / "unweave-link"
        try:
            link.symlink_to(real, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        _age(link, 40)
        result = cleanup.scan(
            projects_root=self.projects, model_cache=self.cache, temp_dir=self.temp,
            min_age_hours=24,
        )
        self.assertFalse(any(item["path"] == str(link) for item in result["items"]))
        busy = cleanup.scan(
            projects_root=self.projects, model_cache=self.cache, temp_dir=self.temp,
            jobs_busy=True,
        )
        self.assertEqual(busy["count"], 0)

    def test_clean_removes_and_skips_changed(self):
        path = self._old_dir(self.temp, "unweave-gone")
        scan = cleanup.scan(
            projects_root=self.projects, model_cache=self.cache, temp_dir=self.temp,
            min_age_hours=24,
        )
        # Rename between scan and run.
        renamed = self.temp / "unweave-renamed"
        path.rename(renamed)
        _age(renamed, 30)
        result = cleanup.clean(
            None, previous=scan, projects_root=self.projects, model_cache=self.cache,
            temp_dir=self.temp, min_age_hours=24,
        )
        self.assertEqual(result["removed"], [])
        self.assertTrue(any(skip["reason"] for skip in result["skipped"]))
        self.assertTrue(renamed.is_dir())

        scan2 = cleanup.scan(
            projects_root=self.projects, model_cache=self.cache, temp_dir=self.temp,
            min_age_hours=24,
        )
        cleaned = cleanup.clean(
            None, previous=scan2, projects_root=self.projects, model_cache=self.cache,
            temp_dir=self.temp, min_age_hours=24,
        )
        self.assertIn(scan2["items"][0]["id"], cleaned["removed"])
        self.assertFalse(renamed.exists())

    def test_startup_sections_logic(self):
        none = cleanup.sections_for_startup(
            updates_should_prompt=False, cleanup_bytes=0,
            cleanup_auto=False, cleanup_dont_ask=False,
        )
        self.assertFalse(none["open"])
        both = cleanup.sections_for_startup(
            updates_should_prompt=True, cleanup_bytes=80 * 1024 * 1024,
            cleanup_auto=False, cleanup_dont_ask=False,
        )
        self.assertTrue(both["show_updates"] and both["show_cleanup"] and both["open"])
        silent = cleanup.sections_for_startup(
            updates_should_prompt=False, cleanup_bytes=10 * 1024 * 1024,
            cleanup_auto=False, cleanup_dont_ask=False,
        )
        self.assertTrue(silent["silent_cleanup"])
        self.assertFalse(silent["show_cleanup"])
        auto = cleanup.sections_for_startup(
            updates_should_prompt=False, cleanup_bytes=80 * 1024 * 1024,
            cleanup_auto=True, cleanup_dont_ask=False,
        )
        self.assertTrue(auto["silent_cleanup"])
        self.assertFalse(auto["show_cleanup"])


class DownloadCapTests(unittest.TestCase):
    def test_ffmpeg_cap_aborts_endless_stream(self):
        from unweave import setup_env

        class Endless:
            headers = {"Content-Length": "100"}

            def read(self, _n):
                return b"x" * 1024

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        library = SimpleNamespace(lock=__import__("threading").Lock(), logs=[],
                                  process=None, job={"status": "running", "progress": 0})
        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch.object(setup_env, "urlopen", return_value=Endless()), \
                 mock.patch.object(setup_env, "ffmpeg_url", return_value="http://example/ffmpeg.zip"), \
                 mock.patch.object(setup_env, "_host_arch_ok", return_value=True), \
                 mock.patch.object(setup_env, "_cancelling", return_value=False), \
                 mock.patch.object(setup_env, "_tick"), \
                 mock.patch.object(setup_env, "_log"), \
                 mock.patch.object(setup_env, "ffmpeg_dir", return_value=Path(temporary) / "ffmpeg"):
                with self.assertRaisesRegex(RuntimeError, "larger than expected"):
                    setup_env._install_ffmpeg(library, 0, 50)

    def test_model_cap_aborts_endless_stream(self):
        from unweave.audio import model_cache

        class Endless:
            headers = {"Content-Length": "2048"}

            def read(self, _n):
                return b"y" * 1024

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with tempfile.TemporaryDirectory() as temporary:
            dest = Path(temporary) / "model.bin"
            with mock.patch.object(model_cache, "urlopen", return_value=Endless()):
                with self.assertRaisesRegex(RuntimeError, "larger than expected"):
                    model_cache.cached_download("http://example/model.bin", dest)


class SeparationScratchTests(unittest.TestCase):
    def test_normalized_input_uses_output_folder(self):
        from unweave.audio import pipeline

        calls = []

        def fake_temp(*args, **kwargs):
            calls.append(kwargs)
            return tempfile.TemporaryDirectory(*args, **kwargs)

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "project" / ".separation-x" / "stems"
            output.mkdir(parents=True)
            source = Path(temporary) / "song.wav"
            source.write_bytes(b"RIFF")
            with mock.patch.object(pipeline.tempfile, "TemporaryDirectory", side_effect=fake_temp), \
                 mock.patch.object(pipeline, "require_runtime"), \
                 mock.patch.object(pipeline, "resolve_plan", return_value=("htdemucs", ("vocals",), ())), \
                 mock.patch.object(pipeline, "publish_names", return_value=("vocals",)), \
                 mock.patch.object(pipeline, "validate_outputs"), \
                 mock.patch.object(pipeline, "probe_duration", return_value=1.0), \
                 mock.patch.object(pipeline, "normalize"), \
                 mock.patch.object(pipeline, "_run_demucs", return_value={"vocals": output / "vocals.flac"}), \
                 mock.patch.object(pipeline, "_collect", return_value=[]), \
                 mock.patch.object(pipeline, "output_directory", return_value=output), \
                 mock.patch("torch.set_num_threads"):
                # _collect returning [] still runs the input TemporaryDirectory.
                try:
                    pipeline.separate(str(source), output=output, stems=["vocals"])
                except Exception:
                    pass
            input_calls = [c for c in calls if c.get("prefix") == ".unweave-input-"]
            self.assertTrue(input_calls)
            self.assertEqual(Path(input_calls[0]["dir"]), output)


class LibraryCleanupTests(unittest.TestCase):
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

    def test_sweep_removes_project_staging(self):
        project = self.projects / "Song"
        project.mkdir()
        staging = project / ".separation-old"
        staging.mkdir()
        (staging / "input.wav").write_bytes(b"x" * 50)
        _age(staging, 30)
        removed = self.library.sweep_stale_staging()
        self.assertTrue(any(".separation-old" in path for path in removed))
        self.assertFalse(staging.exists())


if __name__ == "__main__":
    unittest.main()
