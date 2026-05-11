"""Tests for the bundled avatar manifest discovery."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from teams_simulator import avatars as avatars_mod
from teams_simulator.avatars import (
    BundledAvatar,
    default_bundled_avatar,
    list_bundled_avatars,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    list_bundled_avatars.cache_clear()
    yield
    list_bundled_avatars.cache_clear()


def _write_manifest(tmp: Path, entries: list[dict]) -> Path:
    p = tmp / "avatars.json"
    p.write_text(json.dumps(entries), encoding="utf-8")
    return p


def test_bundled_manifest_is_present_and_loads():
    """The repository ships a working manifest with at least one avatar."""
    avatars = list_bundled_avatars()
    assert len(avatars) >= 1, "expected at least one bundled avatar"
    assert all(isinstance(a, BundledAvatar) for a in avatars)
    assert all(a.exists for a in avatars), "manifest references missing files"
    # Hipster names — first one is the default
    labels = [a.label for a in avatars]
    assert labels == sorted(set(labels), key=labels.index), "labels must be unique-in-order"


def test_default_avatar_matches_first_entry():
    avatars = list_bundled_avatars()
    if not avatars:
        pytest.skip("no avatars bundled")
    assert default_bundled_avatar() == avatars[0]


def test_missing_manifest_returns_empty(tmp_path: Path):
    assert list_bundled_avatars(tmp_path / "does-not-exist.json") == ()


def test_malformed_manifest_returns_empty(tmp_path: Path):
    p = tmp_path / "avatars.json"
    p.write_text("{not valid json", encoding="utf-8")
    assert list_bundled_avatars(p) == ()


def test_manifest_skips_missing_files(tmp_path: Path, monkeypatch):
    # Create one real PNG and one referenced-but-missing.
    real = tmp_path / "real.png"
    real.write_bytes(b"\x89PNG\r\n\x1a\n")
    manifest = _write_manifest(tmp_path, [
        {"id": "real", "label": "Real", "file": "real.png"},
        {"id": "ghost", "label": "Ghost", "file": "missing.png"},
    ])
    monkeypatch.setattr(avatars_mod, "REPO_ROOT", tmp_path)
    out = list_bundled_avatars(manifest)
    assert [a.id for a in out] == ["real"]


def test_manifest_skips_invalid_entries(tmp_path: Path, monkeypatch):
    real = tmp_path / "real.png"
    real.write_bytes(b"x")
    manifest = _write_manifest(tmp_path, [
        {"id": "", "label": "Blank", "file": "real.png"},          # missing id
        {"id": "noFile", "label": "No file"},                       # missing file
        "not a dict",                                               # wrong type
        {"id": "ok", "label": "OK", "file": "real.png"},
    ])
    monkeypatch.setattr(avatars_mod, "REPO_ROOT", tmp_path)
    out = list_bundled_avatars(manifest)
    assert [a.id for a in out] == ["ok"]


def test_label_falls_back_to_capitalised_id(tmp_path: Path, monkeypatch):
    real = tmp_path / "x.png"
    real.write_bytes(b"x")
    manifest = _write_manifest(tmp_path, [
        {"id": "kai", "label": "", "file": "x.png"},
    ])
    monkeypatch.setattr(avatars_mod, "REPO_ROOT", tmp_path)
    out = list_bundled_avatars(manifest)
    assert out[0].label == "Kai"
