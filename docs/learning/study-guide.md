# Unweave — Condensed technical study guide

**Prefer the all-in-one NotebookLM source:** [`notebooklm-pack.md`](notebooklm-pack.md).

Upload that single file (or its raw GitHub URL) and say `Start tutoring`.
This short guide remains as a quick human-readable cheat sheet.

## One-sentence definition

Unweave is a **local** desktop stem separator: Python runs Demucs/MDX/RoFormer on your
machine, a stdlib HTTP server exposes a job API on loopback, and a vanilla-JS UI
(inside pywebview) drives import → separate → mix → export.

## Layers

```
Web UI  --poll /api/state-->  HTTP server  -->  Job queue
                                                    | stream stderr
                                                    v
                                              python -m unweave
                                                    |
                                                    v
                                         FFmpeg · PyTorch · ONNX
                                                    |
                                                    v
                                         project stems/ (atomic)
```

- Worker → queue: **stream**
- UI → server: **poll** (~1 s busy)

## Models

| Request | Model | Backend |
|---|---|---|
| Vocals + instrumental only | `UVR_MDXNET_KARA_2` | ONNX |
| Any other multi-stem plan | `htdemucs_6s` | PyTorch |
| Guitar lead/rhythm | RoFormer checkpoint | PyTorch |

## Design rules (short)

Atomic publish · one multi-stem model · compute-then-drop · scratch in staging ·
kill process tree · free-space check · dual progress · job logs · leave a core free ·
UI never imports torch.

## Key files

`audio/pipeline.py` · `guitar_split.py` · `model_cache.py` · `webui/library.py` ·
`webui/server.py` · `setup_env.py` · `web/js/app.js`
