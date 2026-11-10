# -*- coding: utf-8 -*-
"""MiOpusClip - exportar un clip a Premiere Pro (2025.6 o mas nuevo) y DaVinci Resolve (18.5 o mas nuevo).

Por cada clip deja una carpeta con:
    clip.otio               la linea de tiempo (se importa directo en Premiere y en DaVinci)
    video_vertical.mp4      el video ya reencuadrado, con 2 s de sobra antes y despues para ajustar cortes
    subtitulos_alpha.mov    subtitulos + titulo con fondo transparente (ProRes 4444), el look exacto
    subtitulos.srt          los mismos subtitulos como texto editable
    capa_logo.png           el logo del cliente ya en su sitio (PNG del tamano del video)
    capa_cierre.png         la tarjeta de cierre (si el cliente tiene)
    LEEME.txt               como importarlo

Uso suelto:  python exportar_nle.py resultados/<carpeta>/proyecto/clip01.json
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import miopusclip as m


def _otio():
    try:
        import opentimelineio as otio  # noqa: F401
    except ImportError:
        print("   instalando OpenTimelineIO (una sola vez)...", flush=True)
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "opentimelineio"], check=True,
                       **m._SIN_VENTANA)
        import opentimelineio as otio  # noqa: F401
    import opentimelineio as otio
    return otio


def _fps_real(fps: float) -> float:
    for nominal, real in ((23.976, 24000 / 1001), (29.97, 30000 / 1001), (59.94, 60000 / 1001)):
        if abs(fps - nominal) < 0.01:
            return real
    return float(fps)


def _srt(palabras: list, ruta: Path, desplazar: float = 0.0) -> None:
    def ts(t):
        t = max(0.0, t)
        h, r = divmod(int(round(t * 1000)), 3600000)
        mi, r = divmod(r, 60000)
        s, ms = divmod(r, 1000)
        return f"{h:02d}:{mi:02d}:{s:02d},{ms:03d}"
    bloques = m._trozos(palabras, 5, 32, set())
    lineas = []
    for k, bl in enumerate(bloques, 1):
        a = bl[0]["i"] + desplazar
        b = (bloques[k][0]["i"] if k < len(bloques) else bl[-1]["f"] + 0.4) + desplazar
        b = min(b, bl[-1]["f"] + 0.6 + desplazar)
        lineas += [str(k), f"{ts(a)} --> {ts(max(b, a + 0.3))}", " ".join(w["t"] for w in bl), ""]
    ruta.write_text("\n".join(lineas), encoding="utf-8")


def _ass_vacio(ruta: Path, ow: int, oh: int) -> Path:
    ruta.write_text("\n".join([
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {ow}", f"PlayResY: {oh}", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        "Style: Cap,Arial,40,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text", ""]),
        encoding="utf-8")
    return ruta


def exportar_clip(linea: dict, cfg: dict, trabajo: Path, ass: Path, log=print) -> Path:
    """linea = el clipNN.json que deja el render. ass = los subtitulos del clip ya recortado."""
    otio = _otio()
    fuente = linea["fuente"]
    fps = float(linea["fps"])
    rate = _fps_real(fps)
    ow, oh = int(linea["ancho"]), int(linea["alto"])
    ini, fin = float(linea["inicio"]), float(linea["fin"])
    tramos = linea["tramos"]
    titulo = (linea.get("meta") or {}).get("titulo") or "clip"
    info = m.info_video(fuente)
    margen = float(cfg.get("margen_exportar", 2.0))
    e0, e1 = max(0.0, ini - margen), min(info["dur"] or fin + margen, fin + margen)
    e0 = ini - round((ini - e0) * fps) / fps  # margen en frames enteros
    carpeta = Path(trabajo) / "exportar" / f"{linea['id']}_{m.slug(titulo, 40)}"
    carpeta.mkdir(parents=True, exist_ok=True)
    tmp = Path(ass).parent
    log(f"   exportando para Premiere/DaVinci -> exportar/{carpeta.name}")

    # 1) video vertical con margen, sin subtitulos ni logo (la camara se recalcula para el tramo largo)
    vv = carpeta / "video_vertical.mp4"
    muestras = m.analizar_caras(fuente, e0, e1, info)
    plan = m.plan_camara(muestras, info, ow, oh, fps, e1 - e0)
    plan["fps"] = fps
    sub_vacio = _ass_vacio(tmp / "vacio.ass", ow, oh)
    cfg_v = dict(cfg, zoom_en_cortes=False, calidad=min(int(cfg.get("calidad", 20)), 16))
    m.renderizar_clip(fuente, {"inicio": e0, "fin": e1}, plan, sub_vacio, vv, info, ow, oh, cfg_v, [[e0, e1]], {})

    # 2) subtitulos: con transparencia (look exacto) y en .srt (editables)
    pals = [w for w in linea["subtitulos"]["palabras"]]
    rel = m.palabras_del_clip(pals, {"inicio": ini, "fin": fin}, tramos)
    dur_out = m.duracion_tramos(tramos)
    alpha = carpeta / "subtitulos_alpha.mov"
    m.correr([m.FFMPEG, "-nostdin", "-y", "-f", "lavfi", "-i",
              f"color=c=black@0.0:s={ow}x{oh}:r={m._fps_ffmpeg(fps)}:d={dur_out:.3f},format=rgba",
              "-vf", f"ass={Path(ass).name}:fontsdir=fuentes:alpha=1",
              "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", str(alpha.resolve())], cwd=tmp)
    capas = linea.get("capas") or {}
    intro, outro = capas.get("intro"), capas.get("outro")
    d_intro = 0.0
    if intro:
        d_intro = float(capas.get("intro_seg", 2.0)) if m._es_imagen(intro) else float(m.info_video(intro)["dur"])
    _srt(rel, carpeta / "subtitulos.srt", desplazar=d_intro)

    # 3) capas del cliente
    copias = {}
    for k in ("logo", "cierre", "intro", "outro"):
        if capas.get(k):
            origen = Path(capas[k])
            destino = carpeta / (f"capa_{k}{origen.suffix}" if k in ("logo", "cierre") else f"{k}{origen.suffix}")
            shutil.copy2(origen, destino)
            copias[k] = destino

    # 4) la linea de tiempo
    def rt(seg):
        return otio.opentime.RationalTime(round(seg * rate), rate)

    def rango(a, d):
        return otio.opentime.TimeRange(rt(a), rt(d))

    def ref(ruta: Path, dur: float):
        return otio.schema.ExternalReference(target_url=ruta.resolve().as_uri(), available_range=rango(0, dur))

    largo_vv = e1 - e0
    tl = otio.schema.Timeline(name=f"{linea['id']} {titulo}")
    tl.global_start_time = rt(0)
    v1 = otio.schema.Track(name="V1 Video", kind=otio.schema.TrackKind.Video)
    a1 = otio.schema.Track(name="A1 Audio", kind=otio.schema.TrackKind.Audio)

    def bumper(cual):
        ruta = copias.get(cual)
        if not ruta:
            return
        if m._es_imagen(ruta):
            d = float(capas.get(f"{cual}_seg", 2.0))
            v1.append(otio.schema.Clip(name=cual, media_reference=ref(ruta, 3600), source_range=rango(0, d)))
            a1.append(otio.schema.Gap(source_range=rango(0, d)))
        else:
            inf = m.info_video(ruta)
            d = float(inf["dur"])
            v1.append(otio.schema.Clip(name=cual, media_reference=ref(ruta, d), source_range=rango(0, d)))
            if inf["audio"]:
                a1.append(otio.schema.Clip(name=cual, media_reference=ref(ruta, d), source_range=rango(0, d)))
            else:
                a1.append(otio.schema.Gap(source_range=rango(0, d)))

    bumper("intro")
    for j, (a, b) in enumerate(tramos, 1):
        r = rango(a - e0, b - a)
        v1.append(otio.schema.Clip(name=f"tramo {j}", media_reference=ref(vv, largo_vv), source_range=r))
        a1.append(otio.schema.Clip(name=f"tramo {j}", media_reference=ref(vv, largo_vv), source_range=r))
    extra = 0.0
    if copias.get("cierre") and capas.get("cierre_modo") == "despues":
        extra = float(capas.get("cierre_seg", 3.0))
        v1.append(otio.schema.Gap(source_range=rango(0, extra)))
        a1.append(otio.schema.Gap(source_range=rango(0, extra)))
    bumper("outro")

    pistas = [v1]
    v2 = otio.schema.Track(name="V2 Subtitulos", kind=otio.schema.TrackKind.Video)
    if d_intro:
        v2.append(otio.schema.Gap(source_range=rango(0, d_intro)))
    v2.append(otio.schema.Clip(name="subtitulos", media_reference=ref(alpha, dur_out), source_range=rango(0, dur_out)))
    pistas.append(v2)
    if copias.get("logo"):
        v3 = otio.schema.Track(name="V3 Logo", kind=otio.schema.TrackKind.Video)
        if d_intro:
            v3.append(otio.schema.Gap(source_range=rango(0, d_intro)))
        v3.append(otio.schema.Clip(name="logo", media_reference=ref(copias["logo"], 3600),
                                   source_range=rango(0, dur_out + extra)))
        pistas.append(v3)
    if copias.get("cierre"):
        seg = float(capas.get("cierre_seg", 3.0))
        t0 = dur_out if capas.get("cierre_modo") == "despues" else max(0.0, dur_out - seg)
        v4 = otio.schema.Track(name="V4 Cierre", kind=otio.schema.TrackKind.Video)
        v4.append(otio.schema.Gap(source_range=rango(0, d_intro + t0)))
        v4.append(otio.schema.Clip(name="tarjeta de cierre", media_reference=ref(copias["cierre"], 3600),
                                   source_range=rango(0, seg)))
        pistas.append(v4)
    for p in pistas:
        tl.tracks.append(p)
    tl.tracks.append(a1)
    tl.metadata["miopusclip"] = {"motor": m.VERSION, "ancho": ow, "alto": oh, "fps": fps,
                                 "fuente": fuente, "inicio": ini, "fin": fin}
    otio.adapters.write_to_file(tl, str(carpeta / "clip.otio"))
    (carpeta / "LEEME.txt").write_text(LEEME.format(ow=ow, oh=oh, fps=f"{fps:g}", titulo=titulo), encoding="utf-8")
    return carpeta


LEEME = """Clip "{titulo}" para editar en Premiere Pro o DaVinci Resolve
===========================================================

