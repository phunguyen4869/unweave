"""Filesystem helpers shared by the library and leftover clean-up.

Link detection is deliberately narrow on Windows: OneDrive Files-On-Demand marks
files and folders as reparse points, and those must still be sized and walked.
Only true symlinks and junctions (mount points) count as links.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

# Windows reparse tags we treat as "do not follow / do not delete as a leftover".
IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003  # junctions
IO_REPARSE_TAG_SYMLINK = 0xA000000C


def is_link_like(path: Path) -> bool:
    """True for symlinks and Windows junctions. OneDrive cloud placeholders are not.

    A path that cannot be inspected is treated as unsafe (True) so callers that
    skip links also skip unreadable entries. ``dir_bytes`` skips them rather than
    counting or following them.
    """
    try:
        if path.is_symlink():
            return True
    except OSError:
        return True
    isjunction = getattr(os.path, "isjunction", None)
    if isjunction is not None:
        try:
            if isjunction(path):
                return True
        except OSError:
            return True
    if os.name == "nt":
        try:
            info = os.stat(path, follow_symlinks=False)
            attrs = getattr(info, "st_file_attributes", 0)
            if not (attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT):
                return False
            tag = getattr(info, "st_reparse_tag", 0)
            return tag in (IO_REPARSE_TAG_MOUNT_POINT, IO_REPARSE_TAG_SYMLINK)
        except OSError:
            return True
    return False


def dir_bytes(path: Path) -> int:
    """Sum file sizes under ``path`` without following symlinks or junctions."""
    try:
        if is_link_like(path) or not path.is_dir():
            return 0
    except OSError:
        return 0
    total = 0
    try:
        walker = os.walk(path, followlinks=False)
    except OSError:
        return 0
    for root, dirs, files in walker:
        root_path = Path(root)
        dirs[:] = [name for name in dirs if not is_link_like(root_path / name)]
        for name in files:
            file_path = root_path / name
            if is_link_like(file_path):
                continue
            try:
                total += file_path.stat().st_size
            except OSError:
                continue
    return total
