# -*- coding: utf-8 -*-
"""MiOpusClip - interfaz en el navegador. Se abre sola en http://127.0.0.1:7860"""
from __future__ import annotations

import json
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

# lo que se ve en la app -> lo que entiende el motor
TAMANOS = {"Pequeño": "pequeno", "Normal": "normal", "Grande": "grande", "Gigante": "gigante"}
POSICIONES = {"Arriba": "arriba", "En medio": "medio", "Encima de los subtítulos": "encima_subtitulos"}
DURACION_HOOK = {"3 segundos": 3.0, "5 segundos": 5.0, "Todo el clip": 0.0}
SILENCIOS = {"No recortar": "no", "Suave": "suave", "Normal": "normal", "Agresivo": "agresivo"}
SIN_CLIENTE = "(ninguno)"


def _inv(d: dict, valor, defecto):
    for k, v in d.items():
        if v == valor:
            return k
    return defecto


def _clientes():
    return [SIN_CLIENTE] + m.listar_clientes()


def guardar_key(key: str, cual: str = "ANTHROPIC_API_KEY") -> str:
    key = (key or "").strip()
    if cual == "ANTHROPIC_API_KEY" and not key.startswith("sk-"):
        return "Esa no parece una API key de Claude (empieza con sk-ant-...)."
    if not key:
        return "Pega la key primero."
    env = m.AQUI / ".env"
    lineas = []
    if env.exists():
        lineas = [l for l in env.read_text(encoding="utf-8").splitlines() if not l.startswith(f"{cual}=")]
    lineas.append(f"{cual}={key}")
    env.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    os.environ[cual] = key
    return "Guardada." if cual != "ANTHROPIC_API_KEY" else "Guardada. Ya puedes usar la IA de Claude para elegir clips."


def estado_key() -> str:
    partes = ["API key de Claude: " + ("configurada" if os.environ.get("ANTHROPIC_API_KEY")
                                       else "no configurada (elige clips sin IA)")]
    if os.environ.get("ELEVENLABS_API_KEY"):
        partes.append("ElevenLabs: configurada")
    return " · ".join(partes)


def al_elegir_cliente(nombre):
    """Al elegir un cliente, la app se llena con su estilo (lo puedes cambiar igual)."""
    cfg = m.cargar_config({"cliente": "" if nombre == SIN_CLIENTE else nombre})
    perfil = cfg.get("_cliente") or {}
    partes = []
    if perfil:
        tipos = {"radio": "radio", "canal_youtube": "canal de YouTube", "comediante": "comediante", "marca": "marca"}
        partes.append(f"**{perfil.get('nombre')}**" + (f" ({tipos[perfil['tipo']]})" if perfil.get("tipo") in tipos else ""))
        canal = m._canal_activo(perfil)
        if canal:
            partes.append("insignia del canal ✓" + (f" {canal['handle']}" if canal.get("handle") else " (falta el @)"))
        partes.append("logo ✓" if perfil.get("logo") else "sin logo")
        partes.append("intro ✓" if perfil.get("intro") else "sin intro")
        partes.append("outro ✓" if perfil.get("outro") else "sin outro")
        t = perfil.get("tarjeta_cierre") or {}
        partes.append("tarjeta de cierre ✓" if t.get("activa", bool(t)) else "sin tarjeta de cierre")
        if perfil.get("glosario"):
            partes.append(f"glosario: {len(perfil['glosario'])} palabras")
    info = " · ".join(partes) if partes else "Sin cliente: sin logo ni intro/outro."
    return (gr.update(value=cfg["estilo"]), gr.update(value=_inv(TAMANOS, str(cfg["tam_subtitulos"]), "Normal")),
            gr.update(value=_inv(POSICIONES, cfg["hook_posicion"], "Arriba")),
            gr.update(value=_inv(SILENCIOS, cfg["silencios"], "Normal")), info)


def _opciones(cliente, estilo, tam, pos_hook, dur_hook, hook, silencios, muletillas, zoom, exportar,
              modelo_whisper, corregir, retranscribir, presupuesto, flyer=None, flyer_seg=4) -> dict:
    return {
        "flyer_final": flyer or "", "flyer_segundos": float(flyer_seg or 4),
        "cliente": "" if cliente in (None, SIN_CLIENTE) else cliente, "estilo": estilo,
        "tam_subtitulos": TAMANOS.get(tam, "normal"), "hook_posicion": POSICIONES.get(pos_hook, "arriba"),
        "hook_segundos": DURACION_HOOK.get(dur_hook, 3.0), "hook": bool(hook),
        "silencios": SILENCIOS.get(silencios, "normal"), "quitar_muletillas": bool(muletillas),
        "zoom_en_cortes": bool(zoom), "exportar_nle": bool(exportar), "modelo_whisper": modelo_whisper,
        "corregir_con_claude": bool(corregir), "transcribir_clips_con": "elevenlabs" if retranscribir else "no",
        "presupuesto_claude": float(presupuesto or 0),
    }


