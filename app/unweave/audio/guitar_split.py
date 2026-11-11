"""Reference-free lead guitar inference with the tested listra92 checkpoint."""
import contextlib
import json
import math
from pathlib import Path
import sys
import tempfile
from .model_cache import cached_download
from .output_files import validate_outputs
from .pipeline import parse_trim
from ..tools import cpu_threads

MODEL_URL = ('https://huggingface.co/noblebarkrr/mvsepless_resources/resolve/main/'
             'mel_band_roformer/mbr_lead_rhythm_guitar_listra92.ckpt')
MODEL_SHA256 = 'b3c47bca33609ca1ba0bb2d2076410bfd1eb941b051b72afc1f3e24d12b17eef'


def checkpoint(cache):
    destination = cache.expanduser().resolve() / 'lead_rhythm_listra92.ckpt'
    return cached_download(MODEL_URL, destination, MODEL_SHA256)


# Each end of a section is faded over this long so the cut makes no click.
EDGE_FADE_SECONDS = 0.005


def section_gain(frames: int, fade: int, fade_in: bool, fade_out: bool):
    """Gain applied to the section before the split: 1 inside, ramping at a cut end."""
    import numpy as np
    gain = np.ones(frames, dtype='float32')
    length = min(fade, frames)
    if length > 0:
        if fade_in:
            gain[:length] = np.linspace(0, 1, length, dtype='float32')
        if fade_out:
            gain[-length:] = np.linspace(1, 0, length, dtype='float32')
    return gain


def mute_section(guitar, start_frame: int, gain):
    """Leave a hole in the guitar where the split section was taken out, with the
    opposite fade at its ends. Lead and rhythm add up to the section times `gain`, so
    the guitar plus both of them plays back as the original guitar."""
    guitar = guitar.copy()
    guitar[start_frame:start_frame + len(gain)] *= (1 - gain)[:, None]
    return guitar