La linea de tiempo es clip.otio. Es vertical: {ow}x{oh} a {fps} fps.
No muevas ni renombres los archivos de esta carpeta (clip.otio los busca aqui).

PREMIERE PRO (2025.6 o mas nuevo)
  Archivo > Importar > elige clip.otio
  Se crea una secuencia con las pistas:
    V1 video (cada tramo es un corte de silencio; tienen 2 s de sobra a cada lado para alargar)
    V2 subtitulos con transparencia   V3 logo   V4 tarjeta de cierre   A1 audio
  Si la secuencia no sale vertical: clic derecho en la secuencia > Ajustes de secuencia >
  Tamano de fotograma {ow} x {oh}.
  Subtitulos editables: Archivo > Importar > subtitulos.srt y arrastralo a la secuencia
  (apaga la pista V2 si usas estos).

DAVINCI RESOLVE (18.5 o mas nuevo)
  1. Antes de importar: Archivo > Ajustes del proyecto > Resolucion de la linea de tiempo
     {ow} x {oh}, y la misma frecuencia ({fps} fps).
  2. Archivo > Importar > Linea de tiempo... > elige clip.otio
     (si pregunta, deja marcado importar los clips a la galeria de medios).
  Subtitulos editables: en el Media Pool, clic derecho > Importar subtitulos > subtitulos.srt.

