"""Draw the Forever GB Player logo.

    py scripts/make_logo.py

Writes:
  media/logo.png                 512x512, for the CurseForge project page
  ForeverGBPlayer/media/icon.png 64x64, the addon's icon in WoW's AddOns list (## IconTexture)

An original handheld (deliberately not Nintendo's hardware design or logo) whose 4-shade
green screen shows a pixel-art infinity sign: "Forever". Drawn at 1024 px and scaled down;
the screen's pixel art is drawn as hard-edged squares so it stays crisp.
"""
import pathlib

from PIL import Image, ImageDraw, ImageFilter

ROOT = pathlib.Path(__file__).resolve().parent.parent
S = 1024

# The addon's own DMG palette (lightest -> darkest), same as the atlas and test tools.
SHADES = [(224, 248, 208), (136, 192, 112), (52, 104, 86), (8, 24, 32)]
BG_TOP, BG_BOTTOM = (38, 52, 64), (12, 18, 24)
BODY, BODY_SHADE, BODY_EDGE = (222, 219, 210), (196, 192, 182), (150, 146, 138)
BEZEL = (54, 58, 70)
DPAD = (40, 42, 50)
BUTTON, BUTTON_SHADE = (226, 160, 52), (170, 110, 30)   # amber: an original accent
PILL = (120, 120, 128)


def vertical_gradient(size, top, bottom):
    w, h = size
    grad = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / (h - 1)
        grad.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)))
    return grad.resize((w, h))


def rounded_mask(size, box, radius):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle(box, radius=radius, fill=255)
    return m


# Hand-drawn pixel-art infinity sign ("#" = darkest shade), 18 x 7.
INFINITY = [
    "...####....####...",
    "..##..##..##..##..",
    ".##....####....##.",
    ".##.....##.....##.",
    ".##....####....##.",
    "..##..##..##..##..",
    "...####....####...",
]


def infinity_pixels(n=20):
    """n x n grid of shade indices: the infinity sprite, centred, with a drop shadow."""
    grid = [[0] * n for _ in range(n)]
    ox, oy = (n - len(INFINITY[0])) // 2, (n - len(INFINITY)) // 2
    cells = {(ox + x, oy + y) for y, row in enumerate(INFINITY) for x, c in enumerate(row) if c == "#"}
    for gx, gy in cells:  # 1-pixel shadow down-right in the mid shade
        if (gx + 1, gy + 1) not in cells:
            grid[gy + 1][gx + 1] = 2
    for gx, gy in cells:
        grid[gy][gx] = 3
    for gx, gy in ((3, 3), (16, 15), (15, 3)):  # sparkles
        if grid[gy][gx] == 0:
            grid[gy][gx] = 1
    return grid


def draw_logo():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    # Background tile: dark slate rounded square.
    bg = vertical_gradient((S, S), BG_TOP, BG_BOTTOM).convert("RGBA")
    img.paste(bg, (0, 0), rounded_mask((S, S), (0, 0, S - 1, S - 1), 190))

    # Handheld body with a soft drop shadow.
    body_box = (250, 96, 774, 940)
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((body_box[0] + 14, body_box[1] + 26, body_box[2] + 14, body_box[3] + 26),
                                             radius=70, fill=(0, 0, 0, 150))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(22)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(body_box, radius=70, fill=BODY_EDGE)
    d.rounded_rectangle((body_box[0] + 6, body_box[1] + 4, body_box[2] - 6, body_box[3] - 10), radius=66, fill=BODY)
    # lower half slightly darker for form
    lower = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(lower).rounded_rectangle((body_box[0] + 6, 600, body_box[2] - 6, body_box[3] - 10), radius=66,
                                            fill=BODY_SHADE + (255,))
    ImageDraw.Draw(lower).rectangle((body_box[0] + 6, 600, body_box[2] - 6, 680), fill=BODY + (255,))
    img.alpha_composite(lower)
    d = ImageDraw.Draw(img)

    # Screen bezel and the 4-shade screen with the pixel-art infinity sign.
    d.rounded_rectangle((300, 150, 724, 570), radius=34, fill=BEZEL)
    n, px = 20, 16
    sx0, sy0 = 512 - n * px // 2, 360 - n * px // 2
    grid = infinity_pixels(n)
    for gy in range(n):
        for gx in range(n):
            x, y = sx0 + gx * px, sy0 + gy * px
            d.rectangle((x, y, x + px - 1, y + px - 1), fill=SHADES[grid[gy][gx]])
    # power LED
    d.ellipse((318, 344, 334, 360), fill=(232, 72, 64))

    # D-pad (a plus with a small bevel)
    cx, cy, arm, w = 378, 724, 66, 46
    d.rounded_rectangle((cx - arm, cy - w // 2, cx + arm, cy + w // 2), radius=8, fill=DPAD)
    d.rounded_rectangle((cx - w // 2, cy - arm, cx + w // 2, cy + arm), radius=8, fill=DPAD)
    d.ellipse((cx - 12, cy - 12, cx + 12, cy + 12), fill=(58, 60, 70))

    # Two face buttons, set diagonally
    for bx, by in ((610, 748), (690, 690)):
        d.ellipse((bx - 40, by - 36, bx + 40, by + 44), fill=BUTTON_SHADE)
        d.ellipse((bx - 40, by - 40, bx + 40, by + 40), fill=BUTTON)
        d.ellipse((bx - 24, by - 30, bx + 6, by - 12), fill=(244, 202, 120))

    # Start / select pills
    for px0 in (442, 532):
        d.rounded_rectangle((px0, 840, px0 + 56, 862), radius=11, fill=PILL)
    return img


def main():
    big = draw_logo()
    out_logo = ROOT / "media" / "logo.png"
    out_icon = ROOT / "ForeverGBPlayer" / "media" / "icon.png"
    out_logo.parent.mkdir(parents=True, exist_ok=True)
    out_icon.parent.mkdir(parents=True, exist_ok=True)
    big.resize((512, 512), Image.LANCZOS).save(out_logo, optimize=True)
    big.resize((64, 64), Image.LANCZOS).save(out_icon, optimize=True)
    for p in (out_logo, out_icon):
        print(f"wrote {p} ({p.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
