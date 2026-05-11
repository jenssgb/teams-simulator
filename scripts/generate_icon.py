"""Generate assets/app.ico from samples/avatars/atlas.png.

Pillow embeds multiple resolutions in a single .ico so Windows picks the
right one for the desktop, taskbar, alt-tab, and file explorer.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "samples" / "avatars" / "atlas.png"
DEST = ROOT / "assets" / "app.ico"

ICON_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
              (128, 128), (256, 256)]


def make_square(img: Image.Image, size: int = 512) -> Image.Image:
    src = img.convert("RGBA")
    w, h = src.size
    side = min(w, h)
    left = (w - side) // 2
    top = max(0, (h - side) // 3)
    cropped = src.crop((left, top, left + side, top + side))
    cropped = cropped.resize((size, size), Image.LANCZOS)

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size - 1, size - 1),
        radius=int(size * 0.18),
        fill=255,
    )
    mask = mask.filter(ImageFilter.GaussianBlur(radius=1.0))

    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(cropped, (0, 0), mask)
    return out


def main() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing avatar source: {SOURCE}")
    DEST.parent.mkdir(parents=True, exist_ok=True)

    base = make_square(Image.open(SOURCE), 512)
    base.save(DEST, format="ICO", sizes=ICON_SIZES)
    print(f"wrote {DEST} ({DEST.stat().st_size} bytes, sizes={ICON_SIZES})")


if __name__ == "__main__":
    main()
