import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from unweave.audio import pipeline
from unweave.webui.library import (FINALIZE_FUDGE, GUITAR_TIME_RATIO, JobLog, Library,
                                        SEPARATE_RANGE, prune_job_logs)


class JobQueueTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        base = Path(self.temporary.name)
        with mock.patch.dict(os.environ, {"UNWEAVE_MAX_CONCURRENT_JOBS": "2"}):
            self.library = Library(base / "projects", base / "ui.json", base / "cache")
        self.release = {}

    def tearDown(self):
        for event in self.release.values():
            event.set()
        deadline = time.time() + 5
        while self.library.running() and time.time() < deadline:
            time.sleep(0.01)
        self.temporary.cleanup()

    def fake_separate(self, job, *args, **kwargs):
        """Stand-in worker: reports progress on its own record, then waits to be released."""
        try:
            with self.library.lock:
                job["progress"] = 50
            self.release[job["project"]].wait(5)
            with self.library.lock:
                job.update(status="succeeded", progress=100)
        finally:
            with self.library.lock:
                self.library._finish(job)

    def enqueue(self, project):
        self.release[project] = threading.Event()
        job = {"id": project + "-job", "kind": "separate", "project": project, "status": "queued",
               "started": time.time(), "finished": None, "error": None, "progress": 0,
               "_project": Path(project), "_original": "original.wav", "_stems": ["vocals"],
               "_guitar_split": False, "_trim": None}
        with self.library.lock:
            return self.library._enqueue(job)

    def wait_for(self, predicate):
        deadline = time.time() + 5
        while time.time() < deadline:
            with self.library.lock:
                if predicate():
                    return
            time.sleep(0.01)
        self.fail("condition not reached")

    def statuses(self):
        state = self.library.state()
        jobs = {job["id"]: job for job in state["jobs"] + state["finished_jobs"]}
        return {job_id: job["status"] for job_id, job in jobs.items()}

    def test_concurrent_jobs_keep_their_own_status(self):
        with mock.patch.object(Library, "_separate", self.fake_separate):
            self.enqueue("a")
            self.enqueue("b")
            self.wait_for(lambda: len(self.library.active) == 2)
            # The first job finishes while the second is still running.
            self.release["a"].set()
            self.wait_for(lambda: "a-job" not in self.library.active)
            statuses = self.statuses()
            self.assertEqual(statuses["a-job"], "succeeded")
            self.assertEqual(statuses["b-job"], "running")
            self.release["b"].set()
            self.wait_for(lambda: not self.library.running())
            self.assertEqual(self.statuses()["b-job"], "succeeded")

    def test_state_is_json_serializable_while_jobs_queued(self):
        with mock.patch.object(Library, "_separate", self.fake_separate):
            self.assertNotIn("_project", self.enqueue("a"))
            self.enqueue("b")
            self.enqueue("c")
            self.wait_for(lambda: len(self.library.active) == 2)
            json.dumps(self.library.state())

    def test_same_project_jobs_never_overlap(self):
        with mock.patch.object(Library, "_separate", self.fake_separate):
            self.enqueue("a")
            self.wait_for(lambda: len(self.library.active) == 1)
            second = {"id": "a-second", "kind": "separate", "project": "a", "status": "queued",
                      "started": time.time(), "finished": None, "error": None, "progress": 0,
                      "_project": Path("a"), "_original": "original.wav", "_stems": ["vocals"],
                      "_guitar_split": False, "_trim": None}
            with self.library.lock:
                self.library._enqueue(second)
            self.enqueue("b")
            self.wait_for(lambda: "b-job" in self.library.active)
            self.assertNotIn("a-second", self.library.active)


