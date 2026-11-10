# -*- coding: utf-8 -*-
"""SmartCut - generador de portadas (v0.4). La portada se arma con el video limpio, sin subtitulos.

    python portadas.py "resultados/<carpeta>"                      una portada por clip
    python portadas.py "resultados/<carpeta>" --plantilla etiquetas --clip 03 --rehacer

Lo que hace:
  - Busca los mejores cuadros de cada clip: nitidos, bien expuestos y con la cara grande.
  - Monta el titulo del clip con una plantilla y los colores, letra y logo del cliente.
  - Guarda el diseno en proyecto/portadaNN.json y el .jpg en portadas/.
El editor (editor.py) usa este mismo render para la vista previa: lo que ves es lo que sale.
"""
from __future__ import annotations

import argparse
import base64
import datetime as _dt
import io
import json
import os
import re
import subprocess
import sys
import threading
from collections import OrderedDict
from pathlib import Path

import numpy as np

import miopusclip as m

VERSION_DISENO = 1
FORMATOS = ("9:16", "4:5", "1:1", "16:9")
PLANTILLAS = OrderedDict([
    ("titular", "Titular abajo"),
    ("etiquetas", "Etiquetas de color"),
    ("impacto", "Impacto al centro"),
    ("arriba", "Titular arriba"),
    ("banda", "Banda de marca"),
    ("youtube", "YouTube: persona con glow"),
])
TEXTO_DEFECTO = {
    "tipo": "texto", "texto": "", "x": 0.5, "y": 0.6, "ancho": 0.86, "fuente": "Montserrat Black", "tam": 0.12,
    "color": "#FFFFFF", "color_clave": "#FFD60A", "clave_modo": "color", "mayusculas": True, "alinear": "centro",
    "interlineado": 1.0, "contorno": 0.0, "color_contorno": "#000000", "sombra": 0.55, "caja": "no",
    "color_caja": "#E10600", "opacidad_caja": 1.0, "radio_caja": 0.14, "rotacion": 0.0, "opacidad": 1.0, "visible": True,
}
IMAGEN_DEFECTO = {"tipo": "imagen", "origen": "cliente", "ruta": "", "x": 0.5, "y": 0.16, "ancho": 0.3, "redondo": False,
                  "cara": False, "borde": 0.0, "color_borde": "#FFFFFF", "rotacion": 0.0, "opacidad": 1.0, "visible": True}
FORMA_DEFECTO = {"tipo": "forma", "x": 0.5, "y": 0.66, "ancho": 1.0, "alto": 0.3, "color": "#E10600", "radio": 0.0,
                 "rotacion": 0.0, "opacidad": 1.0, "visible": True}
FONDO_DEFECTO = {"tipo": "cuadro", "t": 0.0, "ajuste": "cubrir", "cx": 0.5, "cy": 0.5, "cx2": 0.7, "zoom": 1.0,
                 "origen": "proyecto", "ruta": "", "color": "#111111", "oscurecer": 0.0, "desenfoque": 0.0, "punch": 1.0,
                 "degradado": "no", "fuerza_degradado": 0.8, "tam_degradado": 0.55, "color_degradado": "#000000", "bajar": 0.0,
                 "mejorar": 0.0, "persona": None}
# La persona recortada del fondo (v0.6): queda nitida encima del fondo oscurecido/desenfocado, con contorno o glow.
PERSONA_DEFECTO = {"activa": False, "estilo": "glow", "color": "#2F7BFF", "grosor": 0.008, "glow": 0.035,
                   "intensidad": 0.9, "px": None, "py": None}

_MATTES: OrderedDict = OrderedDict()
_CANDADO_MODNET = threading.Lock()
_MODNET = {}
_CUADROS: OrderedDict = OrderedDict()
_FONDOS: OrderedDict = OrderedDict()
_IMAGENES: OrderedDict = OrderedDict()
_CANDADO = threading.Lock()
_CANDADO_CARAS = threading.Lock()  # el detector de caras es uno solo y se reajusta en cada uso


# --------------------------------------------------------------------------------------
# utilidades
# --------------------------------------------------------------------------------------

