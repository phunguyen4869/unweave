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



if __name__ == "__main__":
    unittest.main()
