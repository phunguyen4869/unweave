# syntax=docker/dockerfile:1
# Unweave as a headless web server (no pywebview window): the same UI the desktop
# app shows, opened from a browser on the LAN. See docs/docker.md.
#
# Everything the desktop app's first-run setup downloads (FFmpeg, PyTorch,
# audio-separator, yt-dlp) is baked into the image, so the setup screen is already
# complete. Only the AI models are fetched at runtime, into the /data/models volume.

FROM python:3.12-slim-bookworm

# CPU-only PyTorch by default (~0.8 GB instead of ~2.5 GB for CUDA builds). For an
# NVIDIA GPU passed through to the container, build with e.g.
#   --build-arg TORCH_INDEX_URL=https://download.pytorch.org/whl/cu124
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/unweave

# Dependencies first, read from pyproject.toml (the same source of truth setup_env.py
# installs from), so code changes don't re-download PyTorch.
COPY app/pyproject.toml app/pyproject.toml
RUN python - <<'EOF' > /tmp/requirements.txt
import tomllib
project = tomllib.load(open("app/pyproject.toml", "rb"))["project"]
extras = project["optional-dependencies"]
requirements = project["dependencies"] + extras["separation"] + extras["guitars"] + extras["youtube"]
print("\n".join(dict.fromkeys(requirements)))
EOF
RUN pip install --index-url "$TORCH_INDEX_URL" torch \
    && pip install -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# Run from source rather than pip-installing the package: tools.app_version() and
# setup_env read app/pyproject.toml next to the unweave/ package.
COPY app/ app/
ENV PYTHONPATH=/opt/unweave/app

# Unprivileged user; /data holds settings + job logs, the model cache and songs.
# Bind-mounted host folders must be writable by UID/GID 1000.
RUN groupadd --gid 1000 unweave \
    && useradd --uid 1000 --gid 1000 --create-home --shell /usr/sbin/nologin unweave \
    && mkdir -p /data/config /data/models /data/projects \
    && chown -R unweave:unweave /data
USER unweave
VOLUME ["/data"]

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/', timeout=4)" || exit 1

ENTRYPOINT ["tini", "--"]
CMD ["python", "-m", "unweave", "ui", \
     "--host", "0.0.0.0", "--port", "8765", \
     "--config", "/data/config/ui.json", \
     "--cache", "/data/models", \
     "--default-root", "/data/projects"]
