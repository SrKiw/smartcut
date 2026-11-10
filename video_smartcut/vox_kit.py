#!/usr/bin/env python3
"""Vox-style print look: paper, normalization, blend modes, halftone, riso overprint, layered backgrounds.
Library:  import vox_kit as vk   (numpy float images in 0..1, shape HxWx3 or HxW)
QA:       python -I vox_kit.py check-cuts VIDEO t1 t2 ... --ffmpeg PATH
Needs numpy and pillow.
"""
import argparse
import os
import shutil
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont


def hex2rgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)], np.float32)


def luma(img):
    return img if img.ndim == 2 else img @ np.array([0.2126, 0.7152, 0.0722], np.float32)


def rgb(gray):
    return np.repeat(gray[..., None], 3, axis=2)


def blur(gray, r):
    im = Image.fromarray((np.clip(gray, 0, 1) * 255).astype(np.uint8))
    return np.asarray(im.filter(ImageFilter.GaussianBlur(r)), np.float32) / 255


def fractal_noise(h, w, seed=0, octaves=6, base=4):
    rng = np.random.default_rng(seed)
    out = np.zeros((h, w), np.float32)
    amp, tot = 1.0, 0.0
    for o in range(octaves):
        n = base * 2 ** o
        g = rng.random((max(2, int(n * h / w)) + 1, n + 1), dtype=np.float32)
        im = Image.fromarray(g).resize((w, h), Image.BICUBIC)
        out += amp * np.asarray(im, np.float32)
        tot += amp
        amp *= 0.55
    out /= tot
    return (out - out.min()) / (np.ptp(out) + 1e-6)


def paper(h, w, seed=0, folds=3):
    """Neutral paper/grunge plate, roughly gray. Normalize before using it with overlay modes."""
    rng = np.random.default_rng(seed)
    t = 0.5 + 0.28 * (fractal_noise(h, w, seed) - 0.5)
    t += 0.05 * rng.standard_normal((h, w), dtype=np.float32)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    for i in range(folds):
        a, c = rng.uniform(0, np.pi), rng.uniform(0, h + w)
        d = xx * np.cos(a) + yy * np.sin(a) - c * 0.6
        t += 0.05 * np.exp(-(d / 2.5) ** 2) - 0.035 * np.exp(-((d - 5) / 3) ** 2)
    specks = blur((rng.random((h, w)) > 0.9994).astype(np.float32), 1.2) * 3
    return np.clip(t - 0.35 * specks, 0, 1)


def grain(h, w, seed=0, sigma=0.04):
    return np.random.default_rng(seed).normal(0, sigma, (h, w)).astype(np.float32)


def normalize(tex):
    """Desaturate, then move the gray point to the histogram peak so the plate centers on 50% gray."""
    g = luma(tex)
    hist, edges = np.histogram(g, bins=256, range=(0, 1))
    peak = float(np.clip(edges[hist.argmax()] + 0.5 / 256, 0.02, 0.98))
    return np.clip(g, 0, 1) ** (np.log(0.5) / np.log(peak))


def levels_strength(tex, k=1.0):
    """Stacked levels: k>1 strengthens a normalized plate, k<1 softens it, staying centered on 50%."""
    return np.clip(0.5 + (tex - 0.5) * k, 0, 1)


def _soft(a, b):
    return (1 - 2 * b) * a * a + 2 * b * a


def _over(a, b):
    return np.where(a < 0.5, 2 * a * b, 1 - 2 * (1 - a) * (1 - b))


MODES = {
    # Darken family: the plate has a WHITE background.
    "multiply": lambda a, b: a * b,
    "darken": np.minimum,
    # Lighten family: the plate has a BLACK background.
    "screen": lambda a, b: 1 - (1 - a) * (1 - b),
    "lighten": np.maximum,
    # Contrast family: normalize the plate first.
    "overlay": _over,
    "soft_light": _soft,
    "linear_light": lambda a, b: np.clip(a + 2 * b - 1, 0, 1),
    "hard_mix": lambda a, b: (a + b >= 1).astype(np.float32),
}


def blend(base, top, mode="multiply", opacity=1.0):
    if top.ndim == 2 and base.ndim == 3:
        top = rgb(top)
    return np.clip(base * (1 - opacity) + MODES[mode](base, top) * opacity, 0, 1)


def tint(gray, black="#17191B", white="#2B2F31"):
    """Map blacks and whites. Close values give the subtle layered background."""
    b, w = hex2rgb(black), hex2rgb(white)
    return b + luma(gray)[..., None] * (w - b)


def halftone(gray, cell=10, angle=45.0, soft=0.12):
    """Dark areas get bigger, denser dots; light areas smaller, spaced-out dots. White=paper, black=ink."""
    h, w = gray.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    a = np.deg2rad(angle)
    u = (xx * np.cos(a) + yy * np.sin(a)) / cell
    v = (-xx * np.sin(a) + yy * np.cos(a)) / cell
    spot = 0.5 + 0.25 * (np.cos(2 * np.pi * u) + np.cos(2 * np.pi * v))
    return np.clip((spot - (1 - gray) + soft) / (2 * soft), 0, 1)


