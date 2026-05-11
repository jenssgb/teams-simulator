"""Bundled hipster avatar discovery.

Reads ``samples/avatars/avatars.json`` (written by
``scripts/generate_avatars.py``) so the UI / CLI can offer a fixed
dropdown of avatars without rescanning the filesystem.

The manifest is intentionally simple — each entry is ``{id, label, file}``
with ``file`` relative to the repo root. Missing entries are skipped
silently so a partial install (e.g. someone deleted a PNG) still works.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Sequence

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MANIFEST = REPO_ROOT / "samples" / "avatars" / "avatars.json"


@dataclass(frozen=True)
class BundledAvatar:
    """One pre-shipped avatar the user can select from a dropdown."""

    id: str
    label: str
    path: Path

    @property
    def exists(self) -> bool:
        return self.path.is_file()


@lru_cache(maxsize=1)
def list_bundled_avatars(manifest: Path | None = None) -> tuple[BundledAvatar, ...]:
    """Return the bundled avatars from ``avatars.json``.

    Returns an empty tuple if the manifest is missing or unreadable.
    Skips entries whose target PNG is missing on disk.
    """
    path = manifest or MANIFEST
    if not path.is_file():
        log.debug("avatars manifest not found at %s", path)
        return ()

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("could not read avatars manifest %s: %s", path, exc)
        return ()

    if not isinstance(raw, Sequence):
        log.warning("avatars manifest %s is not a list", path)
        return ()

    out: list[BundledAvatar] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        eid = str(entry.get("id", "")).strip()
        label = str(entry.get("label", "")).strip() or eid.capitalize()
        rel = str(entry.get("file", "")).strip()
        if not eid or not rel:
            continue
        target = (REPO_ROOT / rel).resolve()
        if not target.is_file():
            log.debug("skipping avatar %s — file missing: %s", eid, target)
            continue
        out.append(BundledAvatar(id=eid, label=label, path=target))

    return tuple(out)


def default_bundled_avatar() -> BundledAvatar | None:
    """First avatar in the manifest, if any."""
    avatars = list_bundled_avatars()
    return avatars[0] if avatars else None
