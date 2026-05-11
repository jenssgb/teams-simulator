"""Download long, public-domain English monologue audiobooks from LibriVox.

These long samples (~30-60 min each, single narrator) are the right input
for testing the *transcript* path of Microsoft Teams - short clips do not
exercise the speech-to-text pipeline meaningfully.

We do NOT commit them to the repo (they are ~73 MB total). Instead this
script downloads them on demand into ``samples/long/`` (gitignored). The
Windows installer (``setup/install.ps1``) calls this script automatically
during the post-reboot phase.

Properties of every entry below:

* Public domain (the underlying text + LibriVox recording).
* Single narrator (monologue), so the resulting Teams transcript is clean.
* 30-65 minutes of continuous English speech.
* Hosted on archive.org with stable URLs.

Re-run this any time:

    .venv\\Scripts\\python.exe scripts\\download_long_samples.py
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "samples" / "long"
MANIFEST_PATH = OUT_DIR / "long_samples.json"
USER_AGENT = "teams-simulator-bootstrap/1.0 (+https://github.com/jenssgb/teams-simulator)"


@dataclass(frozen=True)
class LongSample:
    slug: str
    label: str
    minutes: int
    url: str
    expected_min_bytes: int
    credit: str


SAMPLES: list[LongSample] = [
    LongSample(
        slug="01_holmes_a_scandal_in_bohemia",
        label="A Scandal in Bohemia (Sherlock Holmes, ~65 min)",
        minutes=65,
        url="https://archive.org/download/adventures_holmes/adventureholmes_01_doyle_64kb.mp3",
        expected_min_bytes=20_000_000,
        credit="A. Conan Doyle, read by LibriVox volunteers (public domain)",
    ),
    LongSample(
        slug="02_holmes_the_red_headed_league",
        label="The Red-Headed League (Sherlock Holmes, ~59 min)",
        minutes=59,
        url="https://archive.org/download/adventures_holmes/adventureholmes_02_doyle_64kb.mp3",
        expected_min_bytes=18_000_000,
        credit="A. Conan Doyle, read by LibriVox volunteers (public domain)",
    ),
    LongSample(
        slug="03_walden_economy_part1",
        label="Walden - 'Economy', part 1 (Thoreau, ~30 min)",
        minutes=30,
        url="https://archive.org/download/walden_librivox/walden_c01_p01_64kb.mp3",
        expected_min_bytes=10_000_000,
        credit="H. D. Thoreau, read by LibriVox volunteers (public domain)",
    ),
]


def _format_size(n: int) -> str:
    return f"{n / (1024 * 1024):.1f} MB"


def _download_one(sample: LongSample, out_path: Path) -> bool:
    """Download ``sample`` to ``out_path``. Idempotent - skip if already
    present and big enough. Returns True on success or skip, False on error."""

    if out_path.exists():
        size = out_path.stat().st_size
        if size >= sample.expected_min_bytes:
            print(f"  [skip] {out_path.name}  ({_format_size(size)} already on disk)")
            return True
        print(f"  [retry] {out_path.name}  (only {_format_size(size)} - re-downloading)")
        try:
            out_path.unlink()
        except OSError:
            pass

    print(f"  [get ] {sample.url}")
    print(f"         -> {out_path}  (expected ~{_format_size(sample.expected_min_bytes)})")
    request = urllib.request.Request(sample.url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=60) as response, \
             open(out_path, "wb") as out_file:
            total = response.length or 0
            written = 0
            chunk = 64 * 1024
            next_report = 0
            while True:
                buf = response.read(chunk)
                if not buf:
                    break
                out_file.write(buf)
                written += len(buf)
                if total and written >= next_report:
                    pct = 100 * written / total
                    print(f"         ... {pct:5.1f}%  ({_format_size(written)} / {_format_size(total)})")
                    next_report += max(total // 10, 1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"  [ERROR] {sample.label}: {exc}", file=sys.stderr)
        if out_path.exists():
            try:
                out_path.unlink()
            except OSError:
                pass
        return False

    size = out_path.stat().st_size
    if size < sample.expected_min_bytes:
        print(
            f"  [ERROR] {sample.label}: downloaded only {_format_size(size)} "
            f"(expected >= {_format_size(sample.expected_min_bytes)})",
            file=sys.stderr,
        )
        return False
    print(f"  [ ok ] {out_path.name}  ({_format_size(size)})")
    return True


def _write_manifest(results: list[tuple[LongSample, Path, bool]]) -> None:
    payload = []
    for sample, path, ok in results:
        if not ok or not path.exists():
            continue
        payload.append({
            "slug": sample.slug,
            "label": sample.label,
            "file": path.name,
            "minutes": sample.minutes,
            "credit": sample.credit,
            "source_url": sample.url,
            "size_bytes": path.stat().st_size,
        })
    MANIFEST_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"  manifest written: {MANIFEST_PATH}  ({len(payload)} entries)")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"download target: {OUT_DIR}")
    results: list[tuple[LongSample, Path, bool]] = []
    for sample in SAMPLES:
        out_path = OUT_DIR / f"{sample.slug}.mp3"
        ok = _download_one(sample, out_path)
        results.append((sample, out_path, ok))

    _write_manifest(results)

    n_ok = sum(1 for _, _, ok in results if ok)
    n_total = len(results)
    print(f"\n{n_ok}/{n_total} long samples available in {OUT_DIR}")
    if n_ok == 0:
        print("WARNING: no long samples were downloaded - the GUI dropdown will be empty.",
              file=sys.stderr)
        # Don't fail the installer - users may be offline. They can still
        # pick the bundled short samples or bring their own audio.
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