def riso(layers, inks, paper_rgb, offsets=None, cell=9, tex=None, seed=0):
    """Overprint: ink passes, each tinted, halftoned, misregistered and multiplied."""
    h, w = layers[0].shape
    out = np.ones((h, w, 3), np.float32) * paper_rgb
    rng = np.random.default_rng(seed)
    offsets = offsets or [(0, 0)] + [tuple(rng.integers(-9, 10, 2)) for _ in layers[1:]]
    for i, (lay, ink) in enumerate(zip(layers, inks)):
        dot = halftone(lay, cell=cell, angle=15 + 30 * i)
        dot = np.roll(dot, offsets[i], axis=(1, 0))
        if tex is not None:
            dot = np.clip(dot + (1 - tex) * 0.28 - 0.08, 0, 1)
        layer = 1 - (1 - dot[..., None]) * (1 - hex2rgb(ink))
        out = out * layer
    return np.clip(out, 0, 1)


def layered_background(plates, h, w, black="#141618", white="#2A2E30", seed=0):
    """Plates: (gray, x, y) images on the subject. Collage, tint subtly, texture."""
    canvas = np.zeros((h, w), np.float32)
    for gray, x, y in plates:
        ph, pw = gray.shape
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(w, x + pw), min(h, y + ph)
        if x1 > x0 and y1 > y0:
            canvas[y0:y1, x0:x1] = np.maximum(canvas[y0:y1, x0:x1], gray[y0 - y:y1 - y, x0 - x:x1 - x])
    out = tint(canvas, black, white)
    return blend(out, normalize(paper(h, w, seed)), "overlay", 0.7)


def ease_out(t):
    t = np.clip(t, 0, 1)
    return 1 - (1 - t) ** 3


def back_out(t, s=1.4):
    t = np.clip(t, 0, 1) - 1
    return t * t * ((s + 1) * t + s) + 1


def hold(t, fps=12):
    """Quantize time to a lower frame rate (12 = on twos at 24 fps)."""
    return np.floor(t * fps + 1e-6) / fps


def in_moment(t, moments):
    return any(a <= t < b for a, b in moments)


def stepped(t, moments, fps=12):
    """Smooth time, except inside the (start, end) moments, where it steps at fps."""
    return hold(t, fps) if in_moment(t, moments) else t


def blur_reveal_mask(w, progress, soft=0.18):
    """Left-to-right blur-on reveal: 1 = sharp. Combine a sharp and a blurred text render."""
    x = np.linspace(0, 1, w, dtype=np.float32)
    return np.clip((progress * (1 + soft) - x) / soft, 0, 1)


def rgba_layer(rgb_img, alpha):
    """Stack HxWx3 color and HxW alpha into a uint8 RGBA PIL image for depth_render."""
    a = np.dstack([np.clip(rgb_img, 0, 1), np.clip(alpha, 0, 1)])
    return Image.fromarray((a * 255).astype(np.uint8), "RGBA")


def depth_render(layers, h, w, cam=(0.0, 0.0, 0.0), focus_z=1000.0, focal=1000.0, dof=0.012, bg=(0, 0, 0)):
    """Pinhole camera over flat cut-outs. layers: dicts with img (RGBA PIL), z, x, y, optional scale, blur.
    Screen size is focal/(z-cam_z), so near layers move and grow faster. Blur grows away from focus_z."""
    cx, cy, cz = cam
    out = Image.new("RGBA", (w, h), tuple(bg) + (255,))
    for L in sorted(layers, key=lambda l: -l["z"]):
        d = L["z"] - cz
        if d <= 60:
            continue
        s = focal / d * L.get("scale", 1.0)
        nw, nh = int(L["img"].width * s), int(L["img"].height * s)
        if nw < 2 or nh < 2 or nw > 6000 or nh > 6000:
            continue
        im = L["img"].resize((nw, nh), Image.BILINEAR)
        r = abs(d - (focus_z - cz)) * dof + L.get("blur", 0)
        if r > 0.4:
            im = im.filter(ImageFilter.GaussianBlur(min(r, 40)))
        px = w / 2 + (L.get("x", 0) - cx) * s - nw / 2
        py = h / 2 + (L.get("y", 0) - cy) * s - nh / 2
        out.paste(im, (int(px), int(py)), im)
    return np.asarray(out.convert("RGB"), np.float32) / 255


