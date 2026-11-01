"""Parse CLI/stderr progress lines into job percent and ETA fields."""

import re
import time

# tqdm bars from audio-separator, e.g. " 45%|████▌     | 23/51 [00:12<00:15,  1.80it/s]"
TQDM = re.compile(r"(\d{1,3})%\|[^|]*\|[^\[]*\[([\d:]+)<([\d:]+|\?)")
GUITAR_PROGRESS = re.compile(r"^Guitar split (\d{1,3})%")
# (marker printed by the CLI, phase, overall progress when the phase starts)
# Prepare/load are short on a warm run — keep their floors small so inference owns the bar.
PHASE_MARKERS = (("Preparing audio", "prepare", 1), ("Loading model", "load", 3),
                 ("Downloading ", "download", 3), ("Separating with", "separate", 5),
                 ("Splitting guitar", "guitar", 5), ("Writing stems", "finalize", 96),
                 ("Exporting stems", "export", 2), ("Exported ", "finalize", 96))
# Overall job.progress maps measured inference elapsed/(elapsed+ETA) into this band.
# step_progress (detail ring) stays 0-100 per pass and does not use this range.
SEPARATE_RANGE = (5, 95)
# Prior only: used to project the not-yet-started guitar pass while Demucs is running.
# Once the guitar pass reports timing, real elapsed/ETA replace this ratio.
GUITAR_TIME_RATIO = 10.0
FINALIZE_FUDGE = 3.0  # writing stems afterwards takes a few seconds
YTDLP_PROGRESS = re.compile(r"\[download\]\s+([\d.]+)%(?:.*ETA\s+([\d:]+))?")


def clock_seconds(text: str):
    try:
        parts = [int(part) for part in text.split(":")]
    except ValueError:
        return None
    total = 0
    for part in parts:
        total = total * 60 + part
    return total


def lock_demucs_elapsed(job: dict):
    """Remember how long the stem pass took before the guitar sample clock resets."""
    if not job.get("split_leaves") or job.get("demucs_elapsed") is not None:
        return
    start = job.get("sample_started") or job.get("phase_started") or job.get("started")
    if start is None:
        job["demucs_elapsed"] = 0.0
        return
    job["demucs_elapsed"] = max(0.0, time.time() - start)


def apply_time_weighted_progress(job: dict, percent: int, spent: float,
                                 remaining: float, guitar: bool):
    """Map overall progress from inference elapsed/(elapsed+remaining).

    While Demucs is running and a guitar pass is still queued, project that
    pass with GUITAR_TIME_RATIO (prior only). Once the guitar pass has a
    usable wall clock, measured Demucs duration + live guitar remaining
    replace the ratio. The first guitar ticks often have spent≈0 (sample
    clock just reset), so keep the prior until spent is meaningful.
    """
    low, high = SEPARATE_RANGE
    split = bool(job.get("split_leaves"))
    on_guitar = guitar or job.get("phase") == "guitar"
    spent = max(0.0, spent)
    remaining = max(0.0, remaining)

    # step_eta is pass-local remaining (no finalize fudge). eta stays whole-job.
    # eta_estimated is True while the guitar prior still pads the whole-job ETA.
    if on_guitar and split:
        demucs_elapsed = float(job.get("demucs_elapsed") or 0.0)
        if spent >= 1.0 and percent > 0:
            done, left = demucs_elapsed + spent, remaining
            step_left, eta_estimated = remaining, False
        elif percent > 0 and demucs_elapsed > 0:
            est_guitar = demucs_elapsed * GUITAR_TIME_RATIO
            done = demucs_elapsed + est_guitar * (percent / 100.0)
            left = est_guitar * (1.0 - percent / 100.0)
            step_left, eta_estimated = left, True
        else:
            done, left = demucs_elapsed, demucs_elapsed * GUITAR_TIME_RATIO
            step_left, eta_estimated = left, True
    elif on_guitar:
        # Split-only: one pass owns the whole inference band (no Demucs prior).
        done, left = spent, remaining
        step_left, eta_estimated = remaining, False
    elif split:
        if percent > 0:
            est_demucs_total = spent / (percent / 100.0)
        else:
            est_demucs_total = spent
        prior_guitar = est_demucs_total * GUITAR_TIME_RATIO
        done, left = spent, remaining + prior_guitar
        step_left, eta_estimated = remaining, True
        if percent >= 100:
            job["demucs_elapsed"] = max(float(job.get("demucs_elapsed") or 0.0), spent)
    else:
        done, left = spent, remaining
        step_left, eta_estimated = remaining, False

    total = done + left
    last_pass_done = percent >= 100 and not (split and not on_guitar)
    if last_pass_done:
        mapped = high
    elif total > 0:
        mapped = low + (high - low) * (done / total)
    else:
        mapped = low
    job["progress"] = max(job["progress"], min(high, mapped))
    job["eta"] = left + FINALIZE_FUDGE
    job["eta_at"] = time.time()
    job["step_eta"] = step_left
    job["step_eta_at"] = time.time()
    job["eta_estimated"] = eta_estimated


def track_progress(job: dict, line: str) -> bool:
    """Update a job's phase/progress/ETA from a CLI output line.
    True hides the line from the UI log."""
    for marker, phase, floor in PHASE_MARKERS:
        if line.startswith(marker):
            job["phase"] = phase
            job["progress"] = max(job["progress"], floor)
            # Every step owns its own 0-100: the dialog's ring restarts for the
            # guitar pass instead of counting one global bar, so a long second
            # pass is visibly its own stage rather than a stalled first one.
            # Only stages that report real sub-progress reset the ring; prepare/
            # load/save keep the finished value so it never jumps back to 0.
            if phase in {"separate", "guitar", "download", "export"}:
                job["step_progress"] = 0
                job["step_eta"] = None
            if phase == "guitar":
                lock_demucs_elapsed(job)
                job["pass_index"] = max(int(job.get("pass_index") or 1), 2)
                job["progress"] = max(job["progress"], SEPARATE_RANGE[0])
            if phase in {"separate", "guitar"}:
                job["phase_started"] = time.time()
            if phase in {"finalize", "download"}:
                job["eta"] = None
                job["step_eta"] = None
            return False
    bar = TQDM.search(line)
    guitar = GUITAR_PROGRESS.match(line)
    step = bar or guitar
    if not step:
        return False
    if job["phase"] in {"separate", "guitar"}:
        # Time the ETA extrapolation from the start of *this* pass. Measuring from
        # the start of the phase made the guitar pass inherit the whole Demucs run:
        # at 15% of the split it reported that Demucs' minutes had to be repeated
        # for the remaining 85%, so TIME LEFT swelled to ~12 minutes.
        sample = "guitar" if guitar else "demucs"
        if job.get("sample") != sample:
            if sample == "guitar":
                lock_demucs_elapsed(job)
            job["sample"] = sample
            job["sample_started"] = time.time()
        percent = min(100, int(step.group(1)))
        job["step_progress"] = max(job.get("step_progress") or 0, percent)
        bar_elapsed = clock_seconds(bar.group(2)) if bar else None
        spent = bar_elapsed if bar_elapsed is not None else (
            time.time() - job.get("sample_started", job["started"]))
        remaining = clock_seconds(bar.group(3)) if bar else None
        if remaining is None and percent:
            remaining = spent * (100 - percent) / percent
        if remaining is not None:
            apply_time_weighted_progress(job, percent, spent, remaining, bool(guitar))
    return True
