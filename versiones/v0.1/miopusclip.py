#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MiOpusClip - tu propio OpusClip.

Video largo (archivo o link) -> transcripcion con tiempos por palabra -> la IA elige
los mejores momentos y les pone puntuacion -> reencuadre vertical siguiendo a quien
habla -> subtitulos animados -> clips listos + galeria HTML.

Uso rapido:
    python miopusclip.py todo "C:/videos/podcast.mp4"
    python miopusclip.py todo "https://www.youtube.com/watch?v=..." --clips 6
    python miopusclip.py diagnostico

Modo por pasos (lo usa el skill de Claude):
    python miopusclip.py transcribir video.mp4 --salida trabajo/
    (alguien escribe trabajo/clips.json)
    python miopusclip.py render video.mp4 --clips trabajo/clips.json --salida trabajo/
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import html
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import wave
from pathlib import Path

import numpy as np

VERSION = "1.0.0"
AQUI = Path(__file__).resolve().parent
MODELOS = AQUI / "modelos"
FUENTES = AQUI / "fuentes"
RESULTADOS = AQUI / "resultados"
CACHE = AQUI / "cache"
PARAKEET_DIR = MODELOS / "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8"
YUNET = MODELOS / "face_detection_yunet_2023mar.onnx"
YUNET_URL = ("https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
             "face_detection_yunet/face_detection_yunet_2023mar.onnx")

try:  # consola de Windows: que los acentos no rompan nada
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

# --------------------------------------------------------------------------------------
# Configuracion
# --------------------------------------------------------------------------------------

CONFIG_DEFECTO = {
    "clips": 8,                 # cuantos clips quieres (maximo)
    "duracion_min": 20,         # segundos
    "duracion_max": 75,
    "formato": "9:16",          # 9:16, 1:1 o 16:9
    "estilo": "opus",           # opus, yulian, simple, ninguno
    "hook": True,               # titulo arriba los primeros segundos
    "hook_segundos": 3.0,
    "idioma": None,             # None = detectar; "es", "en"...
    "ia": "claude",             # claude o ninguna
    "modelo_ia": "claude-sonnet-5-5",
    "backend": "auto",          # auto, whisper, parakeet
    "modelo_whisper": "large-v3-turbo",
    "fuente": "Montserrat ExtraBold",
    "fuente_contraste": "Montserrat Black",
    "contraste_sin_acentos": False,   # pon true si usas Dirty Stains (no tiene acentos)
    "mayusculas": True,
    "color_texto": "#FFFFFF",
    "color_activo": "#FFD60A",  # palabra que se esta diciendo / numeros
    "color_clave": "#E10600",   # palabras clave
    "incluir_risas": True,      # alargar el final si hay risas/aplausos despues del remate
    "calidad": 20,              # 18 = mejor, 23 = mas liviano
}


def cargar_config(extra: dict | None = None) -> dict:
    cfg = dict(CONFIG_DEFECTO)
    archivo = AQUI / "config.json"
    if archivo.exists():
        try:
            cfg.update({k: v for k, v in json.loads(archivo.read_text(encoding="utf-8")).items()
                        if not k.startswith("_")})
        except Exception as e:  # config roto: seguimos con lo de fabrica
            print(f"[aviso] config.json no se pudo leer ({e}); uso valores por defecto")
    if extra:
        cfg.update({k: v for k, v in extra.items() if v is not None})
    return cfg


def cargar_env() -> None:
    """Lee .env (ANTHROPIC_API_KEY=...) sin dependencias."""
    for ruta in (AQUI / ".env", Path.cwd() / ".env"):
        if ruta.exists():
            for linea in ruta.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
                linea = linea.strip()
                if not linea or linea.startswith("#") or "=" not in linea:
                    continue
                k, v = linea.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _log_defecto(msg: str) -> None:
    print(msg, flush=True)


# --------------------------------------------------------------------------------------
# FFmpeg
# --------------------------------------------------------------------------------------

