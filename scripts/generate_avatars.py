"""Generate the bundled hipster avatar set + README hero via Pollinations.ai (Flux).

Re-run any time you want to refresh the visuals. Output is deterministic
because we pin the seed for each subject.

    python scripts/generate_avatars.py

Writes:
    samples/avatars/atlas.png      1024x1024
    samples/avatars/wren.png       1024x1024
    samples/avatars/cosmo.png      1024x1024
    samples/avatars/maeve.png      1024x1024
    samples/avatars/jasper.png     1024x1024
    samples/avatars/avatars.json   manifest used by the UI dropdown
    assets/hero.png                1600x640 cinematic banner
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image  # ensures the PNG is re-encoded in a Tk-compatible flavour

REPO = Path(__file__).resolve().parent.parent
AVATARS = REPO / "samples" / "avatars"
ASSETS = REPO / "assets"

POLLINATIONS = "https://image.pollinations.ai/prompt/"


@dataclass(frozen=True)
class Avatar:
    name: str
    prompt: str
    seed: int


# Five hipster avatars. Diverse age, gender, ethnicity, vibe.
# Square 1024x1024 — frame_source.py letterboxes them into 1280x720 at runtime.
AVATARS_SPEC: list[Avatar] = [
    Avatar(
        "atlas",
        "studio portrait of a friendly bearded hipster man in his early 30s wearing "
        "dark plaid flannel shirt and round tortoiseshell glasses, well-groomed full "
        "beard, soft warm natural lighting, neutral grey studio background, "
        "photorealistic, sharp focus, centered headshot framing, head and shoulders, "
        "looking directly at the camera, neutral pleasant expression",
        seed=11,
    ),
    Avatar(
        "wren",
        "studio portrait of a friendly hipster woman in her late 20s with short "
        "asymmetrical platinum blonde bob haircut and blunt bangs, large round acetate "
        "glasses, wearing a chunky cream knit cardigan, soft warm natural lighting, "
        "neutral pale terracotta background, photorealistic, sharp focus, centered "
        "headshot framing, head and shoulders, looking directly at the camera, "
        "warm friendly half smile",
        seed=22,
    ),
    Avatar(
        "cosmo",
        "studio portrait of a friendly mixed race hipster man in his early 30s with "
        "long dark hair tied in a man-bun and a full dark beard, visible artistic arm "
        "tattoos, blue denim jacket over white t-shirt, soft natural lighting, "
        "neutral warm beige background, photorealistic, sharp focus, centered headshot "
        "framing, head and shoulders, looking directly at the camera, calm confident "
        "expression",
        seed=33,
    ),
    Avatar(
        "maeve",
        "studio portrait of a friendly hipster woman in her early 30s with long curly "
        "auburn red hair and visible freckles, small gold hoop earrings, mustard "
        "yellow corduroy overalls over a white t-shirt, soft warm natural lighting, "
        "neutral pale dusty blue background, photorealistic, sharp focus, centered "
        "headshot framing, head and shoulders, looking directly at the camera, bright "
        "friendly smile",
        seed=44,
    ),
    Avatar(
        "jasper",
        "studio portrait of a friendly hipster man in his 40s wearing a brown wool "
        "felt fedora hat, salt and pepper full beard, vintage brown tweed jacket over "
        "a white oxford shirt, soft natural lighting, neutral deep teal background, "
        "photorealistic, sharp focus, centered headshot framing, head and shoulders, "
        "looking directly at the camera, thoughtful warm expression",
        seed=55,
    ),
]


HERO = Avatar(
    "hero",
    "wide cinematic editorial illustration of a stylish virtual avatar inside an "
    "abstract video conference window, deep midnight indigo and Microsoft Teams "
    "purple gradient background, soft holographic light particles, floating "
    "translucent microphone and webcam glyphs, subtle sound waveform ribbons, "
    "modern minimalist tech aesthetic, professional, dramatic rim lighting, "
    "16:9 aspect ratio composition, no visible text, no logos, no watermark",
    seed=99,
)


def fetch(prompt: str, out: Path, *, width: int, height: int, seed: int,
          model: str = "flux", retries: int = 3, timeout: int = 180) -> None:
    encoded = urllib.parse.quote(prompt, safe="")
    url = (
        f"{POLLINATIONS}{encoded}"
        f"?width={width}&height={height}&seed={seed}"
        f"&nologo=true&model={model}&enhance=true"
    )
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            print(f"  attempt {attempt}/{retries}: GET {url[:90]}…")
            req = urllib.request.Request(url, headers={"User-Agent": "teams-simulator/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
            if len(data) < 5_000:
                raise RuntimeError(f"suspiciously small response ({len(data)} bytes)")
            # Pollinations returns modern (zlib level 9, possibly interlaced)
            # PNGs that Tk's built-in PhotoImage can't decode. Round-trip
            # through Pillow so we get a vanilla PNG suitable for the UI
            # preview thumbnails. We also force RGB to drop any alpha
            # channel that pyvirtualcam doesn't want.
            img = Image.open(BytesIO(data)).convert("RGB")
            img.save(out, format="PNG", optimize=True)
            print(f"  wrote {out.relative_to(REPO)} ({out.stat().st_size:,} bytes, {img.size[0]}x{img.size[1]})")
            return
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            print(f"  ! {exc}")
            time.sleep(5 * attempt)
    raise RuntimeError(f"giving up on {out.name}: {last_err}")


def main() -> None:
    AVATARS.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)

    manifest: list[dict[str, str]] = []
    for av in AVATARS_SPEC:
        out = AVATARS / f"{av.name}.png"
        print(f"\n=== {av.name} ===")
        fetch(av.prompt, out, width=1024, height=1024, seed=av.seed)
        manifest.append({
            "id": av.name,
            "label": av.name.capitalize(),
            "file": f"samples/avatars/{av.name}.png",
        })

    (AVATARS / "avatars.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\nwrote {AVATARS / 'avatars.json'}")

    print(f"\n=== hero banner ===")
    fetch(HERO.prompt, ASSETS / "hero.png",
          width=1600, height=640, seed=HERO.seed)


if __name__ == "__main__":
    main()