def _correr(trabajo_fn):
    """Corre el motor en un hilo y va mostrando el progreso."""
    cola: queue.Queue = queue.Queue()
    resultado: dict = {}

    def trabajador():
        try:
            resultado["ok"] = trabajo_fn(cola.put)
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
        yield "\n".join(lineas[-300:]), None
    if "error" in resultado:
        lineas.append(f"\n[ERROR] {resultado['error']}")
        yield "\n".join(lineas), None
        return
    yield "\n".join(lineas), resultado["ok"]


def _salidas(trabajo, clips):
    galeria = [(str(trabajo / c["archivo"]), f"{c['puntuacion']} pts · {c.get('titulo', '')}") for c in clips]
    tabla = [[c["puntuacion"], c.get("titulo", ""),
              f"{c['duracion']:.0f} s" + (f" (de {c['duracion_original']:.0f})" if c.get("duracion_original") and
                                          c["duracion_original"] - c["duracion"] > 0.4 else ""),
              f"{c.get('hook', 0)}/{c.get('flujo', 0)}/{c.get('valor', 0)}/{c.get('tendencia', 0)}",
              c.get("razon", ""),
              (c.get("caption_post", "") + " " + " ".join("#" + h.lstrip("#") for h in c.get("hashtags", []))).strip()]
             for c in clips]
    return galeria, tabla


def procesar(link, archivo, n, dmin, dmax, formato, instruccion, idioma, usar_ia, modelo_ia, *opciones):
    fuente = archivo or (link or "").strip().strip('"')
    if not fuente:
        raise gr.Error("Pega un link de YouTube, la ruta de un video o sube un archivo.")
    if dmin >= dmax:
        raise gr.Error("La duracion minima tiene que ser menor que la maxima.")
    extra = {"clips": int(n), "duracion_min": float(dmin), "duracion_max": float(dmax), "formato": formato,
             "idioma": None if idioma == "detectar" else idioma, "ia": "claude" if usar_ia else "ninguna",
             "modelo_ia": modelo_ia}
    extra.update(_opciones(*opciones))
    cfg = m.cargar_config(extra)
    for texto, res in _correr(lambda log: m.procesar(fuente, cfg, instruccion or "", log=log)):
        if res is None:
            yield texto, gr.update(), gr.update(), gr.update(), gr.update()
        else:
            trabajo, clips = res
            galeria, tabla = _salidas(trabajo, clips)
            yield texto, galeria, tabla, str(trabajo), m.resumen_gasto()


def rerender(carpeta, formato, *opciones):
    """Mismos clips de la ultima corrida, con el estilo que tengas elegido ahora (no vuelve a llamar a Claude)."""
    if not carpeta:
        raise gr.Error("Primero crea clips (o abre una carpeta de resultados).")
    trabajo = Path(carpeta)
    proyecto = trabajo / "proyecto.json"
    clips_json = trabajo / "clips.json"
    if not clips_json.exists():
        raise gr.Error("No encuentro clips.json en esa carpeta.")
    fuente = None
    if proyecto.exists():
        fuente = json.loads(proyecto.read_text(encoding="utf-8")).get("fuente")
    if not fuente:
        f = next(iter(sorted((trabajo / "fuente").glob("original.*"))), None) if (trabajo / "fuente").exists() else None
        fuente = str(f) if f else None
    if not fuente or not Path(fuente).exists():
        raise gr.Error("No encuentro el video original de esa corrida.")
    viejos = json.loads(clips_json.read_text(encoding="utf-8"))
    claves = ("inicio", "fin", "titulo", "texto_hook", "hook", "flujo", "valor", "tendencia", "razon",
              "caption_post", "hashtags", "palabras_clave")
    manual = [{k: c[k] for k in claves if k in c} for c in viejos]
    extra = {"formato": formato, "clips": len(manual), "ia": "claude"}
    extra.update(_opciones(*opciones))
    cfg = m.cargar_config(extra)
    for texto, res in _correr(lambda log: m.procesar(fuente, cfg, "", trabajo, log=log, clips_manual=manual)):
        if res is None:
            yield texto, gr.update(), gr.update(), gr.update(), gr.update()
        else:
            t, clips = res
            galeria, tabla = _salidas(t, clips)
            yield texto, galeria, tabla, str(t), m.resumen_gasto()