class ProgressTrackingTests(unittest.TestCase):
    """Overall progress is elapsed/(elapsed+ETA) over SEPARATE_RANGE. A ~10× prior
    projects the guitar pass only while Demucs is still running; once guitar reports
    timing, measured Demucs duration + live guitar ETA own the bar."""

    def job(self, split_leaves):
        return {"kind": "separate", "split_leaves": split_leaves, "status": "running",
                "started": time.time(), "phase": "prepare", "progress": 0, "eta": None,
                "step_progress": 0, "step_eta": None, "step_eta_at": None,
                "eta_estimated": False, "pass_count": 2 if split_leaves else 1,
                "pass_index": 1}

    def progress(self, job, lines):
        library = object.__new__(Library)
        seen = []
        for line in lines:
            library._track_progress(job, line)
            seen.append(job["progress"])
        return seen

    def test_prepare_and_load_floors_stay_small(self):
        job = self.job(True)
        self.progress(job, ["Preparing audio", "Loading model"])
        self.assertLess(job["progress"], SEPARATE_RANGE[0] + 1)

    def test_demucs_eta_includes_projected_guitar(self):
        job = self.job(True)
        self.progress(job, [
            "Separating with htdemucs_6s.yaml; model outputs: vocals",
            " 50%|##| 20/40 [01:00<01:00, 3.0s/it]",
        ])
        demucs_only = 60.0  # tqdm remaining
        self.assertGreater(job["eta"], demucs_only + FINALIZE_FUDGE)
        # Prior: est_demucs_total (120s) * GUITAR_TIME_RATIO
        self.assertGreater(job["eta"], demucs_only + 100)
        # Detail panel shows pass-local remaining; whole-job ETA still includes guitar.
        self.assertEqual(job["step_eta"], demucs_only)
        self.assertTrue(job["eta_estimated"])
        self.assertEqual(job["pass_count"], 2)
        self.assertEqual(job["pass_index"], 1)

    def test_after_demucs_overall_stays_low_when_guitar_will_dominate(self):
        job = self.job(True)
        self.progress(job, [
            "Separating with htdemucs_6s.yaml; model outputs: vocals",
            "100%|##| 40/40 [02:10<00:00, 3.2s/it]",
        ])
        # done/(done+10*done) → ~1/11 of the inference band ≈ 13, not the old ~70.
        self.assertLess(job["progress"], 25)
        self.assertGreater(job["progress"], SEPARATE_RANGE[0])

    def test_the_guitar_pass_advances_the_bar(self):
        job = self.job(True)
        self.progress(job, [
            "Separating with htdemucs_6s.yaml; model outputs: vocals",
            "100%|##| 40/40 [02:10<00:00, 3.2s/it]",
            "Splitting guitar",
        ])
        job["demucs_elapsed"] = 130.0
        after_demucs = job["progress"]
        # Prior-based guitar ticks until the pass has a real wall clock.
        seen = self.progress(job, [f"Guitar split {n}%" for n in (25, 50, 75, 100)])
        self.assertEqual(seen, sorted(seen), "progress must never go backwards")
        self.assertGreater(seen[-1] - after_demucs, 40,
                           f"guitar should own most of the bar: {after_demucs} → {seen}")
        self.assertEqual(seen[-1], SEPARATE_RANGE[1])

    def test_mid_guitar_is_not_stuck_near_old_fixed_band(self):
        job = self.job(True)
        self.progress(job, [
            "Separating with htdemucs_6s.yaml; model outputs: vocals",
            "100%|##| 40/40 [02:10<00:00, 3.2s/it]",
            "Splitting guitar",
        ])
        job["demucs_elapsed"] = 130.0
        # Cold guitar clock (spent≈0) uses the ~10× prior until wall time is usable.
        self.progress(job, ["Guitar split 30%"])
        # done=130+0.3*1300, left=0.7*1300 → ~37% of the band, not the old ~77.
        self.assertLess(job["progress"], 55)
        self.assertGreater(job["progress"], 30)
        self.assertEqual(job["step_progress"], 30)

    def test_without_a_split_the_whole_bar_belongs_to_the_model(self):
        job = self.job(False)
        seen = self.progress(job, [
            "Separating with htdemucs_6s.yaml; model outputs: vocals",
            "100%|##| 40/40 [02:10<00:00, 3.2s/it]",
        ])
        self.assertEqual(seen[-1], SEPARATE_RANGE[1])
        self.assertFalse(job["eta_estimated"])
        self.assertEqual(job["pass_count"], 1)

    def test_each_step_owns_its_own_percentage(self):
        # The dialog's ring restarts per step, so a 10x guitar pass starts at 0 again.
        job = self.job(True)
        self.progress(job, [
            "Separating with htdemucs_6s.yaml; model outputs: vocals",
            " 60%|##| 24/40 [01:00<00:40, 2.5s/it]",
        ])
        self.assertGreater(job["step_progress"], 50)
        demucs_overall = job["progress"]
        self.progress(job, ["Splitting guitar"])
        self.assertEqual(job["step_progress"], 0, "the split must start its own gauge")
        self.assertIsNone(job["step_eta"])
        self.assertEqual(job["pass_index"], 2)
        job["demucs_elapsed"] = 100.0
        self.progress(job, ["Guitar split 30%"])
        self.assertEqual(job["step_progress"], 30)
        self.assertGreater(job["progress"], demucs_overall, "the overall bar keeps climbing")
        self.assertTrue(job["eta_estimated"], "cold guitar clock still uses the prior")
        self.assertIsNotNone(job["step_eta"])
        self.assertLess(job["step_eta"], job["eta"])

    def test_saving_stems_does_not_reset_the_ring(self):
        # "Writing stems" has no sub-progress; resetting there made the ring snap from
        # 100% back to 0% for the last second of every job.
        job = self.job(True)
        job["demucs_elapsed"] = 60.0
        self.progress(job, ["Splitting guitar", "Guitar split 100%", "Writing stems"])
        self.assertEqual(job["step_progress"], 100)

    def test_the_guitar_pass_is_its_own_phase(self):
        job = self.job(True)
        self.progress(job, [
            "Separating with htdemucs_6s.yaml; model outputs: vocals",
            "100%|##| 40/40 [02:10<00:00, 3.2s/it]",
        ])
        self.assertEqual(job["phase"], "separate")
        self.progress(job, ["Splitting guitar", "Guitar split 50%"])
        self.assertEqual(job["phase"], "guitar")

    def test_a_split_only_job_starts_its_bar_low(self):
        # No Demucs pass — no 10× prior against a phantom stem pass.
        job = self.job(False)
        job["kind"] = "split-guitar"
        self.progress(job, ["Splitting guitar", "Guitar split 0%"])
        self.assertEqual(job["phase"], "guitar")
        self.assertLess(job["progress"], 20)
        self.assertNotIn("demucs_elapsed", job)

    def test_guitar_eta_uses_live_timing_once_the_clock_is_warm(self):
        job = self.job(True)
        self.progress(job, [
            "Separating with htdemucs_6s.yaml; model outputs: vocals",
            "100%|##| 40/40 [02:10<00:00, 3.2s/it]",
            "Splitting guitar",
        ])
        job["demucs_elapsed"] = 130.0
        self.progress(job, ["Guitar split 1%"])  # establishes sample_started
        job["sample_started"] = time.time() - 130.0
        self.progress(job, ["Guitar split 50%"])
        # Live remaining ≈ 130s + finalize — not another full 10× demucs prior.
        self.assertLess(job["eta"], 130.0 * GUITAR_TIME_RATIO)
        self.assertGreater(job["eta"], 100.0)
        self.assertFalse(job["eta_estimated"])
        self.assertAlmostEqual(job["step_eta"], job["eta"] - FINALIZE_FUDGE, places=3)

    def test_writing_stems_is_announced_only_after_the_split(self):
        # Ordering in the CLI: the marker that jumps the bar to 96 must come last,
        # which is what pipeline.separate() guarantees by printing it after the split.
        source = Path(pipeline.__file__).read_text(encoding="utf-8")
        writing = source.index('print("Writing stems"')
        split = source.index("_run_guitar_split(by_stem, stage, cache)")
        self.assertLess(split, writing)


