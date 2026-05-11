"""Generate the README hero banner + architecture diagram.

Re-run this any time the README needs fresh marketing art. Output is
fully deterministic.

    python scripts/generate_hero.py

writes:
    assets/hero.png           1600 x 520 banner
    assets/architecture.png   1600 x 700 data-flow diagram
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

REPO = Path(__file__).resolve().parent.parent
ASSETS = REPO / "assets"

TEAMS_PURPLE = (98, 100, 167)
TEAMS_PURPLE_DARK = (70, 73, 144)
INK = (24, 26, 46)
INK_LIGHT = (52, 54, 90)
ACCENT = (130, 180, 255)
ACCENT_2 = (255, 198, 130)
WHITE = (245, 246, 252)
GRID = (255, 255, 255, 28)


def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    name = "segoeuib.ttf" if bold else "segoeui.ttf"
    try:
        return ImageFont.truetype(rf"C:\Windows\Fonts\{name}", size)
    except OSError:
        return ImageFont.load_default()


def emoji_font(size: int) -> ImageFont.ImageFont:
    for candidate in ("seguiemj.ttf", "segoeui.ttf"):
        try:
            return ImageFont.truetype(rf"C:\Windows\Fonts\{candidate}", size)
        except OSError:
            continue
    return ImageFont.load_default()


def vertical_gradient(size, top, bottom):
    w, h = size
    img = Image.new("RGB", size, top)
    px = img.load()
    for y in range(h):
        a = y / max(1, h - 1)
        c = (
            int(top[0] * (1 - a) + bottom[0] * a),
            int(top[1] * (1 - a) + bottom[1] * a),
            int(top[2] * (1 - a) + bottom[2] * a),
        )
        for x in range(w):
            px[x, y] = c
    return img


def diagonal_gradient(size, top_left, bottom_right):
    w, h = size
    img = Image.new("RGB", size, top_left)
    px = img.load()
    diag = math.hypot(w, h)
    for y in range(h):
        for x in range(w):
            a = math.hypot(x, y) / diag
            px[x, y] = (
                int(top_left[0] * (1 - a) + bottom_right[0] * a),
                int(top_left[1] * (1 - a) + bottom_right[1] * a),
                int(top_left[2] * (1 - a) + bottom_right[2] * a),
            )
    return img


def add_grid(img: Image.Image, step: int = 40) -> None:
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    for x in range(0, img.size[0], step):
        d.line([(x, 0), (x, img.size[1])], fill=GRID, width=1)
    for y in range(0, img.size[1], step):
        d.line([(0, y), (img.size[0], y)], fill=GRID, width=1)
    img.alpha_composite(overlay) if img.mode == "RGBA" else img.paste(
        Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    )


def add_glow(canvas: Image.Image, cx: int, cy: int, radius: int, color, alpha: int = 90) -> None:
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.ellipse(
        [cx - radius, cy - radius, cx + radius, cy + radius],
        fill=(*color, alpha),
    )
    layer = layer.filter(ImageFilter.GaussianBlur(radius // 2))
    canvas.alpha_composite(layer)


def draw_microphone(d: ImageDraw.ImageDraw, cx: int, cy: int, scale: float = 1.0, color=WHITE) -> None:
    w = int(70 * scale)
    h = int(110 * scale)
    body = [cx - w // 2, cy - h // 2, cx + w // 2, cy - h // 2 + h * 6 // 10]
    d.rounded_rectangle(body, radius=int(35 * scale), fill=color)
    arc_box = [cx - int(60 * scale), cy - int(15 * scale), cx + int(60 * scale), cy + int(55 * scale)]
    d.arc(arc_box, start=0, end=180, fill=color, width=int(8 * scale))
    d.line([(cx, cy + int(55 * scale)), (cx, cy + int(85 * scale))], fill=color, width=int(8 * scale))
    d.line([(cx - int(30 * scale), cy + int(85 * scale)), (cx + int(30 * scale), cy + int(85 * scale))],
           fill=color, width=int(8 * scale))


def draw_camera(d: ImageDraw.ImageDraw, cx: int, cy: int, scale: float = 1.0, color=WHITE) -> None:
    w = int(140 * scale)
    h = int(95 * scale)
    body = [cx - w // 2, cy - h // 2, cx + w // 2 - int(25 * scale), cy + h // 2]
    d.rounded_rectangle(body, radius=int(14 * scale), fill=color)
    lens = [cx + int(15 * scale), cy - int(28 * scale),
            cx + int(15 * scale) + int(56 * scale), cy + int(28 * scale)]
    d.polygon([(lens[0], lens[1]), (lens[2], cy - int(40 * scale)),
               (lens[2], cy + int(40 * scale)), (lens[0], lens[3])],
              fill=color)


def draw_arrow(d: ImageDraw.ImageDraw, x1: int, y1: int, x2: int, y2: int,
               color=WHITE, width: int = 5) -> None:
    d.line([(x1, y1), (x2, y2)], fill=color, width=width)
    angle = math.atan2(y2 - y1, x2 - x1)
    head = 16
    for sign in (-1, 1):
        a = angle + sign * math.radians(28)
        d.line([(x2, y2), (x2 - head * math.cos(a), y2 - head * math.sin(a))],
               fill=color, width=width)


def make_hero() -> Path:
    W, H = 1600, 520
    bg = diagonal_gradient((W, H), TEAMS_PURPLE, INK).convert("RGBA")

    # subtle grid
    overlay = Image.new("RGBA", bg.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for x in range(0, W, 48):
        od.line([(x, 0), (x, H)], fill=(255, 255, 255, 14), width=1)
    for y in range(0, H, 48):
        od.line([(0, y), (W, y)], fill=(255, 255, 255, 14), width=1)
    bg.alpha_composite(overlay)

    # ambient glows
    add_glow(bg, 230, 260, 280, ACCENT, alpha=60)
    add_glow(bg, 1380, 260, 320, ACCENT_2, alpha=55)
    add_glow(bg, 800, 260, 220, (255, 255, 255), alpha=35)

    d = ImageDraw.Draw(bg)

    # left icon — microphone
    draw_microphone(d, 200, 240, scale=1.6, color=WHITE)
    # right icon — camera
    draw_camera(d, 1400, 240, scale=1.7, color=WHITE)

    # title
    title_font = font(108, bold=True)
    sub_font = font(34, bold=False)
    badge_font = font(26, bold=True)

    title = "Teams Simulator"
    tw = d.textlength(title, font=title_font)
    d.text(((W - tw) / 2, 168), title, font=title_font, fill=WHITE)

    # underline accent
    bar_y = 290
    d.rounded_rectangle([W // 2 - 70, bar_y, W // 2 + 70, bar_y + 6],
                        radius=3, fill=ACCENT_2)

    sub = "AI-generated audio + video, streamed into Microsoft Teams as a virtual mic and webcam"
    sw = d.textlength(sub, font=sub_font)
    d.text(((W - sw) / 2, 320), sub, font=sub_font, fill=(220, 224, 245))

    # bottom badges row
    badges = [
        ("Headless install", ACCENT),
        ("VB-Cable + OBS VCam", ACCENT_2),
        ("One-paste Quickstart", (170, 230, 190)),
    ]
    # measure first to center the row
    pad_x = 28
    bh = 56
    gap = 28
    widths = [int(d.textlength(label, font=badge_font) + pad_x * 2) for label, _ in badges]
    total = sum(widths) + gap * (len(badges) - 1)
    bx = (W - total) // 2
    for (label, color), bw in zip(badges, widths):
        d.rounded_rectangle([bx, 410, bx + bw, 410 + bh],
                            radius=28, fill=(255, 255, 255, 50),
                            outline=color, width=3)
        text_w = d.textlength(label, font=badge_font)
        d.text((bx + (bw - text_w) // 2, 420), label, font=badge_font, fill=WHITE)
        bx += bw + gap

    out = ASSETS / "hero.png"
    ASSETS.mkdir(parents=True, exist_ok=True)
    bg.convert("RGB").save(out, optimize=True)
    print(f"wrote {out} ({W}x{H})")
    return out


def rounded_panel(d: ImageDraw.ImageDraw, box, fill, outline=None, radius=22, width=2):
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def make_architecture() -> Path:
    W, H = 1600, 700
    bg = vertical_gradient((W, H), (245, 247, 252), (224, 228, 244)).convert("RGBA")
    d = ImageDraw.Draw(bg)

    title_f = font(38, bold=True)
    box_f = font(26, bold=True)
    sub_f = font(20, bold=False)
    note_f = font(18, bold=False)
    emo_f = emoji_font(36)

    def emoji(x, y, glyph):
        d.text((x, y), glyph, font=emo_f, embedded_color=True)

    d.text((60, 36), "How it works", font=title_f, fill=INK)
    d.text((60, 84),
           "Two pipelines, one timeline. The simulator owns both sides so audio and the in-camera waveform stay in sync.",
           font=sub_f, fill=INK_LIGHT)

    # Source boxes (left)
    src_x = 60
    src_w = 360
    src_h = 130

    rounded_panel(d, [src_x, 200, src_x + src_w, 200 + src_h],
                  fill=(255, 255, 255, 240), outline=TEAMS_PURPLE, width=3)
    emoji(src_x + 22, 216, "🎵")
    d.text((src_x + 76, 222), "audio file", font=box_f, fill=INK)
    d.text((src_x + 22, 264), "wav / flac / mp3 / ogg", font=sub_f, fill=INK_LIGHT)
    d.text((src_x + 22, 292), "+ live RMS analysis", font=sub_f, fill=INK_LIGHT)

    rounded_panel(d, [src_x, 400, src_x + src_w, 400 + src_h],
                  fill=(255, 255, 255, 240), outline=TEAMS_PURPLE, width=3)
    emoji(src_x + 22, 416, "🖼️")
    d.text((src_x + 76, 422), "avatar image", font=box_f, fill=INK)
    d.text((src_x + 22, 464), "png / jpg, letterboxed to 1280x720", font=sub_f, fill=INK_LIGHT)
    d.text((src_x + 22, 492), "+ equalizer-bar overlay", font=sub_f, fill=INK_LIGHT)

    # Engine box (center)
    eng_x = 600
    eng_w = 380
    eng_h = 330
    eng_y = 220
    rounded_panel(d, [eng_x, eng_y, eng_x + eng_w, eng_y + eng_h],
                  fill=(98, 100, 167, 245), outline=(255, 255, 255), width=3, radius=28)
    d.text((eng_x + 26, eng_y + 24), "Teams Simulator", font=box_f, fill=WHITE)
    d.text((eng_x + 26, eng_y + 60), "Python · sounddevice · pyvirtualcam",
           font=sub_f, fill=(220, 224, 245))

    pipe_top = eng_y + 120
    rounded_panel(d, [eng_x + 26, pipe_top, eng_x + eng_w - 26, pipe_top + 80],
                  fill=(255, 255, 255, 245), outline=(255, 255, 255),
                  width=2, radius=14)
    d.text((eng_x + 44, pipe_top + 12), "Audio pipeline", font=box_f, fill=TEAMS_PURPLE_DARK)
    d.text((eng_x + 44, pipe_top + 48),
           "block-aligned OutputStream  →  CABLE Input",
           font=note_f, fill=INK_LIGHT)

    pipe_top2 = pipe_top + 110
    rounded_panel(d, [eng_x + 26, pipe_top2, eng_x + eng_w - 26, pipe_top2 + 80],
                  fill=(255, 255, 255, 245), outline=(255, 255, 255),
                  width=2, radius=14)
    d.text((eng_x + 44, pipe_top2 + 12), "Video pipeline", font=box_f, fill=TEAMS_PURPLE_DARK)
    d.text((eng_x + 44, pipe_top2 + 48),
           "BGR frames  →  OBS Virtual Camera @ 30 fps",
           font=note_f, fill=INK_LIGHT)

    # Driver boxes
    drv_x = 1160
    drv_w = 380
    rounded_panel(d, [drv_x, 200, drv_x + drv_w, 200 + src_h],
                  fill=(255, 255, 255, 240), outline=ACCENT, width=3)
    emoji(drv_x + 22, 216, "🎙️")
    d.text((drv_x + 76, 222), "CABLE Output", font=box_f, fill=INK)
    d.text((drv_x + 22, 264), "VB-Audio Virtual Cable",
           font=sub_f, fill=INK_LIGHT)
    d.text((drv_x + 22, 292), "→ Teams Microphone",
           font=sub_f, fill=TEAMS_PURPLE)

    rounded_panel(d, [drv_x, 400, drv_x + drv_w, 400 + src_h],
                  fill=(255, 255, 255, 240), outline=ACCENT, width=3)
    emoji(drv_x + 22, 416, "📷")
    d.text((drv_x + 76, 422), "OBS Virtual Camera", font=box_f, fill=INK)
    d.text((drv_x + 22, 464), "DirectShow filter (no GUI needed)",
           font=sub_f, fill=INK_LIGHT)
    d.text((drv_x + 22, 492), "→ Teams Camera",
           font=sub_f, fill=TEAMS_PURPLE)

    # Arrows
    arrow_color = (98, 100, 167)
    draw_arrow(d, src_x + src_w + 10, 265, eng_x - 10, 320, color=arrow_color, width=5)
    draw_arrow(d, src_x + src_w + 10, 465, eng_x - 10, 420, color=arrow_color, width=5)
    draw_arrow(d, eng_x + eng_w + 10, 320, drv_x - 10, 265, color=arrow_color, width=5)
    draw_arrow(d, eng_x + eng_w + 10, 420, drv_x - 10, 465, color=arrow_color, width=5)

    # Footer
    d.text((60, H - 60),
           "Both virtual devices are pure user-space software. No GPU. No real microphone.",
           font=sub_f, fill=INK_LIGHT)

    out = ASSETS / "architecture.png"
    bg.convert("RGB").save(out, optimize=True)
    print(f"wrote {out} ({W}x{H})")
    return out


def main() -> None:
    make_hero()
    make_architecture()


if __name__ == "__main__":
    main()
