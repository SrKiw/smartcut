# -*- coding: utf-8 -*-
"""MiOpusClip - interfaz en el navegador. Se abre sola en http://127.0.0.1:7860"""
from __future__ import annotations

import os
import queue
import threading
from pathlib import Path

import gradio as gr

import miopusclip as m

m.cargar_env()
CFG = m.cargar_config()

CSS = """
.gradio-container {max-width: 1280px !important}
#titulo h1 {font-size: 30px; margin: 0; letter-spacing: -.02em}
#titulo p {margin: 4px 0 0; opacity: .7}
#log textarea {font-family: ui-monospace, Consolas, monospace; font-size: 13px}
footer {display: none !important}
"""


def guardar_key(key: str) -> str:
    key = (key or "").strip()
    if not key.startswith("sk-"):
        return "Esa no parece una API key de Claude (empieza con sk-ant-...)."
    env = m.AQUI / ".env"
    lineas = []
    if env.exists():
        lineas = [l for l in env.read_text(encoding="utf-8").splitlines() if not l.startswith("ANTHROPIC_API_KEY=")]
    lineas.append(f"ANTHROPIC_API_KEY={key}")
    env.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    os.environ["ANTHROPIC_API_KEY"] = key
    return "Guardada. Ya puedes usar la IA de Claude para elegir clips."


def estado_key() -> str:
    return ("API key de Claude: configurada" if os.environ.get("ANTHROPIC_API_KEY")
            else "API key de Claude: no configurada (elige clips sin IA)")


def procesar(link, archivo, n, dmin, dmax, estilo, formato, hook, instruccion, idioma, usar_ia, modelo_ia):
    fuente = archivo or (link or "").strip().strip('"')
    if not fuente:
        raise gr.Error("Pega un link de YouTube, la ruta de un video o sube un archivo.")
    if dmin >= dmax:
        raise gr.Error("La duracion minima tiene que ser menor que la maxima.")
    cfg = m.cargar_config({
        "clips": int(n), "duracion_min": float(dmin), "duracion_max": float(dmax), "estilo": estilo,
        "formato": formato, "hook": bool(hook), "idioma": None if idioma == "detectar" else idioma,
        "ia": "claude" if usar_ia else "ninguna", "modelo_ia": modelo_ia,
    })
    cola: queue.Queue = queue.Queue()
    resultado: dict = {}

    def trabajador():
        try:
            resultado["ok"] = m.procesar(fuente, cfg, instruccion or "", log=cola.put)
        except Exception as e:  # mostramos el error en la caja de progreso
            resultado["error"] = e
        finally:
            cola.put(None)

    threading.Thread(target=trabajador, daemon=True).start()
    lineas: list[str] = []
    while True:
        msg = cola.get()
        if msg is None:
            break
        lineas.append(str(msg))
        yield "\n".join(lineas[-300:]), gr.update(), gr.update(), None
    if "error" in resultado:
        lineas.append(f"\n[ERROR] {resultado['error']}")
        yield "\n".join(lineas), gr.update(), gr.update(), None
        return
    trabajo, clips = resultado["ok"]
    galeria = [(str(trabajo / c["archivo"]), f"{c['puntuacion']} pts · {c.get('titulo', '')}") for c in clips]
    tabla = [[c["puntuacion"], c.get("titulo", ""), f"{c['duracion']:.0f} s",
              f"{c.get('hook', 0)}/{c.get('flujo', 0)}/{c.get('valor', 0)}/{c.get('tendencia', 0)}",
              c.get("razon", ""),
              (c.get("caption_post", "") + " " + " ".join("#" + h.lstrip("#") for h in c.get("hashtags", []))).strip()]
             for c in clips]
    yield "\n".join(lineas), galeria, tabla, str(trabajo)


def abrir_carpeta(trabajo):
    if trabajo:
        m.abrir(Path(trabajo))


def abrir_galeria(trabajo):
    if trabajo:
        m.abrir(Path(trabajo) / "galeria.html")


