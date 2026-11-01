import io
import stat
import sys
import tarfile
import tempfile
import threading
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest.mock import patch

from unweave import setup_env


class SetupHealthTests(unittest.TestCase):
    def test_binary_ok_rejects_missing_empty_and_zeroed_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "library.dll"
            self.assertFalse(setup_env._binary_ok(path, 16))
            path.write_bytes(b"MZ")
            self.assertFalse(setup_env._binary_ok(path, 16))
            path.write_bytes(b"\0" * 64)
            self.assertFalse(setup_env._binary_ok(path, 16))
            path.write_bytes(b"MZ" + b"\0" * 62)
            self.assertTrue(setup_env._binary_ok(path, 16))

    @unittest.skipUnless(sys.platform == "win32", "Windows torch layout")
    def test_torch_ok_detects_zeroed_install(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "torch"
            (root / "lib").mkdir(parents=True)
            (root / "__init__.py").write_text("", encoding="utf-8")
            files = {
                root / "lib" / "torch_cpu.dll": 10 * 1024 * 1024,
                root / "lib" / "torch_python.dll": 1024 * 1024,
                root / "_C.cp311-win_amd64.pyd": 1024,
            }
            for path, size in files.items():
                with path.open("wb") as stream:
                    stream.write(b"MZ")
                    stream.truncate(size)
            with patch.object(setup_env, "_package_dir", return_value=root):
                self.assertTrue(setup_env.torch_ok())
                (root / "lib" / "torch_python.dll").write_bytes(b"\0" * (1024 * 1024))
                self.assertFalse(setup_env.torch_ok())

    def test_ffmpeg_url_is_platform_specific(self):
        with patch.object(setup_env.sys, "platform", "linux"):
            self.assertTrue(setup_env.ffmpeg_url().endswith(".tar.xz"))
        with patch.object(setup_env.sys, "platform", "win32"):
            self.assertTrue(setup_env.ffmpeg_url().endswith(".zip"))

    def test_host_arch_ok_rejects_arm_linux(self):
        with patch.object(setup_env.sys, "platform", "linux"), \
                patch.object(setup_env.platform, "machine", return_value="aarch64"):
            self.assertFalse(setup_env._host_arch_ok())
        with patch.object(setup_env.sys, "platform", "linux"), \
                patch.object(setup_env.platform, "machine", return_value="x86_64"):
            self.assertTrue(setup_env._host_arch_ok())
        # Non-Linux platforms are always fine — the guard is about the static build.
        with patch.object(setup_env.sys, "platform", "win32"), \
                patch.object(setup_env.platform, "machine", return_value="ARM64"):
            self.assertTrue(setup_env._host_arch_ok())

    @staticmethod
    def _tarball(path, names):
        with tarfile.open(path, "w:xz") as archive:
            for name in names:
                payload = b"\x7fELF fake"
                info = tarfile.TarInfo(f"ffmpeg-7.0.2-amd64-static/{name}")
                info.size = len(payload)
                info.mode = 0o644
                archive.addfile(info, io.BytesIO(payload))

    def test_extract_ffmpeg_tar_sets_executable_bit(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            archive = work / "ffmpeg.tar.xz"
            self._tarball(archive, ["ffmpeg", "ffprobe"])
            install = work / "install"
            install.mkdir()
            setup_env._extract_ffmpeg_tar(archive, install)
            for name in ("ffmpeg", "ffprobe"):
                target = install / name
                self.assertTrue(target.is_file())
                self.assertTrue(target.stat().st_mode & stat.S_IXUSR)

    def test_extract_ffmpeg_tar_rejects_incomplete_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            archive = work / "ffmpeg.tar.xz"
            self._tarball(archive, ["ffmpeg"])  # ffprobe missing
            install = work / "install"
            install.mkdir()
            with self.assertRaises(RuntimeError) as caught:
                setup_env._extract_ffmpeg_tar(archive, install)
            self.assertIn("ffprobe", str(caught.exception))

    def test_pip_repair_falls_back_when_record_is_unreadable(self):
        class FakeProcess:
            def __init__(self, lines, code):
                self.stdout = iter(lines)
                self.code = code

            def poll(self):
                return self.code

            def wait(self):
                return self.code

            def kill(self):
                pass

            def terminate(self):
                pass

        library = SimpleNamespace(lock=threading.Lock(), logs=[], process=None,
                                  job={"status": "running"})
        processes = [
            FakeProcess(["Collecting torch", "ERROR: field larger than field limit (131072)"], 1),
            FakeProcess(["Successfully installed torch-2.14.1"], 0),
        ]
        commands = []

        def fake_popen(command, **kwargs):
            commands.append(command)
            return processes.pop(0)

        with patch.object(setup_env.subprocess, "Popen", side_effect=fake_popen):
            progress = setup_env._pip_install(library, ["torch"], "separation", 0, 50, force=True)

        self.assertEqual(progress, 50)
        self.assertIn("--force-reinstall", commands[0])
        self.assertIn("--ignore-installed", commands[1])
        self.assertTrue(any("Damaged package metadata" in line for line in library.logs))

    def test_repair_reinstalls_present_ffmpeg(self):
        library = SimpleNamespace(lock=threading.Lock(), logs=[], process=None,
                                  job={"status": "running", "progress": 0})
        installs = []

        def fake_install(_library, start, band):
            installs.append("ffmpeg")
            return start + band

        with patch.object(setup_env, "ffmpeg_ok", return_value=True), \
             patch.object(setup_env, "_install_ffmpeg", side_effect=fake_install), \
             patch.object(setup_env, "_ensure_pip"), \
             patch.object(setup_env, "ensure_ffmpeg_on_path", return_value=True):
            setup_env.run_setup(library, ["ffmpeg"], repair=True)

        self.assertEqual(installs, ["ffmpeg"])
        self.assertEqual(library.job["status"], "succeeded")

    def test_repair_force_reinstalls_present_pip_stage(self):
        library = SimpleNamespace(lock=threading.Lock(), logs=[], process=None,
                                  job={"status": "running", "progress": 0})
        pip_calls = []

        def fake_pip(_library, requirements, stage, start, band, *, force=False):
            pip_calls.append({"stage": stage, "force": force, "requirements": list(requirements)})
            return start + band

        with patch.object(setup_env, "youtube_ok", return_value=True), \
             patch.object(setup_env, "ffmpeg_ok", return_value=True), \
             patch.object(setup_env, "_ensure_pip"), \
             patch.object(setup_env, "ensure_ffmpeg_on_path", return_value=True), \
             patch.object(setup_env, "_pip_install", side_effect=fake_pip), \
             patch.object(setup_env, "stage_requirements", return_value=["yt-dlp"]):
            setup_env.run_setup(library, ["youtube"], repair=True)

        self.assertEqual(len(pip_calls), 1)
        self.assertEqual(pip_calls[0]["stage"], "youtube")
        self.assertTrue(pip_calls[0]["force"])
        self.assertEqual(library.job["status"], "succeeded")

    def test_without_repair_skips_present_ffmpeg(self):
        library = SimpleNamespace(lock=threading.Lock(), logs=[], process=None,
                                  job={"status": "running", "progress": 0})

        def boom(*_args, **_kwargs):
            raise AssertionError("installer should not run when stage is already present")

        with patch.object(setup_env, "ffmpeg_ok", return_value=True), \
             patch.object(setup_env, "_install_ffmpeg", side_effect=boom):
            setup_env.run_setup(library, ["ffmpeg"], repair=False)

        self.assertEqual(library.job["status"], "succeeded")
        self.assertEqual(library.job["progress"], 100)

    def test_pip_progress_line_reports_speed(self):
        parsed = setup_env._pip_progress_from_line("  45.2/100.0 MB 12.5 MB/s eta 0:00:04")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["received"], 45_200_000)
        self.assertEqual(parsed["total"], 100_000_000)
        self.assertEqual(parsed["speed"], 12_500_000.0)
        self.assertIsNone(setup_env._pip_progress_from_line("Collecting torch"))

    def test_ffmpeg_download_reports_speed_on_job(self):
        payload = b"x" * (3 * 1024 * 1024)

        class FakeResponse:
            headers = {"Content-Length": str(len(payload))}

            def __init__(self):
                self._offset = 0

            def read(self, size):
                if self._offset >= len(payload):
                    return b""
                chunk = payload[self._offset:self._offset + size]
                self._offset += len(chunk)
                return chunk

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        library = SimpleNamespace(lock=threading.Lock(), logs=[], process=None,
                                  job={"status": "running", "progress": 0})
        seen = []
        real_tick = setup_env._tick

        def capture(library_arg, phase, stage, progress, **kwargs):
            real_tick(library_arg, phase, stage, progress, **kwargs)
            speed = library_arg.job.get("download_speed")
            if speed:
                seen.append({
                    "speed": speed,
                    "received": library_arg.job.get("download_received"),
                    "total": library_arg.job.get("download_total"),
                })

        with tempfile.TemporaryDirectory() as temporary:
            install = Path(temporary) / "ffmpeg"
            with patch.object(setup_env, "urlopen", return_value=FakeResponse()), \
                 patch.object(setup_env, "ffmpeg_url", return_value="http://example/ffmpeg.zip"), \
                 patch.object(setup_env, "_host_arch_ok", return_value=True), \
                 patch.object(setup_env, "_cancelling", return_value=False), \
                 patch.object(setup_env, "ffmpeg_dir", return_value=install), \
                 patch.object(setup_env, "_extract_ffmpeg_zip"), \
                 patch.object(setup_env, "ensure_ffmpeg_on_path", return_value=True), \
                 patch.object(setup_env, "_tick", side_effect=capture), \
                 patch.object(setup_env.time, "monotonic", side_effect=[0.0, 0.5, 1.0, 1.5, 2.0, 2.5]):
                setup_env._install_ffmpeg(library, 0, 50)

        self.assertTrue(seen, "download ticks should include a positive speed")
        self.assertGreater(seen[-1]["speed"], 0)
        self.assertEqual(seen[-1]["total"], len(payload))
        self.assertEqual(seen[-1]["received"], len(payload))
        # After extract, download_* fields are cleared so the install phase
        # does not keep a stale MB/s.
        self.assertNotIn("download_speed", library.job)


if __name__ == "__main__":
    unittest.main()