class JobLogTests(unittest.TestCase):
    """A cancelled job must leave a trace: the in-memory log dies with the server
    process and drops progress lines, so debugging needed a file."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.job = {"id": "abc123", "kind": "separate", "project": "song",
                    "started": time.time(), "status": "running"}

    def tearDown(self):
        self.temporary.cleanup()

    def test_every_line_including_hidden_progress_is_written(self):
        log = JobLog(self.base, self.job, ["python", "-m", "unweave", "separate"])
        log.write("Separating with htdemucs_6s.yaml")
        log.write("Guitar split 50%")   # hidden from the UI log, kept here
        log.close("cancelled")
        text = log.path.read_text(encoding="utf-8")
        self.assertIn("-m unweave separate", text)
        self.assertIn("Guitar split 50%", text)
        self.assertIn("# status   cancelled", text)

    def test_the_path_is_exposed_on_the_job(self):
        log = JobLog(self.base, self.job, ["x"])
        log.close("succeeded")
        self.assertEqual(self.job["log"], str(log.path))

    def test_an_unwritable_directory_never_breaks_the_run(self):
        blocked = self.base / "file"
        blocked.write_text("not a directory", encoding="utf-8")
        log = JobLog(blocked / "logs", self.job, ["x"])
        log.write("line")     # must be a silent no-op
        log.close("failed", "boom")
        self.assertIsNone(log.handle)
        self.assertNotIn("log", self.job)

    def test_old_logs_are_pruned(self):
        for index in range(5):
            (self.base / f"{index}.log").write_text("x", encoding="utf-8")
        prune_job_logs(self.base, keep=2)
        self.assertEqual(len(list(self.base.glob("*.log"))), 2)


if __name__ == "__main__":
    unittest.main()