def abrir_carpeta(trabajo):
    if trabajo:
        m.abrir(Path(trabajo))


def abrir_galeria(trabajo):
    if trabajo:
        m.abrir(Path(trabajo) / "galeria.html")


def abrir_editor(trabajo):
    """Abre el editor (v0.3) en el navegador; si no esta corriendo, lo arranca en su propia ventana."""
    import socket
    import subprocess
    import sys
    import webbrowser
    ruta = f"#/proyecto/{Path(trabajo).name}" if trabajo else ""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as so:
        corriendo = so.connect_ex(("127.0.0.1", 7861)) == 0
    if corriendo:
        webbrowser.open(f"http://127.0.0.1:7861/{ruta}")
        return
    flags = 0x00000010 if os.name == "nt" else 0  # CREATE_NEW_CONSOLE: su propia ventana negra
    subprocess.Popen([sys.executable, str(m.AQUI / "editor.py"), "--abrir", ruta], cwd=str(m.AQUI), creationflags=flags)


def abrir_clientes():
    m.CLIENTES.mkdir(parents=True, exist_ok=True)
    m.abrir(m.CLIENTES)


with gr.Blocks(title="MiOpusClip") as demo:
    carpeta = gr.State(None)
    gr.Markdown(f"# MiOpusClip <small style='opacity:.5;font-size:14px'>v{m.VERSION}</small>\n"
                "Video largo adentro, clips verticales con subtitulos afuera.", elem_id="titulo")
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
                cliente = gr.Dropdown(_clientes(), value=CFG.get("cliente") or SIN_CLIENTE, label="Cliente",
                                      info="Pone su logo, intro/outro, tarjeta de cierre, glosario y estilo")
                b_clientes = gr.Button("Carpeta de clientes", size="sm")
            info_cliente = gr.Markdown("")
            with gr.Row():
                n = gr.Slider(1, 20, value=CFG["clips"], step=1, label="Cuantos clips")
                formato = gr.Radio(["9:16", "1:1", "4:5", "16:9"], value=CFG["formato"], label="Formato")
            with gr.Row():
                dmin = gr.Slider(5, 120, value=CFG["duracion_min"], step=1, label="Duracion minima (s)")
                dmax = gr.Slider(10, 180, value=CFG["duracion_max"], step=1, label="Duracion maxima (s)")
    with gr.Row():
        with gr.Column():
            gr.Markdown("**Subtítulos y título**")
            with gr.Row():
                estilo = gr.Dropdown(["opus", "yulian", "simple", "ninguno"], value=CFG["estilo"], label="Estilo",
                                     info="opus: palabra activa en amarillo · yulian: palabra por palabra + claves en rojo")
                tam = gr.Radio(list(TAMANOS), value=_inv(TAMANOS, str(CFG["tam_subtitulos"]), "Normal"),
                               label="Tamaño de los subtítulos")
            with gr.Row():
                hook = gr.Checkbox(value=CFG["hook"], label="Poner el título (hook)")
                pos_hook = gr.Radio(list(POSICIONES), value=_inv(POSICIONES, CFG["hook_posicion"], "Arriba"),
                                    label="Dónde va el título")
                dur_hook = gr.Radio(list(DURACION_HOOK), value=_inv(DURACION_HOOK, float(CFG["hook_segundos"] or 0), "3 segundos"),
                                    label="Cuánto dura")
        with gr.Column():
            gr.Markdown("**Edición**")
            with gr.Row():
                silencios = gr.Radio(list(SILENCIOS), value=_inv(SILENCIOS, CFG["silencios"], "Normal"),
                                     label="Recortar silencios", info="Nunca corta encima de risas ni a mitad de palabra")
            with gr.Row():
                muletillas = gr.Checkbox(value=CFG["quitar_muletillas"], label='Quitar "eh", "mmm"')
                zoom = gr.Checkbox(value=CFG["zoom_en_cortes"], label="Zoom en cada corte")
                exportar = gr.Checkbox(value=CFG["exportar_nle"], label="Exportar para Premiere / DaVinci")
            with gr.Row():
                flyer = gr.File(label="Flyer al final (opcional)", file_types=["image", "video"], type="filepath",
                                height=110)
                flyer_seg = gr.Slider(2, 10, value=float(CFG.get("flyer_segundos") or 4), step=0.5,
                                      label="Segundos del flyer", info="Se pone después de cada clip (y del outro)")
            with gr.Row():
                idioma = gr.Dropdown(["detectar", "es", "en", "pt", "fr", "it"],
                                     value=CFG["idioma"] or "detectar", label="Idioma")
                usar_ia = gr.Checkbox(value=CFG["ia"] == "claude", label="Usar Claude para elegir")
    with gr.Accordion("Transcripción", open=False):
        with gr.Row():
            modelo_whisper = gr.Dropdown(["large-v3-turbo", "large-v3"], value=CFG["modelo_whisper"],
                                         label="Modelo de Whisper", allow_custom_value=True,
                                         info="large-v3: más preciso, ~2 veces más lento (la primera vez baja 3 GB)")
            corregir = gr.Checkbox(value=CFG["corregir_con_claude"],
                                   label="Corregir con Claude las palabras de los clips (usa el glosario; centavos)")
            retranscribir = gr.Checkbox(value=CFG["transcribir_clips_con"] == "elevenlabs",
                                        label="Re-transcribir los clips con ElevenLabs (de pago, ~$0.22 la hora)")
        with gr.Row():
            key11 = gr.Textbox(label="API key de ElevenLabs (opcional)", type="password")
            guardar11 = gr.Button("Guardar key de ElevenLabs")
    with gr.Accordion("Configuración y gasto de Claude", open=False):
        with gr.Row():
            modelo_ia = gr.Dropdown(m.MODELOS_CLAUDE, value=CFG["modelo_ia"], label="Modelo de Claude",
                                    allow_custom_value=True,
                                    info="Sonnet: mejor relacion calidad/precio · Haiku: casi gratis · Opus: el mas fino")
            presupuesto = gr.Number(value=float(CFG.get("presupuesto_claude") or 0), label="Presupuesto por video (USD)",
                                    info="Si el costo estimado lo pasa, no llama a Claude. 0 = sin límite")
        with gr.Row():
            key = gr.Textbox(label="API key de Claude", type="password", placeholder="sk-ant-...")
            guardar = gr.Button("Guardar key")
        estado = gr.Markdown(estado_key())
        gasto_md = gr.Markdown(m.resumen_gasto())
        gr.Markdown("Antes de llamar a Claude, el progreso muestra el costo estimado con cada modelo; "
                    "después, lo que costó de verdad. Todo queda anotado en `uso/uso.csv`. "
                    "Precios en `precios.json` si cambian.")
    progreso = gr.Textbox(label="Progreso", lines=10, max_lines=18, elem_id="log", autoscroll=True)
    galeria = gr.Gallery(label="Clips (ordenados por puntuacion)", columns=4, height="auto", object_fit="contain")
    tabla = gr.Dataframe(headers=["Pts", "Titulo", "Dur.", "Hook/Flujo/Valor/Tend.", "Por que funciona", "Texto para publicar"],
                         label="Detalle", wrap=True, interactive=False)
    with gr.Row():
        b_rerender = gr.Button("Volver a renderizar con estas opciones")
        b_editor = gr.Button("Editar los clips", variant="primary")
        b_galeria = gr.Button("Abrir galeria")
        b_carpeta = gr.Button("Abrir carpeta de clips")

    opciones = [cliente, estilo, tam, pos_hook, dur_hook, hook, silencios, muletillas, zoom, exportar,
                modelo_whisper, corregir, retranscribir, presupuesto, flyer, flyer_seg]
    salidas = [progreso, galeria, tabla, carpeta, gasto_md]
    boton.click(procesar, [link, archivo, n, dmin, dmax, formato, instruccion, idioma, usar_ia, modelo_ia, *opciones],
                salidas)
    b_rerender.click(rerender, [carpeta, formato, *opciones], salidas)
    cliente.change(al_elegir_cliente, cliente, [estilo, tam, pos_hook, silencios, info_cliente])
    guardar.click(guardar_key, key, estado)
    guardar11.click(lambda k: guardar_key(k, "ELEVENLABS_API_KEY"), key11, estado)
    b_carpeta.click(abrir_carpeta, carpeta, None)
    b_galeria.click(abrir_galeria, carpeta, None)
    b_editor.click(abrir_editor, carpeta, None)
    b_clientes.click(abrir_clientes, None, None)
    demo.load(lambda c: (al_elegir_cliente(c)[4], m.resumen_gasto()), cliente, [info_cliente, gasto_md])

if __name__ == "__main__":
    m.RESULTADOS.mkdir(parents=True, exist_ok=True)
    demo.queue().launch(inbrowser=os.environ.get("MIOPUSCLIP_NO_NAVEGADOR") is None, server_name="127.0.0.1",
                        allowed_paths=[str(m.RESULTADOS), str(m.AQUI)], css=CSS,
                        theme=gr.themes.Soft(primary_hue="red", neutral_hue="zinc"))
