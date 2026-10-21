"""Derive every AGRO-AI Academy logo asset from the official lockup.

    node scripts/brand/render-logo.mjs /tmp/logo@2x.png
    python3 scripts/brand/build_assets.py /tmp/logo@2x.png

The input is the transparent 2x render of brand/agro-ai-academy-logo.svg. The
lockup has three horizontal bands: the mark, the AGRO-AI wordmark and the
ACADEMY wordmark. Assets only crop, scale, recolour (for dark surfaces) or
rearrange those official pixels; nothing is redrawn.

Writes public/static/brand/*, public/favicon.ico and src/lib/brand-jpeg.js.
"""

import base64
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "public/static/brand"
LIME = np.array([214, 252, 91])  # brightest tone of the mark
CREAM = (255, 253, 248)  # certificate paper


def bands(img):
    """Row ranges of the mark, AGRO-AI and ACADEMY, found from the alpha gaps."""
    alpha = np.array(img.getchannel("A")) > 20
    rows = np.where(alpha.any(axis=1))[0]
    runs, start = [], rows[0]
    for prev, cur in zip(rows, rows[1:]):
        if cur - prev > 3:
            runs.append((start, prev + 1))
            start = cur
    runs.append((start, rows[-1] + 1))
    if len(runs) != 3:
        raise SystemExit(f"expected 3 bands (mark, AGRO-AI, ACADEMY), found {len(runs)}")
    return runs


def trim(img):
    return img.crop(img.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox())


def light_variant(img, agro, academy):
    """Wordmark recoloured for dark surfaces: AGRO-AI white, ACADEMY lime."""
    a = np.array(img).astype(float)
    a[agro[0]:agro[1], :, :3] = 255
    seg = a[academy[0]:academy[1], :, :3]
    a[academy[0]:academy[1], :, :3] = seg * 0.3 + LIME * 0.7
    return Image.fromarray(a.clip(0, 255).astype("uint8"), "RGBA")


def horizontal(img, mark_band, word_top, word_bottom):
    """Mark beside the stacked wordmark (AGRO-AI over ACADEMY)."""
    mark = trim(img.crop((0, mark_band[0], img.width, mark_band[1])))
    words = trim(img.crop((0, word_top, img.width, word_bottom)))
    h = mark.height
    wh = round(h * 0.6)
    words = words.resize((round(words.width * wh / words.height), wh), Image.LANCZOS)
    gap = round(h * 0.2)
    canvas = Image.new("RGBA", (mark.width + gap + words.width, h), (0, 0, 0, 0))
    canvas.alpha_composite(mark, (0, 0))
    canvas.alpha_composite(words, (mark.width + gap, (h - wh) // 2))
    return canvas


def fit(img, height=None, width=None):
    if height:
        return img.resize((round(img.width * height / img.height), height), Image.LANCZOS)
    return img.resize((width, round(img.height * width / img.width)), Image.LANCZOS)


def square(img, size, pad=0.0, bg=None):
    inner = round(size * (1 - 2 * pad))
    m = fit(img, height=inner) if img.height >= img.width else fit(img, width=inner)
    canvas = Image.new("RGBA", (size, size), bg or (0, 0, 0, 0))
    canvas.alpha_composite(m, ((size - m.width) // 2, (size - m.height) // 2))
    return canvas


def on(img, color):
    bg = Image.new("RGBA", img.size, color + (255,))
    bg.alpha_composite(img)
    return bg.convert("RGB")


def save_png(img, name, webp=False):
    path = OUT / name
    img.save(path, optimize=True)
    print(f"{path.relative_to(ROOT)}  {img.width}x{img.height}  {path.stat().st_size // 1024} KB")
    if webp:  # pages use WebP; PNG stays for email clients
        wpath = path.with_suffix(".webp")
        img.save(wpath, "WEBP", quality=88, method=6)
        print(f"{wpath.relative_to(ROOT)}  {wpath.stat().st_size // 1024} KB")


def social_card(light_stacked):
    """1200x630 share image: the light lockup on the brand's forest gradient."""
    w, h = 1200, 630
    y, x = np.mgrid[0:h, 0:w].astype(float)
    deep, mid = np.array([8, 37, 3]), np.array([28, 76, 7])
    t = np.clip((x / w) * 0.55 + (y / h) * 0.45, 0, 1)[..., None]
    base = deep * (1 - t) + mid * t
    glow = np.exp(-(((x - w * 0.82) / 420) ** 2 + ((y - h * 0.1) / 300) ** 2))[..., None]
    rgb = base * (1 - 0.35 * glow) + np.array([111, 172, 30]) * 0.35 * glow
    card = Image.fromarray(rgb.clip(0, 255).astype("uint8"), "RGB").convert("RGBA")
    lock = fit(light_stacked, height=470)
    card.alpha_composite(lock, ((w - lock.width) // 2, (h - lock.height) // 2))
    return card.convert("RGB")


def main(src):
    OUT.mkdir(parents=True, exist_ok=True)
    img = Image.open(src).convert("RGBA")
    mark_b, agro_b, academy_b = bands(img)
    light = light_variant(img, agro_b, academy_b)
    mark = trim(img.crop((0, mark_b[0], img.width, mark_b[1])))

    # Stacked lockup (hero, auth, about) and its dark-surface variant.
    save_png(fit(trim(img), width=560), "academy-lockup.png", webp=True)
    save_png(fit(trim(light), width=560), "academy-lockup-light.png", webp=True)
    # Horizontal lockup (header, footer, email, certificate).
    horiz = horizontal(img, mark_b, agro_b[0], academy_b[1])
    horiz_light = horizontal(light, mark_b, agro_b[0], academy_b[1])
    save_png(fit(horiz, height=112), "academy-lockup-h.png", webp=True)
    save_png(fit(horiz_light, height=112), "academy-lockup-h-light.png", webp=True)
    # Mark: favicons, app icons, schema.org logo.
    for size in (32, 64, 128, 192, 512):
        save_png(square(mark, size), f"academy-mark-{size}.png")
    touch = square(mark, 180, pad=0.12, bg=(255, 255, 255, 255)).convert("RGB")
    save_png(touch, "apple-touch-icon.png")
    touch.save(ROOT / "public/apple-touch-icon.png", optimize=True)  # iOS requests it at the root
    square(mark, 48).save(ROOT / "public/favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    print("public/favicon.ico  16/32/48")
    # Email header: opaque, since some clients mishandle PNG transparency.
    save_png(on(fit(horiz, height=88), (255, 255, 255)), "email-lockup.png")
    save_png(social_card(trim(light)), "og-academy.png")

    # Certificate header, embedded in every PDF as a baseline JPEG.
    cert = on(fit(horiz, height=176), CREAM)
    from io import BytesIO

    buf = BytesIO()
    cert.save(buf, "JPEG", quality=90, optimize=True, progressive=False)
    b64 = base64.b64encode(buf.getvalue()).decode()
    (ROOT / "src/lib/brand-jpeg.js").write_text(
        "// Generated by scripts/brand/build_assets.py from brand/agro-ai-academy-logo.svg — do not edit.\n"
        "// Horizontal AGRO-AI Academy lockup on certificate paper, as a baseline JPEG for certificate PDFs.\n"
        f'export const LOCKUP_JPEG_B64 =\n  "{b64}";\n'
        f"export const LOCKUP_JPEG_WIDTH = {cert.width};\n"
        f"export const LOCKUP_JPEG_HEIGHT = {cert.height};\n"
    )
    print(f"src/lib/brand-jpeg.js  {cert.width}x{cert.height}  {len(buf.getvalue()) // 1024} KB")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
