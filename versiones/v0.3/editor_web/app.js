// MiOpusClip · editor (v0.3). Sin dependencias salvo JASSUB (los subtitulos, igual que en el render).
import JASSUB from '/web/jassub/jassub.es.js'

const $ = (s, el = document) => el.querySelector(s)
const $$ = (s, el = document) => [...el.querySelectorAll(s)]
function h (tag, attrs = {}, ...hijos) {
  const el = document.createElement(tag)
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue
    if (k === 'class') el.className = v
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v)
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v)
    else if (k === 'html') el.innerHTML = v
    else el.setAttribute(k, v === true ? '' : v)
  }
  for (const c of hijos.flat()) if (c != null && c !== false) el.append(c.nodeType ? c : document.createTextNode(String(c)))
  return el
}
async function api (url, opts = {}) {
  const o = { ...opts }
  if (o.body && !(o.body instanceof FormData) && typeof o.body !== 'string') {
    o.body = JSON.stringify(o.body)
    o.headers = { 'Content-Type': 'application/json', ...(o.headers || {}) }
  }
  const r = await fetch(url, o)
  if (!r.ok) {
    let msg = r.statusText
    try { msg = (await r.json()).detail || msg } catch {}
    throw new Error(msg)
  }
  return r.json()
}
function aviso (msg, tipo = 'info', ms = 4200) {
  const el = h('div', { class: tipo }, msg)
  $('#avisos').append(el)
  setTimeout(() => el.remove(), ms)
}
const fmt = (t, dec = 1) => {
  t = Math.max(0, t || 0)
  const m = Math.floor(t / 60); const s = t - m * 60
  const hh = Math.floor(m / 60)
  const ss = s.toFixed(dec).padStart(dec ? 3 + dec : 2, '0')
  return hh ? `${hh}:${String(m % 60).padStart(2, '0')}:${ss}` : `${m}:${ss}`
}
const clamp = (v, a, b) => Math.max(a, Math.min(b, v))
const norm = t => (t || '').replace(/[^\p{L}\p{N}_]/gu, '').toLowerCase()
const colorPts = p => p >= 80 ? '#2ECC71' : p >= 65 ? '#FFD60A' : '#FF8A3D'
const MODOS = [
  ['auto', 'Auto', '--auto', 'Sigue a quien habla (lo que decide MiOpusClip)'],
  ['recorte', 'Recorte', '--recorte', 'Encuadre fijo: arrastra el cuadro en el video original'],
  ['completo', 'Completo', '--completo', 'El video entero sobre fondo desenfocado'],
  ['split', 'Split', '--split', 'Dos personas: una arriba y otra abajo'],
  ['grafico', 'Gráfico', '--grafico', 'Una foto o video a pantalla completa (el audio sigue)']
]
const COLOR = Object.fromEntries(MODOS.map(m => [m[0], getComputedStyle(document.documentElement).getPropertyValue(m[2]).trim() || '#888']))
const NOMBRE = Object.fromEntries(MODOS.map(m => [m[0], m[1]]))

function modal (contenido) {
  const md = $('#modal')
  $('.contenido', md).replaceChildren(contenido)
  md.hidden = false
  const cerrar = () => { md.hidden = true; $$('video', md).forEach(v => v.pause()) }
  $('.cerrar', md).onclick = cerrar
  md.onclick = e => { if (e.target === md) cerrar() }
  return cerrar
}
function migas (...partes) {
  $('#migas').replaceChildren(...partes.flatMap((p, i) => (i ? [h('span', {}, '›'), p] : [p])))
}

