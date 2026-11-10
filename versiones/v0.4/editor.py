# -*- coding: utf-8 -*-
"""MiOpusClip - editor de clips y portadas en el navegador. Se abre solo en http://127.0.0.1:7861

    python editor.py                 abre el editor
    python editor.py --no-abrir      solo el servidor
    python editor.py --puerto 7862

Lo que hace:
  - Lista tus resultados y sus clips (tambien los de la v0.1).
  - Abre un clip con lo que habia antes y despues (proxy liviano hecho con la GPU si hay).
  - Mueves el inicio y el fin, cortas o corriges palabras, cambias el titulo y el estilo.
  - Divides el clip en tomas: seguimiento automatico, recorte fijo, video completo, split o grafico.
  - Renderiza con el mismo motor de siempre (miopusclip.py).
  - Genera y edita la portada de cada clip (portadas.py).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import shutil
import socket
import threading
import time
import traceback
import uuid
import wave
from pathlib import Path

import numpy as np

import miopusclip as m
import portadas as pt

AQUI = Path(__file__).resolve().parent
ESTATICO = AQUI / "editor_web"
PUERTO = 7861
CONTEXTO = 30.0  # segundos que se ven antes y despues del clip

try:
    from fastapi import Body, FastAPI, File, HTTPException, Request, UploadFile
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles
except ImportError:  # pragma: no cover
    raise SystemExit("Falta FastAPI. Corre INSTALAR.bat otra vez (viene con la app).")

app = FastAPI(title="MiOpusClip editor")
RED = {"activa": False, "usuario": "miopusclip", "clave": ""}


@app.middleware("http")
async def _clave_de_red(request: Request, call_next):
    """En modo red, las otras compus (la Mac) entran con usuario y clave. Esta PC entra directo."""
    cliente = request.client.host if request.client else ""
    if RED["activa"] and RED["clave"] and cliente not in ("127.0.0.1", "::1"):
        import base64
        import secrets
        ok = False
        h = request.headers.get("authorization", "")
        if h.startswith("Basic "):
            try:
                _u, _, clave = base64.b64decode(h[6:]).decode("utf-8").partition(":")
                ok = secrets.compare_digest(clave, RED["clave"])
            except Exception:
                ok = False
        if not ok:
            from starlette.responses import Response
            return Response("Clave de MiOpusClip", status_code=401,
                            headers={"WWW-Authenticate": 'Basic realm="MiOpusClip", charset="UTF-8"'})
    return await call_next(request)
m.cargar_env()

# --------------------------------------------------------------------------------------
# utilidades
# --------------------------------------------------------------------------------------

_CANDADO = threading.Lock()
_TRANSCRIPCIONES: dict = {}


def _carpeta(nombre: str) -> Path:
    """Una carpeta de resultados, sin dejar salir de resultados/."""
    if not nombre or "/" in nombre or "\\" in nombre or nombre.startswith("."):
        raise HTTPException(400, "carpeta invalida")
    d = (m.RESULTADOS / nombre).resolve()
    if d.parent != m.RESULTADOS.resolve() or not d.is_dir():
        raise HTTPException(404, f"no existe la carpeta {nombre}")
    return d


def _id(cid: str) -> str:
    if not re.fullmatch(r"\d{1,3}", cid or ""):
        raise HTTPException(400, "clip invalido")
    return f"{int(cid):02d}"


def _leer(p: Path, defecto=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return defecto


def _escribir(p: Path, datos) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def _fuente_de(d: Path) -> str | None:
    pj = _leer(d / "proyecto.json", {}) or {}
    f = pj.get("fuente")
    if f and Path(f).exists():
        return str(Path(f))
    if (d / "fuente").exists():
        for p in sorted((d / "fuente").glob("original.*"), key=lambda p: p.stat().st_size, reverse=True):
            if p.suffix.lower() in (".mp4", ".mkv", ".webm", ".mov"):
                return str(p)
    return None


def _transcripcion(d: Path) -> dict:
    clave = str(d)
    tj = d / "transcripcion.json"
    mt = tj.stat().st_mtime if tj.exists() else 0
    if clave not in _TRANSCRIPCIONES or _TRANSCRIPCIONES[clave][0] != mt:
        datos = _leer(tj, {}) or {}
        datos.setdefault("palabras", [])
        datos.setdefault("reacciones", [])
        _TRANSCRIPCIONES[clave] = (mt, datos)
    return _TRANSCRIPCIONES[clave][1]


def _url_media(d: Path, ruta: Path) -> str:
    rel = Path(ruta).resolve().relative_to(d.resolve()).as_posix()
    return f"/media/{d.name}/{rel}"


def _nvenc() -> bool:
    try:
        return m.tiene_nvenc()
    except Exception:
        return False


# --------------------------------------------------------------------------------------
# proyectos y clips
# --------------------------------------------------------------------------------------

def importar_v01(d: Path) -> list:
    """Resultados viejos (sin proyecto/): arma la linea de tiempo de cada clip desde clips.json."""
    clips = _leer(d / "clips.json", []) or []
    fuente = _fuente_de(d)
    if not clips or not fuente:
        return []
    info = m.info_video(fuente)
    fps = 30.0 if info["fps"] > 31 or info["fps"] < 20 else round(info["fps"], 3)
    pj = _leer(d / "proyecto.json", {}) or {}
    formato = (pj.get("opciones") or {}).get("formato", "9:16")
    ow, oh = m.tamano_salida(formato)
    pals = _transcripcion(d)["palabras"]
    hechos = []
    for n, c in enumerate(clips, 1):
        cid = f"{n:02d}"
        ruta = d / "proyecto" / f"clip{cid}.json"
        if ruta.exists():
            continue
        ini, fin = float(c["inicio"]), float(c["fin"])
        linea = {
            "version": 3, "motor": m.VERSION, "fuente": fuente, "id": cid, "inicio": ini, "fin": fin,
            "tramos": c.get("tramos") or [[ini, fin]], "fps": fps, "ancho": ow, "alto": oh,
            "fuente_w": info["w"], "fuente_h": info["h"], "formato": formato,
            "silencios": (pj.get("opciones") or {}).get("silencios", m.CONFIG_DEFECTO["silencios"]), "zoom_en_cortes": True,
            "cortes": [], "tomas": [{"modo": "auto", "desde": ini, "hasta": fin}],
            "camara": {"modo": c.get("camara") or "seguir", "desde": ini, "keyframes": []},
            "subtitulos": {"estilo": (pj.get("opciones") or {}).get("estilo"), "tam": None,
                           "palabras": [w for w in pals if ini - 0.05 <= w["i"] < fin - 0.08],
                           "palabras_clave": c.get("palabras_clave", [])},
            "hook": {"texto": c.get("texto_hook") or c.get("titulo", ""), "posicion": None, "segundos": None, "tam": None},
            "cliente": pj.get("cliente"), "capas": {}, "salida": str(d / c["archivo"]) if c.get("archivo") else "",
            "meta": {k: c.get(k) for k in ("titulo", "texto_hook", "puntuacion", "hook", "flujo", "valor",
                                           "tendencia", "razon", "caption_post", "hashtags")},
        }
        _escribir(ruta, linea)
        c["proyecto"] = f"proyecto/clip{cid}.json"
        hechos.append(cid)
    if hechos:
        _escribir(d / "clips.json", clips)
    return hechos


def _miniatura(d: Path, linea: dict) -> str | None:
    salida = Path(linea.get("salida") or "")
    if not salida.exists():
        return None
    mini = d / "miniaturas" / f"clip{linea['id']}.jpg"
    if not mini.exists() or mini.stat().st_mtime < salida.stat().st_mtime:
        mini.parent.mkdir(parents=True, exist_ok=True)
        try:
            m.correr([m.FFMPEG, "-nostdin", "-y", "-ss", "1.2", "-i", str(salida), "-frames:v", "1",
                      "-vf", "scale=270:-2", "-q:v", "4", str(mini)])
        except Exception:
            return None
    return _url_media(d, mini) + f"?v={int(mini.stat().st_mtime)}"


@app.get("/api/estado")
def estado():
    return {"version": m.VERSION, "nvenc": _nvenc(), "clientes": m.listar_clientes(),
            "resultados": str(m.RESULTADOS)}


@app.get("/api/proyectos")
def proyectos():
    out = []
    if not m.RESULTADOS.exists():
        return out
    for d in sorted((p for p in m.RESULTADOS.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True):
        clips = _leer(d / "clips.json", None)
        if not isinstance(clips, list) or not clips:
            continue
        pj = _leer(d / "proyecto.json", {}) or {}
        out.append({"carpeta": d.name, "titulo": pj.get("titulo") or d.name, "clips": len(clips),
                    "fecha": pj.get("fecha") or _dt.datetime.fromtimestamp(d.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                    "cliente": pj.get("cliente"), "editable": bool(_fuente_de(d)),
                    "v01": not (d / "proyecto").exists()})
    return out


@app.get("/api/proyecto/{carpeta}")
def proyecto(carpeta: str):
    d = _carpeta(carpeta)
    if not (d / "proyecto").exists() or not list((d / "proyecto").glob("clip*.json")):
        if not _fuente_de(d):
            raise HTTPException(409, "No encuentro el video original de esta carpeta, asi que no se puede editar.")
        importar_v01(d)
    pj = _leer(d / "proyecto.json", {}) or {}
    clips = []
    for ruta in sorted((d / "proyecto").glob("clip[0-9]*.json")):
        if not re.fullmatch(r"clip\d+\.json", ruta.name):
            continue
        l = _leer(ruta, None)
        if not l:
            continue
        meta = l.get("meta") or {}
        clips.append({"id": l["id"], "titulo": meta.get("titulo") or f"Clip {l['id']}",
                      "puntuacion": meta.get("puntuacion") or 0, "inicio": l["inicio"], "fin": l["fin"],
                      "duracion": l.get("duracion") or round(l["fin"] - l["inicio"], 1), "editado": bool(l.get("editado")),
                      "miniatura": _miniatura(d, l),
                      "video": _url_media(d, Path(l["salida"])) if l.get("salida") and Path(l["salida"]).exists() and
                      Path(l["salida"]).resolve().is_relative_to(d.resolve()) else None,
                      "texto_hook": (l.get("hook") or {}).get("texto")})
    clips.sort(key=lambda c: (-int(c["puntuacion"] or 0), c["id"]))
    return {"carpeta": d.name, "titulo": pj.get("titulo") or d.name, "cliente": pj.get("cliente"),
            "fuente": _fuente_de(d), "clips": clips, "duracion_fuente": _transcripcion(d).get("duracion")}


def _linea(d: Path, cid: str) -> tuple[Path, dict]:
    ruta = d / "proyecto" / f"clip{cid}.json"
    l = _leer(ruta, None)
    if not l:
        raise HTTPException(404, "no existe ese clip")
    l.setdefault("tomas", [{"modo": "auto", "desde": l["inicio"], "hasta": l["fin"]}])
    l.setdefault("cortes", [])
    l.setdefault("silencios", "normal")
    l.setdefault("zoom_en_cortes", True)
    l.setdefault("camara", {"modo": "seguir", "keyframes": []})
    l["camara"].setdefault("desde", l["inicio"])
    if not l.get("fuente_w"):
        info = m.info_video(l["fuente"])
        l["fuente_w"], l["fuente_h"] = info["w"], info["h"]
    return ruta, l


def _palabras_contexto(d: Path, l: dict, desde: float, hasta: float) -> list:
    """Las palabras de la ventana: dentro del clip las del clip (ya corregidas), fuera las de la transcripcion."""
    dentro = [w for w in l["subtitulos"]["palabras"]]
    a, b = (min(w["i"] for w in dentro), max(w["f"] for w in dentro)) if dentro else (l["inicio"], l["fin"])
    fuera = [w for w in _transcripcion(d)["palabras"] if desde <= w["i"] <= hasta and not (a - 0.01 <= w["i"] <= b + 0.01)]
    return sorted([dict(w) for w in dentro + fuera], key=lambda w: w["i"])


@app.get("/api/clip/{carpeta}/{cid}")
def clip(carpeta: str, cid: str, desde: float | None = None, hasta: float | None = None):
    d = _carpeta(carpeta)
    cid = _id(cid)
    _, l = _linea(d, cid)
    tr = _transcripcion(d)
    dur = float(tr.get("duracion") or m.info_video(l["fuente"])["dur"])
    desde = max(0.0, l["inicio"] - CONTEXTO) if desde is None else max(0.0, float(desde))
    hasta = min(dur, l["fin"] + CONTEXTO) if hasta is None else min(dur, float(hasta))
    cfg = m.cfg_de_linea(l)
    pj = _leer(d / "proyecto.json", {}) or {}
    return {
        "linea": l, "duracion_fuente": dur, "ventana": [desde, hasta],
        "palabras": _palabras_contexto(d, l, desde, hasta),
        "reacciones": [r for r in tr.get("reacciones", []) if r[1] >= desde and r[0] <= hasta],
        "opciones": {k: cfg.get(k) for k in ("estilo", "tam_subtitulos", "hook_posicion", "hook_segundos", "tam_hook",
                                             "silencios", "zoom_en_cortes", "formato")},
        "clientes": m.listar_clientes(), "cliente": l.get("cliente") or pj.get("cliente") or "",
        "titulo_proyecto": pj.get("titulo") or d.name,
        "fuentes": [{"nombre": p.name, "url": f"/fuentes/{p.name}", "familias": _familias(p)}
                    for p in sorted(list(m.FUENTES.glob("*.ttf")) + list(m.FUENTES.glob("*.otf")))],
    }


def _familias(p: Path) -> list:
    try:
        from PIL import ImageFont
        f = ImageFont.truetype(str(p), 20)
        fam, est = f.getname()
        return sorted({fam.lower(), f"{fam} {est}".lower(), p.stem.lower(), p.stem.replace("-", " ").lower()})
    except Exception:
        return [p.stem.lower()]


# --------------------------------------------------------------------------------------
# proxy (video liviano para el editor), onda de audio y capas
# --------------------------------------------------------------------------------------

@app.post("/api/proxy/{carpeta}/{cid}")
def proxy(carpeta: str, cid: str, datos: dict = Body(...)):
    d = _carpeta(carpeta)
    cid = _id(cid)
    _, l = _linea(d, cid)
    dur = float(_transcripcion(d).get("duracion") or m.info_video(l["fuente"])["dur"])
    desde = max(0.0, float(datos.get("desde", l["inicio"] - CONTEXTO)))
    hasta = min(dur, float(datos.get("hasta", l["fin"] + CONTEXTO)))
    # se reutiliza cualquier proxy que ya cubra la ventana
    carpeta_p = d / "proxy"
    carpeta_p.mkdir(exist_ok=True)
    for p in carpeta_p.glob(f"clip{cid}_*.mp4"):
        mm = re.fullmatch(rf"clip{cid}_(\d+)_(\d+)\.mp4", p.name)
        if mm and int(mm.group(1)) / 10 <= desde + 0.01 and int(mm.group(2)) / 10 >= hasta - 0.01 and p.stat().st_size > 1000:
            return {"url": _url_media(d, p), "desde": int(mm.group(1)) / 10, "hasta": int(mm.group(2)) / 10}
    a, b = int(desde * 10), int(round(hasta * 10))
    salida = carpeta_p / f"clip{cid}_{a}_{b}.mp4"
    tmp = salida.with_suffix(".tmp.mp4")
    cpu = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-g", "15", "-bf", "0", "-tune", "fastdecode"]
    gpu = ["-c:v", "h264_nvenc", "-preset", "p3", "-cq", "30", "-b:v", "0", "-g", "15", "-bf", "0"]

    def cmd(enc):
        return [m.FFMPEG, "-nostdin", "-y", "-ss", f"{a / 10:.3f}", "-t", f"{(b - a) / 10:.3f}", "-i", l["fuente"],
                "-vf", "scale=-2:540,setsar=1", *enc, "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-ac", "2",
                "-movflags", "+faststart", str(tmp)]

    if _nvenc():
        try:
            m.correr(cmd(gpu))
        except RuntimeError:
            m.correr(cmd(cpu))
    else:
        m.correr(cmd(cpu))
    os.replace(tmp, salida)
    # proxies viejos de este clip que ya no hacen falta
    for p in carpeta_p.glob(f"clip{cid}_*.mp4"):
        if p != salida:
            try:
                p.unlink()
            except OSError:
                pass
    return {"url": _url_media(d, salida), "desde": a / 10, "hasta": b / 10}


@app.get("/api/onda/{carpeta}")
def onda(carpeta: str, desde: float, hasta: float, n: int = 1500):
    d = _carpeta(carpeta)
    wav = d / "audio16k.wav"
    if not wav.exists():
        f = _fuente_de(d)
        if not f:
            return {"picos": []}
        m.extraer_audio(f, wav)
    n = max(50, min(6000, n))
    with wave.open(str(wav), "rb") as w:
        sr = w.getframerate()
        total = w.getnframes()
        i0, i1 = max(0, int(desde * sr)), min(total, int(hasta * sr))
        w.setpos(i0)
        x = np.frombuffer(w.readframes(max(0, i1 - i0)), dtype=np.int16).astype(np.float32) / 32768.0
    if len(x) < n:
        return {"picos": [round(float(abs(v)), 3) for v in x]}
    paso = len(x) // n
    x = np.abs(x[: paso * n]).reshape(n, paso)
    picos = np.sqrt(np.mean(x ** 2, axis=1)) * 2.2
    return {"picos": [round(float(min(1.0, v)), 3) for v in picos]}


@app.get("/api/capas/{cliente}")
def capas(cliente: str, w: int = 1080, h: int = 1920):
    """El logo y la tarjeta de cierre del cliente para la vista previa (los mismos PNG que usa el render)."""
    if cliente in ("", "ninguno", "-"):
        return {}
    if cliente not in m.listar_clientes():
        raise HTTPException(404, "cliente desconocido")
    perfil = m.cargar_cliente(cliente)
    destino = m.CACHE / "capas_editor" / cliente / f"{w}x{h}"
    out = {}
    logo = m.capa_logo(perfil, w, h, destino / "capa_logo.png")
    if logo:
        out["logo"] = f"/capa/{cliente}/{w}x{h}/capa_logo.png?v={int(logo.stat().st_mtime)}"
    t = perfil.get("tarjeta_cierre") or {}
    cierre = m.capa_cierre(perfil, w, h, destino / "capa_cierre.png") if t else None
    if cierre:
        out["cierre"] = f"/capa/{cliente}/{w}x{h}/capa_cierre.png?v={int(cierre.stat().st_mtime)}"
        out["cierre_seg"] = float(t.get("segundos", 3.0))
        out["cierre_modo"] = t.get("modo", "encima")
    return out


@app.get("/capa/{cliente}/{tam}/{nombre}")
def capa_archivo(cliente: str, tam: str, nombre: str):
    if cliente not in m.listar_clientes() or nombre not in ("capa_logo.png", "capa_cierre.png") or not re.fullmatch(r"\d+x\d+", tam):
        raise HTTPException(404)
    p = m.CACHE / "capas_editor" / cliente / tam / nombre
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, headers={"Cache-Control": "no-cache"})


@app.get("/media/{carpeta}/{ruta:path}")
def media(carpeta: str, ruta: str):
    d = _carpeta(carpeta)
    p = (d / ruta).resolve()
    if not p.is_relative_to(d.resolve()) or not p.is_file():
        raise HTTPException(404)
    return FileResponse(p)


@app.get("/fuentes/{nombre}")
def fuente(nombre: str):
    p = (m.FUENTES / nombre).resolve()
    if p.parent != m.FUENTES.resolve() or not p.is_file():
        raise HTTPException(404)
    return FileResponse(p, headers={"Cache-Control": "max-age=86400"})


# --------------------------------------------------------------------------------------
# vista previa: tramos y subtitulos (el mismo .ass que usa el render)
# --------------------------------------------------------------------------------------

def _mezclar(l: dict, cambios: dict) -> dict:
    nuevo = json.loads(json.dumps(l))
    for k, v in (cambios or {}).items():
        if k in ("subtitulos", "hook", "meta", "camara") and isinstance(v, dict):
            nuevo.setdefault(k, {}).update(v)
        elif k not in ("id", "fuente", "version"):
            nuevo[k] = v
    return nuevo


@app.post("/api/previa/{carpeta}/{cid}")
def previa(carpeta: str, cid: str, cambios: dict = Body(...)):
    d = _carpeta(carpeta)
    cid = _id(cid)
    _, l = _linea(d, cid)
    l = _mezclar(l, cambios)
    cfg = m.cfg_de_linea(l, m.cargar_config({"cliente": l.get("cliente") or ""}))
    fuente = l["fuente"]
    wav = d / "audio16k.wav"
    if not wav.exists():
        m.extraer_audio(fuente, wav)
    with _CANDADO:  # la envolvente del audio se calcula una vez y se guarda
        tramos = m.tramos_de_linea(l, wav, _transcripcion(d).get("reacciones", []), cfg)
    ini, fin = float(l["inicio"]), float(l["fin"])
    sub = l["subtitulos"]
    pals = [w for w in sub["palabras"] if (w.get("t") or "").strip() and not w.get("oculta")]
    rel = m.palabras_del_clip(pals, {"inicio": ini, "fin": fin}, tramos)
    dur_out = m.duracion_tramos(tramos)
    tmp = m.CACHE / "editor_ass"
    tmp.mkdir(parents=True, exist_ok=True)
    ass = tmp / f"{uuid.uuid4().hex}.ass"
    m.generar_ass(rel, cfg, int(l["ancho"]), int(l["alto"]), (l.get("hook") or {}).get("texto", ""),
                  sub.get("palabras_clave", []), ass, dur_out)
    texto = ass.read_text(encoding="utf-8")
    try:
        ass.unlink()
    except OSError:
        pass
    return {"tramos": tramos, "duracion": dur_out, "ass": texto,
            "opciones": {k: cfg.get(k) for k in ("estilo", "tam_subtitulos", "hook_posicion", "hook_segundos",
                                                 "tam_hook", "silencios", "zoom_en_cortes", "hook")}}


# --------------------------------------------------------------------------------------
# caras (para centrar el recorte o armar el split) y seguimiento automatico
# --------------------------------------------------------------------------------------

@app.post("/api/caras/{carpeta}/{cid}")
def caras(carpeta: str, cid: str, datos: dict = Body(...)):
    d = _carpeta(carpeta)
    _, l = _linea(d, _id(cid))
    t = float(datos.get("t", l["inicio"]))
    info = m.info_video(l["fuente"])
    muestras = m.analizar_caras(l["fuente"], max(0.0, t - 0.4), t + 0.6, info, fps=5.0)
    mejor = max(muestras, key=lambda s: len(s[1]), default=(0, []))[1]
    return {"caras": sorted(({"cx": round(c["cx"]), "cy": round(c["cy"]), "w": round(c["w"])} for c in mejor),
                            key=lambda c: c["cx"]), "w": info["w"], "h": info["h"]}


@app.post("/api/seguimiento/{carpeta}/{cid}")
def seguimiento(carpeta: str, cid: str, datos: dict = Body(...)):
    """Vuelve a calcular el seguimiento automatico para un rango nuevo (cuando alargas el clip)."""
    d = _carpeta(carpeta)
    _, l = _linea(d, _id(cid))
    ini, fin = float(datos.get("inicio", l["inicio"])), float(datos.get("fin", l["fin"]))
    info = m.info_video(l["fuente"])
    fps = float(l["fps"])
    muestras = m.analizar_caras(l["fuente"], ini, fin, info)
    plan = m.plan_camara(muestras, info, int(l["ancho"]), int(l["alto"]), fps, fin - ini)
    return {"modo": plan["modo"], "cw": plan.get("cw"), "ch": plan.get("ch"), "desde": ini, "hasta": fin, "recorte": plan.get("recorte"),
            "keyframes": m._keyframes_camara(plan, fps)}


# --------------------------------------------------------------------------------------
# guardar, clip nuevo, buscar, subir graficos
# --------------------------------------------------------------------------------------

@app.put("/api/clip/{carpeta}/{cid}")
def guardar(carpeta: str, cid: str, cambios: dict = Body(...)):
    d = _carpeta(carpeta)
    cid = _id(cid)
    ruta, l = _linea(d, cid)
    hist = d / "proyecto" / "historial"
    hist.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ruta, hist / f"clip{cid}_{_dt.datetime.now():%Y%m%d_%H%M%S}.json")
    viejos = sorted(hist.glob(f"clip{cid}_*.json"))
    for p in viejos[:-20]:  # se guardan las ultimas 20 versiones
        p.unlink(missing_ok=True)
    nuevo = _mezclar(l, cambios)
    ini, fin = float(nuevo["inicio"]), float(nuevo["fin"])
    if fin - ini < 1.0:
        raise HTTPException(400, "El clip tiene que durar al menos 1 segundo.")
    nuevo["subtitulos"]["palabras"] = [w for w in nuevo["subtitulos"]["palabras"] if ini - 0.05 <= w["i"] < fin - 0.08]
    nuevo["editado"] = True
    nuevo["guardado"] = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    _escribir(ruta, nuevo)
    return {"ok": True, "guardado": nuevo["guardado"]}


@app.get("/api/buscar/{carpeta}")
def buscar(carpeta: str, q: str = ""):
    d = _carpeta(carpeta)
    q = m._normalizar(q).strip()
    if len(q) < 2:
        return []
    out = []
    for fr in m.frases(_transcripcion(d)["palabras"]):
        if q in m._normalizar(fr["texto"]):
            out.append({"i": fr["i"], "f": fr["f"], "texto": fr["texto"]})
            if len(out) >= 60:
                break
    return out


@app.post("/api/nuevo/{carpeta}")
def nuevo_clip(carpeta: str, datos: dict = Body(...)):
    """Clip nuevo desde un momento de la transcripcion (empieza en esa frase, dura ~30 s)."""
    d = _carpeta(carpeta)
    tr = _transcripcion(d)
    fuente = _fuente_de(d)
    if not fuente:
        raise HTTPException(409, "no encuentro el video original")
    ini = float(datos["inicio"])
    fin = float(datos.get("fin") or ini + 30.0)
    frs = m.frases(tr["palabras"])
    finales = [f["f"] for f in frs if ini + 15 <= f["f"] <= ini + 45]
    if "fin" not in datos and finales:
        fin = min(finales, key=lambda x: abs(x - (ini + 30)))
    ids = [int(p.stem[4:]) for p in (d / "proyecto").glob("clip[0-9]*.json") if p.stem[4:].isdigit()]
    cid = f"{(max(ids) if ids else 0) + 1:02d}"
    info = m.info_video(fuente)
    fps = 30.0 if info["fps"] > 31 or info["fps"] < 20 else round(info["fps"], 3)
    pj = _leer(d / "proyecto.json", {}) or {}
    ow, oh = m.tamano_salida((pj.get("opciones") or {}).get("formato", "9:16"))
    titulo = (datos.get("titulo") or "").strip() or "Clip nuevo"
    linea = {
        "version": 3, "motor": m.VERSION, "fuente": fuente, "id": cid, "inicio": ini, "fin": fin,
        "tramos": [[ini, fin]], "fps": fps, "ancho": ow, "alto": oh, "fuente_w": info["w"], "fuente_h": info["h"],
        "formato": (pj.get("opciones") or {}).get("formato", "9:16"),
        "silencios": (pj.get("opciones") or {}).get("silencios", "normal"), "zoom_en_cortes": True,
        "cortes": [], "tomas": [{"modo": "auto", "desde": ini, "hasta": fin}],
        "camara": {"modo": "seguir", "desde": ini, "keyframes": []},
        "subtitulos": {"estilo": None, "tam": None,
                       "palabras": [w for w in tr["palabras"] if ini - 0.05 <= w["i"] < fin - 0.08], "palabras_clave": []},
        "hook": {"texto": titulo if titulo != "Clip nuevo" else "", "posicion": None, "segundos": None, "tam": None},
        "cliente": pj.get("cliente"), "capas": {},
        "salida": str(d / "clips" / f"{cid}_0pts_{m.slug(titulo, 40)}.mp4"),
        "meta": {"titulo": titulo, "puntuacion": 0, "caption_post": "", "hashtags": []},
    }
    _escribir(d / "proyecto" / f"clip{cid}.json", linea)
    clips = _leer(d / "clips.json", []) or []
    clips.append({"inicio": ini, "fin": fin, "titulo": titulo, "puntuacion": 0, "proyecto": f"proyecto/clip{cid}.json",
                  "archivo": f"clips/{Path(linea['salida']).name}", "duracion": round(fin - ini, 1), "hashtags": []})
    _escribir(d / "clips.json", clips)
    return {"id": cid}


@app.post("/api/subir/{carpeta}")
async def subir(carpeta: str, archivo: UploadFile = File(...)):
    d = _carpeta(carpeta)
    nombre = Path(archivo.filename or "grafico").name
    base, ext = os.path.splitext(nombre)
    if ext.lower() not in (".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov", ".webm", ".m4v", ".gif"):
        raise HTTPException(400, "Solo imagenes (png, jpg, webp) o videos (mp4, mov, webm).")
    destino = d / "medios" / f"{m.slug(base, 40)}{ext.lower()}"
    destino.parent.mkdir(exist_ok=True)
    k = 1
    while destino.exists():
        destino = d / "medios" / f"{m.slug(base, 40)}-{k}{ext.lower()}"
        k += 1
    with destino.open("wb") as f:
        while True:
            trozo = await archivo.read(1 << 20)
            if not trozo:
                break
            f.write(trozo)
    return {"ruta": destino.relative_to(d).as_posix(), "url": _url_media(d, destino),
            "tipo": "imagen" if m._es_imagen(destino) else "video"}


@app.post("/api/abrir/{carpeta}")
def abrir_carpeta(carpeta: str, datos: dict = Body(default={})):
    d = _carpeta(carpeta)
    que = (datos or {}).get("que")
    destino = {"clips": d / "clips", "portadas": d / "portadas"}.get(que, d)
    destino.mkdir(exist_ok=True)
    m.abrir(destino)
    return {"ok": True}


# --------------------------------------------------------------------------------------
# render en segundo plano (uno a la vez)
# --------------------------------------------------------------------------------------

_TRABAJOS: dict = {}
_COLA = threading.Lock()


def _render(job: str, ruta: Path, exportar: bool):
    t = _TRABAJOS[job]

    def log(msg):
        t["log"].append(str(msg))
        t["log"] = t["log"][-200:]

    with _COLA:
        t["estado"] = "renderizando"
        t0 = time.time()
        try:
            cfg = None
            if exportar:
                l = _leer(ruta, {})
                cfg = m.cfg_de_linea(l)
                cfg["exportar_nle"] = True
            linea = m.render_editado(ruta, log=log, cfg=cfg)
            d = ruta.parent.parent
            t.update({"estado": "listo", "segundos": round(time.time() - t0),
                      "video": _url_media(d, Path(linea["salida"])) + f"?v={int(time.time())}",
                      "duracion": linea.get("duracion")})
        except Exception as e:
            log(f"[ERROR] {e}")
            log(traceback.format_exc()[-1500:])
            t.update({"estado": "error", "error": str(e)[:400]})


@app.post("/api/render/{carpeta}/{cid}")
def render(carpeta: str, cid: str, datos: dict = Body(default={})):
    d = _carpeta(carpeta)
    cid = _id(cid)
    ruta, _ = _linea(d, cid)
    job = uuid.uuid4().hex[:10]
    ocupado = any(t["estado"] in ("en cola", "renderizando") for t in _TRABAJOS.values())
    _TRABAJOS[job] = {"estado": "en cola" if ocupado else "renderizando", "log": [], "clip": cid, "carpeta": d.name}
    threading.Thread(target=_render, args=(job, ruta, bool((datos or {}).get("exportar"))), daemon=True).start()
    return {"job": job}


@app.get("/api/trabajo/{job}")
def trabajo(job: str):
    if job not in _TRABAJOS:
        raise HTTPException(404)
    return _TRABAJOS[job]


# --------------------------------------------------------------------------------------
# portadas (v0.4)
# --------------------------------------------------------------------------------------

def _linea_portada(d: Path, cid: str) -> dict:
    _, l = _linea(d, cid)
    return l


def _datos_marca(perfil: dict | None) -> dict:
    mc = pt.marca_de(perfil)
    cliente = (perfil or {}).get("_id")
    for i in mc["imagenes"]:
        i["url"] = f"/api/cliente_img/{cliente}/{i['ruta']}"
    return mc


@app.get("/api/portadas/{carpeta}")
def portadas(carpeta: str):
    d = _carpeta(carpeta)
    if not (d / "proyecto").exists() or not list((d / "proyecto").glob("clip*.json")):
        if not _fuente_de(d):
            raise HTTPException(409, "No encuentro el video original de esta carpeta.")
        importar_v01(d)
    pj = _leer(d / "proyecto.json", {}) or {}
    clips = []
    for cid in pt.ids_clips(d):
        l = _leer(d / "proyecto" / f"clip{cid}.json", None)
        if not l:
            continue
        meta = l.get("meta") or {}
        dis = pt.cargar_diseno(d, l, crear=False) or {}
        img = dis.get("exportada")
        imagen = None
        if img and (d / img).exists():
            imagen = _url_media(d, d / img) + f"?v={int((d / img).stat().st_mtime)}"
        clips.append({"id": cid, "titulo": meta.get("titulo") or f"Clip {cid}", "puntuacion": meta.get("puntuacion") or 0,
                      "imagen": imagen, "por_exportar": bool(dis) and bool(dis.get("por_exportar")), "tiene": bool(dis),
                      "miniatura": _miniatura(d, l)})
    clips.sort(key=lambda c: (-int(c["puntuacion"] or 0), c["id"]))
    return {"carpeta": d.name, "titulo": pj.get("titulo") or d.name, "clips": clips,
            "plantillas": [{"id": k, "nombre": v} for k, v in pt.PLANTILLAS.items()]}


@app.get("/api/portada/{carpeta}/{cid}")
def portada(carpeta: str, cid: str):
    d = _carpeta(carpeta)
    cid = _id(cid)
    l = _linea_portada(d, cid)
    dis = pt.cargar_diseno(d, l)
    pj = _leer(d / "proyecto.json", {}) or {}
    meta = l.get("meta") or {}
    medios = []
    if (d / "medios").exists():
        medios = [{"nombre": p.stem, "ruta": f"medios/{p.name}", "url": _url_media(d, p)}
                  for p in sorted((d / "medios").iterdir()) if p.is_file() and m._es_imagen(p)]
    return {"diseno": dis, "titulo_proyecto": pj.get("titulo") or d.name, "titulo": meta.get("titulo") or f"Clip {cid}",
            "inicio": l["inicio"], "fin": l["fin"], "fps": l.get("fps") or 30, "formato_clip": l.get("formato") or "9:16",
            "sugeridos": pt.textos_sugeridos(l), "fuentes": pt.fuentes_disponibles(), "clientes": m.listar_clientes(),
            "plantillas": [{"id": k, "nombre": v} for k, v in pt.PLANTILLAS.items()], "formatos": list(pt.FORMATOS),
            "marca": _datos_marca(pt.perfil_de(d, l, dis)), "medios": medios,
            "tiene_video": bool(l.get("salida") and Path(l["salida"]).exists()),
            "exportada": _url_media(d, d / dis["exportada"]) if dis.get("exportada") and (d / dis["exportada"]).exists() else None}


@app.get("/api/portada_marca/{cliente}")
def portada_marca(cliente: str):
    if cliente in ("", "-"):
        return _datos_marca(None)
    if cliente not in m.listar_clientes():
        raise HTTPException(404, "cliente desconocido")
    return _datos_marca(m.cargar_cliente(cliente))


@app.get("/api/cliente_img/{cliente}/{ruta:path}")
def cliente_img(cliente: str, ruta: str):
    if cliente not in m.listar_clientes():
        raise HTTPException(404)
    raiz = (m.CLIENTES / cliente).resolve()
    p = (raiz / ruta).resolve()
    if not p.is_relative_to(raiz) or not p.is_file() or not m._es_imagen(p):
        raise HTTPException(404)
    return FileResponse(p)


@app.get("/api/portada/{carpeta}/{cid}/candidatos")
def portada_candidatos(carpeta: str, cid: str):
    d = _carpeta(carpeta)
    l = _linea_portada(d, _id(cid))
    cuadros = pt.candidatos(d, l)
    return [{**c, "url": _url_media(d, d / c["archivo"]), "encuadre": pt.encuadre_clip(l, c["t"])} for c in cuadros]


@app.post("/api/portada/{carpeta}/{cid}/previa")
def portada_previa(carpeta: str, cid: str, datos: dict = Body(...)):
    d = _carpeta(carpeta)
    l = _linea_portada(d, _id(cid))
    return pt.previa(d, l, datos.get("diseno") or {}, int(datos.get("ancho") or 540))


@app.post("/api/portada/{carpeta}/{cid}/plantilla")
def portada_plantilla(carpeta: str, cid: str, datos: dict = Body(...)):
    d = _carpeta(carpeta)
    l = _linea_portada(d, _id(cid))
    dis = datos.get("diseno") or {}
    return pt.aplicar_plantilla(dis, str(datos.get("nombre") or "titular"), l, pt.perfil_de(d, l, dis))


@app.post("/api/portada/{carpeta}/{cid}/encuadre")
def portada_encuadre(carpeta: str, cid: str, datos: dict = Body(...)):
    d = _carpeta(carpeta)
    l = _linea_portada(d, _id(cid))
    return pt.encuadre_clip(l, float(datos.get("t", l["inicio"])))


@app.put("/api/portada/{carpeta}/{cid}")
def portada_guardar(carpeta: str, cid: str, dis: dict = Body(...)):
    d = _carpeta(carpeta)
    cid = _id(cid)
    _linea_portada(d, cid)
    return {"ok": True, "guardado": pt.guardar_diseno(d, cid, dis)["guardado"]}


@app.post("/api/portada/{carpeta}/{cid}/exportar")
def portada_exportar(carpeta: str, cid: str, dis: dict = Body(...)):
    d = _carpeta(carpeta)
    cid = _id(cid)
    l = _linea_portada(d, cid)
    salida = pt.exportar(d, l, pt.guardar_diseno(d, cid, dis))
    return {"url": _url_media(d, salida) + f"?v={int(time.time())}", "archivo": salida.name}


def _trabajo_portadas(job: str, fn):
    t = _TRABAJOS[job]

    def log(msg):
        t["log"].append(str(msg))
        t["log"] = t["log"][-200:]

    with _COLA:
        t["estado"] = "renderizando"
        t0 = time.time()
        try:
            t.update({"resultado": fn(log), "estado": "listo", "segundos": round(time.time() - t0)})
        except Exception as e:
            log(f"[ERROR] {e}")
            log(traceback.format_exc()[-1500:])
            t.update({"estado": "error", "error": str(e)[:400]})


def _lanzar_portadas(fn, carpeta: str) -> dict:
    job = uuid.uuid4().hex[:10]
    ocupado = any(t["estado"] in ("en cola", "renderizando") for t in _TRABAJOS.values())
    _TRABAJOS[job] = {"estado": "en cola" if ocupado else "renderizando", "log": [], "carpeta": carpeta}
    threading.Thread(target=_trabajo_portadas, args=(job, fn), daemon=True).start()
    return {"job": job}


@app.post("/api/portadas/{carpeta}/generar")
def portadas_generar(carpeta: str, datos: dict = Body(default={})):
    d = _carpeta(carpeta)
    plantilla = (datos or {}).get("plantilla")
    rehacer = bool((datos or {}).get("rehacer"))

    def fn(log):
        return len(pt.generar_todas(d, plantilla, rehacer, log=log))
    return _lanzar_portadas(fn, d.name)


@app.post("/api/portada/{carpeta}/{cid}/video")
def portada_video(carpeta: str, cid: str):
    d = _carpeta(carpeta)
    l = _linea_portada(d, _id(cid))

    def fn(log):
        return _url_media(d, pt.video_con_portada(d, l, log=log)) + f"?v={int(time.time())}"
    return _lanzar_portadas(fn, d.name)


# --------------------------------------------------------------------------------------
# pagina
# --------------------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def inicio():
    return HTMLResponse((ESTATICO / "index.html").read_text(encoding="utf-8"),
                        headers={"Cache-Control": "no-cache"})


app.mount("/web", StaticFiles(directory=str(ESTATICO)), name="web")


@app.exception_handler(Exception)
async def _error(_req: Request, exc: Exception):
    return JSONResponse({"detail": f"{type(exc).__name__}: {exc}"}, status_code=500)


def puerto_libre(p: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", p)) != 0


def main():
    ap = argparse.ArgumentParser(description="Editor de MiOpusClip")
    ap.add_argument("--puerto", type=int, default=PUERTO)
    ap.add_argument("--no-abrir", action="store_true")
    ap.add_argument("--abrir", default="", help="ruta dentro del editor, p.ej. #/proyecto/<carpeta>")
    ap.add_argument("--red", action="store_true", help="que tambien se pueda abrir desde otra compu de tu red")
    a = ap.parse_args()
    if a.red:
        os.environ["MIOPUSCLIP_RED"] = "1"
    RED.update(m.config_red())
    url = f"http://127.0.0.1:{a.puerto}/{a.abrir}"
    if not puerto_libre(a.puerto):
        print(f"El editor ya esta abierto: {url}")
        if not a.no_abrir:
            import webbrowser
            webbrowser.open(url)
        return
    m.RESULTADOS.mkdir(parents=True, exist_ok=True)
    print(f"MiOpusClip {m.VERSION} - editor en {url}\n(no cierres esta ventana mientras lo usas)")
    if RED["activa"]:
        print(f"\nDesde la Mac (u otra compu de tu casa): http://{RED['ip']}:{a.puerto}"
              f"   usuario: {RED['usuario']}   clave: {RED['clave']}")
    if not a.no_abrir:
        import webbrowser
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    import uvicorn
    uvicorn.run(app, host="0.0.0.0" if RED["activa"] else "127.0.0.1", port=a.puerto, log_level="warning")


if __name__ == "__main__":
    main()