def _leer(p: Path, defecto=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return defecto


def _escribir(p: Path, datos) -> None:
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def _guardar_lru(cache: OrderedDict, clave, valor, maximo: int):
    with _CANDADO:
        cache[clave] = valor
        cache.move_to_end(clave)
        while len(cache) > maximo:
            cache.popitem(last=False)
    return valor


def _sacar_lru(cache: OrderedDict, clave):
    with _CANDADO:
        v = cache.get(clave)
        if v is not None:
            cache.move_to_end(clave)
        return v


def _rgb(color, defecto=(255, 255, 255)) -> tuple:
    from PIL import ImageColor
    try:
        return ImageColor.getrgb(str(color))[:3]
    except Exception:
        return defecto


def _contraste(color) -> str:
    r, g, b = _rgb(color)
    return "#111111" if 0.299 * r + 0.587 * g + 0.114 * b > 150 else "#FFFFFF"


def _num(v, defecto: float, a: float, b: float) -> float:
    try:
        return max(a, min(b, float(v)))
    except (TypeError, ValueError):
        return defecto


def _opacar(im, op: float):
    if op < 0.999:
        im.putalpha(im.getchannel("A").point(lambda v: int(v * op)))
    return im


def _pegar(base, capa, x: int, y: int) -> None:
    """alpha_composite que aguanta capas que se salen del cuadro."""
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(base.width, x + capa.width), min(base.height, y + capa.height)
    if x1 <= x0 or y1 <= y0:
        return
    base.alpha_composite(capa.crop((x0 - x, y0 - y, x1 - x, y1 - y)), (x0, y0))


def linea_clip(d: Path, cid: str) -> dict:
    l = _leer(Path(d) / "proyecto" / f"clip{cid}.json")
    if not l:
        raise RuntimeError(f"No existe el clip {cid} en {Path(d).name}")
    return l


def ruta_diseno(d: Path, cid: str) -> Path:
    return Path(d) / "proyecto" / f"portada{cid}.json"


def ids_clips(d: Path) -> list:
    return sorted(p.stem[4:] for p in (Path(d) / "proyecto").glob("clip[0-9]*.json") if re.fullmatch(r"clip\d+\.json", p.name))


def perfil_de(d: Path, l: dict, diseno: dict | None = None) -> dict | None:
    nombre = (diseno or {}).get("cliente")
    if nombre is None:
        nombre = l.get("cliente") or (_leer(Path(d) / "proyecto.json", {}) or {}).get("cliente")
    return m.cargar_cliente(nombre) if nombre else None


def fuentes_disponibles() -> list:
    """Los nombres que entiende el motor, con la familia y el estilo (p.ej. Montserrat Black)."""
    from PIL import ImageFont
    nombres = set()
    for p in list(m.FUENTES.glob("*.ttf")) + list(m.FUENTES.glob("*.otf")):
        try:
            fam, est = ImageFont.truetype(str(p), 20).getname()
            nombres.add(fam if not est or est.lower() == "regular" else f"{fam} {est}")
        except Exception:
            pass
    return sorted(nombres)


def _fuente_valida(nombre: str | None) -> str:
    for n in (f"{nombre} Black", f"{nombre} ExtraBold", nombre, "Montserrat Black", "Montserrat ExtraBold"):
        if n and not n.startswith("None") and m._archivo_fuente(n):
            return n
    return "Montserrat Black"


def marca_de(perfil: dict | None) -> dict:
    """Colores, letra e imagenes de la marca del cliente (bloque "marca" de cliente.json)."""
    global_cfg = m.cargar_config({})
    cfg = (perfil or {}).get("config") or {}
    mc = (perfil or {}).get("marca") or {}
    colores = [c for k, c in (mc.get("colores") or {}).items() if not k.startswith("_")]
    acento = cfg.get("color_activo") or cfg.get("color_clave") or global_cfg.get("color_activo") or "#FFD60A"
    caja = cfg.get("color_hook_fondo") or acento
    fuente = _fuente_valida(mc.get("fuente") or cfg.get("fuente_contraste") or global_cfg.get("fuente_contraste"))
    paleta = list(OrderedDict.fromkeys([*colores, acento, caja, "#FFFFFF", "#111111", "#FFD60A", "#E10600"]))
    return {"colores": paleta, "acento": acento, "caja": caja, "texto_caja": cfg.get("color_hook_texto") or _contraste(caja),
            "fuente": fuente, "imagenes": imagenes_cliente(perfil)}


def imagenes_cliente(perfil: dict | None) -> list:
    if not perfil:
        return []
    carpeta = Path(perfil["_dir"])
    out, vistos = [], set()

    def sumar(p: Path, tipo: str, nombre: str | None = None):
        rel = p.resolve().relative_to(carpeta.resolve()).as_posix()
        if rel not in vistos and p.is_file() and m._es_imagen(p):
            vistos.add(rel)
            out.append({"nombre": nombre or p.stem, "ruta": rel, "tipo": tipo})

    if perfil.get("logo"):
        sumar(Path(perfil["logo"]), "logo", "Logo")
    for nombre, r in ((perfil.get("marca") or {}).get("personas") or {}).items():
        sumar(carpeta / r, "persona", nombre)
    if (carpeta / "marca").exists():
        for p in sorted((carpeta / "marca").iterdir()):
            if p.suffix.lower() == ".png" and "paleta" not in p.stem.lower():
                sumar(p, "logo")
    return out


def _ruta_imagen(d: Path, l: dict, diseno: dict, origen: str, ruta: str) -> Path | None:
    """Solo archivos del cliente o de la carpeta del video: nada de rutas que se salgan."""
    if not ruta:
        return None
    if origen == "cliente":
        perfil = perfil_de(d, l, diseno)
        if not perfil:
            return None
        raiz = Path(perfil["_dir"]).resolve()
    else:
        raiz = Path(d).resolve()
    p = (raiz / ruta).resolve()
    return p if p.is_file() and p.is_relative_to(raiz) and m._es_imagen(p) else None


# --------------------------------------------------------------------------------------
# el cuadro del video, sin subtitulos
# --------------------------------------------------------------------------------------

def cuadro(d: Path, l: dict, t: float):
    """Un cuadro del original a tamano completo. Queda guardado en disco para no volver a sacarlo."""
    from PIL import Image
    clave_t = int(round(float(t) * 25))
    carpeta = Path(d) / "portadas" / "cuadros"
    ruta = carpeta / f"{clave_t:08d}.jpg"
    ya = _sacar_lru(_CUADROS, str(ruta))
    if ya is not None:
        return ya
    if not ruta.exists() or ruta.stat().st_size < 500:
        carpeta.mkdir(parents=True, exist_ok=True)
        tmp = ruta.with_suffix(f".{threading.get_ident()}.tmp.jpg")
        m.correr([m.FFMPEG, "-nostdin", "-v", "error", "-y", "-ss", f"{clave_t / 25:.3f}", "-i", str(l["fuente"]),
                  "-frames:v", "1", "-q:v", "1", "-pix_fmt", "yuvj444p", str(tmp)])
        os.replace(tmp, ruta)
        for viejo in sorted(carpeta.glob("*.jpg"), key=lambda p: p.stat().st_mtime)[:-80]:
            viejo.unlink(missing_ok=True)
    im = Image.open(ruta).convert("RGB")
    im.load()
    return _guardar_lru(_CUADROS, str(ruta), im, 6)


def _toma_en(l: dict, t: float) -> dict:
    tomas = l.get("tomas") or [{"modo": "auto", "desde": l["inicio"], "hasta": l["fin"]}]
    for tm in tomas:
        if t < float(tm.get("hasta", l["fin"])):
            return tm
    return tomas[-1]


def _x_camara(l: dict, t: float) -> float | None:
    cam = l.get("camara") or {}
    kf = cam.get("keyframes") or []
    if not kf:
        return None
    rel = t - float(cam.get("desde", l["inicio"]))
    x = kf[0][1]
    for tt, xx in kf:
        if tt <= rel + 1e-6:
            x = xx
        else:
            break
    return float(x)


def _ancho_recorte(l: dict) -> int:
    w, h = int(l["fuente_w"]), int(l["fuente_h"])
    cam = l.get("camara") or {}
    if cam.get("cw"):
        return int(cam["cw"])
    return min(w, int(round(h * int(l["ancho"]) / int(l["alto"]))))


def encuadre_clip(l: dict, t: float) -> dict:
    """El mismo encuadre que tiene el clip en ese momento, para que la portada se vea igual."""
    w, h = float(l["fuente_w"]), float(l["fuente_h"])
    tm = _toma_en(l, t)
    modo = tm.get("modo") or "auto"
    cam = l.get("camara") or {}
    cw = _ancho_recorte(l)
    if w / h <= int(l["ancho"]) / int(l["alto"]) + 0.04:  # el original ya es vertical
        return {"ajuste": "cubrir", "cx": 0.5, "cy": 0.5, "zoom": 1.0}
    if modo == "completo" or (modo == "auto" and cam.get("modo") == "ajustar"):
        return {"ajuste": "completo", "cx": 0.5, "cy": 0.5, "zoom": 1.0}
    if modo == "split":
        ws = min(w, h * int(l["ancho"]) / (int(l["alto"]) / 2))
        xa = tm.get("x") if tm.get("x") is not None else w * 0.3 - ws / 2
        xb = tm.get("x2") if tm.get("x2") is not None else w * 0.7 - ws / 2
        return {"ajuste": "split", "cx": (float(xa) + ws / 2) / w, "cx2": (float(xb) + ws / 2) / w, "cy": 0.5, "zoom": 1.0}
    if modo == "recorte" and tm.get("x") is not None:
        return {"ajuste": "cubrir", "cx": (float(tm["x"]) + cw / 2) / w, "cy": 0.3 if float(tm.get("zoom") or 1) > 1.01 else 0.5,
                "zoom": float(tm.get("zoom") or 1)}
    x = _x_camara(l, t)
    return {"ajuste": "cubrir", "cx": 0.5 if x is None else (x + cw / 2) / w, "cy": 0.5, "zoom": 1.0}


def _ventana(sw: int, sh: int, W: int, H: int, cx: float, cy: float, zoom: float) -> tuple:
    esc = max(W / sw, H / sh) * max(1.0, zoom)
    cw, ch = W / esc, H / esc
    x0 = max(0.0, min(sw - cw, cx * sw - cw / 2))
    y0 = max(0.0, min(sh - ch, cy * sh - ch / 2))
    return x0, y0, x0 + cw, y0 + ch


# --------------------------------------------------------------------------------------
# mejorar la imagen y recortar personas (v0.6)
# --------------------------------------------------------------------------------------

def mejorar(im, fuerza: float):
    """Look de portada de YouTube sin IA de pago: contraste local (CLAHE), nitidez en dos radios
    (detalle fino + 'claridad') y mas color, todo dosificado por 'fuerza' (0-1)."""
    import cv2
    from PIL import Image
    f = max(0.0, min(1.0, float(fuerza)))
    if f < 0.001:
        return im
    bgr = cv2.cvtColor(np.asarray(im.convert("RGB")), cv2.COLOR_RGB2BGR)
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    l_, a_, b_ = cv2.split(lab)
    l_ = cv2.createCLAHE(clipLimit=1.0 + 2.2 * f, tileGridSize=(8, 8)).apply(l_)
    bgr = cv2.cvtColor(cv2.merge([l_, a_, b_]), cv2.COLOR_LAB2BGR).astype(np.float32)
    lado = max(bgr.shape[:2])
    fino = cv2.GaussianBlur(bgr, (0, 0), max(0.8, lado / 1400))
    ancho = cv2.GaussianBlur(bgr, (0, 0), max(4.0, lado / 160))
    bgr = bgr + (bgr - fino) * (0.9 * f) + (bgr - ancho) * (0.35 * f)
    hsv = cv2.cvtColor(np.clip(bgr, 0, 255).astype(np.uint8), cv2.COLOR_BGR2HSV).astype(np.float32)
    s = hsv[..., 1] / 255.0
    hsv[..., 1] = np.clip((s + (1 - s) * s * 0.9 * f) * 255.0, 0, 255)  # vibrance: sube mas lo apagado
    rgb = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2RGB)
    return Image.fromarray(rgb, "RGB")


def _mejorar_rgba(im, fuerza: float):
    """mejorar() sin perder la transparencia de un PNG."""
    alfa = im.getchannel("A") if im.mode == "RGBA" else None
    out = mejorar(im.convert("RGB"), fuerza).convert("RGBA")
    if alfa is not None:
        out.putalpha(alfa)
    return out


def _modnet():
    ruta = m.AQUI / "modelos" / "modnet.onnx"
    if not ruta.exists():
        raise RuntimeError("Falta el modelo modelos/modnet.onnx para recortar personas.")
    if "s" not in _MODNET:
        import onnxruntime as ort
        _MODNET["s"] = ort.InferenceSession(str(ruta), providers=["CPUExecutionProvider"])
    return _MODNET["s"]