Hecho con MiOpusClip.
"""


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    ruta = Path(sys.argv[1]).resolve()
    linea = json.loads(ruta.read_text(encoding="utf-8"))
    trabajo = ruta.parent.parent
    cfg = m.cargar_config({"cliente": linea.get("cliente") or ""})
    ow, oh = int(linea["ancho"]), int(linea["alto"])
    tmp = trabajo / "tmp" / f"exportar{linea['id']}"
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "fuentes").mkdir(exist_ok=True)
    for p in list(m.FUENTES.glob("*.ttf")) + list(m.FUENTES.glob("*.otf")):
        shutil.copy2(p, tmp / "fuentes" / p.name)
    sub = linea["subtitulos"]
    cfg.update({"estilo": sub.get("estilo") or cfg["estilo"], "tam_subtitulos": sub.get("tam") or cfg["tam_subtitulos"]})
    h = linea.get("hook") or {}
    for k_cfg, k_h in (("hook_posicion", "posicion"), ("hook_segundos", "segundos"), ("tam_hook", "tam")):
        if h.get(k_h) is not None:
            cfg[k_cfg] = h[k_h]
    rel = m.palabras_del_clip(sub["palabras"], {"inicio": linea["inicio"], "fin": linea["fin"]}, linea["tramos"])
    ass = tmp / "subs.ass"
    m.generar_ass(rel, cfg, ow, oh, h.get("texto", ""), sub.get("palabras_clave", []), ass,
                  m.duracion_tramos(linea["tramos"]))
    carpeta = exportar_clip(linea, cfg, trabajo, ass)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"Listo: {carpeta}")
