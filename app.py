# -*- coding: utf-8 -*-
"""SmartCut - interfaz en el navegador. Se abre sola en http://127.0.0.1:7860"""
from __future__ import annotations

import json
import os
import queue
import re
import threading
from pathlib import Path

import gradio as gr

import miopusclip as m

m.cargar_env()
CFG = m.cargar_config()
RED = m.config_red()

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


def _opciones_musica():
    m.MUSICA.mkdir(exist_ok=True)
    lista = m.canciones()
    return [("Sin música", "")] + ([("Una al azar", "azar")] if lista else []) + [(p.stem, p.name) for p in lista]


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
              modelo_whisper, corregir, retranscribir, presupuesto, flyer=None, flyer_seg=4, volumen=True,
              sin_punt=False, musica="", vol_musica="normal", efectos="suave") -> dict:
    return {
        "subir_volumen": bool(volumen), "sin_puntuacion": bool(sin_punt), "musica": musica or "",
        "volumen_musica": vol_musica or "normal", "efectos": efectos or "no",
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


def _id_youtube(url: str) -> str | None:
    r = re.search(r"(?:v=|youtu\.be/|/shorts/|/live/|/embed/)([A-Za-z0-9_-]{11})", url or "")
    return r.group(1) if r else None


def vista_youtube(url):
    """Reproductor de YouTube dentro de la app para elegir el fragmento (sin bajar el video)."""
    vid = _id_youtube(url)
    if not vid:
        return ""
    # YouTube pide saber desde que pagina se ve (referrer); sin eso sale "video no disponible"
    return (f'<iframe id="yt_fragmento_player" src="https://www.youtube.com/embed/{vid}?enablejsapi=1&rel=0" '
            'referrerpolicy="strict-origin-when-cross-origin" '
            'style="width:100%;aspect-ratio:16/9;border:0;border-radius:10px" allow="autoplay; encrypted-media" '
            'allowfullscreen></iframe>')


def texto_fragmento(desde, hasta):
    try:
        a, b = m.leer_tiempo(desde), m.leer_tiempo(hasta)
    except RuntimeError as e:
        return f"⚠️ {e}"
    if not a and not b:
        return ""
    if b and b <= a:
        return "⚠️ El fin tiene que ir después del inicio."
    return f"Fragmento: {m.fmt_t(a)} → {m.fmt_t(b) if b else 'el final'}" + (f" ({m.fmt_t(b - a)})" if b else "")


# Lee el segundo en que va el video (el subido o el de YouTube) y lo escribe como 1:05:30
JS_MOMENTO = """() => {
    const v = document.querySelector('#previa_fragmento video');
    let t = (v && v.currentSrc && v.offsetParent !== null) ? v.currentTime : (window.__ytT || 0);
    t = Math.floor(t);
    const h = Math.floor(t / 3600), mi = Math.floor(t % 3600 / 60), s = t % 60;
    const dd = (x) => String(x).padStart(2, '0');
    return h ? `${h}:${dd(mi)}:${dd(s)}` : `${mi}:${dd(s)}`;
}"""

# YouTube avisa en que segundo va si se le pide (postMessage), sin cargar su API completa
HEAD = """<script>
window.addEventListener('message', (e) => {
  if (!/(^|\\.)youtube\\.com$/.test(new URL(e.origin).hostname)) return;
  try { const d = JSON.parse(e.data); if (d.info && typeof d.info.currentTime === 'number') window.__ytT = d.info.currentTime; } catch (_) {}
});
setInterval(() => {
  const f = document.getElementById('yt_fragmento_player');
  if (f && f.contentWindow) f.contentWindow.postMessage(JSON.stringify({event: 'listening', id: 1}), '*');
}, 1000);
</script>"""


def _crear(repetir, link, archivo, desde, hasta, n, dmin, dmax, formato, instruccion, idioma, usar_ia, modelo_ia,
           *opciones):
    fuente = archivo or (link or "").strip().strip('"')
    if not fuente:
        raise gr.Error("Pega un link de YouTube, la ruta de un video o sube un archivo.")
    if dmin >= dmax:
        raise gr.Error("La duracion minima tiene que ser menor que la maxima.")
    try:
        a, b = m.leer_tiempo(desde), m.leer_tiempo(hasta)
    except RuntimeError as e:
        raise gr.Error(str(e))
    if b and b <= a:
        raise gr.Error("En el fragmento, el fin tiene que ir después del inicio.")
    extra = {"clips": int(n), "duracion_min": float(dmin), "duracion_max": float(dmax), "formato": formato,
             "idioma": None if idioma == "detectar" else idioma, "ia": "claude" if usar_ia else "ninguna",
             "modelo_ia": modelo_ia, "desde": a, "hasta": b}
    extra.update(_opciones(*opciones))
    cfg = m.cargar_config(extra)
    previos = []

    def trabajo_fn(log):
        try:
            return m.procesar(fuente, cfg, instruccion or "", log=log, repetir=repetir)
        except m.VideoRepetido as e:
            previos.extend(e.previos)
            log(str(e))
            return None

    oculto = (gr.update(visible=False), gr.update())
    for texto, res in _correr(trabajo_fn):
        if res is None:
            if previos:
                p = previos[0]
                aviso = (f"### Este video ya lo procesaste\n**{p['titulo']}** · {p['clips']} clips · {p['fecha']}\n\n"
                         "No gasté nada ni creé clips repetidos.")
                yield (texto, gr.update(), gr.update(), p["ruta"], gr.update(), gr.update(visible=True), aviso)
            else:
                yield (texto, gr.update(), gr.update(), gr.update(), gr.update(), *oculto)
        else:
            trabajo, clips = res
            galeria, tabla = _salidas(trabajo, clips)
            yield (texto, galeria, tabla, str(trabajo), m.resumen_gasto(), *oculto)


def procesar(*args):
    yield from _crear(False, *args)


def procesar_distintos(*args):
    """El mismo video, pero con otros momentos: Claude no repite los que ya tienen clip."""
    yield from _crear(True, *args)


def ver_existentes(carpeta_previa):
    """Muestra los clips que ya existen de ese video, sin crear nada."""
    if not carpeta_previa:
        raise gr.Error("No encuentro esa carpeta.")
    trabajo = Path(carpeta_previa)
    clips = json.loads((trabajo / "clips.json").read_text(encoding="utf-8"))
    for c in clips:
        c.setdefault("puntuacion", 0)
        c.setdefault("duracion", float(c.get("fin", 0)) - float(c.get("inicio", 0)))
    galeria, tabla = _salidas(trabajo, [c for c in clips if c.get("archivo") and (trabajo / c["archivo"]).exists()])
    return galeria, tabla, gr.update(visible=False)


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


def abrir_carpeta(trabajo, request: gr.Request):
    if not trabajo:
        return
    if not m.es_local(_host(request)):
        gr.Info(f"La carpeta está en la PC donde corre SmartCut: {trabajo}. Desde aquí baja los clips en la galería "
                "o en el editor (botón Descargar).")
        return
    m.abrir(Path(trabajo))


def abrir_galeria(trabajo, request: gr.Request = None):
    if trabajo and request is not None and not m.es_local(_host(request)):
        gr.Info("Abrí la galería en otra pestaña. Si no aparece, permite las ventanas emergentes de esta página.")
        return
    if trabajo:
        m.abrir(Path(trabajo) / "galeria.html")


def _host(request) -> str:
    try:
        return (request.headers.get("host") or "127.0.0.1").split(":")[0] if request else "127.0.0.1"
    except Exception:
        return "127.0.0.1"


def _editor_corriendo() -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as so:
        return so.connect_ex(("127.0.0.1", 7861)) == 0


def arrancar_editor() -> None:
    """Arranca el editor (en su propia ventana) si no esta corriendo, y espera a que responda."""
    import subprocess
    import sys
    import time
    if _editor_corriendo():
        return
    flags = 0x00000010 if os.name == "nt" else 0  # CREATE_NEW_CONSOLE: su propia ventana negra
    args = [sys.executable, str(m.AQUI / "editor.py"), "--no-abrir"] + (["--red"] if RED["activa"] else [])
    subprocess.Popen(args, cwd=str(m.AQUI), creationflags=flags)
    for _ in range(40):
        time.sleep(0.4)
        if _editor_corriendo():
            return


def abrir_editor(trabajo, request: gr.Request):
    """Abre el editor (v0.3) en el navegador de quien lo pidio: esta PC o la Mac."""
    arrancar_editor()
    ruta = f"#/proyecto/{Path(trabajo).name}" if trabajo else ""
    url = f"http://{_host(request)}:7861/{ruta}"
    return f'<a id="ir_editor" href="{url}" target="_blank">Abrir el editor &rarr; {url}</a>'


def abrir_clientes():
    m.CLIENTES.mkdir(parents=True, exist_ok=True)
    m.abrir(m.CLIENTES)


with gr.Blocks(title="SmartCut") as demo:
    carpeta = gr.State(None)
    gr.Markdown(f"# SmartCut <small style='opacity:.5;font-size:14px'>v{m.VERSION}</small>\n"
                "Video largo adentro, clips verticales con subtitulos afuera.", elem_id="titulo")
    with gr.Row():
        with gr.Column(scale=5):
            link = gr.Textbox(label="Link de YouTube o ruta del video en tu PC",
                              placeholder='https://www.youtube.com/watch?v=...   o   C:\\Users\\yo\\Videos\\show.mp4')
            archivo = gr.File(label="...o sube el video", file_types=["video"], type="filepath")
            with gr.Accordion("Sacar clips solo de un fragmento (opcional)", open=False):
                gr.Markdown("Pon el video donde quieras y marca el inicio y el fin. Vacío = todo el video.")
                yt_previa = gr.HTML("", elem_id="yt_fragmento")
                previa = gr.Video(label="Vista previa", visible=False, interactive=False, elem_id="previa_fragmento",
                                  height=300)
                with gr.Row():
                    with gr.Column(min_width=160):
                        desde = gr.Textbox(label="Desde", placeholder="0:00")
                        b_desde = gr.Button("Marcar inicio aquí", size="sm")
                    with gr.Column(min_width=160):
                        hasta = gr.Textbox(label="Hasta", placeholder="final")
                        b_hasta = gr.Button("Marcar fin aquí", size="sm")
                largo_fragmento = gr.Markdown("")
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
                volumen = gr.Checkbox(value=CFG.get("subir_volumen", True), label="Subir el volumen si está bajito")
                sin_punt = gr.Checkbox(value=CFG.get("sin_puntuacion", False), label="Subtítulos sin signos de puntuación")
            with gr.Row():
                musica = gr.Dropdown(_opciones_musica(), value=CFG.get("musica") or "", label="Música de fondo",
                                     info="Baja sola cuando hablan. Pon tus canciones en la carpeta 'musica'",
                                     allow_custom_value=True)
                vol_musica = gr.Radio(["bajo", "normal", "alto"], value=CFG.get("volumen_musica") or "normal",
                                      label="Volumen de la música")
                efectos = gr.Dropdown([("Sin efectos", "no"), ("En zooms, textos y lower thirds", "suave"),
                                       ("También en cada corte", "completo")], value=CFG.get("efectos") or "suave",
                                      label="Efectos de sonido")
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
    with gr.Group(visible=False) as caja_repetido:
        aviso_repetido = gr.Markdown("")
        with gr.Row():
            b_ver_previos = gr.Button("Ver los clips que ya tengo", variant="primary")
            b_distintos = gr.Button("Crear clips de otros momentos")
    progreso = gr.Textbox(label="Progreso", lines=10, max_lines=18, elem_id="log", autoscroll=True)
    galeria = gr.Gallery(label="Clips (ordenados por puntuacion)", columns=4, height="auto", object_fit="contain")
    tabla = gr.Dataframe(headers=["Pts", "Titulo", "Dur.", "Hook/Flujo/Valor/Tend.", "Por que funciona", "Texto para publicar"],
                         label="Detalle", wrap=True, interactive=False)
    with gr.Row():
        b_rerender = gr.Button("Volver a renderizar con estas opciones")
        b_editor = gr.Button("Editar los clips", variant="primary")
        b_galeria = gr.Button("Abrir galeria")
        b_carpeta = gr.Button("Abrir carpeta de clips")
    link_editor = gr.HTML("")

    opciones = [cliente, estilo, tam, pos_hook, dur_hook, hook, silencios, muletillas, zoom, exportar,
                modelo_whisper, corregir, retranscribir, presupuesto, flyer, flyer_seg, volumen,
                sin_punt, musica, vol_musica, efectos]
    salidas = [progreso, galeria, tabla, carpeta, gasto_md]
    salidas_crear = [*salidas, caja_repetido, aviso_repetido]
    entradas_crear = [link, archivo, desde, hasta, n, dmin, dmax, formato, instruccion, idioma, usar_ia, modelo_ia, *opciones]
    link.change(vista_youtube, link, yt_previa)
    archivo.change(lambda f: gr.update(value=f, visible=bool(f)), archivo, previa)
    b_desde.click(None, None, desde, js=JS_MOMENTO)
    b_hasta.click(None, None, hasta, js=JS_MOMENTO)
    desde.change(texto_fragmento, [desde, hasta], largo_fragmento)
    hasta.change(texto_fragmento, [desde, hasta], largo_fragmento)
    boton.click(procesar, entradas_crear, salidas_crear)
    b_distintos.click(procesar_distintos, entradas_crear, salidas_crear)
    b_ver_previos.click(ver_existentes, carpeta, [galeria, tabla, caja_repetido])
    b_rerender.click(rerender, [carpeta, formato, *opciones], salidas)
    cliente.change(al_elegir_cliente, cliente, [estilo, tam, pos_hook, silencios, info_cliente])
    guardar.click(guardar_key, key, estado)
    guardar11.click(lambda k: guardar_key(k, "ELEVENLABS_API_KEY"), key11, estado)
    b_carpeta.click(abrir_carpeta, carpeta, None)
    # Desde otro equipo (la Mac) la galeria se abre ahi mismo, servida por el editor (puerto 7861).
    b_galeria.click(abrir_galeria, carpeta, None, js="""(c) => {
        const h = location.hostname;
        if (c && !['127.0.0.1', 'localhost', '::1'].includes(h)) {
            const n = c.split(/[\\\\/]/).filter(Boolean).pop();
            window.open(location.protocol + '//' + h + ':7861/media/' + encodeURIComponent(n) + '/galeria.html', '_blank');
        }
        return c;
    }""")
    b_editor.click(abrir_editor, carpeta, link_editor).then(
        None, None, None, js="() => { const a = document.querySelector('#ir_editor'); if (a) window.open(a.href, '_blank') }")
    b_clientes.click(abrir_clientes, None, None)
    demo.load(lambda c: (al_elegir_cliente(c)[4], m.resumen_gasto()), cliente, [info_cliente, gasto_md])

if __name__ == "__main__":
    m.RESULTADOS.mkdir(parents=True, exist_ok=True)
    if RED["activa"]:
        print(f"\n=== SmartCut {m.VERSION} en tu red ===\n"
              f"En esta PC:  http://127.0.0.1:7860\n"
              f"Desde la Mac: http://{RED['ip']}:7860   (o http://{RED['equipo']}.local:7860)\n"
              f"Usuario: {RED['usuario']}   Clave: {RED['clave']}\n"
              f"El editor queda en el puerto 7861 con la misma clave.\n")
        arrancar_editor()
    demo.queue().launch(inbrowser=os.environ.get("MIOPUSCLIP_NO_NAVEGADOR") is None,
                        server_name="0.0.0.0" if RED["activa"] else "127.0.0.1",
                        auth=(RED["usuario"], RED["clave"]) if RED["activa"] and RED["clave"] else None,
                        auth_message="SmartCut: escribe el usuario y la clave que salen en la ventana negra de la PC.",
                        allowed_paths=[str(m.RESULTADOS), str(m.AQUI)], css=CSS, head=HEAD,
                        theme=gr.themes.Soft(primary_hue="red", neutral_hue="zinc"))