with gr.Blocks(title="MiOpusClip") as demo:
    carpeta = gr.State(None)
    gr.Markdown("# MiOpusClip\nVideo largo adentro, clips verticales con subtitulos afuera.", elem_id="titulo")
    with gr.Row():
        with gr.Column(scale=5):
            link = gr.Textbox(label="Link de YouTube o ruta del video en tu PC",
                              placeholder='https://www.youtube.com/watch?v=...   o   C:\\Users\\yo\\Videos\\show.mp4')
            archivo = gr.File(label="...o sube el video", file_types=["video"], type="filepath")
            instruccion = gr.Textbox(label="Que buscas (opcional)",
                                     placeholder="Ej: solo los chistes sobre la familia / los momentos donde habla de dinero")
            boton = gr.Button("Crear clips", variant="primary", size="lg")
        with gr.Column(scale=4):
            with gr.Row():
                n = gr.Slider(1, 20, value=CFG["clips"], step=1, label="Cuantos clips")
                formato = gr.Radio(["9:16", "1:1", "4:5", "16:9"], value=CFG["formato"], label="Formato")
            with gr.Row():
                dmin = gr.Slider(5, 120, value=CFG["duracion_min"], step=1, label="Duracion minima (s)")
                dmax = gr.Slider(10, 180, value=CFG["duracion_max"], step=1, label="Duracion maxima (s)")
            with gr.Row():
                estilo = gr.Dropdown(["opus", "yulian", "simple", "ninguno"], value=CFG["estilo"], label="Subtitulos",
                                     info="opus: palabra activa en amarillo · yulian: palabra por palabra + claves en rojo")
                idioma = gr.Dropdown(["detectar", "es", "en", "pt", "fr", "it"],
                                     value=CFG["idioma"] or "detectar", label="Idioma")
            with gr.Row():
                hook = gr.Checkbox(value=CFG["hook"], label="Titulo (hook) arriba al inicio")
                usar_ia = gr.Checkbox(value=CFG["ia"] == "claude", label="Usar Claude para elegir")
            with gr.Accordion("Configuracion", open=False):
                modelo_ia = gr.Dropdown(["claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5"],
                                        value=CFG["modelo_ia"], label="Modelo de Claude", allow_custom_value=True,
                                        info="Sonnet: mejor relacion calidad/precio · Haiku: casi gratis · Opus: el mas fino")
                key = gr.Textbox(label="API key de Claude", type="password", placeholder="sk-ant-...")
                guardar = gr.Button("Guardar key")
                estado = gr.Markdown(estado_key())
    progreso = gr.Textbox(label="Progreso", lines=10, max_lines=18, elem_id="log", autoscroll=True)
    galeria = gr.Gallery(label="Clips (ordenados por puntuacion)", columns=4, height="auto", object_fit="contain")
    tabla = gr.Dataframe(headers=["Pts", "Titulo", "Dur.", "Hook/Flujo/Valor/Tend.", "Por que funciona", "Texto para publicar"],
                         label="Detalle", wrap=True, interactive=False)
    with gr.Row():
        b_galeria = gr.Button("Abrir galeria")
        b_carpeta = gr.Button("Abrir carpeta de clips")

    boton.click(procesar, [link, archivo, n, dmin, dmax, estilo, formato, hook, instruccion, idioma, usar_ia, modelo_ia],
                [progreso, galeria, tabla, carpeta])
    guardar.click(guardar_key, key, estado)
    b_carpeta.click(abrir_carpeta, carpeta, None)
    b_galeria.click(abrir_galeria, carpeta, None)

if __name__ == "__main__":
    m.RESULTADOS.mkdir(parents=True, exist_ok=True)
    demo.queue().launch(inbrowser=os.environ.get("MIOPUSCLIP_NO_NAVEGADOR") is None, server_name="127.0.0.1",
                        allowed_paths=[str(m.RESULTADOS), str(m.AQUI)], css=CSS,
                        theme=gr.themes.Soft(primary_hue="red", neutral_hue="zinc"))
