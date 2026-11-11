"""GitHub Releases lookup for the in-app update check (spec 10)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from .netutil import urlopen

GITHUB_OWNER = "um1chc5"
GITHUB_REPO = "unweave"
RELEASES_LATEST_API = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
RELEASES_LATEST_PAGE = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
CHECK_INTERVAL_S = 24 * 3600
ASK_AGAIN_S = 7 * 24 * 3600
FETCH_TIMEOUT_S = 8.0


def normalize_tag(tag: str | None) -> str:
    if not tag:
        return ""
    return str(tag).strip().lstrip("vV")


def version_tuple(version: str) -> tuple[int, ...]:
    """Semver-ish tuple for shipped tags like 1.3.1 (leading v stripped)."""
    core = normalize_tag(version).split("+", 1)[0].split("-", 1)[0]
    parts: list[int] = []
    for piece in core.split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def is_newer(latest: str, current: str) -> bool:
    if not normalize_tag(latest) or not normalize_tag(current):
        return False
    return version_tuple(latest) > version_tuple(current)


def fetch_latest_release(user_agent: str, opener=None) -> dict:
    """Return {tag, url, name} for the latest stable GitHub release.

    Uses /releases/latest, which already skips drafts and prereleases.
    `opener` is an optional callable(Request) -> file-like (for tests).
    """
    request = urllib.request.Request(
        RELEASES_LATEST_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": user_agent or "Unweave",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    open_url = opener or (lambda req: urlopen(req, timeout=FETCH_TIMEOUT_S))
    try:
        with open_url(request) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise ValueError(f"Update check failed (HTTP {error.code}).") from error
    except urllib.error.URLError as error:
        raise ValueError("Could not reach GitHub to check for updates.") from error
    except (TimeoutError, OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError("Could not reach GitHub to check for updates.") from error

    if not isinstance(payload, dict):
        raise ValueError("Unexpected response from GitHub Releases.")
    if payload.get("draft") or payload.get("prerelease"):
        raise ValueError("Latest GitHub release is not a stable build.")
    tag = normalize_tag(payload.get("tag_name"))
    if not tag:
        raise ValueError("GitHub release has no version tag.")
    url = payload.get("html_url") or RELEASES_LATEST_PAGE
    name = payload.get("name") or tag
    return {"tag": tag, "url": url, "name": name}