// ---------------------------------------------------------------- vistas
let editor = null
async function ruta () {
  if (editor) { await editor.salir(); editor = null }
  $('#acciones').replaceChildren()
  const p = location.hash.replace(/^#\/?/, '').split('/').map(decodeURIComponent)
  try {
    if (p[0] === 'proyecto' && p[1]) await vistaProyecto(p[1])
    else if (p[0] === 'clip' && p[1] && p[2]) { editor = new Editor(p[1], p[2]); await editor.abrir() }
    else await vistaInicio()
  } catch (e) {
    $('#vista').replaceChildren(h('p', { class: 'cargando' }, 'No se pudo abrir: ' + e.message))
  }
}
window.addEventListener('hashchange', ruta)

async function vistaInicio () {
  migas(h('b', {}, 'Tus videos'))
  const lista = await api('/api/proyectos')
  const v = $('#vista')
  v.replaceChildren(h('h1', {}, 'Elige un video'))
  if (!lista.length) { v.append(h('p', { class: 'ayuda' }, 'Todavía no hay resultados. Crea clips con la app de MiOpusClip y vuelve aquí.')); return }
  v.append(h('div', { class: 'rejilla' }, lista.map(p => h('a', {
    class: 'tarjeta', href: p.editable ? `#/proyecto/${encodeURIComponent(p.carpeta)}` : null,
    style: p.editable ? null : { opacity: 0.5, cursor: 'default' },
    title: p.editable ? '' : 'No encuentro el video original de este resultado'
  }, h('div', { class: 'proy' }, h('b', {}, p.titulo),
    h('span', {}, `${p.clips} clips · ${p.fecha}`, p.cliente ? h('span', { class: 'etq' }, p.cliente) : null, p.v01 ? h('span', { class: 'etq' }, 'v0.1') : null))))))
}

async function vistaProyecto (carpeta) {
  const pr = await api(`/api/proyecto/${encodeURIComponent(carpeta)}`)
  migas(h('a', { href: '#/' }, 'Tus videos'), h('b', {}, pr.titulo))
  $('#acciones').replaceChildren(h('button', { class: 'btn', onclick: () => api(`/api/abrir/${encodeURIComponent(carpeta)}`, { method: 'POST', body: { que: 'clips' } }) }, 'Abrir carpeta'))
  const v = $('#vista')
  const res = h('div', { class: 'resultados' })
  const q = h('input', { type: 'search', placeholder: 'Busca una frase en la transcripción para hacer un clip nuevo…' })
  const buscar = async () => {
    res.replaceChildren()
    if (q.value.trim().length < 2) return
    const r = await api(`/api/buscar/${encodeURIComponent(carpeta)}?q=${encodeURIComponent(q.value)}`)
    if (!r.length) { res.append(h('p', { class: 'ayuda' }, 'No aparece en la transcripción.')); return }
    res.append(...r.map(x => h('div', {}, h('code', {}, fmt(x.i, 0)), h('p', {}, x.texto),
      h('button', {
        class: 'btn chico',
        onclick: async () => {
          const n = await api(`/api/nuevo/${encodeURIComponent(carpeta)}`, { method: 'POST', body: { inicio: Math.max(0, x.i - 0.05), titulo: x.texto.split(' ').slice(0, 8).join(' ') } })
          location.hash = `#/clip/${encodeURIComponent(carpeta)}/${n.id}`
        }
      }, 'Crear clip aquí'))))
  }
  q.addEventListener('keydown', e => { if (e.key === 'Enter') buscar() })
  v.replaceChildren(h('h1', {}, pr.titulo), h('div', { class: 'buscador' }, q, h('button', { class: 'btn', onclick: buscar }, 'Buscar')), res,
    h('div', { class: 'rejilla' }, pr.clips.map(c => h('a', { class: 'tarjeta', href: `#/clip/${encodeURIComponent(carpeta)}/${c.id}` },
      h('div', { class: 'mini', style: c.miniatura ? { backgroundImage: `url("${c.miniatura}")` } : null },
        h('span', { class: 'pts', style: { '--c': colorPts(c.puntuacion) } }, c.puntuacion || '–'),
        c.editado ? h('span', { class: 'ed' }, 'editado') : null),
      h('div', { class: 'info' }, h('b', {}, c.titulo), h('span', {}, `${fmt(c.inicio, 0)} → ${fmt(c.fin, 0)} · ${Math.round(c.duracion)} s`))))))
}

// ---------------------------------------------------------------- editor
class Editor {
  constructor (carpeta, id) {
    this.carpeta = carpeta; this.id = id
    this.base = `${encodeURIComponent(carpeta)}/${id}`
    this.deshacer = []; this.rehacer = []
    this.sel = { toma: 0, palabra: -1 }
    this.medios = {}
    this.capas = {}
    this.tramos = []; this.durOut = 0
    this.reproduciendo = false; this.modoClip = true
    this.pendiente = { previa: null, guardar: null }
    this.sucio = false; this.guardando = null
    this._teclas = e => this.tecla(e)
    this._redim = () => this.medir()
  }

  // ------------------------------------------------ carga
  async abrir () {
    $('#vista').replaceChildren(h('p', { class: 'cargando' }, 'Abriendo el clip…'))
    const r = await api(`/api/clip/${this.base}`)
    this.r = r
    this.l = r.linea
    this.pal = r.palabras
    this.ventana = r.ventana
    this.cliente = r.cliente || ''
    this.l.cliente = this.cliente
    this.l.hook = this.l.hook || { texto: '' }
    this.l.subtitulos.palabras_clave = this.l.subtitulos.palabras_clave || []
    this.fw = this.l.fuente_w; this.fh = this.l.fuente_h
    const c0 = this.l.camara || {}
    this.rangoCam = [c0.desde ?? this.l.inicio, c0.hasta ?? this.l.fin]
    this.ow = this.l.ancho; this.oh = this.l.alto
    migas(h('a', { href: '#/' }, 'Tus videos'), h('a', { href: `#/proyecto/${encodeURIComponent(this.carpeta)}` }, r.titulo_proyecto),
      h('b', {}, (this.l.meta && this.l.meta.titulo) || `Clip ${this.id}`))
    this.armar()
    document.addEventListener('keydown', this._teclas)
    window.addEventListener('resize', this._redim)
    window.onbeforeunload = () => (this.sucio ? 'Hay cambios sin guardar' : undefined)
    this.estado('Preparando el video…')
    const [px] = await Promise.all([
      api(`/api/proxy/${this.base}`, { method: 'POST', body: { desde: this.ventana[0], hasta: this.ventana[1] } }),
      this.cargarOnda(), this.cargarCapas()
    ])
    this.proxy = px
    this.video.addEventListener('seeked', () => this.dibujar())
    this.video.src = px.url
    await new Promise(res => { this.video.addEventListener('loadeddata', res, { once: true }); this.video.addEventListener('error', res, { once: true }) })
    this.seek(this.l.inicio)
    await this.previa(true)
    this.iniciarSubs()
    const c = this.l.camara || {}
    if (!(c.keyframes || []).length && this.tomasEfectivas().some(t => t.modo === 'auto')) this.recalcularSeguimiento()
    this.estado('')
    this.bucle()
  }

  async cargarOnda () {
    const n = 2400
    const r = await api(`/api/onda/${encodeURIComponent(this.carpeta)}?desde=${this.ventana[0]}&hasta=${this.ventana[1]}&n=${n}`)
    this.onda = r.picos
  }

  async cargarCapas () {
    this.capas = {}
    if (!this.cliente) return
    try {
      const c = await api(`/api/capas/${encodeURIComponent(this.cliente)}?w=${this.ow}&h=${this.oh}`)
      const carga = url => new Promise(res => { const i = new Image(); i.onload = () => res(i); i.onerror = () => res(null); i.src = url })
      this.capas = { logo: c.logo ? await carga(c.logo) : null, cierre: c.cierre ? await carga(c.cierre) : null, cierreSeg: c.cierre_seg || 3, cierreModo: c.cierre_modo || 'encima' }
    } catch (e) { aviso('No pude cargar el logo del cliente: ' + e.message, 'error') }
  }

  iniciarSubs () {
    const fuentes = {}
    for (const f of this.r.fuentes) for (const fam of f.familias) fuentes[fam] = f.url
    fuentes['liberation sans'] = '/web/jassub/default.woff2'
    try {
      this.jassub?.destroy()
    } catch {}
    const cv = this.cvSubs
    const nuevo = cv.cloneNode(false); cv.replaceWith(nuevo); this.cvSubs = nuevo
    nuevo.width = this.cvVert.width; nuevo.height = this.cvVert.height
    try {
      this.jassub = new JASSUB({
        canvas: nuevo, subContent: this.ass || '[Script Info]\nScriptType: v4.00+\n',
        workerUrl: '/web/jassub/jassub-worker.js', wasmUrl: '/web/jassub/jassub-worker.wasm',
        availableFonts: fuentes, fallbackFont: Object.keys(fuentes)[0] || 'liberation sans',
        onDemandRender: false, targetFps: 30
      })
      this.jassub.addEventListener?.('ready', () => this.dibujar())
    } catch (e) { console.error(e); aviso('No pude iniciar la vista previa de subtítulos: ' + e.message, 'error') }
  }

  // ------------------------------------------------ interfaz
  armar () {
    this.video = h('video', { preload: 'auto', playsinline: true, style: { display: 'none' } })
    this.cvOrig = h('canvas')
    this.cvVert = h('canvas'); this.cvSubs = h('canvas'); this.cvSup = h('canvas')
    this.cvTl = h('canvas')
    this.cajaVert = h('div', { class: 'vertical' }, this.cvVert, this.cvSubs, this.cvSup)
    this.avisoFuera = h('div', { class: 'fuera', hidden: true }, 'Fuera del clip')
    this.cajaVert.append(this.avisoFuera)
    this.tiempo = h('span', { class: 'tiempo' })
    this.btnPlay = h('button', { class: 'btn pri', onclick: () => this.alternar(), title: 'Reproducir (espacio)' }, '▶')
    this.lblCam = h('span', { class: 'der' })
    const orig = h('section', { class: 'col-orig' },
      h('div', { class: 'rotulo' }, 'Video original', this.lblCam),
      h('div', { class: 'lienzo' }, this.cvOrig),
      h('div', { class: 'transporte' }, this.btnPlay,
        h('button', { class: 'btn', title: 'Ir al inicio del clip', onclick: () => { this.pausar(); this.seek(this.l.inicio) } }, '⏮'),
        h('button', { class: 'btn', title: '-1 s (←)', onclick: () => this.seek(this.t() - 1) }, '−1s'),
        h('button', { class: 'btn', title: '+1 s (→)', onclick: () => this.seek(this.t() + 1) }, '+1s'),
        this.tiempo,
        h('span', { style: { flex: 1 } }),
        h('button', { class: 'btn chico', title: 'Empieza el clip aquí (I)', onclick: () => this.marcar('inicio', this.t()) }, '⇤ Inicio aquí'),
        h('button', { class: 'btn chico', title: 'Termina el clip aquí (O)', onclick: () => this.marcar('fin', this.t()) }, 'Fin aquí ⇥'),
        h('button', { class: 'btn chico', title: 'Dividir la toma en el cursor (S)', onclick: () => this.dividir() }, '✂ Dividir toma')),
      this.video)
    const vert = h('section', { class: 'col-vert' }, h('div', { class: 'rotulo' }, 'Así va a quedar'), this.cajaVert)
    this.panel = h('section', { class: 'panel' })
    this.lblDur = h('span', { class: 'der' })
    const tl = h('section', { class: 'col-tl' }, h('div', { class: 'rotulo' }, 'Línea de tiempo',
      h('span', { class: 'ayuda', style: { textTransform: 'none', letterSpacing: 0 } }, 'Arrastra los bordes rojos para mover el inicio y el fin · arriba, las tomas'), this.lblDur), this.cvTl)
    this.barraPal = h('div', { class: 'barra-pal' })
    this.cajaPal = h('div', { class: 'palabras' })
    const pal = h('section', { class: 'col-pal' }, this.barraPal, this.cajaPal)
    const ed = h('div', { class: 'editor' }, orig, vert, this.panel, tl, pal)
    $('#vista').replaceChildren(ed)
    $('main').style.padding = '0'
    this.btnGuardar = h('button', { class: 'btn', onclick: () => this.guardar(true) }, 'Guardar')
    this.chkExport = h('input', { type: 'checkbox' })
    this.btnRender = h('button', { class: 'btn pri', onclick: () => this.render() }, 'Renderizar')
    this.lblEstado = h('span', { class: 'estado' })
    $('#acciones').replaceChildren(this.lblEstado,
      h('button', { class: 'btn', title: 'Deshacer (Ctrl+Z)', onclick: () => this.deshacerUno() }, '↶'),
      this.btnGuardar, h('label', { class: 'check', title: 'Además deja la carpeta para Premiere / DaVinci' }, this.chkExport, 'Premiere/DaVinci'), this.btnRender)
    this.pestana = 'tomas'
    this.armarPanel()
    this.armarPalabras()
    this.eventosOrig(); this.eventosTl()
    this.medir()
  }

  medir () {
    const dpr = window.devicePixelRatio || 1
    const alto = clamp(window.innerHeight - 56 - 28 - 175 - 190, 300, 700)
    const ancho = Math.round(alto * this.ow / this.oh)
    Object.assign(this.cajaVert.style, { width: ancho + 'px', height: alto + 'px' })
    const W = Math.round(ancho * dpr); const H = Math.round(alto * dpr)
    const cambiaron = this.cvVert.width !== W
    for (const c of [this.cvVert, this.cvSup]) { c.width = W; c.height = H }
    const ow = this.cvOrig.parentElement.clientWidth || 600
    const oh = Math.min(alto, Math.round(ow * this.fh / this.fw))
    this.cvOrig.style.height = oh + 'px'; this.cvOrig.style.width = Math.round(oh * this.fw / this.fh) + 'px'
    this.cvOrig.parentElement.style.display = 'flex'; this.cvOrig.parentElement.style.justifyContent = 'center'
    this.cvOrig.width = Math.round(oh * this.fw / this.fh * dpr); this.cvOrig.height = Math.round(oh * dpr)
    this.cvTl.width = Math.round(this.cvTl.clientWidth * dpr) || 1200; this.cvTl.height = Math.round(132 * dpr)
    if (cambiaron && this.jassub) this.iniciarSubs()
    this.dibujar()
  }

  estado (txt) { if (this.lblEstado) this.lblEstado.textContent = txt }

  armarPanel () {
    const tabs = [['tomas', 'Tomas'], ['texto', 'Texto'], ['publicar', 'Publicar']]
    const cab = h('div', { class: 'pestanas' }, tabs.map(([k, n]) => h('button', { class: this.pestana === k ? 'on' : '', onclick: () => { this.pestana = k; this.armarPanel() } }, n)))
    const cuerpo = h('div', { class: 'cuerpo' })
    if (this.pestana === 'tomas') this.panelTomas(cuerpo)
    else if (this.pestana === 'texto') this.panelTexto(cuerpo)
    else this.panelPublicar(cuerpo)
    this.panel.replaceChildren(cab, cuerpo)
  }

  panelTomas (c) {
    const ts = this.l.tomas
    this.sel.toma = clamp(this.sel.toma, 0, ts.length - 1)
    const t = ts[this.sel.toma]
    c.append(h('p', { class: 'ayuda' }, 'Divide el clip en tomas (', h('kbd', {}, 'S'), ' en el cursor) y elige cómo se ve cada una.'))
    c.append(h('div', { class: 'lista-tomas' }, ts.map((tm, i) => h('button', {
      class: i === this.sel.toma ? 'on' : '',
      onclick: () => { this.sel.toma = i; this.seek(tm.desde + 0.02); this.armarPanel() }
    }, h('i', { style: { '--c': COLOR[tm.modo || 'auto'] } }), `${i + 1}. ${NOMBRE[tm.modo || 'auto']}`, h('small', {}, `${fmt(tm.desde - this.l.inicio)}–${fmt(tm.hasta - this.l.inicio)}`)))))
    const caja = h('div', { class: 'caja-toma' })
    caja.append(h('div', { class: 'seg' }, MODOS.map(([k, n, col, ayuda]) => h('button', {
      class: (t.modo || 'auto') === k ? 'on' : '', style: { '--c': COLOR[k] }, title: ayuda,
      onclick: () => this.cambiarModo(k)
    }, n))))
    const modo = t.modo || 'auto'
    caja.append(h('p', { class: 'ayuda' }, MODOS.find(m => m[0] === modo)[3]))
    if (modo === 'recorte') {
      caja.append(h('div', { class: 'campo' }, h('span', {}, 'Zoom'), h('div', { class: 'seg' }, [1, 1.15, 1.3, 1.5].map(z => h('button', {
        class: Math.abs((t.zoom || 1) - z) < 0.01 ? 'on' : '', style: { '--c': COLOR.recorte },
        onclick: () => this.cambio(() => { t.zoom = z }, true)
      }, z === 1 ? 'Normal' : `${z}×`)))))
      caja.append(h('div', { class: 'fila' },
        h('button', { class: 'btn chico', onclick: () => this.centrarCara() }, '🎯 Centrar en la cara'),
        h('label', { class: 'check', title: 'Al entrar a esta toma la cámara se desliza en vez de cortar' },
          h('input', { type: 'checkbox', checked: t.transicion === 'suave', onchange: e => this.cambio(() => { t.transicion = e.target.checked ? 'suave' : 'corte' }) }), 'Entrada suave')))
    } else if (modo === 'split') {
      caja.append(h('div', { class: 'fila' }, h('button', { class: 'btn chico', onclick: () => this.centrarCara(true) }, '🎯 Buscar las 2 caras'),
        h('span', { class: 'ayuda' }, 'Arrastra el cuadro A (arriba) y el B (abajo).')))
    } else if (modo === 'grafico') {
      const inp = h('input', { type: 'file', accept: 'image/*,video/*', style: { display: 'none' }, onchange: e => this.subirGrafico(e.target.files[0]) })
      caja.append(h('div', { class: 'fila' }, h('button', { class: 'btn chico', onclick: () => inp.click() }, t.grafico ? 'Cambiar archivo' : 'Elegir foto o video'), inp,
        h('span', { class: 'ayuda' }, t.grafico ? t.grafico.split('/').pop() : 'Todavía no hay archivo')))
      if (t.grafico) {
        const url = `/media/${encodeURIComponent(this.carpeta)}/${t.grafico}`
        caja.append(/\.(mp4|mov|webm|m4v)$/i.test(t.grafico) ? h('video', { class: 'grafico-prev', src: url, muted: true, controls: true }) : h('img', { class: 'grafico-prev', src: url }))
      }
      caja.append(h('div', { class: 'campo' }, h('span', {}, 'Ajuste'), h('div', { class: 'seg' }, [['cubrir', 'Llenar la pantalla'], ['contener', 'Completo con fondo']].map(([k, n]) => h('button', {
        class: (t.ajuste || 'cubrir') === k ? 'on' : '', style: { '--c': COLOR.grafico }, onclick: () => this.cambio(() => { t.ajuste = k }, true)
      }, n)))))
    } else if (modo === 'auto') {
      const c2 = this.l.camara || {}
      caja.append(h('p', { class: 'ayuda' }, c2.modo === 'seguir' ? 'Sigue la cara de quien habla.' : c2.modo === 'ajustar' ? 'No hay caras claras: va el video completo.' : ''))
      caja.append(h('button', { class: 'btn chico', onclick: () => this.recalcularSeguimiento(true) }, '↻ Recalcular seguimiento'))
    }
    caja.append(h('div', { class: 'fila' },
      h('button', { class: 'btn chico', onclick: () => this.dividir() }, '✂ Dividir en el cursor'),
      this.sel.toma > 0 ? h('button', { class: 'btn chico', onclick: () => this.unir() }, 'Unir con la anterior') : null))
    c.append(caja)
    c.append(h('p', { class: 'ayuda' }, 'Atajos: ', h('kbd', {}, 'espacio'), ' play · ', h('kbd', {}, 'I'), '/', h('kbd', {}, 'O'), ' inicio/fin · ',
      h('kbd', {}, '←'), h('kbd', {}, '→'), ' 1 s · ', h('kbd', {}, 'Supr'), ' cortar palabra · ', h('kbd', {}, 'Ctrl+Z'), ' deshacer'))
  }

  panelTexto (c) {
    const op = this.opciones || this.r.opciones || {}
    const hk = this.l.hook
    const sub = this.l.subtitulos
    const sel = (valor, ops, al) => h('select', { onchange: e => al(e.target.value) }, ops.map(([k, n]) => h('option', { value: k, selected: String(valor) === String(k) }, n)))
    c.append(h('div', { class: 'campo' }, h('span', {}, 'Título (hook)'),
      h('input', { type: 'text', value: hk.texto || '', maxlength: 90, oninput: e => this.cambio(() => { hk.texto = e.target.value }, false, 'hook') }),
      h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: hk.activo !== false, onchange: e => this.cambio(() => { hk.activo = e.target.checked }) }), 'Mostrar el título')))
    c.append(h('div', { class: 'fila' },
      h('div', { class: 'campo' }, h('span', {}, 'Dónde va'), sel(hk.posicion || op.hook_posicion, [['arriba', 'Arriba'], ['medio', 'En medio'], ['encima_subtitulos', 'Encima de los subtítulos']], v => this.cambio(() => { hk.posicion = v }))),
      h('div', { class: 'campo' }, h('span', {}, 'Cuánto dura'), sel(hk.segundos ?? op.hook_segundos, [[3, '3 segundos'], [5, '5 segundos'], [0, 'Todo el clip']], v => this.cambio(() => { hk.segundos = Number(v) }))),
      h('div', { class: 'campo' }, h('span', {}, 'Tamaño'), sel(hk.tam || op.tam_hook, [['pequeno', 'Pequeño'], ['normal', 'Normal'], ['grande', 'Grande'], ['gigante', 'Gigante']], v => this.cambio(() => { hk.tam = v })))))
    c.append(h('div', { class: 'fila' },
      h('div', { class: 'campo' }, h('span', {}, 'Subtítulos'), sel(sub.estilo || op.estilo, [['opus', 'Opus'], ['yulian', 'Yulian'], ['simple', 'Simple'], ['ninguno', 'Ninguno']], v => this.cambio(() => { sub.estilo = v }))),
      h('div', { class: 'campo' }, h('span', {}, 'Tamaño de letra'), sel(sub.tam || op.tam_subtitulos, [['pequeno', 'Pequeño'], ['normal', 'Normal'], ['grande', 'Grande'], ['gigante', 'Gigante']], v => this.cambio(() => { sub.tam = v })))))
    c.append(h('div', { class: 'fila' },
      h('div', { class: 'campo' }, h('span', {}, 'Recortar silencios'), sel(this.l.silencios || op.silencios, [['no', 'No'], ['suave', 'Suave'], ['normal', 'Normal'], ['agresivo', 'Agresivo']], v => this.cambio(() => { this.l.silencios = v }))),
      h('div', { class: 'campo' }, h('span', {}, 'Cliente'), sel(this.cliente, [['', '(ninguno)'], ...this.r.clientes.map(x => [x, x])], async v => {
        this.cambio(() => { this.cliente = v; this.l.cliente = v })
        await this.cargarCapas(); this.dibujar()
      }))))
    c.append(h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: this.l.zoom_en_cortes !== false, onchange: e => this.cambio(() => { this.l.zoom_en_cortes = e.target.checked }) }), 'Zoom leve en cada corte de silencio'))
    c.append(h('p', { class: 'ayuda' }, 'Las palabras se corrigen abajo: clic para elegir una, doble clic para escribir. ', h('kbd', {}, 'K'), ' la pinta en rojo, ', h('kbd', {}, 'Supr'), ' la corta del video, ', h('kbd', {}, 'H'), ' la oculta solo del subtítulo.'))
  }

  panelPublicar (c) {
    const meta = this.l.meta = this.l.meta || {}
    c.append(h('div', { class: 'campo' }, h('span', {}, 'Nombre del clip'), h('input', { type: 'text', value: meta.titulo || '', oninput: e => this.cambio(() => { meta.titulo = e.target.value }, false, 'meta') })))
    c.append(h('div', { class: 'campo' }, h('span', {}, 'Texto para publicar'), h('textarea', { rows: 5, oninput: e => this.cambio(() => { meta.caption_post = e.target.value }, false, 'meta') }, meta.caption_post || '')))
    c.append(h('div', { class: 'campo' }, h('span', {}, 'Hashtags (separados por espacio)'), h('input', {
      type: 'text', value: (meta.hashtags || []).map(x => '#' + String(x).replace(/^#/, '')).join(' '),
      oninput: e => this.cambio(() => { meta.hashtags = e.target.value.split(/\s+/).map(x => x.replace(/^#/, '')).filter(Boolean) }, false, 'meta')
    })))
    if (meta.razon) c.append(h('p', { class: 'ayuda' }, 'Por qué funciona: ', meta.razon))
    c.append(h('button', { class: 'btn', onclick: () => { navigator.clipboard.writeText(`${meta.caption_post || ''} ${(meta.hashtags || []).map(x => '#' + x).join(' ')}`.trim()); aviso('Copiado', 'ok', 1500) } }, 'Copiar texto y hashtags'))
  }

  // ------------------------------------------------ palabras
  armarPalabras () {
    const ini = this.l.inicio; const fin = this.l.fin
    const claves = new Set(this.l.subtitulos.palabras_clave.map(norm))
    const cortes = this.l.cortes || []
    const reac = this.r.reacciones || []
    let ri = 0
    const nodos = []
    this.pal.forEach((w, i) => {
      while (ri < reac.length && reac[ri][0] < w.i) { if (reac[ri][1] > this.ventana[0]) nodos.push(h('span', { class: 'risa', title: 'Risas / aplausos' }, `😂 ${(reac[ri][1] - reac[ri][0]).toFixed(1)}s`)); ri++ }
      const dentro = w.i >= ini - 0.05 && w.i < fin - 0.08
      const cortada = dentro && cortes.some(([a, b]) => (w.i + w.f) / 2 > a && (w.i + w.f) / 2 < b)
      const enSilencio = dentro && !cortada && this.tramos.length && !this.tramos.some(([a, b]) => (w.i + w.f) / 2 >= a - 0.02 && (w.i + w.f) / 2 <= b + 0.02)
      const cls = ['w', dentro ? '' : 'fuera', claves.has(norm(w.t)) ? 'clave' : '', cortada ? 'cortada' : '', enSilencio ? 'silencio' : '', w.oculta ? 'oculta' : '', i === this.sel.palabra ? 'sel' : ''].filter(Boolean).join(' ')
      nodos.push(h('span', { class: cls, 'data-i': i, title: `${fmt(w.i)}` }, w.t), ' ')
    })
    this.cajaPal.replaceChildren(...nodos)
    this.marcarBordes()
    this.cajaPal.onclick = e => {
      const s = e.target.closest('.w'); if (!s) return
      const i = Number(s.dataset.i); this.elegirPalabra(i); this.seek(this.pal[i].i)
    }
    this.cajaPal.ondblclick = e => { const s = e.target.closest('.w'); if (s) this.editarPalabra(Number(s.dataset.i)) }
    this.armarBarraPal()
  }

  marcarBordes () {
    $$('.w', this.cajaPal).forEach(s => s.classList.remove('borde-i', 'borde-f'))
    const dentro = this.pal.map((w, i) => [w, i]).filter(([w]) => w.i >= this.l.inicio - 0.05 && w.i < this.l.fin - 0.08)
    if (!dentro.length) return
    $(`.w[data-i="${dentro[0][1]}"]`, this.cajaPal)?.classList.add('borde-i')
    $(`.w[data-i="${dentro.at(-1)[1]}"]`, this.cajaPal)?.classList.add('borde-f')
  }

  elegirPalabra (i) {
    $(`.w.sel`, this.cajaPal)?.classList.remove('sel')
    this.sel.palabra = i
    $(`.w[data-i="${i}"]`, this.cajaPal)?.classList.add('sel')
    this.armarBarraPal()
  }

  armarBarraPal () {
    const i = this.sel.palabra; const w = this.pal[i]
    if (!w) { this.barraPal.replaceChildren(h('span', { class: 'ayuda' }, 'Clic en una palabra para elegirla y saltar a ese momento. Las grises están fuera del clip; las tachadas, cortadas.')); return }
    const dentro = w.i >= this.l.inicio - 0.05 && w.i < this.l.fin - 0.08
    const cortada = this.palabraCortada(w)
    const clave = this.l.subtitulos.palabras_clave.map(norm).includes(norm(w.t))
    this.barraPal.replaceChildren(h('span', { class: 'sel' }, `“${w.t}”`), h('span', { class: 'ayuda' }, fmt(w.i)),
      h('button', { class: 'btn chico', onclick: () => this.marcar('inicio', w.i - 0.03) }, '⇤ Empezar aquí'),
      h('button', { class: 'btn chico', onclick: () => this.marcar('fin', w.f + 0.08) }, 'Terminar aquí ⇥'),
      dentro ? h('button', { class: 'btn chico', onclick: () => this.editarPalabra(i) }, '✎ Corregir') : null,
      dentro ? h('button', { class: 'btn chico' + (clave ? ' on' : ''), onclick: () => this.alternarClave(i) }, clave ? '★ Quitar rojo' : '★ En rojo') : null,
      dentro ? h('button', { class: 'btn chico' + (cortada ? ' on' : ''), onclick: () => this.alternarCorte(i) }, cortada ? '↺ Restaurar' : '✂ Cortar del video') : null,
      dentro ? h('button', { class: 'btn chico' + (w.oculta ? ' on' : ''), onclick: () => this.alternarOculta(i) }, w.oculta ? '👁 Mostrar' : '🚫 Ocultar del subtítulo') : null)
  }

  editarPalabra (i) {
    const w = this.pal[i]; const s = $(`.w[data-i="${i}"]`, this.cajaPal); if (!w || !s) return
    const inp = h('input', { value: w.t })
    inp.style.width = Math.max(4, w.t.length + 2) + 'ch'
    s.replaceWith(inp); inp.focus(); inp.select()
    let hecho = false
    const fin = ok => {
      if (hecho) return; hecho = true
      const v = inp.value.trim()
      if (ok && v && v !== w.t) this.cambio(() => { w.t = v }, true)
      this.armarPalabras(); this.elegirPalabra(i)
    }
    inp.addEventListener('keydown', e => { e.stopPropagation(); if (e.key === 'Enter') fin(true); if (e.key === 'Escape') fin(false) })
    inp.addEventListener('blur', () => fin(true))
  }

  palabraCortada (w) { const m = (w.i + w.f) / 2; return (this.l.cortes || []).some(([a, b]) => m > a && m < b) }

  alternarCorte (i) {
    const w = this.pal[i]
    this.cambio(() => {
      const m = (w.i + w.f) / 2
      if (this.palabraCortada(w)) { this.l.cortes = this.l.cortes.filter(([a, b]) => !(m > a && m < b)); return }
      const prev = this.pal[i - 1]; const sig = this.pal[i + 1]
      const a = Math.max(prev ? prev.f : w.i - 0.08, w.i - 0.08)
      const b = Math.min(sig ? sig.i : w.f + 0.05, w.f + 0.05)
      this.l.cortes = [...(this.l.cortes || []), [Math.round(a * 1000) / 1000, Math.round(b * 1000) / 1000]]
    }, true)
  }

  alternarClave (i) {
    const n = norm(this.pal[i].t)
    this.cambio(() => {
      const sub = this.l.subtitulos
      sub.palabras_clave = sub.palabras_clave.map(norm).includes(n) ? sub.palabras_clave.filter(x => norm(x) !== n) : [...sub.palabras_clave, this.pal[i].t.replace(/[^\p{L}\p{N}_ ]/gu, '')]
    }, true)
  }

  alternarOculta (i) { this.cambio(() => { this.pal[i].oculta = !this.pal[i].oculta }, true) }

  // ------------------------------------------------ tomas
  tomasEfectivas () { return this.l.tomas.map(t => ({ ...t, modo: t.modo || 'auto' })) }

  ajustarTomas () {
    const ini = this.l.inicio; const fin = this.l.fin
    let ts = this.l.tomas.filter(t => t.hasta > ini + 0.05 && t.desde < fin - 0.05).map(t => ({ ...t, desde: Math.max(ini, t.desde), hasta: Math.min(fin, t.hasta) }))
    if (!ts.length) ts = [{ modo: 'auto', desde: ini, hasta: fin }]
    ts[0].desde = ini; ts[ts.length - 1].hasta = fin
    for (let i = 1; i < ts.length; i++) ts[i].desde = ts[i - 1].hasta
    this.l.tomas = ts
  }

  tomaEn (t) { const ts = this.l.tomas; for (let i = 0; i < ts.length; i++) if (t < ts[i].hasta) return i; return ts.length - 1 }

  dividir () {
    const t = this.t()
    const i = this.tomaEn(t); const tm = this.l.tomas[i]
    if (t <= tm.desde + 0.2 || t >= tm.hasta - 0.2) { aviso('Pon el cursor dentro de una toma (no tan pegado al borde) para dividirla.'); return }
    this.cambio(() => { this.l.tomas.splice(i, 1, { ...tm, hasta: t }, { ...tm, desde: t }); this.sel.toma = i + 1 })
    this.armarPanel()
  }

  unir () {
    const i = this.sel.toma; if (i <= 0) return
    this.cambio(() => { this.l.tomas[i - 1].hasta = this.l.tomas[i].hasta; this.l.tomas.splice(i, 1); this.sel.toma = i - 1 })
    this.armarPanel()
  }

  cambiarModo (modo) {
    const t = this.l.tomas[this.sel.toma]
    this.cambio(() => {
      t.modo = modo
      const g = this.geo()
      if (modo === 'recorte' && t.x == null) t.x = Math.round(this.xAuto(Math.max(t.desde, Math.min(t.hasta, this.t()))) ?? (this.fw - g.cw) / 2)
      if (modo === 'split') {
        if (t.x == null) t.x = Math.round(clamp(this.fw * 0.3 - g.ws / 2, 0, this.fw - g.ws))
        if (t.x2 == null) t.x2 = Math.round(clamp(this.fw * 0.7 - g.ws / 2, 0, this.fw - g.ws))
      }
    }, true)
    this.armarPanel()
    if (modo === 'split') this.centrarCara(true, true)
  }

  async centrarCara (dos = false, silencioso = false) {
    const t = this.l.tomas[this.sel.toma]; const g = this.geo()
    const tt = clamp(this.t(), t.desde, t.hasta - 0.05)
    try {
      this.estado('Buscando caras…')
      const r = await api(`/api/caras/${this.base}`, { method: 'POST', body: { t: tt } })
      this.estado('')
      const cs = [...r.caras].sort((a, b) => b.w - a.w)
      if (!cs.length) { if (!silencioso) aviso('No encontré caras en este momento. Mueve el cursor a donde se vean y prueba otra vez.'); return }
      if (dos) {
        if (cs.length < 2) { if (!silencioso) aviso('Solo encontré una cara aquí.'); return }
        const [a, b] = cs.slice(0, 2).sort((p, q) => p.cx - q.cx)
        this.cambio(() => { t.x = Math.round(clamp(a.cx - g.ws / 2, 0, this.fw - g.ws)); t.x2 = Math.round(clamp(b.cx - g.ws / 2, 0, this.fw - g.ws)) }, true)
      } else {
        const cx = this.xCentro(t, tt)
        const c = cs.reduce((m, c) => Math.abs(c.cx - cx) < Math.abs(m.cx - cx) ? c : m, cs[0])
        this.cambio(() => { t.x = Math.round(clamp(c.cx - g.cw / 2, 0, this.fw - g.cw)) }, true)
      }
    } catch (e) { this.estado(''); aviso('No pude buscar caras: ' + e.message, 'error') }
  }

  async subirGrafico (archivo) {
    if (!archivo) return
    const t = this.l.tomas[this.sel.toma]
    const fd = new FormData(); fd.append('archivo', archivo)
    try {
      this.estado('Subiendo…')
      const r = await api(`/api/subir/${encodeURIComponent(this.carpeta)}`, { method: 'POST', body: fd })
      this.estado('')
      this.cambio(() => { t.grafico = r.ruta; t.modo = 'grafico' }, true)
      this.armarPanel()
    } catch (e) { this.estado(''); aviso(e.message, 'error') }
  }

  async recalcularSeguimiento (avisar = false) {
    if (this._siguiendo) return
    this._siguiendo = true
    this.lblCam.textContent = 'Calculando el seguimiento…'
    try {
      const r = await api(`/api/seguimiento/${this.base}`, { method: 'POST', body: { inicio: this.l.inicio, fin: this.l.fin } })
      this.l.camara = { ...this.l.camara, ...r }
      this.rangoCam = [r.desde, r.hasta]
      if (avisar) aviso('Seguimiento actualizado', 'ok', 1500)
    } catch (e) { aviso('No pude calcular el seguimiento: ' + e.message, 'error') }
    this._siguiendo = false
    this.lblCam.textContent = ''
    this.dibujar()
  }

  // ------------------------------------------------ geometria
  geo () {
    const c = this.l.camara || {}
    let ch = this.fh; let cw = Math.round(this.fh * this.ow / this.oh / 2) * 2
    if (cw > this.fw) { cw = Math.floor(this.fw / 2) * 2; ch = Math.round(cw * this.oh / this.ow / 2) * 2 }
    if (c.modo === 'seguir' && c.cw) { cw = c.cw; ch = c.ch || ch }
    const hh = Math.floor(this.oh / 2)
    let hs = this.fh; let ws = Math.round(hs * this.ow / hh / 2) * 2
    if (ws > this.fw) { ws = Math.floor(this.fw / 2) * 2; hs = Math.round(ws * hh / this.ow / 2) * 2 }
    const vertical = Math.abs(this.fw / this.fh - this.ow / this.oh) < 0.04 || this.fw / this.fh < this.ow / this.oh
    return { cw, ch, ws, hs, hh, vertical }
  }

  xAuto (t) {
    const c = this.l.camara || {}; const kf = c.keyframes || []
    if (!kf.length) return null
    const tr = t - (c.desde ?? this.l.inicio)
    let x = kf[0][1]
    for (const [tt, xx] of kf) { if (tt <= tr + 1e-6) x = xx; else break }
    return x
  }

  modoEfectivo (tm) {
    const c = this.l.camara || {}
    const m = tm.modo || 'auto'
    if (this.geo().vertical && (m === 'auto' || m === 'recorte' || m === 'split')) return 'escalar'
    if (m === 'auto') return c.modo === 'ajustar' ? 'completo' : (c.modo === 'escalar' ? 'escalar' : 'recorte')
    if (m === 'grafico' && !tm.grafico) return this.modoEfectivo({ modo: 'auto' })
    return m
  }

  xCentro (tm, t) { const g = this.geo(); const x = this.xRecorte(tm, t); return x + g.cw / 2 }

  xRecorte (tm, t) {
    const g = this.geo()
    let x
    if ((tm.modo || 'auto') === 'recorte' && tm.x != null) x = tm.x
    else x = this.xAuto(t) ?? (this.fw - g.cw) / 2
    return clamp(x, 0, this.fw - g.cw)
  }

  // ------------------------------------------------ tiempo
  t () { return (this.video.currentTime || 0) + (this.proxy ? this.proxy.desde : this.ventana[0]) }
  seek (t) {
    t = clamp(t, this.ventana[0], this.ventana[1] - 0.05)
    if (this.proxy) this.video.currentTime = Math.max(0, t - this.proxy.desde)
    this.modoClip = t >= this.l.inicio - 0.01 && t < this.l.fin
    this.dibujar()
  }

  aSalida (t) { let acc = 0; for (const [a, b] of this.tramos) { if (t < a) return acc; if (t <= b) return acc + (t - a); acc += b - a } return acc }
  tramoEn (t) { return this.tramos.findIndex(([a, b]) => t >= a - 1e-4 && t < b) }

  alternar () { this.reproduciendo ? this.pausar() : this.reproducir() }
  reproducir () {
    const t = this.t()
    if (t >= this.l.fin - 0.05 || t < this.l.inicio - 0.01) { if (t >= this.l.fin - 0.05 || (t < this.l.inicio && this.modoClip)) this.seek(this.l.inicio) }
    this.modoClip = this.t() >= this.l.inicio - 0.01 && this.t() < this.l.fin
    this.video.play().catch(() => {})
    this.reproduciendo = true; this.btnPlay.textContent = '❚❚'
  }

  pausar () { this.video.pause(); this.reproduciendo = false; if (this.btnPlay) this.btnPlay.textContent = '▶'; this.dibujar() }

  bucle () {
    if (this._muerto) return
    if (this.reproduciendo) {
      const t = this.t()
      if (this.modoClip && this.tramos.length) {
        if (t >= this.l.fin - 0.02) { this.pausar(); this.seek(this.l.inicio) } else if (this.tramoEn(t) < 0 && t >= this.l.inicio) {
          const sig = this.tramos.find(([a]) => a > t)
          if (sig) this.video.currentTime = sig[0] - this.proxy.desde + 0.005
          else { this.pausar(); this.seek(this.l.inicio) }
        }
      }
      if (this.video.ended || t >= this.ventana[1] - 0.06) this.pausar()
      this.dibujar()
    }
    requestAnimationFrame(() => this.bucle())
  }

  // ------------------------------------------------ dibujo
  dibujar () {
    if (!this.cvOrig || this._muerto) return
    const t = this.t()
    this.dibujarOrig(t); this.dibujarVert(t); this.dibujarTl(t)
    const dentro = t >= this.l.inicio - 0.01 && t < this.l.fin
    this.tiempo.replaceChildren(h('b', {}, dentro ? fmt(this.aSalida(t)) : '—'), ` / ${fmt(this.durOut)}  ·  original ${fmt(t)}`)
    if (this.lblDur) this.lblDur.textContent = `clip ${fmt(this.l.inicio)} → ${fmt(this.l.fin)} · queda en ${fmt(this.durOut)} (sin silencios)`
    const cur = this.pal.findIndex(w => t >= w.i && t < w.f + 0.05)
    if (cur !== this._ahora) {
      $('.w.ahora', this.cajaPal)?.classList.remove('ahora')
      if (cur >= 0) {
        const s = $(`.w[data-i="${cur}"]`, this.cajaPal)
        if (s) { s.classList.add('ahora'); if (this.reproduciendo) s.scrollIntoView({ block: 'nearest' }) }
      }
      this._ahora = cur
    }
  }

  dibujarOrig (t) {
    const cv = this.cvOrig; const ctx = cv.getContext('2d'); const W = cv.width; const H = cv.height
    ctx.clearRect(0, 0, W, H)
    if (this.video.readyState >= 2) ctx.drawImage(this.video, 0, 0, W, H)
    const k = W / this.fw
    const dentro = t >= this.l.inicio - 0.01 && t < this.l.fin
    const tm = this.l.tomas[this.tomaEn(clamp(t, this.l.inicio, this.l.fin - 0.001))]
    const modo = this.modoEfectivo(tm); const g = this.geo()
    const rects = []
    if (modo === 'recorte') {
      const z = (tm.modo === 'recorte' && tm.zoom) || 1
      const x = this.xRecorte(tm, t); const cwz = g.cw / z; const chz = g.ch / z
      const xz = x + (g.cw - cwz) / 2; const yz = z > 1.01 ? (this.fh - chz) * 0.3 : (this.fh - g.ch) / 2
      rects.push({ x: xz, y: yz, w: cwz, h: chz, c: tm.modo === 'recorte' ? COLOR.recorte : COLOR.auto, etq: tm.modo === 'recorte' ? 'Recorte' : 'Auto' })
    } else if (modo === 'split') {
      rects.push({ x: tm.x, y: (this.fh - g.hs) / 2, w: g.ws, h: g.hs, c: COLOR.split, etq: 'A · arriba' }, { x: tm.x2, y: (this.fh - g.hs) / 2, w: g.ws, h: g.hs, c: '#e7a5ff', etq: 'B · abajo' })
    }
    if (rects.length) {
      ctx.save(); ctx.fillStyle = '#000a'
      ctx.beginPath(); ctx.rect(0, 0, W, H)
      if (modo === 'recorte') { const r = rects[0]; ctx.rect(r.x * k, r.y * k, r.w * k, r.h * k) }
      ctx.fill('evenodd'); ctx.restore()
      for (const r of rects) {
        ctx.lineWidth = 3 * (window.devicePixelRatio || 1); ctx.strokeStyle = r.c
        ctx.strokeRect(r.x * k, r.y * k, r.w * k, r.h * k)
        ctx.fillStyle = r.c; ctx.font = `600 ${12 * (window.devicePixelRatio || 1)}px system-ui`
        ctx.fillText(r.etq, r.x * k + 6, r.y * k + 16 * (window.devicePixelRatio || 1))
      }
      this._rects = rects.map(r => ({ ...r, k }))
    } else this._rects = []
    if (!dentro) { ctx.fillStyle = '#0008'; ctx.fillRect(0, 0, W, H); ctx.fillStyle = '#fff'; ctx.font = `600 ${15 * (window.devicePixelRatio || 1)}px system-ui`; ctx.fillText('Fuera del clip (contexto)', 14, 26 * (window.devicePixelRatio || 1)) }
    this.cvOrig.style.cursor = rects.length && dentro ? 'ew-resize' : 'default'
  }

  dibujarFuente (ctx, sx, sy, sw, sh, dx, dy, dw, dh) {
    const k = this.video.videoWidth / this.fw
    if (!k) return
    ctx.drawImage(this.video, sx * k, sy * k, sw * k, sh * k, dx, dy, dw, dh)
  }

  cubrir (ctx, src, sw, sh, W, H, y0 = 0, alto = H) {
    const e = Math.max(W / sw, alto / sh); const w = sw * e; const hh = sh * e
    ctx.drawImage(src, 0, 0, sw, sh, (W - w) / 2, y0 + (alto - hh) / 2, w, hh)
  }

  contener (ctx, src, sw, sh, W, H) {
    ctx.save(); ctx.filter = 'blur(14px) brightness(0.88)'; this.cubrir(ctx, src, sw, sh, W, H); ctx.restore()
    const e = Math.min(W / sw, H / sh); const w = sw * e; const hh = sh * e
    ctx.drawImage(src, 0, 0, sw, sh, (W - w) / 2, (H - hh) / 2, w, hh)
  }

  medio (ruta) {
    if (!ruta) return null
    if (this.medios[ruta]) return this.medios[ruta]
    const url = `/media/${encodeURIComponent(this.carpeta)}/${ruta}`
    let el
    if (/\.(mp4|mov|webm|m4v)$/i.test(ruta)) { el = h('video', { src: url, muted: true, preload: 'auto', playsinline: true, loop: true }); el.addEventListener('loadeddata', () => this.dibujar()) } else { el = new Image(); el.onload = () => this.dibujar(); el.src = url }
    this.medios[ruta] = el
    return el
  }

  dibujarVert (t) {
    const cv = this.cvVert; const ctx = cv.getContext('2d'); const W = cv.width; const H = cv.height
    ctx.fillStyle = '#000'; ctx.fillRect(0, 0, W, H)
    if (this.video.readyState < 2) return
    const tc = clamp(t, this.l.inicio, this.l.fin - 0.001)
    const tm = this.l.tomas[this.tomaEn(tc)]
    const modo = this.modoEfectivo(tm); const g = this.geo()
    const tOut = this.aSalida(t)
    const vw = this.video.videoWidth; const vh = this.video.videoHeight
    const iTramo = this.tramoEn(t)
    const saltoZoom = this.l.zoom_en_cortes !== false && this.tramos.length > 1 && iTramo % 2 === 1
    if (modo === 'recorte' || modo === 'escalar') {
      let sx, sy, sw, sh
      if (modo === 'escalar') {
        const e = Math.max(this.ow / this.fw, this.oh / this.fh); sw = this.ow / e; sh = this.oh / e; sx = (this.fw - sw) / 2; sy = (this.fh - sh) / 2
      } else {
        const z = (tm.modo === 'recorte' && tm.zoom) || 1
        const x = this.xRecorte(tm, t); sw = g.cw / z; sh = g.ch / z
        sx = x + (g.cw - sw) / 2; sy = z > 1.01 ? (this.fh - sh) * 0.3 : (this.fh - g.ch) / 2
        if (z > 1.01) sx = clamp(sx, 0, this.fw - sw)
      }
      if (saltoZoom && !(tm.modo === 'recorte' && (tm.zoom || 1) > 1.01)) {
        const z2 = 1.12; const nw = sw / z2; const nh = sh / z2
        sx += (sw - nw) / 2; sy += (sh - nh) * 0.3; sw = nw; sh = nh
      }
      this.dibujarFuente(ctx, sx, sy, sw, sh, 0, 0, W, H)
    } else if (modo === 'completo') {
      this.contener(ctx, this.video, vw, vh, W, H)
    } else if (modo === 'split') {
      const ys = (this.fh - g.hs) / 2; const hTop = Math.round(H * g.hh / this.oh)
      this.dibujarFuente(ctx, clamp(tm.x ?? 0, 0, this.fw - g.ws), ys, g.ws, g.hs, 0, 0, W, hTop)
      this.dibujarFuente(ctx, clamp(tm.x2 ?? 0, 0, this.fw - g.ws), ys, g.ws, g.hs, 0, hTop, W, H - hTop)
      ctx.fillStyle = '#000d'; ctx.fillRect(0, hTop - 3 * W / this.ow, W, 6 * W / this.ow)
    } else if (modo === 'grafico') {
      const el = this.medio(tm.grafico)
      const esVideo = el && el.tagName === 'VIDEO'
      const listo = el && (esVideo ? el.readyState >= 2 : el.complete && el.naturalWidth)
      if (listo) {
        const sw = esVideo ? el.videoWidth : el.naturalWidth; const sh = esVideo ? el.videoHeight : el.naturalHeight
        if (esVideo) {
          const rel = Math.max(0, tOut - this.aSalida(Math.max(tm.desde, this.l.inicio)))
          if (!this.reproduciendo || Math.abs(el.currentTime - (rel % (el.duration || 1e9))) > 0.4) el.currentTime = rel % (el.duration || 1e9)
          if (this.reproduciendo && el.paused) el.play().catch(() => {}); if (!this.reproduciendo && !el.paused) el.pause()
        }
        if ((tm.ajuste || 'cubrir') === 'contener') this.contener(ctx, el, sw, sh, W, H)
        else this.cubrir(ctx, el, sw, sh, W, H)
      }
    }
    for (const el of Object.values(this.medios)) if (el.tagName === 'VIDEO' && (modo !== 'grafico' || el !== this.medios[tm.grafico]) && !el.paused) el.pause()
    // logo y tarjeta de cierre, como en el render
    const sup = this.cvSup.getContext('2d'); sup.clearRect(0, 0, W, H)
    const c = this.capas
    const t0 = c.cierre ? (c.cierreModo === 'despues' ? this.durOut : Math.max(0, this.durOut - c.cierreSeg)) : Infinity
    if (c.logo && tOut < t0 + 0.3) ctx.drawImage(c.logo, 0, 0, W, H)
    if (c.cierre && tOut >= t0) { sup.globalAlpha = clamp((tOut - t0) / 0.35, 0, 1); sup.drawImage(c.cierre, 0, 0, W, H); sup.globalAlpha = 1 }
    const dentro = t >= this.l.inicio - 0.01 && t < this.l.fin
    this.avisoFuera.hidden = dentro
    this.cvSubs.style.visibility = dentro ? 'visible' : 'hidden'
    if (this.jassub && dentro && (this._tSub == null || Math.abs(this._tSub - tOut) > 0.001)) {
      this._tSub = tOut
      try { this.jassub.setCurrentTime(true, tOut) } catch {}
    }
  }

  xTl (t) { return (t - this.ventana[0]) / (this.ventana[1] - this.ventana[0]) * this.cvTl.width }
  tTl (x) { return this.ventana[0] + x / this.cvTl.width * (this.ventana[1] - this.ventana[0]) }

  dibujarTl (t) {
    const cv = this.cvTl; const ctx = cv.getContext('2d'); const W = cv.width; const H = cv.height
    const d = window.devicePixelRatio || 1
    ctx.clearRect(0, 0, W, H)
    const yT = 4 * d; const hT = 20 * d; const yO = 30 * d; const hO = 72 * d; const yR = 106 * d
    const xi = this.xTl(this.l.inicio); const xf = this.xTl(this.l.fin)
    // tomas
    this.l.tomas.forEach((tm, i) => {
      const a = this.xTl(tm.desde); const b = this.xTl(tm.hasta)
      ctx.fillStyle = COLOR[tm.modo || 'auto']; ctx.globalAlpha = i === this.sel.toma ? 1 : 0.6
      ctx.fillRect(a + 1, yT, Math.max(1, b - a - 2), hT); ctx.globalAlpha = 1
      if (i === this.sel.toma) { ctx.strokeStyle = '#fff'; ctx.lineWidth = 2 * d; ctx.strokeRect(a + 1, yT, Math.max(1, b - a - 2), hT) }
      if (b - a > 60 * d) { ctx.fillStyle = '#fff'; ctx.font = `600 ${11 * d}px system-ui`; ctx.fillText(`${i + 1}. ${NOMBRE[tm.modo || 'auto']}`, a + 6 * d, yT + 14 * d) }
    })
    // onda
    const n = this.onda?.length || 0
    ctx.fillStyle = '#16161a'; ctx.fillRect(0, yO, W, hO)
    ctx.fillStyle = '#ffffff0d'; ctx.fillRect(xi, yO, xf - xi, hO)
    if (n) {
      const paso = W / n
      for (let i = 0; i < n; i++) {
        const x = i * paso; const tt = this.tTl(x + paso / 2)
        const dentro = tt >= this.l.inicio && tt < this.l.fin
        const queda = dentro && this.tramoEn(tt) >= 0
        ctx.fillStyle = !dentro ? '#4a4a52' : queda ? '#d8d6d0' : '#6b2a2a'
        const v = this.onda[i] * hO * 0.48
        ctx.fillRect(x, yO + hO / 2 - v, Math.max(1, paso - 0.5), Math.max(1, v * 2))
      }
    }
    // cortes manuales
    for (const [a, b] of this.l.cortes || []) { ctx.fillStyle = '#e1060055'; ctx.fillRect(this.xTl(a), yO, Math.max(2, this.xTl(b) - this.xTl(a)), hO) }
    // risas
    for (const [a, b] of this.r.reacciones || []) { ctx.fillStyle = '#FFD60A'; ctx.fillRect(this.xTl(a), yO + hO - 4 * d, Math.max(2, this.xTl(b) - this.xTl(a)), 3 * d) }
    // fuera del clip
    ctx.fillStyle = '#0009'; ctx.fillRect(0, yT, xi, yO + hO - yT); ctx.fillRect(xf, yT, W - xf, yO + hO - yT)
    // bordes del clip
    for (const x of [xi, xf]) {
      ctx.fillStyle = '#E10600'; ctx.fillRect(x - 2 * d, yT, 4 * d, yO + hO - yT)
      ctx.fillRect(x - 6 * d, yO + hO / 2 - 12 * d, 12 * d, 24 * d)
    }
    // regla
    ctx.fillStyle = '#8b8a93'; ctx.font = `${10.5 * d}px system-ui`
    const dur = this.ventana[1] - this.ventana[0]; const cada = dur > 240 ? 30 : dur > 120 ? 10 : 5
    for (let s = Math.ceil(this.ventana[0] / cada) * cada; s < this.ventana[1]; s += cada) {
      const x = this.xTl(s); ctx.fillRect(x, yR, 1, 5 * d); ctx.fillText(fmt(s, 0), x + 3 * d, yR + 15 * d)
    }
    // cursor
    const xc = this.xTl(t); ctx.fillStyle = '#fff'; ctx.fillRect(xc - d, 0, 2 * d, yO + hO + 4 * d)
  }

  // ------------------------------------------------ raton
  eventosOrig () {
    let arrastre = null
    const pos = e => { const r = this.cvOrig.getBoundingClientRect(); return { x: (e.clientX - r.left) / r.width * this.fw, y: (e.clientY - r.top) / r.height * this.fh } }
    this.cvOrig.addEventListener('pointerdown', e => {
      const t = this.t(); if (t < this.l.inicio - 0.01 || t >= this.l.fin) return
      const i = this.tomaEn(t); const tm = this.l.tomas[i]; const modo = this.modoEfectivo(tm)
      if (modo !== 'recorte' && modo !== 'split') return
      const p = pos(e); const g = this.geo()
      if (this.sel.toma !== i) { this.sel.toma = i; this.armarPanel() }
      let cual = 'x'
      if (modo === 'split') cual = Math.abs(p.x - (tm.x + g.ws / 2)) <= Math.abs(p.x - (tm.x2 + g.ws / 2)) ? 'x' : 'x2'
      this.guardarDeshacer()
      if (modo === 'recorte' && (tm.modo || 'auto') === 'auto') { tm.modo = 'recorte'; tm.x = Math.round(this.xRecorte(tm, t)); this.armarPanel() }
      const ancho = modo === 'split' ? g.ws : g.cw
      arrastre = { tm, cual, dx: p.x - ((tm[cual] ?? 0) + ancho / 2), ancho }
      this.cvOrig.setPointerCapture(e.pointerId)
    })
    this.cvOrig.addEventListener('pointermove', e => {
      if (!arrastre) return
      const p = pos(e)
      arrastre.tm[arrastre.cual] = Math.round(clamp(p.x - arrastre.dx - arrastre.ancho / 2, 0, this.fw - arrastre.ancho))
      this.dibujar()
    })
    this.cvOrig.addEventListener('pointerup', () => { if (arrastre) { arrastre = null; this.marcarSucio(); this.programarPrevia() } })
  }

  eventosTl () {
    let arr = null
    const x = e => { const r = this.cvTl.getBoundingClientRect(); return (e.clientX - r.left) / r.width * this.cvTl.width }
    const d = () => window.devicePixelRatio || 1
    this.cvTl.addEventListener('pointerdown', e => {
      const px = x(e); const t = this.tTl(px); const y = (e.clientY - this.cvTl.getBoundingClientRect().top) * d()
      const cerca = 8 * d()
      if (Math.abs(px - this.xTl(this.l.inicio)) < cerca) arr = { que: 'inicio' }
      else if (Math.abs(px - this.xTl(this.l.fin)) < cerca) arr = { que: 'fin' }
      else if (y < 26 * d()) {
        const j = this.l.tomas.findIndex((tm, k) => k > 0 && Math.abs(px - this.xTl(tm.desde)) < cerca)
        if (j > 0) arr = { que: 'borde', j }
        else if (t >= this.l.inicio && t < this.l.fin) { this.sel.toma = this.tomaEn(t); this.armarPanel(); this.seek(t); return }
      }
      if (arr) { this.guardarDeshacer(); this.cvTl.setPointerCapture(e.pointerId); return }
      this.pausar(); this.seek(t)
      arr = { que: 'cursor' }; this.cvTl.setPointerCapture(e.pointerId)
    })
    this.cvTl.addEventListener('pointermove', e => {
      const px = x(e); const t = this.tTl(px)
      if (!arr) {
        const cerca = 8 * d()
        const borde = Math.abs(px - this.xTl(this.l.inicio)) < cerca || Math.abs(px - this.xTl(this.l.fin)) < cerca
        this.cvTl.style.cursor = borde ? 'col-resize' : 'pointer'
        return
      }
      if (arr.que === 'cursor') { this.seek(t); return }
      if (arr.que === 'borde') {
        const ts = this.l.tomas; const j = arr.j
        const v = clamp(t, ts[j - 1].desde + 0.2, ts[j].hasta - 0.2)
        ts[j - 1].hasta = v; ts[j].desde = v; this.dibujar(); return
      }
      const v = e.shiftKey ? t : this.pegar(t, arr.que)
      if (arr.que === 'inicio') this.l.inicio = clamp(v, this.ventana[0], this.l.fin - 1)
      else this.l.fin = clamp(v, this.l.inicio + 1, this.ventana[1])
      this.ajustarTomas()
      this.seek(arr.que === 'inicio' ? this.l.inicio : this.l.fin - 0.3)
    })
    this.cvTl.addEventListener('pointerup', () => {
      if (!arr) return
      const que = arr.que; arr = null
      if (que === 'inicio' || que === 'fin' || que === 'borde') this.trasCambiarRango(que !== 'borde')
    })
  }

  pegar (t, que) {
    let mejor = t; let dist = 0.35
    for (const w of this.pal) {
      const v = que === 'inicio' ? w.i - 0.03 : w.f + 0.08
      if (Math.abs(v - t) < dist) { dist = Math.abs(v - t); mejor = v }
    }
    return Math.round(mejor * 1000) / 1000
  }

  marcar (que, t) {
    t = Math.round(t * 1000) / 1000
    if (que === 'inicio' && t >= this.l.fin - 1) { aviso('El inicio tiene que quedar antes del fin.'); return }
    if (que === 'fin' && t <= this.l.inicio + 1) { aviso('El fin tiene que quedar después del inicio.'); return }
    this.guardarDeshacer()
    this.l[que] = clamp(t, this.ventana[0], this.ventana[1])
    this.ajustarTomas()
    this.trasCambiarRango(true)
  }

  trasCambiarRango (rango) {
    this.marcarSucio(); this.programarPrevia(); this.armarPalabras(); this.armarPanel()
    if (!rango) return
    const [desde, hasta] = this.rangoCam
    if (this.l.tomas.some(t => (t.modo || 'auto') === 'auto') && (this.l.inicio < desde - 0.5 || this.l.fin > hasta + 0.5)) this.recalcularSeguimiento()
    if (this.l.inicio < this.ventana[0] + 3 || this.l.fin > this.ventana[1] - 3) this.ampliarVentana()
  }

  async ampliarVentana () {
    if (this._ampliando) return
    this._ampliando = true
    const nueva = [Math.max(0, this.l.inicio - 30), Math.min(this.r.duracion_fuente, this.l.fin + 30)]
    if (nueva[0] >= this.ventana[0] - 1 && nueva[1] <= this.ventana[1] + 1) { this._ampliando = false; return }
    this.estado('Ampliando el contexto…')
    try {
      const t = this.t()
      const px = await api(`/api/proxy/${this.base}`, { method: 'POST', body: { desde: nueva[0], hasta: nueva[1] } })
      const r = await api(`/api/clip/${this.base}?desde=${px.desde}&hasta=${px.hasta}`)
      this.ventana = [px.desde, px.hasta]
      const editadas = new Map(this.pal.map(w => [w.i.toFixed(3), w]))
      this.pal = r.palabras.filter(w => w.i >= px.desde && w.i <= px.hasta).map(w => editadas.get(w.i.toFixed(3)) || w)
      for (const w of editadas.values()) if (!this.pal.includes(w)) this.pal.push(w)
      this.pal.sort((a, b) => a.i - b.i)
      this.proxy = px; this.video.src = px.url
      await new Promise(res => this.video.addEventListener('loadeddata', res, { once: true }))
      this.seek(t)
      await this.cargarOnda()
      this.armarPalabras()
    } catch (e) { aviso('No pude ampliar el contexto: ' + e.message, 'error') }
    this.estado(''); this._ampliando = false; this.dibujar()
  }

  // ------------------------------------------------ cambios, previa y guardado
  instantanea () {
    return JSON.stringify({ l: { inicio: this.l.inicio, fin: this.l.fin, cortes: this.l.cortes, tomas: this.l.tomas, hook: this.l.hook, meta: this.l.meta, silencios: this.l.silencios, zoom_en_cortes: this.l.zoom_en_cortes, cliente: this.l.cliente, subtitulos: { ...this.l.subtitulos, palabras: undefined } }, pal: this.pal.map(w => [w.t, w.oculta || false]), cliente: this.cliente })
  }

  restaurar (s) {
    const o = JSON.parse(s)
    Object.assign(this.l, o.l, { subtitulos: { ...this.l.subtitulos, ...o.l.subtitulos } })
    o.pal.forEach(([t, oc], i) => { if (this.pal[i]) { this.pal[i].t = t; this.pal[i].oculta = oc } })
    this.cliente = o.cliente
  }

  guardarDeshacer (tipo) {
    if (tipo && this._ultimoTipo === tipo && Date.now() - this._ultimoT < 1500) { this._ultimoT = Date.now(); return }
    this._ultimoTipo = tipo; this._ultimoT = Date.now()
    this.deshacer.push(this.instantanea()); if (this.deshacer.length > 80) this.deshacer.shift()
    this.rehacer = []
  }

  deshacerUno () {
    const s = this.deshacer.pop(); if (!s) { aviso('No hay nada que deshacer.'); return }
    this.rehacer.push(this.instantanea()); this.restaurar(s)
    this.ajustarTomas(); this.marcarSucio(); this.programarPrevia(); this.armarPalabras(); this.armarPanel(); this.cargarCapas().then(() => this.dibujar())
  }

  cambio (fn, repintar = false, tipo) {
    this.guardarDeshacer(tipo)
    fn()
    this.marcarSucio(); this.programarPrevia()
    if (repintar) { this.armarPalabras(); if (this.pestana === 'tomas') this.armarPanel() }
    this.dibujar()
  }

  marcarSucio () {
    this.sucio = true; this.estado('Cambios sin guardar')
    clearTimeout(this.pendiente.guardar)
    this.pendiente.guardar = setTimeout(() => this.guardar(), 2000)
  }

  programarPrevia () { clearTimeout(this.pendiente.previa); this.pendiente.previa = setTimeout(() => this.previa(), 220) }

  cambios () {
    const ini = this.l.inicio; const fin = this.l.fin
    return {
      inicio: ini, fin, cortes: this.l.cortes || [], tomas: this.l.tomas.map(t => { const o = { ...t }; for (const k of Object.keys(o)) if (k.startsWith('_')) delete o[k]; return o }),
      silencios: this.l.silencios, zoom_en_cortes: this.l.zoom_en_cortes !== false, cliente: this.cliente,
      subtitulos: { estilo: this.l.subtitulos.estilo, tam: this.l.subtitulos.tam, palabras_clave: this.l.subtitulos.palabras_clave, palabras: this.pal.filter(w => w.i >= ini - 0.05 && w.i < fin - 0.08).map(w => ({ t: w.t, i: w.i, f: w.f, ...(w.oculta ? { oculta: true } : {}) })) },
      hook: this.l.hook, meta: this.l.meta, camara: this.l.camara
    }
  }

  async previa (primera = false) {
    const pedido = (this._pedido = (this._pedido || 0) + 1)
    try {
      const r = await api(`/api/previa/${this.base}`, { method: 'POST', body: this.cambios() })
      if (pedido !== this._pedido) return
      this.tramos = r.tramos; this.durOut = r.duracion; this.ass = r.ass; this.opciones = r.opciones
      if (this.jassub) { try { this.jassub.setTrack(r.ass); this._tSub = null } catch (e) { console.error(e) } }
      if (!primera) this.armarPalabras(); else this.armarPalabras()
      this.dibujar()
    } catch (e) { aviso('No pude actualizar la vista previa: ' + e.message, 'error') }
  }

  async guardar (avisar = false) {
    clearTimeout(this.pendiente.guardar)
    if (this.guardando) await this.guardando
    if (!this.sucio && !avisar) return
    const p = (async () => {
      try {
        this.estado('Guardando…')
        await api(`/api/clip/${this.base}`, { method: 'PUT', body: this.cambios() })
        this.sucio = false; this.estado('Guardado ✓')
        if (avisar) aviso('Guardado', 'ok', 1500)
      } catch (e) { this.estado('No se pudo guardar'); aviso('No pude guardar: ' + e.message, 'error') }
    })()
    this.guardando = p; await p; this.guardando = null
  }

  async render () {
    this.pausar()
    $$('#modal video').forEach(v => { v.pause(); v.removeAttribute('src'); v.load() })
    this.sucio = true
    await this.guardar()
    this.btnRender.disabled = true
    const log = h('pre', { class: 'render-log' }, 'Empezando…')
    const est = h('b', {}, 'Renderizando el clip…')
    const cerrar = modal(h('div', { style: { minWidth: '420px' } }, est, log))
    try {
      const { job } = await api(`/api/render/${this.base}`, { method: 'POST', body: { exportar: this.chkExport.checked } })
      while (true) {
        await new Promise(r => setTimeout(r, 900))
        const t = await api(`/api/trabajo/${job}`)
        log.textContent = (t.log || []).slice(-8).join('\n') || t.estado
        if (t.estado === 'en cola') est.textContent = 'Esperando a que termine otro render…'
        if (t.estado === 'listo') {
          $('.contenido', $('#modal')).replaceChildren(h('div', { style: { display: 'grid', gap: '10px', justifyItems: 'center' } },
            h('b', {}, `Listo en ${t.segundos} s · ${fmt(t.duracion)}`),
            h('video', { src: t.video, controls: true, autoplay: true }),
            h('div', { class: 'fila' }, h('button', { class: 'btn', onclick: () => api(`/api/abrir/${encodeURIComponent(this.carpeta)}`, { method: 'POST', body: { que: 'clips' } }) }, 'Abrir carpeta de clips'),
              h('a', { class: 'btn', href: t.video, download: '' }, 'Descargar'),
              h('button', { class: 'btn pri', onclick: () => cerrar() }, 'Seguir editando'))))
          break
        }
        if (t.estado === 'error') { est.textContent = 'No se pudo renderizar'; est.style.color = '#ff6b6b'; break }
      }
    } catch (e) { est.textContent = 'No se pudo renderizar: ' + e.message }
    this.btnRender.disabled = false
  }

  tecla (e) {
    if (e.target.closest('input, textarea, select')) return
    const k = e.key.toLowerCase()
    if ((e.ctrlKey || e.metaKey) && k === 'z') { e.preventDefault(); this.deshacerUno(); return }
    if ((e.ctrlKey || e.metaKey) && k === 's') { e.preventDefault(); this.guardar(true); return }
    if (e.ctrlKey || e.metaKey || e.altKey) return
    const i = this.sel.palabra
    const acciones = {
      ' ': () => this.alternar(),
      arrowleft: () => this.seek(this.t() - (e.shiftKey ? 5 : 1)),
      arrowright: () => this.seek(this.t() + (e.shiftKey ? 5 : 1)),
      i: () => this.marcar('inicio', this.t()),
      o: () => this.marcar('fin', this.t()),
      s: () => this.dividir(),
      escape: () => this.elegirPalabra(-1)
    }
    if (i >= 0) {
      Object.assign(acciones, {
        delete: () => this.alternarCorte(i),
        backspace: () => this.alternarCorte(i),
        k: () => this.alternarClave(i),
        h: () => this.alternarOculta(i),
        e: () => this.editarPalabra(i),
        enter: () => this.editarPalabra(i)
      })
    }
    if (acciones[k]) { e.preventDefault(); acciones[k]() }
  }

  async salir () {
    this._muerto = true
    this.pausar()
    document.removeEventListener('keydown', this._teclas)
    window.removeEventListener('resize', this._redim)
    window.onbeforeunload = null
    if (this.sucio) await this.guardar()
    try { this.jassub?.destroy() } catch {}
    for (const el of Object.values(this.medios)) if (el.tagName === 'VIDEO') el.pause()
    this.video?.removeAttribute('src'); this.video?.load?.()
    $('main').style.padding = ''
  }
}

ruta()