def mascara_personas(im) -> np.ndarray:
    """Mascara suave (0-1) de las personas de la foto, del tamano de la foto (MODNet, en la PC)."""
    import cv2
    rgb = np.asarray(im.convert("RGB"))
    h, w = rgb.shape[:2]
    clave = (h, w, hash(rgb[::7, ::7].tobytes()))
    ya = _sacar_lru(_MATTES, clave)
    if ya is not None:
        return ya
    k = 512 / max(h, w)
    nh, nw = max(32, int(round(h * k / 32)) * 32), max(32, int(round(w * k / 32)) * 32)
    x = cv2.resize(rgb, (nw, nh), interpolation=cv2.INTER_AREA).astype(np.float32) / 127.5 - 1.0
    with _CANDADO_MODNET:
        s = _modnet()
        sal = s.run(None, {s.get_inputs()[0].name: x.transpose(2, 0, 1)[None]})[0][0, 0]
    mate = np.clip(cv2.resize(sal, (w, h), interpolation=cv2.INTER_LINEAR), 0, 1).astype(np.float32)
    return _guardar_lru(_MATTES, clave, mate, 6)


def elegir_persona(mate: np.ndarray, px=None, py=None) -> np.ndarray:
    """Con un punto (0-1), solo la persona en la que se hizo clic (o la mas cercana); sin punto, todas
    las que no sean manchitas."""
    import cv2
    h, w = mate.shape
    duro = (mate > 0.5).astype(np.uint8)
    n, etiquetas, stats, cent = cv2.connectedComponentsWithStats(duro, 8)
    if n <= 1:
        return mate
    areas = stats[1:, cv2.CC_STAT_AREA]
    if px is None or py is None:
        quedan = [i + 1 for i, a in enumerate(areas) if a >= 0.02 * h * w or a == areas.max()]
    else:
        x, y = int(max(0, min(w - 1, float(px) * w))), int(max(0, min(h - 1, float(py) * h)))
        lab = etiquetas[y, x]
        if lab == 0:  # clic al lado: la persona mas cercana
            d = ((cent[1:, 0] - x) ** 2 + (cent[1:, 1] - y) ** 2) / np.maximum(areas, 1) ** 0.5
            lab = int(np.argmin(d)) + 1
        quedan = [lab]
    keep = np.isin(etiquetas, quedan).astype(np.uint8)
    lado = max(3, int(min(h, w) * 0.015)) | 1
    keep = cv2.dilate(keep, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (lado, lado)))
    return mate * keep.astype(np.float32)


def _alfas_efecto(mate: np.ndarray, op: dict, W: int) -> list:
    """Las capas del efecto como mascaras 0-1 (se pintan del color elegido, debajo de la persona)."""
    import cv2
    estilo = op.get("estilo") or "glow"
    inten = _num(op.get("intensidad"), 0.9, 0.0, 1.5)
    capas = []
    if estilo in ("glow", "ambos"):
        r = max(2.0, _num(op.get("glow"), 0.035, 0.0, 0.15) * W)
        halo = np.zeros_like(mate)
        for s, peso in ((r, 1.0), (r * 0.35, 0.9)):  # halo ancho + nucleo neon
            halo = np.maximum(halo, np.clip(cv2.GaussianBlur(mate, (0, 0), s) * 2.2 * peso, 0, 1))
        capas.append(np.clip(halo * inten, 0, 1))
    if estilo in ("contorno", "ambos"):
        g = max(2, int(_num(op.get("grosor"), 0.008, 0.0, 0.05) * W))
        dil = cv2.dilate((mate > 0.5).astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * g + 1, 2 * g + 1)))
        capas.append(cv2.GaussianBlur(dil.astype(np.float32), (0, 0), 1.2))
    return capas


def realzar_persona(fondo, persona, mate: np.ndarray, op: dict, W: int):
    """Pega la persona (nitida, sin los efectos del fondo) con contorno y/o glow del color elegido."""
    from PIL import Image
    op = {**PERSONA_DEFECTO, **(op or {})}
    color = np.array(_rgb(op["color"], (47, 123, 255)), np.float32)
    base = np.asarray(fondo.convert("RGB"), np.float32)
    for k in _alfas_efecto(mate, op, W):
        base = base * (1 - k[..., None]) + color * k[..., None]
    a = mate[..., None]
    base = base * (1 - a) + np.asarray(persona.convert("RGB"), np.float32) * a
    return Image.fromarray(np.clip(base, 0, 255).astype(np.uint8), "RGB").convert("RGBA")


def recortar_imagen(im, op: dict | None, W: int):
    """Una foto suelta (p.ej. un invitado) sin su fondo, con contorno/glow alrededor. RGBA con margen."""
    from PIL import Image
    op = {**PERSONA_DEFECTO, **(op or {})}
    mate = elegir_persona(mascara_personas(im), op.get("px"), op.get("py"))
    rgba = np.asarray(im.convert("RGBA")).copy()
    rgba[..., 3] = (mate * 255).astype(np.uint8)
    recorte = Image.fromarray(rgba, "RGBA")
    bb = recorte.getchannel("A").point(lambda v: 255 if v > 20 else 0).getbbox()
    if bb:
        recorte = recorte.crop(bb)
    if op.get("estilo") == "nada":
        return recorte
    # el efecto se mide en pixeles de la portada: la foto se ve a ~ su ancho, asi que se escala a eso
    escala = max(0.3, recorte.width / max(1, W))
    margen = int(max(op["glow"] * 2.2 if op["estilo"] != "contorno" else 0, op["grosor"] * 1.5) * W * escala) + 4
    lienzo = Image.new("RGBA", (recorte.width + 2 * margen, recorte.height + 2 * margen), (0, 0, 0, 0))
    lienzo.alpha_composite(recorte, (margen, margen))
    a = np.asarray(lienzo.getchannel("A"), np.float32) / 255.0
    color = np.array(_rgb(op["color"], (47, 123, 255)), np.float32)
    rgb = np.zeros(a.shape + (3,), np.float32)
    alfa = np.zeros_like(a)
    for k in _alfas_efecto(a, op, int(W * escala)) + [a]:  # "encima de" con alfa directa, de abajo hacia arriba
        src = color if k is not a else np.asarray(lienzo, np.float32)[..., :3]
        nueva = k + alfa * (1 - k)
        rgb = (src * k[..., None] + rgb * (alfa * (1 - k))[..., None]) / np.maximum(nueva, 1e-4)[..., None]
        alfa = nueva
    return Image.fromarray(np.dstack([np.clip(rgb, 0, 255), alfa * 255]).astype(np.uint8), "RGBA")


