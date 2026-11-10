# Solo 3 texturas, normalizadas como pide la skill: papel para el fondo, y halftone de comic con ruido para encima de todo.
from pathlib import Path

import numpy as np
from PIL import Image

import vox_kit as vk

P = Path(__file__).resolve().parent / "public"
REPO = Path.home() / ".claude/skills/vox-style-animation/assets/texturas"


def guardar(arr, nombre):
    Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8)).save(P / nombre, quality=92)


def plancha(ruta, w, h, centro=1.0):
    im = Image.open(ruta).convert("RGB")
    cw, ch = int(im.width * centro), int(im.height * centro)
    im = im.crop(((im.width - cw) // 2, (im.height - ch) // 2, (im.width + cw) // 2, (im.height + ch) // 2))
    k = max(w / im.width, h / im.height)
    im = im.resize((int(im.width * k) + 1, int(im.height * k) + 1), Image.LANCZOS)
    x, y = (im.width - w) // 2, (im.height - h) // 2
    return np.asarray(im.crop((x, y, x + w, y + h)), np.float32) / 255


# 1. papel robusto: el centro de la hoja arrugada, sin sus bordes negros
guardar(vk.normalize(plancha(REPO / "papel/tl_paper_367.jpg", 1400, 2200, 0.72)), "t_papel.jpg")

# 2 y 3. halftone de comic + ruido, centrados en gris 50 % para que solo sumen textura
comic = vk.normalize(plancha(REPO / "grunge/tl_grunge_351.jpg", 1080, 1920))
ruido = vk.grain(1920, 1080, seed=7, sigma=0.05)
guardar(np.clip(vk.levels_strength(comic, 1.5) + ruido, 0, 1), "o_comic.jpg")

# fotogramas de la pelicula: dos tintas (negro sobre amarillo). Es dibujo de la tira, no textura de fondo
for i in (1, 2, 3, 4):
    g = plancha(P / f"f{i}.jpg", 640, 360).mean(axis=2)
    tinta = vk.halftone(np.clip((g - 0.12) * 1.5, 0, 1), cell=7, angle=35)
    guardar((np.ones((360, 640, 3), np.float32) * vk.hex2rgb("#FFD60A")) * tinta[..., None], f"h{i}.jpg")
print("texturas listas")
