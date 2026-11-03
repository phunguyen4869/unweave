# Docker / Proxmox LXC Guide

Unweave can run as a headless server in Docker and be used from any browser on your
network. This is the same web UI the desktop app shows inside its window; the
container just runs it without the window. A common home-lab setup is a Docker LXC
on Proxmox VE, which this guide walks through. Any other Docker host works the same
way from step 2.

The image already contains FFmpeg, PyTorch (CPU build), audio-separator and yt-dlp,
so the first-run setup screen is complete. The AI models (~455 MB) still download
the first time each one is used, into the models volume.

## 1. Create the LXC (Proxmox)

Either use the community [Proxmox VE Helper-Scripts](https://community-scripts.github.io/ProxmoxVE/)
"Docker" LXC, or create a Debian 12 container yourself and install Docker in it.
Whichever you pick:

| Setting | Recommended |
|---|---|
| Template | Debian 12 (or Ubuntu 24.04) |
| Type | Unprivileged |
| Features | `nesting=1`, `keyctl=1` (needed for Docker in an unprivileged LXC) |
| CPU | 4+ cores (separation is CPU-bound; more cores = faster) |
| RAM | 8 GB minimum, 12–16 GB for long songs or guitar splitting |
| Disk | 30 GB+ (image ~4 GB, models ~0.5 GB, then your songs) |

For a container you created yourself, turn on the features from the Proxmox host:

```bash
pct set <CTID> --features nesting=1,keyctl=1
```

then install Docker inside it:

```bash
apt update && apt install -y curl git
curl -fsSL https://get.docker.com | sh
```

## 2. Get the code and configure

Inside the LXC:

```bash
git clone https://github.com/um1chc5/unweave.git
cd unweave
cp .env.example .env
```

Edit `.env` and set `UNWEAVE_ALLOWED_HOSTS` to the address you will type in the
browser: the LXC's IP (`ip -4 addr show eth0`), and any DNS name or reverse-proxy
domain. Requests with any other `Host` header are refused with "Local same-origin
requests only", which protects against DNS-rebinding attacks from other websites.

```dotenv
UNWEAVE_ALLOWED_HOSTS=192.168.1.50,unweave.lan
```

The container runs as UID/GID 1000, so create the data folders with that owner
first (otherwise Docker creates them as root and the app can't write to them):

```bash
mkdir -p data/config data/models data/projects
chown -R 1000:1000 data
```

## 3. Build and start

```bash
docker compose up -d --build
```

The first build downloads about 1.5 GB and takes a few minutes. Then open
`http://<LXC-IP>:8765`. Follow the logs with:

```bash
docker compose logs -f
```

## Where things go

| In the container | On the Docker host (default) | Contents |
|---|---|---|
| `/data/config` | `./data/config` | `ui.json` settings and per-job logs |
| `/data/models` | `./data/models` | Downloaded AI models |
| `/data/projects` | `./data/projects` | Your separated songs (default projects folder) |

The host paths are set by `UNWEAVE_CONFIG_DIR`, `UNWEAVE_MODELS_DIR` and
`UNWEAVE_PROJECTS_DIR` in `.env`.

### Keeping songs on a NAS or the Proxmox host's storage

Mount the storage into the LXC first (from the Proxmox host):

```bash
pct set <CTID> -mp0 /tank/music/unweave,mp=/mnt/unweave
```

then point `UNWEAVE_PROJECTS_DIR=/mnt/unweave` in `.env`. In an unprivileged LXC,
UID 1000 inside the LXC is UID 101000 on the Proxmox host, so the folder on the host
must be writable by that user (`chown -R 101000:101000 /tank/music/unweave`).

## Settings

| Variable | Default | Effect |
|---|---|---|
| `UNWEAVE_ALLOWED_HOSTS` | (required) | Hostnames/IPs the UI may be opened with, comma-separated. `name` matches any port, `name:port` only that port, `*` any host (turns off DNS-rebinding protection) |
| `UNWEAVE_PORT` | `8765` | Port on the Docker host |
| `UNWEAVE_THREADS` | CPU count − 1 | Inference threads. Docker sees all of the Proxmox host's cores, so set this to the LXC's core count if you limited it |
| `UNWEAVE_MAX_CONCURRENT_JOBS` | `1` | Separation jobs run at once |
| `TZ` | `UTC` | Time zone for logs |
| `TORCH_INDEX_URL` | CPU wheels | PyTorch build to install (build-time) |

## Updating

```bash
cd unweave
git pull
docker compose up -d --build
```

Your settings, models and songs live in the volumes and are kept. The in-app update
notice points to the desktop installers; ignore it and update with `git pull`
instead.

## Behind a reverse proxy

Nginx Proxy Manager, Caddy and Traefik all work. Add the proxy's domain to
`UNWEAVE_ALLOWED_HOSTS`, and make sure the proxy forwards the original `Host` header
(Nginx needs `proxy_set_header Host $host;`; NPM, Caddy and Traefik do it by
default). Raise the request body limit so audio uploads (up to 2 GB) aren't cut off,
for example `client_max_body_size 2g;` in Nginx.

Unweave has no login. Don't expose it to the internet without putting
authentication in front of it (the proxy's access list, Authelia, a VPN like
Tailscale, …).

## GPU (optional)

The default image uses CPU-only PyTorch. With an NVIDIA GPU passed through to the
LXC and the NVIDIA Container Toolkit installed in it, set
`TORCH_INDEX_URL=https://download.pytorch.org/whl/cu124` in `.env`, add a GPU
reservation to `docker-compose.yml`:

```yaml
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
```

and rebuild with `docker compose up -d --build`.

## Limitations

- **Show in folder** opens a file manager on the machine running the app, which a
  container doesn't have. Browse the projects folder on the host or over a share
  instead.
- The folder picker in the UI browses the container's filesystem. Projects folders
  must be inside a mounted volume (`/data/projects` or another one you add) or they
  vanish when the container is recreated.

## Troubleshooting

**"Local same-origin requests only. To open it from another machine…"**
The address in your browser isn't in `UNWEAVE_ALLOWED_HOSTS`. Add it to `.env`, then
`docker compose up -d`.

**"Permission denied" writing to `/data/...`.**
The host folder isn't owned by UID 1000: `chown -R 1000:1000 data` (or the folder
you set in `.env`).

**Docker won't start inside the LXC.**
Check that `nesting=1` and `keyctl=1` are on (`pct config <CTID>`), then restart the
LXC.

**Separation is killed partway through.**
Usually out of memory: give the LXC more RAM, and keep
`UNWEAVE_MAX_CONCURRENT_JOBS=1`.
