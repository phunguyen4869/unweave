"""Group mixing: folded stems exist only inside other.flac, never on their own."""

import subprocess
import tempfile
import unittest
from pathlib import Path

from unweave.audio.pipeline import mix_stems
from unweave.tools import ensure_ffmpeg_on_path

HAVE_FFMPEG = ensure_ffmpeg_on_path()


def tone(path: Path, frequency: int) -> Path:
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "lavfi",
                    "-i", f"sine=frequency={frequency}:duration=0.4:sample_rate=44100",
                    "-c:a", "flac", str(path)], check=True, stdout=subprocess.DEVNULL)
    return path


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg is required to exercise the amix path")
class MixStemsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def peaks(self, path: Path) -> float:
        result = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-i", str(path),
                                 "-af", "volumedetect", "-f", "null", "-"],
                                capture_output=True, text=True)
        for line in result.stderr.splitlines():
            if "max_volume:" in line:
                return float(line.split("max_volume:")[1].split("dB")[0])
        raise AssertionError(f"no peak reported for {path.name}")

    def test_one_member_is_copied_without_a_mix(self):
        source = tone(self.root / "piano.flac", 440)
        destination = self.root / "other.flac"
        mix_stems([source], destination)
        self.assertTrue(destination.is_file())
        self.assertAlmostEqual(self.peaks(source), self.peaks(destination), delta=0.2)

    def test_members_sum_rather_than_average(self):
        loud = tone(self.root / "vocals.flac", 440)
        same = tone(self.root / "piano.flac", 440)
        destination = self.root / "other.flac"
        mix_stems([loud, same], destination)
        # amix with normalize=0 sums, so two identical tones are ~+6 dB.
        self.assertAlmostEqual(self.peaks(destination), self.peaks(loud) + 6.02, delta=0.4)

    def test_the_members_are_left_untouched(self):
        members = [tone(self.root / "vocals.flac", 440), tone(self.root / "piano.flac", 660)]
        before = [path.stat().st_size for path in members]
        mix_stems(members, self.root / "other.flac")
        self.assertEqual([path.stat().st_size for path in members], before)

    def test_a_missing_member_fails_loudly(self):
        present = tone(self.root / "vocals.flac", 440)
        with self.assertRaises(RuntimeError):
            mix_stems([present, self.root / "piano.flac"], self.root / "other.flac")


if __name__ == "__main__":
    unittest.main()
