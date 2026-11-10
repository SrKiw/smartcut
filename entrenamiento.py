# -*- coding: utf-8 -*-
"""SmartCut - lo que corriges a mano se junta para entrenar Whisper con el habla dominicana.

    python entrenamiento.py                     cuanto llevas revisado
    python entrenamiento.py exportar <carpeta>  audio y texto listos para entrenar

Solo cuenta lo que revisó una persona: las frases donde corregiste una palabra y los clips que
marcaste como revisados. Lo que cambia Claude no entra, porque el modelo aprendería sus errores.
"""
from __future__ import annotations

import csv
import json
import sys
import threading
import wave
from pathlib import Path

import miopusclip as m

ARCHIVO = m.AQUI / "entrenamiento" / "frases.json"
MINUTOS_PRIMER_ENTRENAMIENTO = 180  # 3 horas: antes de eso es dificil que se note la mejora
_CANDADO = threading.Lock()


def _leer() -> dict:
    try:
        return json.loads(ARCHIVO.read_text(encoding="utf-8"))
    except Exception:
        return {}


def registrar(d: Path, palabras: list, cambiadas: set | None = None, origen: str = "correccion") -> int:
    """Guarda las frases con alguna palabra en `cambiadas`; sin `cambiadas`, todas (clip revisado)."""
    pals = sorted((w for w in palabras if (w.get("t") or "").strip()), key=lambda w: float(w["i"]))
    nuevas = 0
    with _CANDADO:
        datos = _leer()
        for fr in m.frases(pals):
            grupo = pals[fr["w0"]:fr["w1"] + 1]
            if cambiadas is not None and not any(round(float(w["i"]), 3) in cambiadas for w in grupo):
                continue
            if fr["f"] - fr["i"] < 0.5:  # muy corta: casi no le ensena nada al modelo
                continue
            clave = f"{Path(d).name}|{fr['i']:.3f}"
            nuevas += clave not in datos
            datos[clave] = {"carpeta": Path(d).name, "i": fr["i"], "f": fr["f"], "texto": fr["texto"], "origen": origen}
        ARCHIVO.parent.mkdir(exist_ok=True)
        tmp = ARCHIVO.with_suffix(".tmp")
        tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(ARCHIVO)
    return nuevas


def estado() -> dict:
    datos = _leer()
    seg = sum(float(x["f"]) - float(x["i"]) for x in datos.values())
    return {"frases": len(datos), "minutos": round(seg / 60, 1), "meta_minutos": MINUTOS_PRIMER_ENTRENAMIENTO,
            "videos": len({x["carpeta"] for x in datos.values()})}


def exportar(destino: Path) -> dict:
    """Un .wav de 16 kHz por frase y un metadata.csv: lo que necesita el entrenamiento."""
    destino = Path(destino)
    (destino / "audio").mkdir(parents=True, exist_ok=True)
    filas, faltan = [], 0
    for n, x in enumerate(sorted(_leer().values(), key=lambda v: (v["carpeta"], v["i"]))):
        wav = m.RESULTADOS / x["carpeta"] / "audio16k.wav"
        if not wav.exists():
            faltan += 1
            continue
        with wave.open(str(wav), "rb") as w:
            sr = w.getframerate()
            w.setpos(max(0, int((float(x["i"]) - 0.1) * sr)))
            trozo = w.readframes(int((float(x["f"]) - float(x["i"]) + 0.2) * sr))
            params = w.getparams()
        nombre = f"audio/{n:06d}.wav"
        with wave.open(str(destino / nombre), "wb") as s:
            s.setparams(params)
            s.writeframes(trozo)
        filas.append({"file_name": nombre, "transcription": x["texto"], "video": x["carpeta"]})
    with (destino / "metadata.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, ["file_name", "transcription", "video"])
        w.writeheader()
        w.writerows(filas)
    return {"frases": len(filas), "sin_audio": faltan, "carpeta": str(destino)}


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "exportar":
        print(exportar(Path(sys.argv[2])))
    else:
        e = estado()
        print(f"{e['frases']} frases revisadas · {e['minutos']} min de {e['meta_minutos']} · {e['videos']} videos")
