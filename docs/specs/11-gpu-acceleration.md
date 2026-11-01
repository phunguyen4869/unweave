# 11 — GPU acceleration

Status: Backlog

What this covers: running separation on an NVIDIA GPU when the user has one, as an
opt-in component. Nothing here is implemented. Do not start it without an NVIDIA
machine to test on (the main dev machine has Intel UHD 730 graphics only).

## Why

Everything runs on the CPU today, on every platform:

- The guitar split (the ~10× slower second pass) is hard-coded to CPU:
  `torch.load(..., map_location='cpu')` and the model and chunks are never moved to a
  device ([`audio/guitar_split.py`](../../app/unweave/audio/guitar_split.py)). Its log
  line even says "· CPU".
- First-run setup installs `torch` from PyPI, which on Windows is a **CPU-only build**,
  so Demucs never gets CUDA either. `audio-separator` would use CUDA by itself if the
  installed torch had it.

On an NVIDIA card the guitar split could plausibly drop from minutes to well under a
minute. This is the largest remaining speed-up; it only helps users with NVIDIA GPUs.

## Scope

1. **Detection.** Offer the component only when an NVIDIA GPU and a recent enough
   driver are present (`nvidia-smi` on PATH, parse its CSV output). No offer otherwise.
2. **Opt-in setup stage.** A new optional stage in `setup_env.py` (like YouTube) that
   replaces the CPU torch with the CUDA build from the PyTorch index
   (`--index-url https://download.pytorch.org/whl/cu12x`). About 2.5 GB, so it must be
   explicit, show its size, and be removable (fall back to reinstalling CPU torch).
   `setup_env.torch_has_cuda()` already tells a CUDA build from a CPU one without
   importing torch.
3. **Device selection.** `guitar_split.py`: pick `cuda` when
   `torch.cuda.is_available()`, else `cpu`; move the model and each chunk, keep the
   overlap-add buffers where the math happens, and bring the result back to CPU before
   writing. Batch 2–4 chunks per call on GPU. Log the device instead of "CPU".
4. **Fallback.** Any CUDA error (out of memory, driver mismatch) retries the job on CPU
   once, with a log line, rather than failing the separation.
5. **Concurrency.** `_derive_max_concurrent_jobs()` currently allows 3 jobs on a CUDA
   build. Cap it by VRAM as well (two models resident per job), and divide
   `cpu_threads()` by the number of active jobs so CPU work does not oversubscribe.

## Out of scope

- Intel and AMD GPUs (DirectML, XPU, ROCm). Support for these models is patchy and on
  integrated graphics it is often no faster than the CPU. Revisit only with numbers.
- Apple Silicon (MPS): the app is not packaged for macOS.

## Acceptance

- On an NVIDIA machine: the guitar split and Demucs run on the GPU, results match the
  CPU output within float tolerance, and a forced CUDA error falls back to CPU.
- On a machine without NVIDIA: no offer, no behaviour change.
- Removing the component restores the CPU build and separation still works.

## Related

- [08 — Performance](08-performance.md) — CPU threads, the real-song benchmark.
- [05 — Job queue](05-job-queue.md) — the concurrency cap.
- [04 — First-run setup](04-first-run-setup.md) — setup stages.
- [12 — Settings panel](12-settings-panel.md) — where the component would be managed.