def motion_at_cuts(ff, src, cuts, fps=None, thresh=0.3, span=3):
    """Motion just before and after each hard cut, on a heavy downscale so grain doesn't count."""
    W, H = 72, 128
    p = subprocess.run([ff, "-nostdin", "-v", "error", "-i", src, "-vf", f"scale={W}:{H}:flags=area", "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True)
    fr = np.frombuffer(p.stdout, np.uint8).reshape(-1, H, W).astype(np.float32)
    if fps is None:
        info = subprocess.run([ff, "-hide_banner", "-i", src], capture_output=True, text=True).stderr
        fps = float(info.split(" fps")[0].split()[-1])
    d = np.abs(fr[1:] - fr[:-1]).mean(axis=(1, 2))
    res = []
    for t in cuts:
        c = int(np.argmax(d[max(0, int(t * fps) - 2):int(t * fps) + 3])) + max(0, int(t * fps) - 2)
        before, after = float(d[max(0, c - span):c].mean()), float(d[c + 1:c + 1 + span].mean())
        verdict = "EN MOVIMIENTO" if before > thresh and after > thresh else "QUIETO: revisar"
        res.append((round(c / fps + 1 / fps, 2), round(before, 2), round(after, 2), verdict))
    return res


def find_font(names):
    # primero las de este proyecto y las de Windows (la lista original solo buscaba en rutas de Mac)
    roots = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "public"), "C:/Windows/Fonts",
             os.path.expanduser("~/Library/Fonts"), "/Library/Fonts", "/System/Library/Fonts/Supplemental", "/System/Library/Fonts"]
    for n in names:
        for r in roots:
            p = os.path.join(r, n)
            if os.path.exists(p):
                return p
    raise FileNotFoundError(names)


SANS = lambda: find_font(["Helvetica-Bold.ttf", "Arial Bold.ttf", "arialbd.ttf", "Helvetica.ttc"])
SERIF = lambda: find_font(["Georgia Bold.ttf", "georgiab.ttf", "Times New Roman Bold.ttf", "Georgia.ttf"])
SERIF_IT = lambda: find_font(["Georgia Italic.ttf", "georgiai.ttf", "Times New Roman Italic.ttf", "Georgia.ttf"])


def text_mask(h, w, text, font_path, size, cx, cy, squeeze=1.0):
    """White-on-black alpha for one line, centered at (cx, cy). squeeze<1 condenses it."""
    f = ImageFont.truetype(font_path, size)
    l, t, r, b = f.getbbox(text)
    tw, th = r - l, b - t
    im = Image.new("L", (tw + 8, th + 8), 0)
    ImageDraw.Draw(im).text((4 - l, 4 - t), text, font=f, fill=255)
    if squeeze != 1.0:
        im = im.resize((max(1, int(im.width * squeeze)), im.height), Image.LANCZOS)
    out = Image.new("L", (w, h), 0)
    out.paste(im, (int(cx - im.width / 2), int(cy - im.height / 2)))
    return np.asarray(out, np.float32) / 255


def caption_pill(frame, text, cy=1140, fill="#111111", size=46, alpha=0.88):
    """Small uppercase caption on a rounded pill. cy defaults to the Reels safe band (1080-1210)."""
    h, w = frame.shape[:2]
    f = ImageFont.truetype(SANS(), size)
    l, t, r, b = f.getbbox(text.upper())
    tw, th = r - l, b - t
    pad_x, pad_y = 22, 14
    x0, y0 = int(w / 2 - tw / 2 - pad_x), int(cy - th / 2 - pad_y)
    x1, y1 = int(w / 2 + tw / 2 + pad_x), int(cy + th / 2 + pad_y)
    im = Image.fromarray((frame * 255).astype(np.uint8))
    ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    c = tuple(int(v * 255) for v in hex2rgb(fill)) + (int(255 * alpha),)
    d.rounded_rectangle((x0, y0, x1, y1), radius=12, fill=c)
    d.text((w / 2 - tw / 2 - l, cy - th / 2 - t), text.upper(), font=f, fill=(255, 255, 255, 255))
    return np.asarray(Image.alpha_composite(im.convert("RGBA"), ov).convert("RGB"), np.float32) / 255


def hand_arrow(h, w, p0, p1, bend=60, progress=1.0, width=7, seed=0):
    """Hand-drawn annotation arrow as an alpha mask, drawing on with progress."""
    rng = np.random.default_rng(seed)
    p0, p1 = np.array(p0, float), np.array(p1, float)
    n = p1 - p0
    ctrl = (p0 + p1) / 2 + np.array([n[1], -n[0]]) / (np.linalg.norm(n) + 1e-6) * bend
    ts = np.linspace(0, max(0.01, progress), 40)
    pts = [(1 - t) ** 2 * p0 + 2 * t * (1 - t) * ctrl + t * t * p1 for t in ts]
    pts = [tuple(p + rng.normal(0, 0.8, 2)) for p in pts]
    im = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(im)
    d.line(pts, fill=255, width=width, joint="curve")
    if progress >= 0.98:
        tip, prev = np.array(pts[-1]), np.array(pts[-5])
        v = (tip - prev) / (np.linalg.norm(tip - prev) + 1e-6)
        for ang in (2.55, -2.55):
            c, s = np.cos(ang), np.sin(ang)
            e = tip + 34 * np.array([v[0] * c - v[1] * s, v[0] * s + v[1] * c])
            d.line([tuple(tip), tuple(e)], fill=255, width=width)
    return np.asarray(im, np.float32) / 255


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["check-cuts"])
    ap.add_argument("path")
    ap.add_argument("times", nargs="*", type=float)
    ap.add_argument("--ffmpeg", default=shutil.which("ffmpeg"))
    a = ap.parse_args()
    for row in motion_at_cuts(a.ffmpeg, a.path, a.times):
        print(row)