def split_guitar(source: Path, output: Path, cache: Path, trim=None,
                 replace_source: bool = False) -> list[Path]:
    """Split `source` into lead.flac and rhythm.flac in `output`.

    With `replace_source`, the split also updates the guitar stem it came from, which
    must then sit in `output`: a split of the whole stem removes it, since lead and
    rhythm add back up to it, and a section split mutes that section of it."""
    source = source.expanduser().resolve()
    output = output.expanduser().resolve()
    if not source.is_file():
        raise ValueError('Separate the guitar track first.')
    if replace_source and source.parent != output:
        raise ValueError('Replacing the guitar stem needs it inside the output folder.')
    paths = [output/'lead.flac', output/'rhythm.flac']
    settings_path = output/'separation.json'
    validate_outputs(source, paths + [settings_path])
    settings = json.loads(settings_path.read_text(encoding='utf-8')) if settings_path.exists() else {}
    if not isinstance(settings, dict):
        raise ValueError('Separation settings must contain a JSON object.')
    saved = settings.get('trim')
    base = 0.0
    if isinstance(saved, dict):
        value = saved.get('start', 0)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
            base = float(value)
    try:
        import numpy as np
        import soundfile as sf
        import torch
        from ..vendor.roformer.mel_band_roformer import MelBandRoformer
    except ImportError as error:
        raise RuntimeError('Install guitar splitting support: pip install -e ".[guitars]"') from error
    info = sf.info(source)
    duration = info.frames / info.samplerate
    local_trim = parse_trim(trim, duration, 2.0) if trim is not None else None
    fade_in = local_trim is not None and local_trim[0] > 0.0005
    fade_out = local_trim is not None and local_trim[1] < duration - 0.0005
    # A range that spans the whole stem is the whole stem: nothing is cut off.
    whole = not (fade_in or fade_out)
    start_frame, gain = 0, None
    if local_trim is not None:
        start_frame = round(local_trim[0] * info.samplerate)
        frames = min(info.frames - start_frame, round((local_trim[1] - local_trim[0]) * info.samplerate))
        mix, sr = sf.read(source, dtype='float32', always_2d=True,
                          start=start_frame, frames=max(0, frames))
        gain = section_gain(len(mix), round(EDGE_FADE_SECONDS * info.samplerate), fade_in, fade_out)
        mix *= gain[:, None]
    else:
        mix, sr = sf.read(source, dtype='float32', always_2d=True)
    if sr != 44100 or mix.shape[1] != 2 or len(mix) == 0 or not np.isfinite(mix).all():
        raise ValueError('Guitar splitting requires a nonempty, finite stereo 44.1 kHz guitar stem.')
    weights = checkpoint(cache)
    torch.set_num_threads(cpu_threads())
    torch.manual_seed(42)
    config = json.loads((Path(__file__).resolve().parents[1] / 'vendor/roformer/lead_rhythm.json').read_text(encoding='utf-8'))
    config['multi_stft_resolutions_window_sizes'] = tuple(config['multi_stft_resolutions_window_sizes'])
    with contextlib.redirect_stdout(sys.stderr):
        model = MelBandRoformer(**config)
        model.load_state_dict(torch.load(weights, map_location='cpu', weights_only=True), strict=True)
        model.eval()
    # Same batch-one overlap/add procedure as the tested MSST generic demix.
    chunk, step, fade = 132300, 66150, 13230
    length = len(mix)
    audio = torch.from_numpy(mix.T.copy())
    padded = length > 2 * step
    if padded:
        audio = torch.nn.functional.pad(audio, (step, step), mode='reflect')
    result = torch.zeros_like(audio)
    counter = torch.zeros(audio.shape[-1])
    window = torch.ones(chunk)
    window[:fade] = torch.linspace(0, 1, fade)
    window[-fade:] = torch.linspace(1, 0, fade)
    print('Splitting guitar into lead and rhythm · 50% overlap · CPU', file=sys.stderr, flush=True)
    with torch.inference_mode():
        for start in range(0, audio.shape[-1], step):
            part = audio[:, start:start + chunk]
            size = part.shape[-1]
            part = torch.nn.functional.pad(part, (0, chunk-size), mode='reflect' if size > chunk//2 else 'constant')
            prediction = model(part[None])[0, ..., :size]
            blend = window.clone()
            if start == 0:
                blend[:fade] = 1
            elif start + step >= audio.shape[-1]:
                blend[-fade:] = 1
            result[:, start:start+size] += prediction * blend[:size]
            counter[start:start+size] += blend[:size]
            print(f'Guitar split {min(100, round((start+step)/audio.shape[-1]*100))}%', file=sys.stderr, flush=True)
        result /= counter
    if padded:
        result = result[:, step:-step]
    lead = result.numpy().T
    if lead.shape != mix.shape or not np.isfinite(lead).all():
        raise RuntimeError('Guitar model produced invalid audio.')
    output.mkdir(parents=True, exist_ok=True)
    settings['lead_rhythm_split'] = {'model': 'listra92', 'sha256': MODEL_SHA256, 'overlap': 0.5}
    if local_trim is not None:
        settings['lead_rhythm_split']['trim'] = {
            'start': round(base + local_trim[0], 3),
            'end': round(base + local_trim[1], 3),
        }
    if replace_source:
        # Tells the project listing whether the guitar stem left behind still belongs
        # on screen (a muted one does) or predates this rule.
        settings['lead_rhythm_split']['guitar'] = 'removed' if whole else 'muted'
    with tempfile.TemporaryDirectory(prefix='.guitar-split-', dir=output) as temporary:
        stage = Path(temporary)
        # 24-bit: FLAC has no float format, and soundfile would default to 16-bit.
        sf.write(stage/paths[0].name, lead, sr, subtype='PCM_24')
        sf.write(stage/paths[1].name, mix-lead, sr, subtype='PCM_24')
        (stage/settings_path.name).write_text(json.dumps(settings, indent=2)+'\n', encoding='utf-8')
        if replace_source and not whole:
            guitar, _ = sf.read(source, dtype='float32', always_2d=True)
            sf.write(stage/source.name, mute_section(guitar, start_frame, gain), sr, subtype=info.subtype)
        validate_outputs(source, paths + [settings_path])
        for path in paths + [settings_path]:
            (stage/path.name).replace(path)
        if replace_source and not whole:
            (stage/source.name).replace(source)
    if replace_source and whole:
        source.unlink()
    return [path.resolve() for path in paths]