def componer_fondo(d: Path, l: dict, diseno: dict, W: int, H: int):
    """El fondo ya con sus efectos. Se guarda el ultimo: mover un texto no lo vuelve a calcular."""
    from PIL import Image, ImageEnhance, ImageFilter
    f = {**FONDO_DEFECTO, **(diseno.get("fondo") or {})}
    clave = json.dumps([str(d), l["id"], f, W, H], sort_keys=True)
    ya = _sacar_lru(_FONDOS, clave)
    if ya is not None:
        return ya
    zoom = _num(f["zoom"], 1.0, 1.0, 4.0)
    cx, cy = _num(f["cx"], 0.5, 0.0, 1.0), _num(f["cy"], 0.5, 0.0, 1.0)
    info = {"vx": 1.0, "vy": 1.0}
    src = None
    if f["tipo"] == "imagen":
        ruta = _ruta_imagen(d, l, diseno, f.get("origen"), f.get("ruta"))
        if ruta:
            src = _imagen(ruta).convert("RGB")
    elif f["tipo"] == "cuadro":
        src = cuadro(d, l, _num(f["t"], l["inicio"], 0.0, 1e7))
    if src is None:
        im = Image.new("RGB", (W, H), _rgb(f["color"], (17, 17, 17)))
    elif f["ajuste"] == "completo":
        v = _ventana(src.width, src.height, W // 4, H // 4, 0.5, 0.5, 1.0)
        im = src.resize((W // 4, H // 4), Image.BILINEAR, box=v).filter(ImageFilter.GaussianBlur(4))
        im = ImageEnhance.Brightness(im.resize((W, H), Image.BICUBIC)).enhance(0.8)
        e = min(W / src.width, H / src.height) * zoom
        w2, h2 = int(src.width * e), int(src.height * e)
        grande = src.resize((w2, h2), Image.LANCZOS)
        x = int((W - w2) / 2 + (0.5 - cx) * w2)
        y = int((H - h2) / 2 + (0.5 - cy) * h2)
        im.paste(grande, (x, y))
    elif f["ajuste"] == "split":
        hh = H // 2
        im = Image.new("RGB", (W, H))
        for k, c in enumerate((cx, _num(f["cx2"], 0.7, 0.0, 1.0))):
            alto = hh if k == 0 else H - hh
            v = _ventana(src.width, src.height, W, alto, c, cy, zoom)
            im.paste(src.resize((W, alto), Image.LANCZOS, box=v), (0, 0 if k == 0 else hh))
        im.paste((0, 0, 0), (0, hh - 3, W, hh + 3))
    else:
        v = _ventana(src.width, src.height, W, H, cx, cy, zoom)
        info = {"vx": (v[2] - v[0]) / src.width, "vy": (v[3] - v[1]) / src.height}
        im = src.resize((W, H), Image.LANCZOS, box=v)
    mej = _num(f.get("mejorar"), 0.0, 0.0, 1.0)
    if src is not None and mej > 0.001:
        im = mejorar(im, mej)
    per = {**PERSONA_DEFECTO, **(f.get("persona") or {})}
    persona = None
    if src is not None and per["activa"] and f["ajuste"] != "split":
        try:
            persona = (im.copy(), elegir_persona(mascara_personas(im), per.get("px"), per.get("py")))
        except Exception as e:  # sin modelo o con error: la portada sale igual, sin recorte
            print(f"[aviso] no pude recortar la persona: {e}")
    punch = _num(f["punch"], 1.0, 0.5, 1.8)
    if abs(punch - 1) > 0.01:
        im = ImageEnhance.Color(ImageEnhance.Contrast(im).enhance(1 + (punch - 1) * 0.6)).enhance(punch)
    blur = _num(f["desenfoque"], 0.0, 0.0, 1.0)
    if blur > 0.001:
        im = im.filter(ImageFilter.GaussianBlur(blur * min(W, H) * 0.05))
    tinte = _rgb(f["color_degradado"], (0, 0, 0))
    bajar = _num(f.get("bajar"), 0.0, 0.0, 0.6)
    if bajar > 0.001:  # el cuadro baja y arriba queda espacio para el titulo
        corrido = Image.new("RGB", (W, H), tinte)
        corrido.paste(im, (0, int(bajar * H)))
        im = corrido
    arr = np.asarray(im, dtype=np.float32)
    osc = _num(f["oscurecer"], 0.0, 0.0, 1.0)
    if osc > 0.001:
        arr = arr * (1 - osc)
    lado = f["degradado"]
    y = np.linspace(0, 1, H, dtype=np.float32)
    alfa = np.zeros(H, np.float32)
    if lado in ("abajo", "arriba", "ambos"):
        fuerza = _num(f["fuerza_degradado"], 0.8, 0.0, 1.0)
        tam = max(0.05, _num(f["tam_degradado"], 0.55, 0.05, 1.0))
        ab = np.clip((y - (1 - tam)) / tam, 0, 1) if lado in ("abajo", "ambos") else alfa
        ar = np.clip(((tam - y) / tam), 0, 1) if lado in ("arriba", "ambos") else alfa
        alfa = np.maximum(ab, ar) ** 0.9 * fuerza
    if bajar > 0.001:  # sin raya donde empieza el cuadro
        alfa = np.maximum(alfa, 1 - np.clip((y - bajar) / 0.16, 0, 1) ** 0.8)
    if alfa.max() > 0:
        a = alfa[:, None, None]
        arr = arr * (1 - a) + np.array(tinte, np.float32) * a
    final = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB").convert("RGBA")
    if persona:
        nitida, mate = persona
        if abs(punch - 1) > 0.01:  # la persona si lleva el color y contraste, no el oscurecido ni el blur
            nitida = ImageEnhance.Color(ImageEnhance.Contrast(nitida).enhance(1 + (punch - 1) * 0.6)).enhance(punch)
        if bajar > 0.001:
            corrida = Image.new("RGB", (W, H))
            corrida.paste(nitida, (0, int(bajar * H)))
            nitida = corrida
            m2 = np.zeros_like(mate)
            m2[int(bajar * H):] = mate[:H - int(bajar * H)]
            mate = m2
        final = realzar_persona(final, nitida, mate, per, W)
    return _guardar_lru(_FONDOS, clave, (final, info), 4)


# --------------------------------------------------------------------------------------
# capas
# --------------------------------------------------------------------------------------

def _partir_marcas(texto: str, mayusculas: bool) -> list:
    """'hola *mundo*' -> parrafos de (palabra, resaltada). Los asteriscos marcan lo que va resaltado."""
    parrafos = []
    for cruda in str(texto or "").split("\n"):
        pals, clave = [], False
        for tok in cruda.split():
            limpio = tok.replace("*", "")
            if tok.startswith("*"):
                clave = True
            if limpio:
                pals.append((limpio.upper() if mayusculas else limpio, clave))
            if tok.endswith("*") and (len(tok) > 1 or not tok.startswith("*")):
                clave = False
        parrafos.append(pals)
    return parrafos


def _envolver(pals: list, ancho: float, medir, espacio: float) -> list:
    lineas, actual, w = [], [], 0.0
    for p in pals:
        wp = medir(p[0])
        if actual and w + espacio + wp > ancho:
            lineas.append(actual)
            actual, w = [], 0.0
        w += (espacio if actual else 0) + wp
        actual.append(p)
    if actual:
        lineas.append(actual)
    return lineas


def _balanceado(pals: list, ancho: float, medir, espacio: float) -> list:
    """Las mismas lineas, pero parejas: evita una palabra sola colgando abajo."""
    n = len(_envolver(pals, ancho, medir, espacio))
    if n <= 1:
        return _envolver(pals, ancho, medir, espacio)
    lo, hi = max(medir(p[0]) for p in pals), ancho
    for _ in range(10):
        mid = (lo + hi) / 2
        if len(_envolver(pals, mid, medir, espacio)) <= n:
            hi = mid
        else:
            lo = mid
    return _envolver(pals, hi, medir, espacio)


def _maquetar(c: dict, W: int, H: int) -> tuple | None:
    """Tamano real de la letra y lineas del texto (si una palabra no cabe en la caja, se achica)."""
    tam = max(10, int(_num(c["tam"], 0.1, 0.01, 0.6) * min(W, H)))
    ancho_max = max(0.08, _num(c["ancho"], 0.86, 0.08, 1.5)) * W
    parrafos = _partir_marcas(c["texto"], bool(c["mayusculas"]))
    todas = [p for pa in parrafos for p in pa]
    if not todas:
        return None
    fuente = m._fuente_pil(c["fuente"], tam)
    for _ in range(4):
        ancha = max(fuente.getlength(p[0]) for p in todas)
        if ancha <= ancho_max or tam <= 10:
            break
        tam = max(10, int(tam * ancho_max / ancha * 0.995))
        fuente = m._fuente_pil(c["fuente"], tam)
    espacio = fuente.getlength(" ")
    lineas = []
    for pa in parrafos:
        lineas.extend(_balanceado(pa, ancho_max, fuente.getlength, espacio) if pa else [[]])
    return tam, fuente, lineas, espacio


def capa_texto(c: dict, W: int, H: int):
    """Devuelve (imagen RGBA sin rotar, ancho y alto del bloque de texto en pixeles)."""
    from PIL import Image, ImageDraw, ImageFilter
    maqueta = _maquetar(c, W, H)
    if not maqueta:
        return None, 0, 0
    tam, fuente, lineas, espacio = maqueta
    medir = fuente.getlength
    anchos = [sum(medir(p[0]) for p in li) + espacio * max(0, len(li) - 1) for li in lineas]
    bw = int(np.ceil(max(anchos)))
    caja_h = fuente.getbbox("H")
    cap = caja_h[3] - caja_h[1]
    inter = _num(c["interlineado"], 1.0, 0.6, 2.2)
    con_caja = c["caja"] in ("linea", "bloque")
    pad_x, pad_y = (int(tam * 0.26), int(cap * 0.24)) if con_caja else (0, 0)
    paso = int(round(cap * 1.28 * inter + (2 * pad_y if c["caja"] == "linea" else 0)))
    bh = cap + paso * (len(lineas) - 1)
    trazo = int(_num(c["contorno"], 0.0, 0.0, 0.25) * tam)
    sombra = _num(c["sombra"], 0.0, 0.0, 1.0)
    desenfoque = int(tam * 0.09)
    margen = max(pad_x, pad_y) + trazo + int(tam * 0.5) + (desenfoque * 3 if sombra else 0)
    lw, lh = bw + 2 * margen, bh + 2 * margen
    capa = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))
    dib = ImageDraw.Draw(capa)
    op_caja = int(255 * _num(c["opacidad_caja"], 1.0, 0.0, 1.0))
    color_caja = _rgb(c["color_caja"], (225, 6, 0)) + (op_caja,)
    radio = int(_num(c["radio_caja"], 0.14, 0.0, 0.5) * tam)
    if c["caja"] == "bloque":
        dib.rounded_rectangle([margen - pad_x, margen - pad_y, margen + bw + pad_x, margen + bh + pad_y], radius=radio, fill=color_caja)
    color, resalte = _rgb(c["color"]), _rgb(c["color_clave"], (255, 214, 10))
    texto_resalte = _rgb(_contraste(c["color_clave"]))
    alinear = c["alinear"]
    for i, li in enumerate(lineas):
        y = margen + cap + paso * i
        x = margen + {"izquierda": 0.0, "derecha": bw - anchos[i]}.get(alinear, (bw - anchos[i]) / 2)
        if c["caja"] == "linea" and li:
            dib.rounded_rectangle([x - pad_x, y - cap - pad_y, x + anchos[i] + pad_x, y + pad_y], radius=radio, fill=color_caja)
        for palabra, clave in li:
            wp = medir(palabra)
            tinta, trazo_p = color, trazo
            if clave and c["clave_modo"] == "caja":
                pz = int(tam * 0.1)
                dib.rounded_rectangle([x - pz, y - cap - pz, x + wp + pz, y + pz], radius=max(2, radio // 2), fill=resalte + (255,))
                tinta, trazo_p = texto_resalte, 0  # dentro del recuadro el contorno se comeria las letras
            elif clave:
                tinta = resalte
            dib.text((x, y), palabra, font=fuente, fill=tinta + (255,), anchor="ls", stroke_width=trazo_p,
                     stroke_fill=_rgb(c["color_contorno"], (0, 0, 0)) + (255,))
            x += wp + espacio
    if sombra > 0.001:
        alfa = capa.getchannel("A").point(lambda v: int(v * sombra)).filter(ImageFilter.GaussianBlur(desenfoque))
        negra = Image.new("RGBA", capa.size, (0, 0, 0, 0))
        negra.putalpha(alfa)
        fondo = Image.new("RGBA", capa.size, (0, 0, 0, 0))
        fondo.alpha_composite(negra, (0, min(int(tam * 0.04) + 1, margen // 2)))
        fondo.alpha_composite(capa)
        capa = fondo
    return capa, bw + 2 * pad_x, bh + 2 * pad_y


def _imagen(ruta: Path):
    from PIL import Image
    clave = (str(ruta), ruta.stat().st_mtime)
    ya = _sacar_lru(_IMAGENES, clave)
    if ya is not None:
        return ya
    im = Image.open(ruta).convert("RGBA")
    if max(im.size) > 2600:
        k = 2600 / max(im.size)
        im = im.resize((int(im.width * k), int(im.height * k)), Image.LANCZOS)
    return _guardar_lru(_IMAGENES, clave, im, 8)


def _recorte_cara(im):
    """Cuadro alrededor de la cara mas grande de una foto; sin cara, el centro de la foto."""
    import cv2
    w, h = im.size
    esc = min(1.0, 900 / max(w, h))
    pequena = cv2.cvtColor(np.asarray(im.convert("RGB").resize((max(1, int(w * esc)), max(1, int(h * esc))))), cv2.COLOR_RGB2BGR)
    caras = []
    with _CANDADO_CARAS:
        tipo, det = m._detector()
        if tipo == "yunet":
            det.setInputSize((pequena.shape[1], pequena.shape[0]))
            _, res = det.detect(pequena)
            caras = [] if res is None else [tuple(float(v) for v in f[:4]) for f in res]
        else:
            caras = [tuple(float(v) for v in f) for f in det.detectMultiScale(cv2.cvtColor(pequena, cv2.COLOR_BGR2GRAY), 1.15, 5)]
    lado = min(w, h)
    cx, cy = w / 2, h / 2
    if caras:
        x, y, cw, ch = max(caras, key=lambda f: f[2] * f[3])
        cx, cy = (x + cw / 2) / esc, (y + ch / 2) / esc
        lado = min(lado, int(max(cw, ch) / esc * 2.3))
    x0 = int(max(0, min(w - lado, cx - lado / 2)))
    y0 = int(max(0, min(h - lado, cy - lado / 2)))
    return im.crop((x0, y0, x0 + lado, y0 + lado))


def capa_imagen(c: dict, d: Path, l: dict, diseno: dict, W: int):
    from PIL import Image, ImageDraw
    ruta = _ruta_imagen(d, l, diseno, c.get("origen"), c.get("ruta"))
    if not ruta:
        return None
    im = _imagen(ruta)
    rec = c.get("recorte_persona") or {}
    if rec.get("activa"):  # la persona sin su fondo, con contorno/glow (como en las portadas de La Escala)
        try:
            if _num(c.get("mejorar"), 0.0, 0.0, 1.0) > 0.001:
                im = _mejorar_rgba(im, c["mejorar"])
            im = recortar_imagen(im, rec, W)
        except Exception as e:
            print(f"[aviso] no pude recortar la persona de la foto: {e}")
        ancho = max(4, int(_num(c["ancho"], 0.3, 0.01, 2.0) * W))
        return im.resize((ancho, max(4, int(im.height * ancho / im.width))), Image.LANCZOS)
    if _num(c.get("mejorar"), 0.0, 0.0, 1.0) > 0.001:
        im = _mejorar_rgba(im, c["mejorar"])
    if c.get("cara"):
        im = _recorte_cara(im)
    elif im.getchannel("A").getextrema()[0] < 255:
        bb = im.getchannel("A").getbbox()
        if bb:
            im = im.crop(bb)
    if c.get("redondo") and im.width != im.height:
        lado = min(im.size)
        im = im.crop(((im.width - lado) // 2, (im.height - lado) // 2, (im.width + lado) // 2, (im.height + lado) // 2))
    ancho = max(4, int(_num(c["ancho"], 0.3, 0.01, 2.0) * W))
    alto = max(4, int(im.height * ancho / im.width))
    im = im.resize((ancho, alto), Image.LANCZOS)
    borde = int(_num(c.get("borde"), 0.0, 0.0, 0.2) * ancho)
    if c.get("redondo"):
        mascara = Image.new("L", (ancho * 2, alto * 2), 0)
        ImageDraw.Draw(mascara).ellipse([0, 0, ancho * 2 - 1, alto * 2 - 1], fill=255)
        mascara = mascara.resize((ancho, alto), Image.LANCZOS)
        im = im.copy()
        im.putalpha(mascara)
    if borde:
        marco = Image.new("RGBA", (ancho + 2 * borde, alto + 2 * borde), (0, 0, 0, 0))
        dib = ImageDraw.Draw(marco)
        tinta = _rgb(c.get("color_borde")) + (255,)
        if c.get("redondo"):
            dib.ellipse([0, 0, marco.width - 1, marco.height - 1], fill=tinta)
        else:
            dib.rectangle([0, 0, marco.width - 1, marco.height - 1], fill=tinta)
        marco.alpha_composite(im, (borde, borde))
        im = marco
    return im


def capa_forma(c: dict, W: int, H: int):
    from PIL import Image, ImageDraw
    w, h = max(2, int(_num(c["ancho"], 1.0, 0.01, 2.0) * W)), max(2, int(_num(c["alto"], 0.3, 0.005, 2.0) * H))
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    r = int(_num(c.get("radio"), 0.0, 0.0, 0.5) * min(w, h))
    ImageDraw.Draw(im).rounded_rectangle([0, 0, w - 1, h - 1], radius=r, fill=_rgb(c["color"]) + (255,))
    return im


def render(d: Path, l: dict, diseno: dict) -> tuple:
    """La portada completa. Devuelve (imagen RGB, cajas de cada capa para el editor, datos del fondo)."""
    from PIL import Image
    W, H = m.tamano_salida(diseno.get("formato") or l.get("formato") or "9:16")
    base, info = componer_fondo(d, l, diseno, W, H)
    lienzo = base.copy()
    cajas = []
    for c0 in diseno.get("capas") or []:
        tipo = c0.get("tipo")
        c = {**{"texto": TEXTO_DEFECTO, "imagen": IMAGEN_DEFECTO, "forma": FORMA_DEFECTO}.get(tipo, {}), **c0}
        if tipo not in ("texto", "imagen", "forma"):
            continue
        cw, ch = 0, 0
        if tipo == "texto":
            im, cw, ch = capa_texto(c, W, H)
        elif tipo == "imagen":
            im = capa_imagen(c, d, l, diseno, W)
        else:
            im = capa_forma(c, W, H)
        if im is None:
            cajas.append({"id": c.get("id"), "tipo": tipo, "x": c["x"], "y": c["y"], "w": 0.2, "h": 0.05, "rot": 0, "vacia": True})
            continue
        if tipo != "texto":
            cw, ch = im.size
        if c.get("visible", True):
            im = _opacar(im.copy() if tipo == "imagen" else im, _num(c["opacidad"], 1.0, 0.0, 1.0))
            rot = _num(c["rotacion"], 0.0, -180.0, 180.0)
            if abs(rot) > 0.01:
                im = im.rotate(-rot, expand=True, resample=Image.BICUBIC)
            _pegar(lienzo, im, int(round(c["x"] * W - im.width / 2)), int(round(c["y"] * H - im.height / 2)))
        cajas.append({"id": c.get("id"), "tipo": tipo, "x": c["x"], "y": c["y"], "w": cw / W, "h": ch / H,
                      "rot": c.get("rotacion", 0), "oculta": not c.get("visible", True)})
    return lienzo.convert("RGB"), cajas, {**info, "W": W, "H": H}


def previa(d: Path, l: dict, diseno: dict, ancho: int = 540) -> dict:
    from PIL import Image
    im, cajas, info = render(d, l, diseno)
    ancho = max(180, min(int(ancho), im.width))
    chica = im.resize((ancho, int(im.height * ancho / im.width)), Image.BILINEAR if ancho > im.width / 2 else Image.BOX)
    buf = io.BytesIO()
    chica.save(buf, "JPEG", quality=86)
    return {"imagen": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii"), "cajas": cajas, "fondo": info}


# --------------------------------------------------------------------------------------
# los mejores cuadros del clip
# --------------------------------------------------------------------------------------

def _rangos_utiles(l: dict) -> list:
    """Los tramos que de verdad quedaron en el clip, sin tomas de grafico."""
    tramos = l.get("tramos") or [[l["inicio"], l["fin"]]]
    out = []
    for a, b in tramos:
        for tm in l.get("tomas") or [{"modo": "auto", "desde": a, "hasta": b}]:
            if tm.get("modo") == "grafico" and tm.get("grafico"):
                continue
            x, y = max(a, float(tm.get("desde", a))), min(b, float(tm.get("hasta", b)))
            if y - x > 0.2:
                out.append((x, y))
    return out or [(float(l["inicio"]), float(l["fin"]))]


def _puntaje_cuadro(img: np.ndarray, caras: list, x0: int, x1: int, reaccion: bool) -> tuple:
    """Nitidez + exposicion + cara grande y centrada en lo que se ve del recorte."""
    import cv2
    region = img[:, x0:x1]
    gris = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    media = float(gris.mean())
    exposicion = max(0.0, 1.0 - abs(media - 118) / 118)
    ancho = max(1, x1 - x0)
    dentro = [c for c in caras if x0 <= c[0] + c[2] / 2 <= x1]
    nit_zona = gris
    cara_pts = 0.0
    mejor = None
    if dentro:
        mejor = max(dentro, key=lambda c: c[2])
        x, y, w, h = mejor[:4]
        ax, ay = max(0, int(x) - x0), max(0, int(y))
        zona = gris[ay:ay + int(h), ax:ax + int(w)]
        if zona.size > 100:
            nit_zona = zona
        rel = w / ancho
        centrado = 1.0 - min(1.0, abs((x + w / 2 - x0) / ancho - 0.5) * 2)
        arriba = 1.0 - min(1.0, abs((y + h / 2) / img.shape[0] - 0.38) * 2.2)
        cara_pts = 0.45 + min(1.0, rel / 0.45) * 0.3 + centrado * 0.15 + arriba * 0.1
    nitidez = min(1.0, np.log1p(cv2.Laplacian(nit_zona, cv2.CV_64F).var()) / 7.0)
    puntos = 0.5 * cara_pts + 0.32 * nitidez + 0.18 * exposicion + (0.08 if reaccion else 0.0)
    return puntos, mejor


def candidatos(d: Path, l: dict, n: int = 8, log=lambda _m: None) -> list:
    """Hasta n cuadros buenos y separados entre si. Queda guardado por si vuelves a abrir la portada."""
    import cv2
    d = Path(d)
    firma = json.dumps([l["inicio"], l["fin"], l.get("tramos"), l.get("tomas"), n], sort_keys=True)
    ruta_cache = d / "portadas" / "candidatos" / f"clip{l['id']}.json"
    cache = _leer(ruta_cache, {}) or {}
    if cache.get("firma") == firma and all((d / x["archivo"]).exists() for x in cache.get("cuadros", [])):
        return cache["cuadros"]
    ini, fin = float(l["inicio"]), float(l["fin"])
    W0, H0 = int(l["fuente_w"]), int(l["fuente_h"])
    wd = min(960, W0) // 2 * 2
    hd = int(round(H0 * wd / W0 / 2)) * 2
    esc = wd / W0
    fps = 2.0
    cmd = [m.FFMPEG, "-nostdin", "-v", "error", "-ss", f"{ini:.3f}", "-t", f"{fin - ini:.3f}", "-i", str(l["fuente"]),
           "-vf", f"fps={fps},scale={wd}:{hd}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    proc = subprocess.Popen([str(c) for c in cmd], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            stdin=subprocess.DEVNULL, **m._SIN_VENTANA)
    rangos = _rangos_utiles(l)
    reacciones = (_leer(d / "transcripcion.json", {}) or {}).get("reacciones") or []
    tam, k, filas = wd * hd * 3, 0, []
    try:
        while True:
            buf = proc.stdout.read(tam)
            if len(buf) < tam:
                break
            t = ini + k / fps
            k += 1
            if not any(a <= t <= b for a, b in rangos):
                continue
            img = np.frombuffer(buf, np.uint8).reshape(hd, wd, 3)
            with _CANDADO_CARAS:
                tipo, det = m._detector()
                if tipo == "yunet":
                    det.setInputSize((wd, hd))
                    _, res = det.detect(img)
                    caras = [] if res is None else [tuple(float(v) for v in f[:4]) for f in res if f[14] >= 0.6]
                else:
                    caras = [tuple(float(v) for v in f) for f in det.detectMultiScale(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), 1.15, 5)]
            enc = encuadre_clip(l, t)
            if enc["ajuste"] == "cubrir":
                vent = _ventana(W0, H0, int(l["ancho"]), int(l["alto"]), enc["cx"], enc["cy"], enc["zoom"])
                x0, x1 = int(vent[0] * esc), int(vent[2] * esc)
            else:
                x0, x1 = 0, wd
            reac = any(float(r[0]) - 0.5 <= t <= float(r[1]) + 0.5 for r in reacciones)
            puntos, cara = _puntaje_cuadro(img, caras, x0, x1, reac)
            # sin seguimiento guardado: se encuadra en la cara de ese cuadro
            cx_cara = (cara[0] + cara[2] / 2) / wd if cara else None
            filas.append((puntos, t, x0, x1, img, cx_cara))
            filas.sort(key=lambda f: -f[0])
            filas = filas[:40]  # no hace falta guardar en memoria todos los cuadros
    finally:
        proc.stdout.close()
        proc.wait()
    elegidos = []
    for f in filas:
        if all(abs(f[1] - e[1]) >= 2.0 for e in elegidos):
            elegidos.append(f)
        if len(elegidos) >= n:
            break
    carpeta = d / "portadas" / "candidatos"
    carpeta.mkdir(parents=True, exist_ok=True)
    for viejo in carpeta.glob(f"clip{l['id']}_*.jpg"):
        viejo.unlink(missing_ok=True)
    cuadros = []
    for puntos, t, x0, x1, img, cx_cara in elegidos:
        mini = img[:, x0:x1]
        alto = 320
        ancho = max(2, int(mini.shape[1] * alto / mini.shape[0]))
        nombre = f"clip{l['id']}_{int(t * 100):08d}.jpg"
        cv2.imwrite(str(carpeta / nombre), cv2.resize(mini, (ancho, alto), interpolation=cv2.INTER_AREA), [cv2.IMWRITE_JPEG_QUALITY, 82])
        cuadros.append({"t": round(t, 2), "puntos": round(float(puntos) * 100), "archivo": f"portadas/candidatos/{nombre}",
                        "cx_cara": round(cx_cara, 4) if cx_cara is not None else None})
    _escribir(ruta_cache, {"firma": firma, "cuadros": cuadros})
    log(f"   {len(cuadros)} cuadros buenos en el clip {l['id']}")
    return cuadros


# --------------------------------------------------------------------------------------
# plantillas y diseno
# --------------------------------------------------------------------------------------

def textos_sugeridos(l: dict) -> list:
    meta = l.get("meta") or {}
    out = [(l.get("hook") or {}).get("texto"), meta.get("texto_hook"), meta.get("titulo")]
    return [t for t in OrderedDict.fromkeys(str(x).strip() for x in out if x) if t]


def texto_inicial(l: dict) -> str:
    """El titulo del clip con la palabra clave resaltada; si no hay clave, la palabra mas larga."""
    sug = textos_sugeridos(l)
    texto = sug[0] if sug else ""
    if not texto or "*" in texto:
        return texto
    claves = {m._normalizar(x) for x in ((l.get("subtitulos") or {}).get("palabras_clave") or [])}
    pals = texto.split()
    i = next((k for k, p in enumerate(pals) if m._normalizar(p) in claves), None)
    if i is None and pals:
        i = max(range(len(pals)), key=lambda k: len(pals[k]))
    if i is not None:
        pals[i] = f"*{pals[i]}*"
    return " ".join(pals)


def _tam_para(texto: str) -> float:
    n = len(texto.split())
    return 0.17 if n <= 3 else 0.145 if n <= 5 else 0.12 if n <= 8 else 0.095


def _ajustar_alto(c: dict, W: int, H: int, maximo: float) -> dict:
    """La letra mas grande con la que el titulo queda en pocas lineas y sin tapar la cara."""
    pocas = max(2, int(np.ceil(len(c["texto"].split()) / 2.5)))
    for _ in range(24):
        completa = {**TEXTO_DEFECTO, **c}
        _, _, alto = capa_texto(completa, W, H)
        maqueta = _maquetar(completa, W, H)
        if (alto <= maximo * H and (not maqueta or len(maqueta[2]) <= pocas)) or c["tam"] <= 0.05:
            break
        c["tam"] = round(c["tam"] * 0.95, 4)
    return c


def _logo(perfil: dict | None, y: float, ancho: float) -> list:
    imgs = imagenes_cliente(perfil)
    logos = [i for i in imgs if i["tipo"] == "logo"]
    if not logos:
        return []
    return [{**IMAGEN_DEFECTO, "id": "logo", "origen": "cliente", "ruta": logos[0]["ruta"], "x": 0.5, "y": y, "ancho": ancho}]


def _ruta_plantilla_propia(perfil: dict | None) -> Path:
    return (Path(perfil["_dir"]) if perfil else m.CACHE) / "plantilla_portada.json"


def guardar_plantilla_propia(diseno: dict, perfil: dict | None) -> None:
    """Guarda este diseno para reusarlo en los proximos videos (por cliente)."""
    _escribir(_ruta_plantilla_propia(perfil), {
        "capas": diseno.get("capas") or [],
        "fondo": {k: v for k, v in (diseno.get("fondo") or {}).items() if k in (
            "oscurecer", "desenfoque", "punch", "degradado", "fuerza_degradado", "tam_degradado", "color_degradado", "bajar")}})


def _aplicar_propia(diseno: dict, l: dict, perfil: dict | None) -> dict | None:
    guardada = _leer(_ruta_plantilla_propia(perfil))
    if not guardada:
        return None
    texto = next((c.get("texto") for c in diseno.get("capas") or [] if c.get("tipo") == "texto" and c.get("texto")), None) or texto_inicial(l)
    capas = json.loads(json.dumps(guardada["capas"]))
    primero = next((c for c in capas if c.get("tipo") == "texto"), None)
    if primero:  # el texto de este clip, en el lugar y con la letra guardados
        primero["texto"] = texto
    return {**diseno, "plantilla": "propia", "capas": capas, "fondo": {**FONDO_DEFECTO, **(diseno.get("fondo") or {}), **guardada["fondo"]}}


def sugerir_titulos(l: dict) -> list:
    """Cinco textos cortos para la portada, escritos por Claude con lo que se dice en el clip (fracciones de centavo)."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("Falta la API key de Claude (se pone en la app, en Configuración).")
    import anthropic
    palabras = " ".join(w.get("t", "") for w in (l.get("subtitulos") or {}).get("palabras") or [])[:6000]
    modelo = m.cargar_config({}).get("modelo_correccion") or "claude-haiku-5-5"
    r = anthropic.Anthropic().messages.create(model=modelo, max_tokens=300, messages=[{"role": "user", "content": (
        "Escribe 5 textos para la portada de este clip vertical, en el mismo idioma y tono del video. Maximo 6 palabras cada uno. "
        "Deben dar ganas de abrirlo sin prometer algo que el clip no cumple. Pon entre *asteriscos* la palabra mas fuerte de cada uno. "
        f"Contesta solo con los 5 textos, uno por linea, sin numeros.\n\nLo que se dice en el clip:\n{palabras}")}])
    m.registrar_uso("titulos_portada", modelo, usage=r.usage)
    texto = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
    return [x.strip(" -•\"") for x in texto.splitlines() if x.strip()][:5]


def aplicar_plantilla(diseno: dict, nombre: str, l: dict, perfil: dict | None) -> dict:
    """Cambia colores, letra y lugar de las capas. Conserva el texto y el cuadro que ya elegiste."""
    if nombre == "propia":
        propia = _aplicar_propia(diseno, l, perfil)
        if propia:
            return propia
    if nombre not in PLANTILLAS:
        nombre = "titular"
    mc = marca_de(perfil)
    W, H = m.tamano_salida(diseno.get("formato") or l.get("formato") or "9:16")
    apaisado = W > H
    texto = next((c.get("texto") for c in diseno.get("capas") or [] if c.get("tipo") == "texto" and c.get("texto")), None) or texto_inicial(l)
    base = {**TEXTO_DEFECTO, "id": "titulo", "texto": texto, "fuente": mc["fuente"], "tam": _tam_para(texto),
            "color_clave": mc["acento"], "color_caja": mc["caja"], "ancho": 0.6 if apaisado else 0.88}
    logo_ancho = 0.14 if apaisado else max(0.2, min(0.34, float((perfil or {}).get("logo_tam") or 0.26)))
    fondo = {**FONDO_DEFECTO, **(diseno.get("fondo") or {}), "oscurecer": 0.0, "degradado": "no", "punch": 1.08}
    fondo["bajar"] = 0.0
    capas = []
    # el texto va debajo de la cara y el logo sobre la parte oscura, donde siempre se lee
    if nombre == "titular":
        fondo.update(degradado="abajo", fuerza_degradado=0.96, tam_degradado=0.6)
        capas = [_ajustar_alto({**base, "y": 0.63}, W, H, 0.26), *_logo(perfil, 0.82, logo_ancho)]
    elif nombre == "etiquetas":
        fondo.update(degradado="abajo", fuerza_degradado=0.8, tam_degradado=0.42)
        t = {**base, "y": 0.63, "tam": _tam_para(texto) * 0.8, "caja": "linea", "color": mc["texto_caja"], "sombra": 0.0,
             "color_clave": mc["texto_caja"], "interlineado": 0.9}
        capas = [_ajustar_alto(t, W, H, 0.26), *_logo(perfil, 0.83, logo_ancho)]
    elif nombre == "impacto":
        fondo.update(oscurecer=0.3, punch=1.15, degradado="abajo", fuerza_degradado=0.8, tam_degradado=0.4)
        t = {**base, "y": 0.63, "tam": _tam_para(texto) * 1.12, "rotacion": -4.0, "contorno": 0.05, "sombra": 0.8,
             "clave_modo": "caja", "color_clave": mc["caja"]}
        capas = [_ajustar_alto(t, W, H, 0.3), *_logo(perfil, 0.84, logo_ancho)]
    elif nombre == "arriba":
        # se baja el cuadro para que el titulo tenga su espacio y no tape la cara
        fondo.update(degradado="ambos", fuerza_degradado=0.92, tam_degradado=0.3, bajar=0.0 if apaisado else 0.34)
        capas = [_ajustar_alto({**base, "y": 0.42 if apaisado else 0.22}, W, H, 0.2), *_logo(perfil, 0.86, logo_ancho)]
    elif nombre == "youtube":
        # como las portadas de La Escala: fondo oscuro y suave, la persona nitida con glow y un titular gigante
        fondo.update(oscurecer=0.4, desenfoque=0.18, punch=1.18, mejorar=0.6, degradado="ambos", fuerza_degradado=0.7,
                     tam_degradado=0.3, bajar=0.0 if apaisado else 0.13,  # en vertical: espacio arriba para el titulo
                     persona={**PERSONA_DEFECTO, **((diseno.get("fondo") or {}).get("persona") or {}),
                              "activa": True, "estilo": "glow", "color": mc["acento"], "glow": 0.035 if apaisado else 0.024})
        t = {**base, "x": 0.66 if apaisado else 0.5, "y": 0.3 if apaisado else 0.15, "ancho": 0.62 if apaisado else 0.94,
             "tam": _tam_para(texto) * (1.25 if apaisado else 1.6), "contorno": 0.07, "sombra": 0.85, "color": "#FFFFFF",
             "color_clave": "#FFD60A", "interlineado": 0.9}
        capas = [_ajustar_alto(t, W, H, 0.42 if apaisado else 0.22), *_logo(perfil, 0.88, logo_ancho)]
    else:  # banda
        cf = mc["caja"]
        tinta = mc["texto_caja"]
        acento = mc["acento"] if mc["acento"].lower() != cf.lower() else tinta
        logo = _logo(perfil, 0.735, logo_ancho)
        banda = {**FORMA_DEFECTO, "id": "banda", "y": 0.615, "alto": 0.3, "color": cf}
        t = {**base, "y": 0.575 if logo else 0.615, "color": tinta, "sombra": 0.0, "color_clave": acento, "tam": _tam_para(texto) * 0.92}
        capas = [banda, _ajustar_alto(t, W, H, 0.17 if logo else 0.25), *logo]
    if apaisado:  # en horizontal el logo va a la esquina: en medio taparia a la persona
        for c in capas:
            if c.get("id") == "logo":
                c.update(x=0.09, y=0.14)
    return {**diseno, "plantilla": nombre, "fondo": fondo, "capas": capas}


def diseno_nuevo(d: Path, l: dict, plantilla: str | None = None, log=lambda _m: None) -> dict:
    perfil = perfil_de(d, l)
    cuadros = candidatos(d, l, log=log)
    t = cuadros[0]["t"] if cuadros else (float(l["inicio"]) + float(l["fin"])) / 2
    enc = encuadre_clip(l, t)
    if enc["ajuste"] == "cubrir" and not (l.get("camara") or {}).get("keyframes") and cuadros and cuadros[0].get("cx_cara") is not None:
        enc["cx"] = cuadros[0]["cx_cara"]
    formato = l.get("formato") or "9:16"
    if (perfil or {}).get("_id") is None:
        cliente = ""
    else:
        cliente = perfil["_id"]
    base = {"version": VERSION_DISENO, "id": l["id"], "formato": formato, "cliente": cliente,
            "fondo": {**FONDO_DEFECTO, **enc, "t": t}, "capas": []}
    guardada = "propia" if _ruta_plantilla_propia(perfil).exists() else None  # tu plantilla manda si ya guardaste una
    return aplicar_plantilla(base, plantilla or guardada or "titular", l, perfil)


def cargar_diseno(d: Path, l: dict, crear: bool = True) -> dict | None:
    ruta = ruta_diseno(d, l["id"])
    dis = _leer(ruta)
    if dis or not crear:
        return dis
    dis = diseno_nuevo(d, l)
    dis["por_exportar"] = True
    _escribir(ruta, dis)
    return dis


def guardar_diseno(d: Path, cid: str, dis: dict) -> dict:
    previo = _leer(ruta_diseno(d, cid), {}) or {}
    dis = {**dis, "version": VERSION_DISENO, "id": cid, "por_exportar": True, "exportada": previo.get("exportada"),
           "guardado": _dt.datetime.now().strftime("%Y-%m-%d %H:%M")}
    _escribir(ruta_diseno(d, cid), dis)
    return dis


def exportar(d: Path, l: dict, dis: dict | None = None) -> Path:
    """Guarda el .jpg en portadas/ (si el archivo cambia de nombre, se borra el anterior)."""
    d = Path(d)
    dis = dis or cargar_diseno(d, l)
    im, _, _ = render(d, l, dis)
    meta = l.get("meta") or {}
    nombre = f"{l['id']}_{m.slug(meta.get('titulo') or 'portada', 40)}"
    formato = dis.get("formato") or l.get("formato") or "9:16"
    if formato != (l.get("formato") or "9:16"):
        nombre += "_" + formato.replace(":", "x")
    salida = d / "portadas" / f"{nombre}.jpg"
    salida.parent.mkdir(parents=True, exist_ok=True)
    im.save(salida, "JPEG", quality=94, subsampling=0, optimize=True)
    viejo = dis.get("exportada")
    if viejo and (d / viejo).resolve() != salida.resolve() and (d / viejo).resolve().parent == salida.parent.resolve():
        (d / viejo).unlink(missing_ok=True)
    dis.update(exportada=salida.relative_to(d).as_posix(), por_exportar=False,
               exportado=_dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
    _escribir(ruta_diseno(d, l["id"]), dis)
    return salida


def generar_todas(d: Path, plantilla: str | None = None, rehacer: bool = False, solo: str | None = None,
                  log=print) -> list:
    """Una portada por clip. Lo ya editado no se toca, salvo que pidas rehacer."""
    d = Path(d)
    hechas = []
    ids = [solo] if solo else ids_clips(d)
    for i, cid in enumerate(ids, 1):
        l = linea_clip(d, cid)
        dis = None if rehacer else cargar_diseno(d, l, crear=False)
        if dis and not dis.get("por_exportar"):
            log(f"[{i}/{len(ids)}] clip {cid}: ya tiene portada")
            hechas.append(d / dis["exportada"])
            continue
        log(f"[{i}/{len(ids)}] clip {cid}: {'exportando tu diseno' if dis else 'buscando el mejor cuadro'}")
        if not dis:
            dis = diseno_nuevo(d, l, plantilla, log=log)
        hechas.append(exportar(d, l, dis))
    return hechas


def video_con_portada(d: Path, l: dict, log=print) -> Path:
    """Copia del clip con la portada en los primeros 3 cuadros, para las apps que eligen la portada
    de un cuadro del video. El clip original no se toca."""
    d = Path(d)
    dis = cargar_diseno(d, l)
    img = exportar(d, l, dis)
    clip = Path(l.get("salida") or "")
    if not clip.exists():
        raise RuntimeError("Primero renderiza el clip: todavia no existe el video.")
    W, H = int(l["ancho"]), int(l["alto"])
    fps = m._fps_ffmpeg(float(l.get("fps") or 30))
    salida = img.with_name(f"{img.stem}_con_portada.mp4")
    grafo = (f"[1:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps={fps},format=yuv420p[p];"
             f"[0:v]scale={W}:{H},setsar=1,fps={fps},format=yuv420p[v];"
             "[0:a]aformat=sample_rates=48000:channel_layouts=stereo[a];"
             "[2:a]aformat=sample_rates=48000:channel_layouts=stereo[s];"
             "[p][s][v][a]concat=n=2:v=1:a=1[vo][ao]")

    def cmd(enc):
        return [m.FFMPEG, "-nostdin", "-v", "error", "-y", "-i", str(clip), "-loop", "1", "-t", "0.1", "-i", str(img),
                "-f", "lavfi", "-t", "0.1", "-i", "anullsrc=r=48000:cl=stereo", "-filter_complex", grafo,
                "-map", "[vo]", "-map", "[ao]", *enc, "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart", str(salida)]

    cpu = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]
    log("Pegando la portada al inicio del video…")
    if m.tiene_nvenc():
        try:
            m.correr(cmd(["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "21", "-b:v", "0"]))
        except RuntimeError:
            m.correr(cmd(cpu))
    else:
        m.correr(cmd(cpu))
    return salida


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Generador de portadas de SmartCut")
    ap.add_argument("carpeta", type=Path, help="la carpeta del video (resultados/<fecha>_<nombre>) o la carpeta de trabajo")
    ap.add_argument("--plantilla", choices=list(PLANTILLAS), default=None)
    ap.add_argument("--clip", default=None, help="solo este clip, p.ej. 03")
    ap.add_argument("--rehacer", action="store_true", help="vuelve a generar aunque ya exista (pierde lo editado)")
    a = ap.parse_args(argv)
    d = a.carpeta if a.carpeta.exists() else m.RESULTADOS / a.carpeta
    if not (d / "proyecto").exists():
        print(f"[ERROR] No encuentro clips en {d}")
        return 1
    solo = f"{int(a.clip):02d}" if a.clip else None
    hechas = generar_todas(d, a.plantilla, a.rehacer, solo)
    print(f"\nListo: {len(hechas)} portadas en {d / 'portadas'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
