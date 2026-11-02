# Unweave

[![Download for Windows](https://img.shields.io/github/v/release/um1chc5/unweave?label=Download%20for%20Windows&style=for-the-badge&color=ff8a3d)](https://github.com/um1chc5/unweave/releases/latest/download/Unweave-Setup-x64.exe)

A desktop app that unweaves songs into their stems with local AI. Based on the excellent [Sound Razor](https://github.com/pedromtcosta/sound-razor) by [pedromtcosta](https://github.com/pedromtcosta).

*Unweave was called **SoundRazer Desktop** up to version 1.2.2. Installing Unweave replaces the old version and keeps your songs, settings and downloaded components.*

## About

Unweave packages Sound Razor into a native Windows application with an enhanced, modern UI. It uses AI models (Demucs, MDX, RoFormer) to separate mixed audio into individual instrument stems - vocals, drums, bass, guitar, piano, and more. You can also split guitars into lead and rhythm parts.

## Features

- **Native Desktop App** - Runs in its own window using pywebview, no browser needed
- **Enhanced UI** - Beautiful, modern interface with improved UX
- **100% Local Processing** - All AI models run on your computer, no cloud uploads
- **Multiple Formats** - Supports WAV, MP3, FLAC, M4A, OGG, AAC and more
- **Guitar Splitting** - Separate lead and rhythm guitar parts
- **YouTube Import** - Download and separate audio directly from YouTube
- **Job Queue** - Queue separations, exports and imports while another one runs
- **Real-time Mixer** - Control volume, mute, and solo each stem independently
- **Playback Speed Control** - Slow down tracks without pitch change for learning
- **Project Management** - Organize all your separated tracks in one place

## Installation

### For Users (Recommended)

**[Download Unweave-Setup-x64.exe](https://github.com/um1chc5/unweave/releases/latest/download/Unweave-Setup-x64.exe)** (latest release) and run it. The installer is tiny and works offline:

- Installs to Program Files (default: `C:\Program Files\Unweave`) — requires administrator rights, so Windows will prompt for them
- Creates a Start Menu entry and registers an uninstaller; you choose whether to also add a desktop icon

On first launch the app window opens immediately and shows a one-time setup screen. You explicitly consent to download and install the remaining pieces — FFmpeg and the PyTorch/audio-separation stack (~1.6 GB total) — before anything downloads. They go into `%LOCALAPPDATA%\Unweave`, which the uninstaller cleans up. AI models (~500 MB) are then downloaded on first separation.

### For Developers

```bash
# Clone or copy this project
cd unweave

# Create virtual environment
uv venv --python 3.11 .venv

# Install dependencies
uv pip install --python .venv/Scripts/python.exe -e ".[full]"

# Run the app
.\.venv\Scripts\unweave.exe
```

## Linux

Unweave also runs on Linux (x86-64). Install it with the bundled script:

```bash
git clone https://github.com/um1chc5/unweave.git
cd unweave
./installer/install-linux.sh
unweave
```

It needs Python 3.11+, `uv` (or `venv`), and GTK 3 + WebKit2 for the native window
(`python3-gi`, `gir1.2-gtk-3.0`, `gir1.2-webkit2-4.1` on Debian/Ubuntu). The
installer writes a launcher and a menu entry, and the app downloads FFmpeg and the
separation engine on first launch, just like the Windows build. See
[docs/linux-install.md](docs/linux-install.md) for the full guide, uninstall steps
and troubleshooting. If playback is silent in the native window, use
`UNWEAVE_BROWSER=1 unweave` (or the in-app banner).

## macOS

```bash
git clone https://github.com/um1chc5/unweave.git
cd unweave
./installer/install-macos.sh
unweave
```

Needs Python 3.11+ and `uv` (or `venv`). No GTK packages — the window uses Cocoa
WKWebView via pywebview. The script also writes an **unsigned**
`~/Applications/Unweave.app` (right-click → Open the first time). No signing or
notarization. See [docs/macos-install.md](docs/macos-install.md).

## System Requirements

- **OS**: Windows 10/11 (64-bit); also Linux and macOS via the install scripts above
- **RAM**: 8GB minimum, 16GB recommended
- **Storage**: about 2 GB for the app's components and AI models, plus room for your songs (see below)
- **CPU**: Modern 64-bit processor (4+ cores recommended)
- **GPU**: Not used yet; everything runs on the CPU

### How much space songs take

Stems are stored as lossless FLAC, about 5–6 MB per stem per minute, so separating a
song takes far more space than the song itself. A 4-minute song separated into all six
stems needs roughly 130–150 MB; splitting the guitar into lead and rhythm adds about
60 MB more. That is 15× or more the size of a typical MP3. Unweave checks for free space
before each job and tells you if a song will not fit. Exports are extra copies on top.

## Technology Stack

- **Backend**: Python with Flask-style HTTP server (inherited from Sound Razor)
- **Frontend**: Vanilla JavaScript, HTML5, CSS3
- **Desktop Wrapper**: [pywebview](https://pywebview.flowrl.com/)
- **AI Models**: [Demucs](https://github.com/facebookresearch/demucs), [MDX-Net](https://github.com/kuielab/mdx-net), [RoFormer](https://github.com/lucidrains/BS-RoFormer)
- **Audio Processing**: [audio-separator](https://github.com/nomadkaraoke/python-audio-separator), PyTorch, ONNX Runtime

## Credits

Unweave is based on [Sound Razor](https://github.com/pedromtcosta/sound-razor) created by **[pedromtcosta](https://github.com/pedromtcosta)**. All core audio separation functionality comes from the original Sound Razor project. Unweave adds a native window wrapper, improved UI design, simplified installation, a job queue and more.

It also stands on the work of these people and projects. The app downloads the models and the separation libraries during setup rather than shipping them; the Mel-Band RoFormer code is included in [`app/unweave/vendor/roformer`](app/unweave/vendor/roformer) with its license.

### AI models

| Model | Used for | Author | License |
|---|---|---|---|
| [Demucs](https://github.com/facebookresearch/demucs) `htdemucs_6s` | 6-stem separation (default) | Meta AI · Alexandre Défossez et al. | MIT |
| [UVR MDX-Net Karaoke 2](https://github.com/Anjok07/ultimatevocalremovergui) `UVR_MDXNET_KARA_2` | Vocals + instrumental | Ultimate Vocal Remover · Anjok07, aufr33 | MIT (UVR asks apps using its models to credit UVR and its developers) |
| [Lead/rhythm guitar](https://huggingface.co/noblebarkrr/mvsepless_resources) `mbr_lead_rhythm_guitar_listra92` | Guitar splitting | listra92 · hosted by noblebarkrr | Not stated by the hosting repository |

### Code and tools

| Project | Used for | Author | License |
|---|---|---|---|
| [Music-Source-Separation-Training](https://github.com/ZFTurbo/Music-Source-Separation-Training) | Mel-Band RoFormer architecture (vendored) | ZFTurbo (Roman Solovyev) | MIT |
| [BS-RoFormer](https://github.com/lucidrains/BS-RoFormer) | Original RoFormer implementation the above builds on | lucidrains (Phil Wang) | MIT |
| [python-audio-separator](https://github.com/nomadkaraoke/python-audio-separator) | Downloading and running the separation models | nomadkaraoke (Andrew Beveridge) | MIT |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | YouTube import | yt-dlp contributors | Unlicense |
| [FFmpeg](https://ffmpeg.org) | Audio conversion and export | FFmpeg developers | LGPL / GPL (the Windows build setup downloads is GPLv3) |
| [pywebview](https://github.com/r0x0r/pywebview) | Desktop window | Roman Sirokov | BSD-3-Clause |
| [PyTorch](https://pytorch.org), [ONNX Runtime](https://onnxruntime.ai), [librosa](https://librosa.org), [NumPy](https://numpy.org), [SoundFile](https://github.com/bastibe/python-soundfile) | Running the models and reading audio | Their respective authors | BSD / MIT / ISC |

### Song info and covers

Song details lookup uses [MusicBrainz](https://musicbrainz.org) (core data CC0) and cover art from the [Cover Art Archive](https://coverartarchive.org), both run by the [MetaBrainz Foundation](https://metabrainz.org). Cover images belong to their respective copyright holders.

## Contributing

Want to help? See [CONTRIBUTING.md](CONTRIBUTING.md). Branch creation on this
repository is limited to the maintainer; open pull requests from a fork.

## License

MIT License - See [LICENSE](LICENSE) file for details.

Original Sound Razor is also MIT licensed by pedromtcosta.