def _buscar_bin(nombre: str) -> str:
    env = os.environ.get(f"MIOPUSCLIP_{nombre.upper()}")
    if env:
        return env
    encontrado = shutil.which(nombre)
    if encontrado:
        return encontrado
    if os.name == "nt":  # winget a veces no refresca el PATH de la sesion
        for base in (Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links",
                     Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"):
            if base.exists():
                for p in base.rglob(f"{nombre}.exe"):
                    return str(p)
    return nombre


FFMPEG = _buscar_bin("ffmpeg")
FFPROBE = _buscar_bin("ffprobe")
_SIN_VENTANA = {"creationflags": 0x08000000} if os.name == "nt" else {}


def correr(cmd: list, cwd: str | Path | None = None) -> str:
    r = subprocess.run([str(c) for c in cmd], cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", **_SIN_VENTANA)
    if r.returncode != 0:
        raise RuntimeError(f"Fallo {Path(str(cmd[0])).name}:\n{(r.stderr or r.stdout)[-2500:]}")
    return r.stdout


def info_video(ruta: str | Path) -> dict:
    out = correr([FFPROBE, "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(ruta)])
    d = json.loads(out)
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), None)
    a = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"), None)
    if v is None:
        raise RuntimeError("El archivo no tiene video.")
    w, h = int(v["width"]), int(v["height"])
    rot = 0
    try:
        rot = int(float(v.get("tags", {}).get("rotate", 0)))
    except Exception:
        pass
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd:
            try:
                rot = int(float(sd["rotation"]))
            except Exception:
                pass
    if abs(rot) % 180 == 90:  # ffmpeg rota solo al decodificar
        w, h = h, w
    num, den = (v.get("avg_frame_rate") or v.get("r_frame_rate") or "30/1").split("/")
    fps = float(num) / float(den) if float(den) else 30.0
    if not 5 < fps < 121:
        fps = 30.0
    dur = float(d.get("format", {}).get("duration") or v.get("duration") or 0)
    return {"w": w, "h": h, "fps": fps, "dur": dur, "audio": a is not None}


def extraer_audio(video: str | Path, wav: Path) -> Path:
    if not wav.exists():
        correr([FFMPEG, "-nostdin", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000",
                "-c:a", "pcm_s16le", str(wav)])
    return wav


def leer_wav(ruta: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(ruta), "rb") as w:
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    return x, sr


def _duracion_wav(ruta: Path) -> float:
    with wave.open(str(ruta), "rb") as w:
        return round(w.getnframes() / float(w.getframerate()), 2)


_NVENC: bool | None = None


def tiene_nvenc() -> bool:
    global _NVENC
    if _NVENC is None:
        if os.environ.get("MIOPUSCLIP_SIN_NVENC"):
            _NVENC = False
        else:
            try:
                correr([FFMPEG, "-nostdin", "-hide_banner", "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.2",
                        "-c:v", "h264_nvenc", "-f", "null", "-"])
                _NVENC = True
            except Exception:
                _NVENC = False
    return _NVENC


def es_url(s: str) -> bool:
    return bool(re.match(r"^https?://", str(s).strip(), re.I))


def slug(s: str, n: int = 50) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return (s[:n].strip("-") or "video")


def fmt_t(seg: float) -> str:
    seg = max(0.0, seg)
    m, s = divmod(seg, 60)
    h, m = divmod(int(m), 60)
    return f"{h}:{m:02d}:{s:05.2f}" if h else f"{m}:{s:05.2f}"


# --------------------------------------------------------------------------------------
# 1. Descargar
# --------------------------------------------------------------------------------------

def descargar(url: str, carpeta: Path, log=_log_defecto) -> tuple[Path, str]:
    try:
        import yt_dlp
    except ImportError:
        raise RuntimeError("Falta yt-dlp: pip install \"yt-dlp[default]\"")
    carpeta.mkdir(parents=True, exist_ok=True)
    ultimo = {"p": -10}

    def progreso(d):
        if d.get("status") == "downloading":
            tot = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if tot:
                p = int(100 * d.get("downloaded_bytes", 0) / tot)
                if p >= ultimo["p"] + 10:
                    ultimo["p"] = p
                    log(f"   descargando... {p}%")

    opts = {
        "outtmpl": str(carpeta / "original.%(ext)s"),
        "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]/b",
        "merge_output_format": "mp4",
        "quiet": True, "no_warnings": True, "noprogress": True, "noplaylist": True,
        "progress_hooks": [progreso],
    }
    if Path(FFMPEG).is_absolute():
        opts["ffmpeg_location"] = str(Path(FFMPEG).parent)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
    titulo = info.get("title") or "video"
    archivos = sorted(carpeta.glob("original.*"), key=lambda p: p.stat().st_size, reverse=True)
    archivos = [p for p in archivos if p.suffix.lower() in (".mp4", ".mkv", ".webm", ".mov")]
    if not archivos:
        raise RuntimeError("yt-dlp no dejo ningun video. Prueba otro link o descarga el archivo a mano.")
    return archivos[0], titulo


# --------------------------------------------------------------------------------------
# 2. Transcribir (faster-whisper en tu PC / Parakeet en la nube)
# --------------------------------------------------------------------------------------

def _preparar_cuda_windows() -> None:
    """faster-whisper necesita cuBLAS y cuDNN; los instalamos con pip y aqui los hacemos visibles."""
    if os.name != "nt":
        return
    import site
    import sysconfig
    bases = set()
    try:
        bases.update(site.getsitepackages())
    except Exception:
        pass
    bases.add(sysconfig.get_paths().get("purelib", ""))
    for base in bases:
        for sub in ("nvidia/cublas/bin", "nvidia/cudnn/bin", "nvidia/cuda_runtime/bin", "nvidia/cuda_nvrtc/bin"):
            p = Path(base) / sub
            if p.is_dir():
                try:
                    os.add_dll_directory(str(p))
                except Exception:
                    pass
                os.environ["PATH"] = str(p) + os.pathsep + os.environ.get("PATH", "")


def _hay_cuda() -> bool:
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def _transcribir_whisper(wav: Path, modelo: str, idioma: str | None, log, vad: bool = True) -> dict:
    _preparar_cuda_windows()
    from faster_whisper import BatchedInferencePipeline, WhisperModel

    def correr_en(device: str) -> dict:
        compute = "float16" if device == "cuda" else "int8"
        log(f"   Whisper {modelo} en {'GPU (CUDA)' if device == 'cuda' else 'CPU'} "
            f"(la primera vez descarga el modelo, ~1.6 GB)")
        m = WhisperModel(modelo, device=device, compute_type=compute)
        if not vad:  # prueba: obliga a que la GPU trabaje de verdad
            segs, info = m.transcribe(str(wav), language=idioma, word_timestamps=True, vad_filter=False)
        else:
            try:
                pipe = BatchedInferencePipeline(model=m)
                segs, info = pipe.transcribe(str(wav), language=idioma, word_timestamps=True,
                                             batch_size=8 if device == "cuda" else 4, vad_filter=True)
            except TypeError:
                segs, info = m.transcribe(str(wav), language=idioma, word_timestamps=True, vad_filter=True)
        total = max(1.0, float(getattr(info, "duration", 0) or 1))
        palabras, ultimo = [], -10
        for seg in segs:
            for w in (seg.words or []):
                t = (w.word or "").strip()
                if t:
                    palabras.append({"t": t, "i": round(float(w.start), 3), "f": round(float(w.end), 3)})
            p = int(100 * float(seg.end) / total)
            if p >= ultimo + 10:
                ultimo = p
                log(f"   transcribiendo... {min(p, 100)}%")
        return {"idioma": getattr(info, "language", idioma) or idioma, "palabras": palabras,
                "backend": f"whisper:{modelo}:{device}"}

    if _hay_cuda():
        try:
            return correr_en("cuda")
        except Exception as e:  # DLL de CUDA que falta, memoria, etc.
            log(f"   [aviso] la GPU fallo ({str(e).splitlines()[0][:160]}). Sigo en CPU (mas lento).")
    return correr_en("cpu")


def _cortes_por_silencio(x: np.ndarray, sr: int, objetivo: float = 20.0, maximo: float = 28.0) -> list:
    """Parte el audio en trozos de ~20 s cortando en el punto mas silencioso."""
    hop = int(sr * 0.02)
    n = len(x) // hop
    if n == 0:
        return [(0, len(x))]
    env = np.sqrt(np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-12)
    cortes, a = [], 0
    while a < len(x):
        if (len(x) - a) / sr <= maximo:
            cortes.append((a, len(x)))
            break
        i0 = (a + int(sr * (objetivo - 6))) // hop
        i1 = min(n, (a + int(sr * maximo)) // hop)
        j = i0 + int(np.argmin(env[i0:i1])) if i1 > i0 else i1
        b = max(a + sr, j * hop)
        cortes.append((a, b))
        a = b
    return cortes


def _transcribir_parakeet(wav: Path, log) -> dict:
    import sherpa_onnx
    if not PARAKEET_DIR.exists():
        raise RuntimeError(f"No encuentro el modelo Parakeet en {PARAKEET_DIR}")
    d = PARAKEET_DIR
    rec = sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=str(d / "encoder.int8.onnx"), decoder=str(d / "decoder.int8.onnx"),
        joiner=str(d / "joiner.int8.onnx"), tokens=str(d / "tokens.txt"),
        num_threads=max(1, os.cpu_count() or 2), model_type="nemo_transducer")
    x, sr = leer_wav(wav)
    trozos = _cortes_por_silencio(x, sr)
    palabras, ultimo = [], -10
    for k, (a, b) in enumerate(trozos):
        s = rec.create_stream()
        s.accept_waveform(sr, x[a:b])
        rec.decode_stream(s)
        r = s.result
        off = a / sr
        durs = list(getattr(r, "durations", []) or [])
        actual = None
        for idx, (tok, ts) in enumerate(zip(r.tokens, r.timestamps)):
            du = durs[idx] if idx < len(durs) else 0.08
            limpio = tok.replace("▁", " ")
            s = limpio.strip()
            if not s:
                continue
            espacio = limpio.startswith(" ")
            cierra = re.fullmatch(r"[\.,;:!?…\"')\]»”]+", s) is not None
            if actual is None:
                nuevo = True
            elif cierra:
                nuevo = False  # la puntuacion de cierre va pegada a la palabra anterior
            elif espacio:
                nuevo = True
            else:
                ult = actual["t"][-1:]
                # "las3" o "noches,cómo": separar
                nuevo = (s[0].isdigit() and ult.isalpha()) or (ult in ",.;:?!…" and s[0].isalnum())
            if nuevo:
                actual = {"t": s, "i": round(off + ts, 3), "f": round(off + ts + du, 3)}
                palabras.append(actual)
            else:
                actual["t"] += s
                actual["f"] = round(off + ts + du, 3)
        p = int(100 * (k + 1) / len(trozos))
        if p >= ultimo + 10:
            ultimo = p
            log(f"   transcribiendo... {p}%")
    return {"idioma": None, "palabras": palabras, "backend": "parakeet-tdt-0.6b-v3"}


def transcribir(video: str | Path, trabajo: Path, cfg: dict, log=_log_defecto) -> dict:
    trabajo.mkdir(parents=True, exist_ok=True)
    wav = extraer_audio(video, trabajo / "audio16k.wav")
    backend = cfg.get("backend", "auto")
    if backend == "auto":
        try:
            import faster_whisper  # noqa: F401
            backend = "whisper"
        except ImportError:
            backend = "parakeet"
    st = Path(video).stat()
    clave = hashlib.sha1(f"{Path(video).resolve()}|{st.st_size}|{int(st.st_mtime)}|{backend}|"
                         f"{cfg.get('modelo_whisper')}|{cfg.get('idioma')}".encode()).hexdigest()[:16]
    cache = CACHE / "transcripciones" / f"{clave}.json"
    if cache.exists():
        log("2/5 Transcripcion: ya la tenia guardada, la reuso.")
        datos = json.loads(cache.read_text(encoding="utf-8"))
    else:
        log("2/5 Transcribiendo (tiempos por palabra)...")
        t0 = time.time()
        if backend == "whisper":
            datos = _transcribir_whisper(wav, cfg.get("modelo_whisper", "large-v3-turbo"), cfg.get("idioma"), log)
        else:
            datos = _transcribir_parakeet(wav, log)
        datos["duracion"] = _duracion_wav(wav)
        log(f"   listo: {len(datos['palabras'])} palabras en {time.time() - t0:.0f} s")
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    if "duracion" not in datos:
        datos["duracion"] = _duracion_wav(wav)
    datos["palabras"], marcas = _limpiar_palabras(datos["palabras"])
    datos["reacciones"] = detectar_reacciones(wav, datos["palabras"], marcas)
    (trabajo / "transcripcion.json").write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    (trabajo / "transcripcion_llm.txt").write_text(texto_para_ia(datos), encoding="utf-8")
    return datos


_RUIDO = re.compile(r"^[\[\(\*].*[\]\)\*]$")
_RISA = re.compile(r"risa|laugh|aplaus|applause|música|musica|music", re.I)


def _limpiar_palabras(palabras: list) -> tuple[list, list]:
    """Quita marcas tipo [Risas] (Musica) y las devuelve como posibles reacciones."""
    limpias, marcas = [], []
    for w in palabras:
        t = w["t"].strip()
        if _RUIDO.match(t):
            if _RISA.search(t):
                marcas.append((w["i"], max(w["f"], w["i"] + 0.8)))
            continue
        if w["f"] <= w["i"]:
            w["f"] = round(w["i"] + 0.05, 3)
        limpias.append({"t": t, "i": w["i"], "f": w["f"]})
    limpias.sort(key=lambda w: w["i"])
    return limpias, marcas


# --------------------------------------------------------------------------------------
# Senales de audio: risas / aplausos (oro para comedia) y energia para cortes limpios
# --------------------------------------------------------------------------------------

def _envolvente_db(x: np.ndarray, sr: int, hop_s: float) -> np.ndarray:
    hop = max(1, int(sr * hop_s))
    n = len(x) // hop
    if n == 0:
        return np.array([-90.0])
    rms = np.sqrt(np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-10)
    return 20 * np.log10(rms + 1e-10)


def detectar_reacciones(wav: Path, palabras: list, marcas: list | None = None) -> list:
    """Zonas sin palabras pero con sonido fuerte (risas, aplausos, gritos del publico)."""
    x, sr = leer_wav(wav)
    hop = 0.05
    db = _envolvente_db(x, sr, hop)
    n = len(db)
    habla = np.zeros(n, bool)
    for w in palabras:
        habla[max(0, int((w["i"] - 0.08) / hop)): min(n, int((w["f"] + 0.08) / hop) + 1)] = True
    if habla.sum() < 10:
        return []
    voz = float(np.median(db[habla]))
    piso = float(np.percentile(db, 10))
    umbral = max(piso + 15, voz - 10)
    fuerte = (db > umbral) & ~habla
    reacciones, i = [], 0
    while i < n:
        if fuerte[i]:
            j, huecos = i, 0
            while j + 1 < n and (fuerte[j + 1] or (huecos < 2 and not habla[j + 1])):
                huecos = 0 if fuerte[j + 1] else huecos + 1
                j += 1
            ini, fin = i * hop, (j + 1 - huecos) * hop
            if fin - ini >= 0.6:
                reacciones.append([round(ini, 2), round(fin, 2)])
            i = j + 1
        else:
            i += 1
    for a, b in (marcas or []):
        if not any(r[0] - 0.5 <= a <= r[1] + 0.5 for r in reacciones):
            reacciones.append([round(a, 2), round(b, 2)])
    unidas = []
    for r in sorted(reacciones):  # una risa larga con pausas cuenta como una
        if unidas and r[0] - unidas[-1][1] < 0.7:
            unidas[-1][1] = max(unidas[-1][1], r[1])
        else:
            unidas.append(list(r))
    return unidas


def frases(palabras: list) -> list:
    """Agrupa palabras en frases (por puntuacion, pausas largas o longitud)."""
    out, ini = [], 0
    for k, w in enumerate(palabras):
        fin_frase = bool(re.search(r"[\.\?!…]['\"»”)]*$", w["t"]))
        pausa = k + 1 < len(palabras) and palabras[k + 1]["i"] - w["f"] > 1.0
        largo = k - ini >= 35
        if fin_frase or pausa or largo or k == len(palabras) - 1:
            grupo = palabras[ini:k + 1]
            out.append({"i": grupo[0]["i"], "f": grupo[-1]["f"], "w0": ini, "w1": k,
                        "texto": " ".join(p["t"] for p in grupo)})
            ini = k + 1
    return out


def texto_para_ia(datos: dict) -> str:
    lineas, rs = [], list(datos.get("reacciones", []))
    for fr in frases(datos["palabras"]):
        while rs and rs[0][0] < fr["i"]:
            a, b = rs.pop(0)
            lineas.append(f"[{a:.1f}] (RISAS/APLAUSOS {b - a:.1f}s)")
        lineas.append(f"[{fr['i']:.1f}-{fr['f']:.1f}] {fr['texto']}")
    for a, b in rs:
        lineas.append(f"[{a:.1f}] (RISAS/APLAUSOS {b - a:.1f}s)")
    return "\n".join(lineas)


# --------------------------------------------------------------------------------------
# 3. Elegir los momentos (Claude) + puntuacion de viralidad
# --------------------------------------------------------------------------------------

_PROPS_CLIP = {
    "inicio": {"type": "number", "description": "Segundo donde empieza (inicio de una frase)."},
    "fin": {"type": "number", "description": "Segundo donde termina (fin de una frase o de las risas)."},
    "titulo": {"type": "string", "description": "Titulo corto y llamativo, maximo 8 palabras."},
    "texto_hook": {"type": "string", "description": "Texto que sale arriba los primeros segundos. Maximo 7 palabras."},
    "hook": {"type": "integer", "description": "0 a 25"},
    "flujo": {"type": "integer", "description": "0 a 25"},
    "valor": {"type": "integer", "description": "0 a 25"},
    "tendencia": {"type": "integer", "description": "0 a 25"},
    "razon": {"type": "string", "description": "Una frase: por que este clip funciona."},
    "caption_post": {"type": "string", "description": "Texto para publicar con el clip (1-2 frases)."},
    "hashtags": {"type": "array", "items": {"type": "string"}},
    "palabras_clave": {"type": "array", "items": {"type": "string"},
                       "description": "0 a 3 palabras EXACTAS del clip que el que habla enfatiza."},
}
ESQUEMA_CLIPS = {
    "type": "object",
    "properties": {
        "clips": {
            "type": "array",
            "items": {"type": "object", "properties": _PROPS_CLIP, "required": list(_PROPS_CLIP),
                      "additionalProperties": False},
        }
    },
    "required": ["clips"],
    "additionalProperties": False,
}
HERRAMIENTA_CLIPS = {
    "name": "entregar_clips",
    "description": "Entrega los clips elegidos, ordenados de mayor a menor puntuacion.",
    "input_schema": ESQUEMA_CLIPS,
}

SISTEMA_IA = """Eres el mejor editor de clips cortos (TikTok, Reels, Shorts) para contenido hablado: stand-up, podcasts, entrevistas, gente hablando a camara. Recibes la transcripcion de un video largo con tiempos en segundos y eliges los momentos con mas potencial de volverse virales.

Reglas para cada clip:
- Se entiende solo, sin haber visto el resto del video.
- Empieza al inicio de una frase y engancha en los primeros 3 segundos (pregunta, frase polemica, inicio de historia, dato fuerte). Nunca empieza a mitad de idea ni con "y", "entonces", "o sea" si se puede evitar.
- Termina en un cierre natural: remate del chiste, conclusion, giro. Si despues del remate hay (RISAS/APLAUSOS), el clip termina al final de las risas.
- Sin tiempos muertos. No se solapa con otros clips.
- Usa los tiempos exactos que aparecen en la transcripcion.

Puntuacion (se honesto, reparte las notas; no todo es 90):
- hook 0-25: los primeros 3 segundos paran el scroll.
- flujo 0-25: se entiende solo y avanza sin relleno.
- valor 0-25: da risa, sorprende, ensena algo o emociona; el remate paga.
- tendencia 0-25: es compartible, identificable o polemico; el tipo de cosa que la gente etiqueta a un amigo.

Escribe titulo, texto_hook, razon, caption_post y hashtags en el idioma del video. palabras_clave: 0 a 3 palabras tal cual aparecen en el clip, las que el que habla remarca (para pintarlas en rojo)."""


def _json_de_texto(texto: str) -> dict:
    """Saca el JSON aunque venga con ```json ... ``` o texto alrededor."""
    t = (texto or "").strip()
    if t.startswith("```"):
        t = t.strip("`")
        t = t[t.find("{"):] if "{" in t else t
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i:
        raise ValueError("no hay JSON en la respuesta")
    return json.loads(t[i:j + 1])


def _pedir_clips(cliente, anthropic, modelo: str, msg: str, log) -> tuple[list, object]:
    """1) salida estructurada (JSON con esquema); 2) si no se puede, herramienta sin forzar o JSON en texto."""
    mensajes = [{"role": "user", "content": msg}]
    formato = {"format": {"type": "json_schema", "schema": ESQUEMA_CLIPS}}
    try:
        try:
            resp = cliente.messages.create(model=modelo, max_tokens=16000, system=SISTEMA_IA,
                                           messages=mensajes, output_config=formato)
        except TypeError:  # libreria anthropic vieja: se manda igual por extra_body
            resp = cliente.messages.create(model=modelo, max_tokens=16000, system=SISTEMA_IA,
                                           messages=mensajes, extra_body={"output_config": formato})
        texto = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")
        return _json_de_texto(texto).get("clips", []), resp
    except (anthropic.AuthenticationError, anthropic.NotFoundError, anthropic.PermissionDeniedError):
        raise
    except anthropic.BadRequestError as e:
        log(f"   (no acepto la salida estructurada: {str(e)[:120]}; pruebo otra forma)")
    except (ValueError, json.JSONDecodeError):
        log("   (la respuesta no vino completa; pruebo otra forma)")
    resp = cliente.messages.create(
        model=modelo, max_tokens=16000,
        system=SISTEMA_IA + "\n\nEntrega el resultado SIEMPRE llamando a la herramienta entregar_clips.",
        tools=[HERRAMIENTA_CLIPS], tool_choice={"type": "auto"}, messages=mensajes)
    bloque = next((b for b in resp.content if getattr(b, "type", "") == "tool_use"), None)
    if bloque is not None:
        return list(bloque.input.get("clips", [])), resp
    texto = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")
    return _json_de_texto(texto).get("clips", []), resp


def elegir_con_claude(datos: dict, cfg: dict, instruccion: str = "", log=_log_defecto) -> list:
    cargar_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("No hay ANTHROPIC_API_KEY (ponla en la app > Configuracion).")
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("Falta la libreria anthropic: pip install anthropic")
    cliente = anthropic.Anthropic(max_retries=4, timeout=600)
    texto = texto_para_ia(datos)
    n, dmin, dmax = int(cfg["clips"]), float(cfg["duracion_min"]), float(cfg["duracion_max"])
    # videos muy largos: por partes de ~2 h
    partes, tam = [], 350_000
    if len(texto) <= tam:
        partes = [texto]
    else:
        lineas, actual = texto.splitlines(), []
        for ln in lineas:
            actual.append(ln)
            if sum(len(x) + 1 for x in actual) > tam:
                partes.append("\n".join(actual))
                actual = actual[-40:]  # un poco de solape
        if actual:
            partes.append("\n".join(actual))
    elegidos = []
    for k, parte in enumerate(partes):
        pedir = n if len(partes) == 1 else max(2, math.ceil(n / len(partes)) + 1)
        extra = f"\nInstruccion del usuario (respetala, solo clips que encajen): {instruccion.strip()}\n" if instruccion and instruccion.strip() else ""
        msg = (f"Duracion total del video: {datos['duracion']:.0f} s.\n"
               f"Quiero hasta {pedir} clips de entre {dmin:.0f} y {dmax:.0f} segundos.{extra}\n"
               f"Transcripcion ([inicio-fin] texto){' - parte %d de %d' % (k + 1, len(partes)) if len(partes) > 1 else ''}:\n\n{parte}")
        log(f"3/5 Claude ({cfg['modelo_ia']}) esta eligiendo los mejores momentos"
            f"{' (parte %d/%d)' % (k + 1, len(partes)) if len(partes) > 1 else ''}...")
        try:
            clips, resp = _pedir_clips(cliente, anthropic, cfg["modelo_ia"], msg, log)
        except anthropic.AuthenticationError:
            raise RuntimeError("Tu API key de Claude no es valida. Revisala en la app > Configuracion")
        except anthropic.NotFoundError:
            raise RuntimeError(f"El modelo '{cfg['modelo_ia']}' no existe. Elige otro en la app > Configuracion")
        except anthropic.APIError as e:  # saldo, limites, red...: seguimos sin IA en vez de parar
            raise RuntimeError(f"Claude dio un error: {str(e)[:200]}")
        except (ValueError, json.JSONDecodeError):
            raise RuntimeError("Claude no devolvio clips legibles. Intenta de nuevo.")
        for c in clips:  # notas dentro de 0-25 aunque el modelo se pase
            for kk in ("hook", "flujo", "valor", "tendencia"):
                try:
                    c[kk] = max(0, min(25, int(c.get(kk, 0))))
                except (TypeError, ValueError):
                    c[kk] = 0
        elegidos.extend(clips)
        u = getattr(resp, "usage", None)
        if u:
            log(f"   tokens: {u.input_tokens} entrada / {u.output_tokens} salida")
    if not elegidos:
        raise RuntimeError("Claude no encontro clips que cumplan lo pedido.")
    return elegidos


def elegir_sin_ia(datos: dict, cfg: dict, log=_log_defecto) -> list:
    """Plan B sin API: ventanas de frases puntuadas por risas, preguntas y ritmo."""
    log("3/5 Eligiendo momentos sin IA (por risas, ritmo y preguntas)...")
    frs = frases(datos["palabras"])
    reac = datos.get("reacciones", [])
    dmin, dmax = float(cfg["duracion_min"]), float(cfg["duracion_max"])
    objetivo = (dmin + dmax) / 2
    cands = []
    for a in range(len(frs)):
        mejor = None
        for b in range(a, len(frs)):
            dur = frs[b]["f"] - frs[a]["i"]
            if dur > dmax:
                break
            if dur < dmin:
                continue
            ini, fin = frs[a]["i"], frs[b]["f"]
            risas = sum(min(3.0, r[1] - r[0]) for r in reac if ini <= r[0] <= fin + 1.0)
            remate = any(fin - 0.3 <= r[0] <= fin + 1.3 for r in reac)  # termina justo en las risas
            n_pal = frs[b]["w1"] - frs[a]["w0"] + 1
            ritmo = n_pal / max(1.0, dur)
            primera = frs[a]["texto"]
            hook = 6 + (6 if "?" in primera else 0) + (4 if "!" in primera else 0) + (3 if len(primera.split()) <= 12 else 0)
            valor = min(25, 8 + 4 * risas + (5 if remate else 0))
            flujo = int(min(25, 10 + 4 * ritmo - abs(dur - objetivo) / 6 + (4 if remate else -3)))
            tend = min(25, 8 + 2 * risas)
            c = {"inicio": ini, "fin": fin, "hook": int(min(25, hook)), "flujo": max(0, flujo),
                 "valor": int(valor), "tendencia": int(tend), "titulo": " ".join(primera.split()[:8]),
                 "texto_hook": " ".join(primera.split()[:7]), "razon": "Elegido por ritmo y reaccion del publico.",
                 "caption_post": primera, "hashtags": [], "palabras_clave": []}
            if mejor is None or _puntaje(c) > _puntaje(mejor):
                mejor = c
        if mejor:
            cands.append(mejor)
    return cands


def _puntaje(c: dict) -> int:
    return int(min(99, sum(int(c.get(k, 0) or 0) for k in ("hook", "flujo", "valor", "tendencia"))))


def ajustar_clips(crudos: list, datos: dict, wav: Path, cfg: dict, log=_log_defecto) -> list:
    """Encaja inicio/fin en frases reales, respeta duraciones, incluye risas y afina el corte en el audio."""
    pals, frs, reac = datos["palabras"], frases(datos["palabras"]), datos.get("reacciones", [])
    if not pals or not frs:
        return []
    x, sr = leer_wav(wav)
    db = _envolvente_db(x, sr, 0.005)
    piso = float(np.percentile(db, 10))
    dmin, dmax = float(cfg["duracion_min"]), float(cfg["duracion_max"])
    total = datos["duracion"]
    inicios = np.array([f["i"] for f in frs])
    finales = np.array([f["f"] for f in frs])

    def callado(t0: float, t1: float) -> bool:
        a, b = int(t0 / 0.005), int(t1 / 0.005)
        return b > a and bool(np.all(db[a:b] < piso + 6))

    listos = []
    for c in crudos:
        try:
            ini, fin = float(c["inicio"]), float(c["fin"])
        except (KeyError, TypeError, ValueError):
            continue
        if fin <= ini:
            continue
        # inicio: la frase que empieza mas cerca (sin traerse mucho de antes)
        cand = [k for k in range(len(frs)) if ini - 1.5 <= inicios[k] <= ini + 4]
        a = min(cand, key=lambda k: abs(inicios[k] - ini)) if cand else None
        # fin: la frase que termina mas cerca, pero solo frases que EMPIEZAN antes del fin elegido
        # (si eligieron el final de las risas, no se mete la frase siguiente; si el fin cae a mitad
        # de frase, se completa la frase y no se pierde el remate)
        cand = [k for k in range(len(frs)) if abs(finales[k] - fin) <= 4 and inicios[k] < fin - 0.3]
        b = min(cand, key=lambda k: abs(finales[k] - fin)) if cand else None
        if b is not None and a is not None and finales[b] <= inicios[a]:
            b = None
        t_ini = frs[a]["i"] if a is not None else min(pals, key=lambda w: abs(w["i"] - ini))["i"]
        if b is not None:
            t_fin = frs[b]["f"]
        else:  # la ultima palabra que termina antes del fin elegido (nunca una que empieza despues)
            t_fin = max([w["f"] for w in pals if w["f"] <= fin + 0.3] or [fin])
        # si eligieron terminar dentro de unas risas (o justo despues), termina cuando acaban
        risa_elegida = next(((r0, r1) for r0, r1 in reac if r0 - 0.3 <= fin <= r1 + 1.5 and r1 > t_fin), None)
        # duraciones
        # solo se recorta lo que pasa del maximo; si el clip es corto se respeta (el remate manda)
        if t_fin - t_ini > dmax + 5:
            ok = [f["f"] for f in frs if t_ini + min(dmin, dmax * 0.5) <= f["f"] <= t_ini + dmax]
            t_fin = max(ok) if ok else t_ini + dmax
        # risas despues del remate
        con_risa = False
        fin_habla = t_fin
        if risa_elegida and risa_elegida[1] - t_fin < 20:
            # hasta donde eligieron (un segundo de aire como mucho), no toda la risa
            t_fin, con_risa = min(risa_elegida[1], max(fin, fin_habla) + 1.0), True
        elif cfg.get("incluir_risas", True):
            for r0, r1 in reac:
                if t_fin - 0.3 <= r0 <= t_fin + 1.3:
                    t_fin = min(r1, t_fin + 3.0)
                    con_risa = True
                    break
        if con_risa:  # nunca meterse en la frase siguiente
            sig_pal = min([w["i"] for w in pals if w["i"] >= fin_habla + 0.05] or [total])
            t_fin = max(fin_habla, min(t_fin, sig_pal - 0.1))
        # afinar en el audio: no cortar media palabra
        previo = max([w["f"] for w in pals if w["f"] <= t_ini + 0.01] or [0.0])
        t = t_ini
        while t > max(previo, t_ini - 0.15) and not callado(t - 0.03, t):
            t -= 0.005
        t_ini = max(0.0, t - 0.03)
        if not con_risa:
            siguiente = min([w["i"] for w in pals if w["i"] >= t_fin - 0.01] or [total])
            t = t_fin
            while t < min(siguiente, t_fin + 0.25) and not callado(t, t + 0.03):
                t += 0.005
            t_fin = min(total, t + 0.05, max(t_fin, siguiente - 0.02))
        t_fin = min(t_fin, total, t_ini + dmax + 5)
        if t_fin - t_ini < 3:
            continue
        nuevo = dict(c)
        nuevo.update({"inicio": round(t_ini, 3), "fin": round(t_fin, 3), "puntuacion": _puntaje(c)})
        listos.append(nuevo)
    # quitar solapes (gana el de mayor puntuacion)
    listos.sort(key=lambda c: c["puntuacion"], reverse=True)
    finales_ok = []
    for c in listos:
        choca = False
        for o in finales_ok:
            inter = min(c["fin"], o["fin"]) - max(c["inicio"], o["inicio"])
            if inter > 0.5 * min(c["fin"] - c["inicio"], o["fin"] - o["inicio"]):
                choca = True
                break
        if not choca:
            finales_ok.append(c)
    return finales_ok[: int(cfg["clips"])]


# --------------------------------------------------------------------------------------
# 4. Reencuadre: detectar caras y seguir a quien habla
# --------------------------------------------------------------------------------------

_DETECTOR = None


def _detector():
    global _DETECTOR
    if _DETECTOR is not None:
        return _DETECTOR
    import cv2
    if not YUNET.exists():
        try:
            import urllib.request
            YUNET.parent.mkdir(parents=True, exist_ok=True)
            urllib.request.urlretrieve(YUNET_URL, str(YUNET))
        except Exception:
            pass
    if YUNET.exists() and YUNET.stat().st_size > 100_000 and hasattr(cv2, "FaceDetectorYN"):
        try:
            _DETECTOR = ("yunet", cv2.FaceDetectorYN.create(str(YUNET), "", (320, 320), 0.6, 0.3, 50))
            return _DETECTOR
        except Exception:
            pass
    casc = cv2.CascadeClassifier(str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"))
    _DETECTOR = ("haar", casc)
    return _DETECTOR


def analizar_caras(video: str | Path, inicio: float, fin: float, info: dict, fps: float = 6.0) -> list:
    """Devuelve muestras [(t, [cara, ...])] con centro, tamano y movimiento de boca."""
    import cv2
    tipo, det = _detector()
    wd = 1280 if info["w"] >= info["h"] else 720  # caras chicas en planos abiertos (escenarios)
    wd = min(wd, info["w"]) // 2 * 2
    hd = int(round(info["h"] * wd / info["w"] / 2)) * 2
    esc = info["w"] / wd
    cmd = [FFMPEG, "-nostdin", "-v", "error", "-ss", f"{inicio:.3f}", "-t", f"{fin - inicio:.3f}", "-i", str(video),
           "-vf", f"fps={fps},scale={wd}:{hd}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    proc = subprocess.Popen([str(c) for c in cmd], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            stdin=subprocess.DEVNULL, **_SIN_VENTANA)
    tam = wd * hd * 3
    muestras, k = [], 0
    if tipo == "yunet":
        det.setInputSize((wd, hd))
    try:
        while True:
            buf = proc.stdout.read(tam)
            if len(buf) < tam:
                break
            img = np.frombuffer(buf, np.uint8).reshape(hd, wd, 3)
            gris = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            caras = []
            if tipo == "yunet":
                _, res = det.detect(img)
                filas = [] if res is None else res
                for f in filas:
                    x, y, w, h = [float(v) for v in f[:4]]
                    if f[14] < 0.55 or w < wd * 0.011:
                        continue
                    rmx, rmy, lmx, lmy = [float(v) for v in f[10:14]]
                    mx0, mx1 = min(rmx, lmx), max(rmx, lmx)
                    mw = max(mx1 - mx0, w * 0.3)
                    cxm, cym = (mx0 + mx1) / 2, (rmy + lmy) / 2
                    caja = (cxm - 0.75 * mw, cym - 0.45 * mw, cxm + 0.75 * mw, cym + 0.65 * mw)
                    caras.append(_cara(x, y, w, h, caja, gris, esc))
            else:
                for (x, y, w, h) in det.detectMultiScale(gris, 1.15, 5, minSize=(int(wd * 0.04),) * 2):
                    caja = (x + 0.2 * w, y + 0.62 * h, x + 0.8 * w, y + 0.95 * h)
                    caras.append(_cara(float(x), float(y), float(w), float(h), caja, gris, esc))
            muestras.append((k / fps, caras))
            k += 1
    finally:
        proc.stdout.close()
        proc.wait()
    return muestras


def _cara(x, y, w, h, caja, gris, esc) -> dict:
    import cv2
    H, W = gris.shape
    x0, y0, x1, y1 = [int(round(v)) for v in caja]
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
    parche = None
    if x1 - x0 >= 4 and y1 - y0 >= 4:
        p = cv2.resize(gris[y0:y1, x0:x1], (24, 16)).astype(np.float32)
        parche = (p - p.mean()) / (p.std() + 8.0)
    return {"cx": (x + w / 2) * esc, "cy": (y + h / 2) * esc, "w": w * esc, "h": h * esc, "parche": parche}


def plan_camara(muestras: list, info: dict, ow: int, oh: int, fps_out: float, dur: float) -> dict:
    """Decide modo (seguir/ajustar/escalar) y la posicion x de la camara para cada frame."""
    W, H = info["w"], info["h"]
    a_src, a_out = W / H, ow / oh
    if abs(a_src - a_out) < 0.04:
        return {"modo": "escalar"}
    if a_src < a_out:  # p.ej. video vertical a formato horizontal
        return {"modo": "ajustar"}
    cw = int(round(H * a_out / 2)) * 2
    ch = H
    con_cara = sum(1 for _, cs in muestras if cs)
    if not muestras or con_cara / len(muestras) < 0.3:
        return {"modo": "ajustar"}
    # grupo de caras chicas repartidas (escenario, panel): recortar a una persona se pierde al que
    # habla, mejor el plano completo. Con caras grandes (podcast) si se sigue a quien habla.
    repartidas = 0
    anchos = []
    for _, cs in muestras:
        anchos.extend(c["w"] for c in cs)
        if len(cs) >= 2:
            xs_c = [c["cx"] for c in cs]
            if max(xs_c) - min(xs_c) > 0.9 * cw:
                repartidas += 1
    if repartidas / len(muestras) > 0.5 and float(np.median(anchos)) < 0.045 * W:
        # recortar al area con gente (de la primera a la ultima persona, con margen) para que el
        # grupo salga mas grande; sin cortar a nadie
        xs_t = np.array([c["cx"] for _, cs in muestras for c in cs])
        mw = float(np.median(anchos))
        margen = max(0.05 * W, 2.5 * mw)
        x0 = max(0.0, float(np.percentile(xs_t, 2)) - margen)
        x1 = min(float(W), float(np.percentile(xs_t, 98)) + margen)
        ancho = max(x1 - x0, H * 0.8)  # nunca mas angosto que 4:5
        centro = (x0 + x1) / 2
        x0 = int(max(0, min(W - ancho, centro - ancho / 2))) // 2 * 2
        ancho = int(min(W - x0, ancho)) // 2 * 2
        plan = {"modo": "ajustar", "motivo": "grupo"}
        if ancho < W * 0.95:
            plan["recorte"] = [ancho, x0]
        return plan
    # --- seguimiento de caras entre muestras
    pistas: list[dict] = []
    obs = []  # por muestra: lista de (pista_id, cara)
    for t, caras in muestras:
        usadas, actual = set(), []
        for c in sorted(caras, key=lambda c: -c["w"]):
            mejor, dist = None, 0.12 * W
            for p in pistas:
                if p["id"] in usadas or t - p["t"] > 1.0:
                    continue
                d = abs(p["cx"] - c["cx"]) + 0.5 * abs(p["cy"] - c["cy"])
                if d < dist:
                    mejor, dist = p, d
            if mejor is None:
                mejor = {"id": len(pistas), "mov": []}
                pistas.append(mejor)
            movi = 0.0
            if c["parche"] is not None and mejor.get("parche") is not None and t - mejor["t"] < 0.5:
                movi = float(np.mean(np.abs(c["parche"] - mejor["parche"])))
            mejor.update({"t": t, "cx": c["cx"], "cy": c["cy"], "w": c["w"], "parche": c["parche"]})
            mejor["mov"].append((t, movi))
            usadas.add(mejor["id"])
            actual.append((mejor["id"], c))
        obs.append((t, actual))

    def habla(pid: int, t: float) -> float:
        vals = [m for (tt, m) in pistas[pid]["mov"] if abs(tt - t) <= 0.7]
        return float(np.mean(vals)) if vals else 0.0

    # --- quien es el protagonista en cada muestra (con histeresis)
    activo, ultimo_cambio = None, -99.0
    objetivo = []  # (t, x, pista)
    for t, actual in obs:
        if not actual:
            objetivo.append((t, None, activo))
            continue
        ids = {pid: c for pid, c in actual}
        if len(ids) == 1:
            nuevo = next(iter(ids))
        else:
            puntajes = {pid: habla(pid, t) + 0.02 * (c["w"] / W) for pid, c in ids.items()}
            mejor = max(puntajes, key=puntajes.get)
            if activo in ids:
                nuevo = activo
                if (mejor != activo and puntajes[mejor] > puntajes[activo] * 1.35 + 0.02
                        and t - ultimo_cambio >= 1.2):
                    nuevo = mejor
            else:
                nuevo = mejor
        if nuevo != activo:
            ultimo_cambio = t
            activo = nuevo
        xs_v = [c["cx"] for c in ids.values()]
        ancho_grupo = max(xs_v) - min(xs_v) + max(c["w"] for c in ids.values()) * 1.6
        if len(ids) >= 2 and ancho_grupo < cw * 0.95:
            # caben todos en el recorte: plano de grupo centrado, sin cortar a nadie
            objetivo.append((t, (max(xs_v) + min(xs_v)) / 2, -1))
        else:
            objetivo.append((t, ids[activo]["cx"], activo))
    # rellenar huecos sin cara con la ultima posicion conocida (o la siguiente)
    xs = [o[1] for o in objetivo]
    ult = next((x for x in xs if x is not None), W / 2)
    for i, x in enumerate(xs):
        if x is None:
            xs[i] = ult
        else:
            ult = x
    ts = np.array([o[0] for o in objetivo])
    xs = np.array(xs, float)
    ids = [o[2] for o in objetivo]
    # --- tomas: cambia la persona o hay salto grande (corte de camara) => corte seco
    limites = [0]
    for i in range(1, len(xs)):
        if (ids[i] != ids[i - 1] and abs(xs[i] - xs[i - 1]) > 0.08 * W) or abs(xs[i] - xs[i - 1]) > 0.18 * W:
            limites.append(i)
    limites.append(len(xs))
    suave = np.empty_like(xs)
    for a, b in zip(limites[:-1], limites[1:]):
        seg = xs[a:b]
        if seg.max() - seg.min() < 0.07 * W:  # casi quieto: camara fija, se ve profesional
            suave[a:b] = np.median(seg)
        else:
            sig = 0.6 * 6
            k = np.arange(-int(3 * sig), int(3 * sig) + 1)
            ker = np.exp(-(k ** 2) / (2 * sig ** 2))
            pad = np.pad(seg, (len(k) // 2, len(k) // 2), mode="edge")
            suave[a:b] = np.convolve(pad, ker / ker.sum(), mode="valid")[: b - a]
    # --- a frames de salida
    n_frames = max(1, int(math.ceil(dur * fps_out)))
    tf = np.arange(n_frames) / fps_out
    toma = np.searchsorted(ts, tf, side="right") - 1
    toma = np.clip(toma, 0, len(ts) - 1)
    x_frames = np.empty(n_frames)
    for a, b in zip(limites[:-1], limites[1:]):
        m = (toma >= a) & (toma < b)
        if m.any():
            x_frames[m] = np.interp(tf[m], ts[a:b], suave[a:b]) if b - a > 1 else suave[a]
    izq = np.clip(np.round(x_frames - cw / 2), 0, W - cw).astype(int)
    return {"modo": "seguir", "cw": cw, "ch": ch, "x": izq.tolist(), "fps": fps_out,
            "caras": round(con_cara / len(muestras), 2), "cambios": len(limites) - 2}


# --------------------------------------------------------------------------------------
# 5. Subtitulos animados (ASS) + render
# --------------------------------------------------------------------------------------

def _color_ass(hexrgb: str) -> str:
    h = hexrgb.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H00{b}{g}{r}".upper()


def _ts_ass(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _esc_ass(t: str) -> str:
    return t.replace("\\", "/").replace("{", "(").replace("}", ")")


def _sin_acentos(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")


_FUENTES_CACHE: dict | None = None


def _archivo_fuente(nombre: str) -> str | None:
    global _FUENTES_CACHE
    if _FUENTES_CACHE is None:
        _FUENTES_CACHE = {}
        try:
            from PIL import ImageFont
            for p in list(FUENTES.glob("*.ttf")) + list(FUENTES.glob("*.otf")):
                try:
                    f = ImageFont.truetype(str(p), 20)
                    fam, est = f.getname()
                    for k in {fam, f"{fam} {est}", p.stem, p.stem.replace("-", " ")}:
                        _FUENTES_CACHE[k.lower()] = str(p)
                except Exception:
                    pass
        except ImportError:
            pass
    return _FUENTES_CACHE.get(nombre.lower())


def _ancho_texto(texto: str, fuente: str, tam: float) -> float:
    ruta = _archivo_fuente(fuente)
    if ruta:
        try:
            from PIL import ImageFont
            return ImageFont.truetype(ruta, 100).getlength(texto) * tam / 100
        except Exception:
            pass
    return len(texto) * tam * 0.66


def _trozos(pals: list, max_pal: int, max_car: int, claves: set) -> list:
    """Agrupa palabras en bloques cortos; las palabras clave cierran su bloque."""
    out, actual = [], []
    for k, w in enumerate(pals):
        if actual:
            largo = len(" ".join(p["t"] for p in actual + [w]))
            pausa = w["i"] - actual[-1]["f"] > 0.6
            if len(actual) >= max_pal or largo > max_car or pausa:
                out.append(actual)
                actual = []
        actual.append(w)
        limpio = re.sub(r"[^\w]", "", w["t"]).lower()
        if re.search(r"[\.,;:\?!…]$", w["t"]) or limpio in claves:
            out.append(actual)
            actual = []
    if actual:
        out.append(actual)
    return out


def generar_ass(pals: list, cfg: dict, ow: int, oh: int, hook: str, claves: list, ruta: Path, dur: float) -> None:
    estilo = cfg.get("estilo", "opus")
    fuente, fuente_c = cfg["fuente"], cfg["fuente_contraste"]
    blanco, activo, rojo = (_color_ass(cfg["color_texto"]), _color_ass(cfg["color_activo"]),
                            _color_ass(cfg["color_clave"]))
    vertical = oh > ow
    base = 90 if vertical else (70 if ow == oh else 60)
    y_cap = int(oh * 0.60) if vertical else int(oh * (0.74 if ow == oh else 0.84))
    max_w = ow * (0.84 if vertical else 0.7)
    cab = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {ow}", f"PlayResY: {oh}", "WrapStyle: 2",
        "ScaledBorderAndShadow: yes", "YCbCr Matrix: TV.709", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        f"Style: Cap,{fuente},{base},{blanco},{blanco},&H00000000,&H96000000,0,0,0,0,100,100,0,0,1,{6 if vertical else 5},3,5,40,40,0,1",
        f"Style: Hook,{fuente_c},{int(base * 0.8)},&H00111111,&H00111111,&H00FFFFFF,&H00000000,0,0,0,0,100,100,0,0,3,{int(base * 0.22)},0,5,60,60,0,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    ev = []
    cx = ow // 2
    # --- hook arriba (zona segura: debajo de los 270 px superiores en 9:16)
    if hook and cfg.get("hook", True):
        h = hook.upper() if cfg.get("mayusculas", True) else hook
        if cfg.get("contraste_sin_acentos"):
            h = _sin_acentos(h)
        tam = int(base * 0.8)
        palabras_h = h.split()
        lineas = [" ".join(palabras_h)]
        if _ancho_texto(lineas[0], fuente_c, tam) > max_w * 0.92 and len(palabras_h) > 1:
            # dos (o tres) lineas parejas, no una larga y una palabra sola
            mejor = None
            for k in range(1, len(palabras_h)):
                a, b = " ".join(palabras_h[:k]), " ".join(palabras_h[k:])
                peor = max(_ancho_texto(a, fuente_c, tam), _ancho_texto(b, fuente_c, tam))
                if mejor is None or peor < mejor[0]:
                    mejor = (peor, [a, b])
            lineas = mejor[1]
            if mejor[0] > max_w * 0.92 and len(palabras_h) > 2:
                tercio = []
                for k1 in range(1, len(palabras_h) - 1):
                    for k2 in range(k1 + 1, len(palabras_h)):
                        ls = [" ".join(palabras_h[:k1]), " ".join(palabras_h[k1:k2]), " ".join(palabras_h[k2:])]
                        peor = max(_ancho_texto(x, fuente_c, tam) for x in ls)
                        if not tercio or peor < tercio[0]:
                            tercio = [peor, ls]
                lineas = tercio[1]
        lineas = lineas[:3]
        ancho = max(_ancho_texto(l, fuente_c, tam) for l in lineas)
        if ancho > max_w * 0.92:
            tam = int(tam * max_w * 0.92 / ancho)
        y_h = int(oh * 0.22) if vertical else int(oh * 0.15)
        t_hook = min(float(cfg.get("hook_segundos", 3.0)), max(1.0, dur - 0.5))
        ev.append(f"Dialogue: 2,{_ts_ass(0.05)},{_ts_ass(t_hook)},Hook,,0,0,0,,"
                  f"{{\\an5\\pos({cx},{y_h})\\fs{tam}\\fad(120,220)\\t(0,180,\\fscx104\\fscy104)\\t(180,320,\\fscx100\\fscy100)}}"
                  + "\\N".join(_esc_ass(l) for l in lineas))
    if estilo == "ninguno" or not pals:
        ruta.write_text("\n".join(cab + ev) + "\n", encoding="utf-8")
        return
    claves_set = {re.sub(r"[^\w]", "", c).lower() for c in (claves or []) if c.strip()}
    max_pal, max_car = (3, 16) if estilo == "yulian" else ((4, 22) if estilo == "simple" else (3, 18))
    bloques = _trozos(pals, max_pal, max_car, claves_set)
    mayus = cfg.get("mayusculas", True) and estilo != "simple"

    def txt(w):
        t = w["t"]
        return t.upper() if mayus else t

    for bi, bl in enumerate(bloques):
        b_ini = bl[0]["i"]
        sig = bloques[bi + 1][0]["i"] if bi + 1 < len(bloques) else dur
        b_fin = min(sig, bl[-1]["f"] + 0.45)
        if sig - bl[-1]["f"] < 0.5:
            b_fin = sig  # sin parpadeo entre bloques seguidos
        es_clave = [re.sub(r"[^\w]", "", w["t"]).lower() in claves_set for w in bl]
        # tamano para que quepa
        linea = " ".join(txt(w) for w, c in zip(bl, es_clave) if not (estilo == "yulian" and c))
        tam = base
        if linea and _ancho_texto(linea, fuente, base * 1.1) > max_w:
            tam = int(base * max_w / _ancho_texto(linea, fuente, base * 1.1))
        for k, w in enumerate(bl):
            t0 = b_ini if k == 0 else w["i"]
            t1 = bl[k + 1]["i"] if k + 1 < len(bl) else b_fin
            if estilo == "yulian" and any(es_clave) and es_clave[-1] and k == len(bl) - 1 and k > 0:
                # la palabra clave aparece sola en la linea 2 y dura al menos 0.7 s
                t1 = max(t1, min(sig, t0 + 0.7))
            if t1 - t0 < 0.02:
                continue
            partes = []
            visibles = bl[: k + 1] if estilo == "yulian" else bl
            l1, l2 = [], []
            for j, ww in enumerate(visibles):
                t = _esc_ass(txt(ww))
                if estilo == "yulian":
                    nuevo = j == k
                    fade = "\\alpha&HFF&\\t(0,90,\\alpha&H00&)" if nuevo else ""
                    if es_clave[j]:
                        tc = _sin_acentos(t) if cfg.get("contraste_sin_acentos") else t
                        tk = min(int(base * 1.38), int(max_w / max(1.0, _ancho_texto(tc, fuente_c, 100) / 100)))
                        l2.append(f"{{\\fn{fuente_c}\\fs{tk}\\c{rojo}{fade}}}{tc}{{\\r}}")
                    else:
                        color = activo if re.search(r"\d", ww["t"]) else blanco
                        l1.append(f"{{\\c{color}{fade}}}{t}{{\\c{blanco}}}")
                elif estilo == "opus":
                    if es_clave[j]:
                        color = rojo
                    elif j == k:
                        color = activo
                    else:
                        color = blanco
                    pop = "\\fscx112\\fscy112\\t(0,90,\\fscx106\\fscy106)" if j == k else ""
                    l1.append(f"{{\\c{color}{pop}}}{t}{{\\c{blanco}\\fscx100\\fscy100}}")
                else:  # simple
                    l1.append(t)
            texto = " ".join(l1)
            if l2:
                texto = (texto + "\\N" if texto else "") + " ".join(l2)
            partes.append(f"{{\\an5\\pos({cx},{y_cap})\\fs{tam}}}" + texto)
            ev.append(f"Dialogue: 1,{_ts_ass(t0)},{_ts_ass(t1)},Cap,,0,0,0,," + "".join(partes))
    ruta.write_text("\n".join(cab + ev) + "\n", encoding="utf-8")


def tamano_salida(formato: str) -> tuple[int, int]:
    return {"9:16": (1080, 1920), "1:1": (1080, 1080), "16:9": (1920, 1080), "4:5": (1080, 1350)}.get(formato, (1080, 1920))


def renderizar_clip(video: str | Path, clip: dict, plan: dict, ass: Path, salida: Path, info: dict,
                    ow: int, oh: int, cfg: dict) -> None:
    tmp = ass.parent
    dur = clip["fin"] - clip["inicio"]
    fuentes_tmp = tmp / "fuentes"
    if not fuentes_tmp.exists():
        fuentes_tmp.mkdir(parents=True)
        for p in list(FUENTES.glob("*.ttf")) + list(FUENTES.glob("*.otf")):
            shutil.copy2(p, fuentes_tmp / p.name)
    subs = f"ass={ass.name}:fontsdir=fuentes"
    if plan["modo"] == "seguir":
        x = plan["x"]
        lineas, prev = [], None
        for i, xi in enumerate(x):
            if xi != prev:
                lineas.append(f"{i / plan['fps']:.4f} crop@cam x {xi};")
                prev = xi
        (tmp / "camara.txt").write_text("\n".join(lineas) + "\n", encoding="utf-8")
        y0 = max(0, (info["h"] - plan["ch"]) // 2)
        vf = (f"fps={plan['fps']},sendcmd=f=camara.txt,crop@cam={plan['cw']}:{plan['ch']}:{x[0]}:{y0},"
              f"scale={ow}:{oh}:flags=lanczos,setsar=1,{subs}")
        filtro = ["-vf", vf]
    elif plan["modo"] == "escalar":
        filtro = ["-vf", f"scale={ow}:{oh}:force_original_aspect_ratio=increase:flags=lanczos,"
                         f"crop={ow}:{oh},setsar=1,{subs}"]
    else:  # ajustar: video completo (o el area con gente) sobre fondo desenfocado
        rec = ""
        if plan.get("recorte"):
            rec = f"crop={plan['recorte'][0]}:{info['h']}:{plan['recorte'][1]}:0,"
        filtro = ["-filter_complex",
                  f"[0:v]{rec}split=2[a][b];[a]scale={ow // 4}:{oh // 4}:force_original_aspect_ratio=increase,"
                  f"crop={ow // 4}:{oh // 4},boxblur=12:3,eq=brightness=-0.10,scale={ow}:{oh}[fondo];"
                  f"[b]scale={ow}:{oh}:force_original_aspect_ratio=decrease:flags=lanczos[frente];"
                  f"[fondo][frente]overlay=(W-w)/2:(H-h)/2,setsar=1,{subs}[v]",
                  "-map", "[v]", "-map", "0:a?"]
    calidad = int(cfg.get("calidad", 20))
    if tiene_nvenc():
        enc = ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", str(calidad + 1), "-b:v", "0"]
    else:
        enc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(calidad)]
    af = f"afade=t=in:d=0.03,afade=t=out:st={max(0.0, dur - 0.08):.3f}:d=0.08"
    cmd = [FFMPEG, "-nostdin", "-y", "-ss", f"{clip['inicio']:.3f}", "-t", f"{dur:.3f}", "-i", str(Path(video).resolve()),
           *filtro, *enc, "-pix_fmt", "yuv420p", "-af", af, "-c:a", "aac", "-b:a", "192k",
           "-movflags", "+faststart", str(salida.resolve())]
    try:
        correr(cmd, cwd=tmp)
    except RuntimeError:
        if enc[1] == "h264_nvenc":  # por si NVENC falla a mitad: reintento con CPU
            enc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(calidad)]
            cmd = [FFMPEG, "-nostdin", "-y", "-ss", f"{clip['inicio']:.3f}", "-t", f"{dur:.3f}", "-i",
                   str(Path(video).resolve()), *filtro, *enc, "-pix_fmt", "yuv420p", "-af", af, "-c:a", "aac",
                   "-b:a", "192k", "-movflags", "+faststart", str(salida.resolve())]
            correr(cmd, cwd=tmp)
        else:
            raise


def renderizar_todos(video: str | Path, clips: list, datos: dict, trabajo: Path, cfg: dict, log=_log_defecto) -> list:
    info = info_video(video)
    ow, oh = tamano_salida(cfg.get("formato", "9:16"))
    fps_out = 30.0 if info["fps"] > 31 or info["fps"] < 20 else round(info["fps"], 3)
    pals = datos["palabras"]
    clips_dir = trabajo / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    hechos = []
    for n, c in enumerate(clips, 1):
        t0 = time.time()
        dur = c["fin"] - c["inicio"]
        log(f"5/5 Clip {n}/{len(clips)}: \"{c.get('titulo', '')}\" ({dur:.0f} s, puntuacion {c.get('puntuacion', '?')})")
        tmp = trabajo / "tmp" / f"clip{n:02d}"
        tmp.mkdir(parents=True, exist_ok=True)
        muestras = analizar_caras(video, c["inicio"], c["fin"], info)
        plan = plan_camara(muestras, info, ow, oh, fps_out, dur)
        if plan["modo"] == "seguir":
            log(f"   camara: siguiendo caras ({int(plan['caras'] * 100)}% del clip con cara, {plan['cambios']} cambios de toma)")
        else:
            motivo = " (grupo en plano abierto)" if plan.get("motivo") == "grupo" else ""
            if plan.get("recorte"):
                motivo += f", zoom al grupo x{info['w'] / plan['recorte'][0]:.2f}"
            log(f"   camara: {'video completo con fondo desenfocado' + motivo if plan['modo'] == 'ajustar' else 'escalado'}")
        rel = [{"t": w["t"], "i": round(w["i"] - c["inicio"], 3), "f": round(w["f"] - c["inicio"], 3)}
               for w in pals if w["i"] >= c["inicio"] - 0.05 and w["i"] < c["fin"] - 0.08]
        ass = tmp / "subs.ass"
        generar_ass(rel, cfg, ow, oh, c.get("texto_hook") or c.get("titulo", ""), c.get("palabras_clave", []), ass, dur)
        nombre = f"{n:02d}_{c.get('puntuacion', 0)}pts_{slug(c.get('titulo', 'clip'), 40)}.mp4"
        salida = clips_dir / nombre
        renderizar_clip(video, c, plan, ass, salida, info, ow, oh, cfg)
        c = dict(c)
        c.update({"archivo": f"clips/{nombre}", "duracion": round(dur, 1), "camara": plan["modo"],
                  "texto": " ".join(w["t"] for w in rel)})
        hechos.append(c)
        log(f"   listo en {time.time() - t0:.0f} s -> {nombre}")
    shutil.rmtree(trabajo / "tmp", ignore_errors=True)
    return hechos


# --------------------------------------------------------------------------------------
# Galeria
# --------------------------------------------------------------------------------------

def galeria_html(trabajo: Path, clips: list, titulo: str) -> Path:
    def color(p):
        return "#2ECC71" if p >= 80 else ("#FFD60A" if p >= 65 else "#FF8A3D")

    tarjetas = []
    for c in clips:
        p = int(c.get("puntuacion", 0))
        barras = "".join(
            f'<div class="b"><span>{k}</span><i style="width:{int(c.get(k, 0)) * 4}%"></i><em>{int(c.get(k, 0))}</em></div>'
            for k in ("hook", "flujo", "valor", "tendencia"))
        tags = " ".join("#" + h.lstrip("#") for h in c.get("hashtags", []))
        post = html.escape(f"{c.get('caption_post', '')} {tags}".strip())
        tarjetas.append(f"""
<article>
  <video src="{html.escape(c['archivo'])}" controls preload="metadata" playsinline></video>
  <div class="info">
    <div class="top"><span class="score" style="--c:{color(p)}">{p}</span>
      <div><h2>{html.escape(c.get('titulo', ''))}</h2>
      <p class="meta">{fmt_t(c['inicio'])} &rarr; {fmt_t(c['fin'])} &middot; {c.get('duracion', 0):.0f} s</p></div></div>
    {barras}
    <p class="razon">{html.escape(c.get('razon', ''))}</p>
    <div class="post"><p>{post}</p><button onclick="copiar(this)">Copiar texto</button></div>
    <a class="dl" href="{html.escape(c['archivo'])}" download>Descargar</a>
  </div>
</article>""")
    pagina = f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Clips · {html.escape(titulo)}</title>
<style>
:root{{--bg:#0b0b0c;--card:#151517;--line:#26262a;--tx:#f2f2f2;--mut:#9a9aa2;--red:#E10600;--yel:#FFD60A}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--tx);font:15px/1.45 system-ui,Segoe UI,Roboto,sans-serif}}
header{{padding:28px 20px 8px;max-width:1300px;margin:auto}}h1{{margin:0;font-size:26px;letter-spacing:-.02em}}
header p{{color:var(--mut);margin:6px 0 0}}main{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:18px;padding:20px;max-width:1300px;margin:auto}}
article{{background:var(--card);border:1px solid var(--line);border-radius:16px;overflow:hidden;display:flex;flex-direction:column}}
video{{width:100%;aspect-ratio:9/16;max-height:560px;background:#000;object-fit:contain}}
.info{{padding:14px 16px 16px;display:flex;flex-direction:column;gap:8px}}.top{{display:flex;gap:12px;align-items:center}}
.score{{flex:none;width:52px;height:52px;border-radius:50%;display:grid;place-items:center;font-weight:800;font-size:20px;border:3px solid var(--c);color:var(--c)}}
h2{{font-size:16px;margin:0;line-height:1.25}}.meta{{margin:2px 0 0;color:var(--mut);font-size:13px}}
.b{{display:grid;grid-template-columns:72px 1fr 24px;align-items:center;gap:8px;font-size:12px;color:var(--mut)}}
.b i{{display:block;height:6px;border-radius:3px;background:linear-gradient(90deg,var(--red),var(--yel))}}.b em{{font-style:normal;text-align:right}}
.razon{{margin:2px 0 0;color:#cfcfd4}}.post{{background:#0f0f11;border:1px solid var(--line);border-radius:10px;padding:10px}}
.post p{{margin:0 0 8px;font-size:13px;white-space:pre-wrap}}button,.dl{{font:inherit;font-size:13px;border-radius:8px;padding:7px 12px;cursor:pointer}}
button{{background:#222226;color:var(--tx);border:1px solid var(--line)}}.dl{{text-align:center;background:var(--red);color:#fff;text-decoration:none;font-weight:600}}
</style></head><body>
<header><h1>{html.escape(titulo)}</h1><p>{len(clips)} clips · ordenados por puntuacion · hecho con MiOpusClip</p></header>
<main>{''.join(tarjetas)}</main>
<script>function copiar(b){{navigator.clipboard.writeText(b.previousElementSibling.innerText).then(()=>{{b.textContent='Copiado';setTimeout(()=>b.textContent='Copiar texto',1500)}})}}</script>
</body></html>"""
    ruta = trabajo / "galeria.html"
    ruta.write_text(pagina, encoding="utf-8")
    return ruta


# --------------------------------------------------------------------------------------
# Pipeline completo
# --------------------------------------------------------------------------------------

def nueva_carpeta(nombre: str, base: Path | None = None) -> Path:
    base = base or RESULTADOS
    d = base / f"{_dt.datetime.now():%Y-%m-%d_%H%M}_{slug(nombre, 40)}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def procesar(fuente: str, cfg: dict, instruccion: str = "", salida: Path | None = None,
             log=_log_defecto, clips_manual: list | None = None,
             nombre_json: str = "clips.json") -> tuple[Path, list]:
    t0 = time.time()
    fuente = str(fuente).strip().strip('"')
    if es_url(fuente):
        trabajo = salida or nueva_carpeta("descarga")
        log("1/5 Descargando el video...")
        video, titulo = descargar(fuente, trabajo / "fuente", log)
        if salida is None:
            nuevo = nueva_carpeta(titulo)
            shutil.move(str(trabajo / "fuente"), str(nuevo / "fuente"))
            shutil.rmtree(trabajo, ignore_errors=True)
            trabajo = nuevo
            video = next((trabajo / "fuente").glob("original.*"))
    else:
        video = Path(fuente)
        if not video.exists():
            raise RuntimeError(f"No encuentro el archivo: {fuente}")
        titulo = video.stem
        trabajo = salida or nueva_carpeta(titulo)
        log(f"1/5 Video: {video.name}")
    trabajo.mkdir(parents=True, exist_ok=True)
    info = info_video(video)
    if not info["audio"]:
        raise RuntimeError("El video no tiene audio; MiOpusClip elige los clips por lo que se dice.")
    log(f"   {info['w']}x{info['h']}, {info['fps']:.0f} fps, {fmt_t(info['dur'])}")
    datos = transcribir(video, trabajo, cfg, log)
    if not datos["palabras"]:
        raise RuntimeError("No se detecto voz en el video.")
    log(f"   {len(datos['reacciones'])} momentos de risas/aplausos detectados")
    if clips_manual is not None:
        crudos = clips_manual
        log("3/5 Usando los clips elegidos a mano (clips.json)")
    elif cfg.get("ia", "claude") == "claude":
        try:
            crudos = elegir_con_claude(datos, cfg, instruccion, log)
        except RuntimeError as e:
            log(f"   [aviso] {e}\n   Sigo sin IA.")
            crudos = elegir_sin_ia(datos, cfg, log)
    else:
        crudos = elegir_sin_ia(datos, cfg, log)
    log("4/5 Ajustando cortes al audio (sin medias palabras)...")
    clips = ajustar_clips(crudos, datos, trabajo / "audio16k.wav", cfg, log)
    if not clips:
        raise RuntimeError("No salio ningun clip valido. Prueba con otra duracion minima/maxima.")
    log(f"   {len(clips)} clips: " + ", ".join(f"{c['puntuacion']}" for c in clips))
    hechos = renderizar_todos(video, clips, datos, trabajo, cfg, log)
    (trabajo / nombre_json).write_text(json.dumps(hechos, ensure_ascii=False, indent=2), encoding="utf-8")
    galeria_html(trabajo, hechos, titulo)
    log(f"Listo: {len(hechos)} clips en {time.time() - t0:.0f} s\n   {trabajo}")
    return trabajo, hechos


def abrir(ruta: Path) -> None:
    try:
        if os.name == "nt":
            os.startfile(str(ruta))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(ruta)])
        else:
            subprocess.Popen(["xdg-open", str(ruta)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


# --------------------------------------------------------------------------------------
# Diagnostico y preparacion
# --------------------------------------------------------------------------------------

def diagnostico(probar_gpu: bool = False) -> int:
    cargar_env()
    ok = True

    def linea(nombre, bien, detalle=""):
        nonlocal ok
        ok = ok and bien
        print(f"  [{'OK' if bien else '!!'}] {nombre}{(': ' + detalle) if detalle else ''}")

    print(f"MiOpusClip {VERSION} - diagnostico")
    try:
        v = correr([FFMPEG, "-hide_banner", "-version"]).splitlines()[0]
        linea("FFmpeg", True, v[:60])
    except Exception as e:
        linea("FFmpeg", False, "no encontrado. Instala con: winget install Gyan.FFmpeg")
    linea("Exportar con la GPU (NVENC)", True, "si" if tiene_nvenc() else "no (uso CPU, funciona igual)")
    try:
        import faster_whisper
        linea("faster-whisper", True, faster_whisper.__version__)
        _preparar_cuda_windows()
        linea("CUDA para transcribir", True, "GPU disponible" if _hay_cuda() else "no hay GPU: transcribe en CPU")
    except ImportError:
        try:
            import sherpa_onnx  # noqa: F401
            linea("Transcripcion", PARAKEET_DIR.exists(), "Parakeet (sherpa-onnx)")
        except ImportError:
            linea("Transcripcion", False, "falta faster-whisper")
    try:
        import cv2
        tipo, _ = _detector()
        linea("Detector de caras", True, f"{tipo} (OpenCV {cv2.__version__})")
    except Exception as e:
        linea("Detector de caras", False, str(e)[:80])
    try:
        import yt_dlp
        linea("yt-dlp (links)", True, yt_dlp.version.__version__)
    except Exception:
        linea("yt-dlp (links)", False, "pip install \"yt-dlp[default]\"")
    tiene_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    print(f"  [{'OK' if tiene_key else '--'}] API key de Claude: "
          f"{'configurada' if tiene_key else 'no configurada (elige clips sin IA)'}")
    fuentes = [p.name for p in FUENTES.glob('*.[to]tf')]
    linea("Fuentes", bool(fuentes), ", ".join(fuentes))
    if probar_gpu:
        print("  Descargando/probando el modelo Whisper (puede tardar unos minutos la primera vez)...")
        try:
            tmp = CACHE / "prueba"
            tmp.mkdir(parents=True, exist_ok=True)
            wav = tmp / "silencio.wav"
            correr([FFMPEG, "-nostdin", "-y", "-f", "lavfi", "-i", "sine=f=220:d=2", "-ac", "1", "-ar", "16000", str(wav)])
            cfg = cargar_config()
            r = _transcribir_whisper(wav, cfg["modelo_whisper"], "es", lambda m: print("  " + m), vad=False)
            if _hay_cuda() and r["backend"].endswith(":cpu"):
                linea("Whisper en la GPU", False, "la GPU fallo y quedo en CPU. Mira 'Problemas' en LEEME.txt")
            else:
                linea("Whisper", True, "GPU (rapido)" if r["backend"].endswith(":cuda") else "CPU")
        except Exception as e:
            linea("Whisper", False, str(e).splitlines()[0][:150])
    return 0 if ok else 1


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------

def _args_comunes(p: argparse.ArgumentParser) -> None:
    p.add_argument("--clips", type=int, help="cuantos clips (maximo)")
    p.add_argument("--min", dest="duracion_min", type=float, help="duracion minima en segundos")
    p.add_argument("--max", dest="duracion_max", type=float, help="duracion maxima en segundos")
    p.add_argument("--formato", choices=["9:16", "1:1", "16:9", "4:5"])
    p.add_argument("--estilo", choices=["opus", "yulian", "simple", "ninguno"], help="subtitulos")
    p.add_argument("--sin-hook", action="store_true", help="no poner titulo arriba")
    p.add_argument("--idioma", help="es, en... (por defecto detecta)")
    p.add_argument("--backend", choices=["auto", "whisper", "parakeet"])
    p.add_argument("--modelo-whisper", dest="modelo_whisper")
    p.add_argument("--salida", type=Path, help="carpeta de salida")
    p.add_argument("--no-abrir", action="store_true")


def main(argv=None) -> int:
    cargar_env()
    ap = argparse.ArgumentParser(prog="miopusclip", description="Tu propio OpusClip.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("todo", help="video o link -> clips listos")
    p.add_argument("fuente")
    p.add_argument("--instruccion", default="", help='que buscar, p.ej. "solo los chistes de la familia"')
    p.add_argument("--ia", choices=["claude", "ninguna"])
    p.add_argument("--modelo-ia", dest="modelo_ia")
    _args_comunes(p)
    p = sub.add_parser("transcribir", help="solo transcribe (para elegir clips a mano o con Claude)")
    p.add_argument("fuente")
    _args_comunes(p)
    p = sub.add_parser("render", help="renderiza clips de un clips.json")
    p.add_argument("fuente")
    p.add_argument("--clips-json", "--json", dest="clips_json", type=Path, required=True)
    _args_comunes(p)
    p = sub.add_parser("diagnostico", help="revisa que todo este instalado")
    p.add_argument("--probar-gpu", action="store_true", help="descarga y prueba Whisper")
    a = ap.parse_args(argv)

    if a.cmd == "diagnostico":
        return diagnostico(a.probar_gpu)
    extra = {k: getattr(a, k, None) for k in ("clips", "duracion_min", "duracion_max", "formato", "estilo",
                                               "idioma", "backend", "modelo_whisper", "ia", "modelo_ia")}
    if getattr(a, "sin_hook", False):
        extra["hook"] = False
    cfg = cargar_config(extra)
    try:
        if a.cmd == "todo":
            trabajo, _ = procesar(a.fuente, cfg, a.instruccion, a.salida)
            if not a.no_abrir:
                abrir(trabajo / "galeria.html")
        elif a.cmd == "transcribir":
            video = Path(a.fuente)
            trabajo = a.salida or nueva_carpeta(video.stem)
            datos = transcribir(video, trabajo, cfg)
            print(f"Transcripcion lista: {len(datos['palabras'])} palabras, {len(datos['reacciones'])} risas/aplausos")
            print(f"   {trabajo / 'transcripcion_llm.txt'}")
        elif a.cmd == "render":
            manual = json.loads(a.clips_json.read_text(encoding="utf-8"))
            if isinstance(manual, dict):
                manual = manual.get("clips", [])
            if a.clips is None:
                cfg["clips"] = max(len(manual), 1)
            destino = a.salida or a.clips_json.parent
            nombre = "clips.json"
            if (Path(destino) / nombre).resolve() == a.clips_json.resolve():
                nombre = "clips_resultado.json"  # nunca pisar la seleccion de entrada
            trabajo, _ = procesar(a.fuente, cfg, "", destino, clips_manual=manual, nombre_json=nombre)
            if not a.no_abrir:
                abrir(trabajo / "galeria.html")
    except KeyboardInterrupt:
        print("\nCancelado.")
        return 130
    except RuntimeError as e:
        print(f"\n[ERROR] {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
