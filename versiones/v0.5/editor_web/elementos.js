// MiOpusClip · zooms, imagenes encima y lower thirds (v0.5). Los tiempos van en segundos del original.
const clamp = (v, a, b) => Math.max(a, Math.min(b, v))
const COLORES = { zoom: '#3b82f6', imagen: '#e5484d', lowerthird: '#FFD60A' }
const NOMBRES = { zoom: 'Zoom', imagen: 'Imagen', lowerthird: 'Lower third' }
const nuevoId = () => 'e' + Math.random().toString(36).slice(2, 8)
const RAMPA = 0.35; const ENTRADA = 0.3

export function instalarElementos (Editor, { h, api, aviso, fmt }) {
  Object.assign(Editor.prototype, {
    elementos () { this.l.elementos = this.l.elementos || []; return this.l.elementos },
    elElegido () { return this.elementos().find(e => e.id === this.sel.elemento) || null },

    agregarElemento (tipo, datos = {}) {
      const t = clamp(this.t(), this.l.inicio, this.l.fin - 0.5)
      const dur = tipo === 'zoom' ? 2.5 : 4
      const el = { id: nuevoId(), tipo, desde: t, hasta: Math.min(this.l.fin, t + dur), ...datos }
      if (tipo === 'zoom') Object.assign(el, { factor: 1.3, x: 0.5, y: 0.35, entrada: 'suave', ...datos })
      if (tipo === 'imagen') Object.assign(el, { x: 0.5, y: 0.4, ancho: 0.6, opacidad: 1, entrada: 'fundido', ...datos })
      if (tipo === 'lowerthird') Object.assign(el, { nombre: '', cargo: '', estilo: 'barra', x: 0.06, y: 0.7, tam: 0.05, color: this.r.marca?.caja, entrada: 'deslizar', ...datos })
      this.guardarDeshacer(); this.elementos().push(el); this.sel.elemento = el.id
      this.marcarSucio(); this.armarPanel(); this.dibujar()
    },

    panelElementos (c) {
      const inp = h('input', { type: 'file', accept: 'image/*', style: { display: 'none' }, onchange: e => this.subirElemento(e.target.files[0]) })
      c.append(h('p', { class: 'ayuda' }, 'Se agregan donde está el cursor. Arrastra la barra arriba de la línea de tiempo para moverlos o alargarlos, y arrastra sobre el video para colocarlos.'))
      c.append(h('div', { class: 'fila' },
        h('button', { class: 'btn chico', onclick: () => this.agregarElemento('zoom') }, '+ Zoom'),
        h('button', { class: 'btn chico', onclick: () => inp.click() }, '+ Imagen'), inp,
        h('button', { class: 'btn chico', onclick: () => this.agregarElemento('lowerthird') }, '+ Lower third')))
      const fotos = [...(this.r.medios || []).map(i => ({ ...i, origen: 'proyecto' })), ...(this.r.marca?.imagenes || []).map(i => ({ ...i, origen: 'cliente' }))]
      if (fotos.length) {
        c.append(h('div', { class: 'imagenes-marca' }, fotos.map(i => h('button', { title: i.nombre, onclick: () => this.agregarElemento('imagen', { ruta: i.ruta, origen: i.origen }) }, h('img', { src: i.url, alt: i.nombre, loading: 'lazy' })))))
      }
      const lista = [...this.elementos()].sort((a, b) => a.desde - b.desde)
      if (!lista.length) c.append(h('p', { class: 'ayuda' }, 'Este clip todavía no tiene elementos.'))
      c.append(h('div', { class: 'lista-capas' }, lista.map(e => h('div', {
        class: e.id === this.sel.elemento ? 'on' : '',
        onclick: () => { this.sel.elemento = e.id; this.seek(e.desde + 0.05); this.armarPanel() }
      }, h('i', { style: { color: COLORES[e.tipo] } }, '■'),
      h('span', {}, e.tipo === 'lowerthird' ? (e.nombre || 'Lower third') : e.tipo === 'imagen' ? (e.ruta || '').split('/').pop() : `Zoom ${e.factor}×`),
      h('small', {}, fmt(e.desde - this.l.inicio, 0))))))
      const el = this.elElegido()
      if (el) c.append(this.controlesElemento(el))
    },

    controlesElemento (el) {
      const caja = h('div', { class: 'caja-toma' }, h('b', {}, NOMBRES[el.tipo]))
      const cambia = (fn, tipo) => { this.guardarDeshacer(tipo); fn(); this.marcarSucio(); this.dibujar() }
      const rango = (etq, k, a, b, paso, sufijo = '') => {
        const lbl = h('b', {}, `${el[k]}${sufijo}`)
        return h('label', { class: 'campo deslizador' }, h('span', {}, etq, lbl), h('input', { type: 'range', min: a, max: b, step: paso, value: el[k], oninput: e => { const v = Number(e.target.value); lbl.textContent = `${v}${sufijo}`; cambia(() => { el[k] = v }, 'el' + k) } }))
      }
      const seg = (etq, k, ops) => h('div', { class: 'campo' }, h('span', {}, etq), h('div', { class: 'seg' }, ops.map(([v, n]) => h('button', { class: el[k] === v ? 'on' : '', onclick: () => { cambia(() => { el[k] = v }); this.armarPanel() } }, n))))
      if (el.tipo === 'zoom') {
        caja.append(rango('Cuánto zoom', 'factor', 1.05, 2.5, 0.05, '×'), seg('Entrada', 'entrada', [['suave', 'Suave'], ['corte', 'De golpe']]))
        caja.append(h('p', { class: 'ayuda' }, 'Clic en el video para elegir hacia dónde acerca.'))
      } else if (el.tipo === 'imagen') {
        caja.append(rango('Tamaño', 'ancho', 0.1, 1.2, 0.01), rango('Opacidad', 'opacidad', 0.1, 1, 0.01), seg('Entrada', 'entrada', [['fundido', 'Fundido'], ['deslizar', 'Desliza'], ['corte', 'De golpe']]))
      } else {
        const personas = (this.r.marca?.imagenes || []).filter(i => i.tipo === 'persona')
        if (personas.length) caja.append(h('div', { class: 'sugeridos' }, personas.map(p => h('button', { onclick: () => { cambia(() => { el.nombre = p.nombre.replace(/\s*\(.*\)$/, '') }); this.armarPanel() } }, p.nombre))))
        const texto = (etq, k) => h('div', { class: 'campo' }, h('span', {}, etq), h('input', { type: 'text', value: el[k] || '', oninput: e => cambia(() => { el[k] = e.target.value }, 'el' + k) }))
        caja.append(texto('Nombre', 'nombre'), texto('Cargo o descripción', 'cargo'), seg('Estilo', 'estilo', [['barra', 'Barra'], ['caja', 'Cajas'], ['simple', 'Simple']]), rango('Tamaño', 'tam', 0.025, 0.09, 0.001))
        const inp = h('input', { type: 'color', value: /^#[0-9a-f]{6}$/i.test(el.color || '') ? el.color : '#e10600', oninput: e => cambia(() => { el.color = e.target.value }, 'elcolor') })
        caja.append(h('div', { class: 'campo' }, h('span', {}, 'Color'), h('div', { class: 'muestras' }, (this.r.marca?.colores || []).map(c => h('button', { class: (el.color || '').toLowerCase() === c.toLowerCase() ? 'on' : '', style: { background: c }, title: c, onclick: () => { cambia(() => { el.color = c }); this.armarPanel() } })), inp)))
        caja.append(seg('Entrada', 'entrada', [['deslizar', 'Desliza'], ['fundido', 'Fundido'], ['corte', 'De golpe']]))
      }
      caja.append(h('div', { class: 'fila' },
        h('button', { class: 'btn chico', onclick: () => { cambia(() => { el.desde = clamp(this.t(), this.l.inicio, el.hasta - 0.2) }); this.armarPanel() } }, '⇤ Empieza aquí'),
        h('button', { class: 'btn chico', onclick: () => { cambia(() => { el.hasta = clamp(this.t(), el.desde + 0.2, this.l.fin) }); this.armarPanel() } }, 'Termina aquí ⇥'),
        h('button', { class: 'btn chico', onclick: () => { cambia(() => { this.l.elementos = this.elementos().filter(e => e !== el) }); this.sel.elemento = null; this.armarPanel() } }, 'Borrar')))
      return caja
    },

    async subirElemento (archivo) {
      if (!archivo) return
      const fd = new FormData(); fd.append('archivo', archivo)
      try {
        const r = await api(`/api/subir/${encodeURIComponent(this.carpeta)}`, { method: 'POST', body: fd })
        if (r.tipo !== 'imagen') { aviso('Aquí solo sirven imágenes (png, jpg o webp).', 'error'); return }
        this.r.medios = [...(this.r.medios || []), { nombre: archivo.name, ruta: r.ruta, url: r.url }]
        this.agregarElemento('imagen', { ruta: r.ruta, origen: 'proyecto' })
      } catch (e) { aviso(e.message, 'error') }
    },

    // ------------------------------------------------ vista previa
    aplicarZoom (ctx, t, W, H) {
      const z = this.elementos().find(e => e.tipo === 'zoom' && t >= e.desde && t <= e.hasta)
      if (!z) return
      const a = this.aSalida(z.desde); const b = this.aSalida(z.hasta); const o = this.aSalida(t)
      let f = z.factor
      if (z.entrada !== 'corte') {
        const k = clamp(Math.min(o - a, b - o) / Math.min(RAMPA, (b - a) / 2 || 1), 0, 1)
        f = 1 + (z.factor - 1) * k * k * (3 - 2 * k)
      }
      if (f <= 1.001) return
      const sw = W / f; const sh = H / f
      ctx.drawImage(ctx.canvas, (W - sw) * z.x, (H - sh) * z.y, sw, sh, 0, 0, W, H)
    },

    imagenDe (el) {
      this._imgEl = this._imgEl || {}
      const clave = `${el.origen}:${el.ruta}`
      if (!this._imgEl[clave]) {
        const i = new Image(); i.onload = () => this.dibujar()
        i.src = el.origen === 'cliente' ? `/api/cliente_img/${encodeURIComponent(this.cliente)}/${el.ruta}` : `/media/${encodeURIComponent(this.carpeta)}/${el.ruta}`
        this._imgEl[clave] = i
      }
      return this._imgEl[clave]
    },

    placaDe (el) {
      this._placas = this._placas || {}
      const clave = JSON.stringify([el.nombre, el.cargo, el.estilo, el.tam, el.color, el.fuente, this.cliente, this.ow, this.oh])
      if (this._placas[clave] === undefined && (el.nombre || '').trim()) {
        this._placas[clave] = null
        api('/api/lowerthird', { method: 'POST', body: { el, cliente: this.cliente, ancho: this.ow, alto: this.oh } }).then(r => {
          const i = new Image(); i.onload = () => { this._placas[clave] = { i, ...r }; this.dibujar() }; i.src = r.png
        }).catch(() => {})
      }
      return this._placas[clave]
    },

    dibujarElementos (ctx, t, W, H) {
      const k = W / this.ow; const o = this.aSalida(t)
      this._cajasEl = []
      for (const el of this.elementos()) {
        if (el.tipo === 'zoom' || t < el.desde || t > el.hasta) continue
        const a = this.aSalida(el.desde); const b = this.aSalida(el.hasta)
        const d = Math.min(ENTRADA, (b - a) / 3) || 0.01
        const s = clamp(Math.min(o - a, b - o) / d, 0, 1)
        const entrada = el.entrada || (el.tipo === 'lowerthird' ? 'deslizar' : 'fundido')
        const alfa = entrada === 'corte' ? 1 : s
        const corre = entrada === 'deslizar' ? (1 - s) * (1 - s) * 0.18 * W : 0
        let caja = null
        ctx.save(); ctx.globalAlpha = alfa
        if (el.tipo === 'imagen') {
          const i = this.imagenDe(el)
          if (i.complete && i.naturalWidth) {
            const w = el.ancho * W; const hh = i.naturalHeight * w / i.naturalWidth
            const x = el.x * W - w / 2; const y = el.y * H - hh / 2
            ctx.globalAlpha = alfa * (el.opacidad ?? 1)
            ctx.drawImage(i, x - corre, y, w, hh); caja = { x, y, w, h: hh }
          }
        } else {
          const p = this.placaDe(el)
          if (p) {
            const w = p.w * k; const hh = p.h * k; const x = el.x * W - p.margen * k; const y = el.y * H - hh / 2
            ctx.drawImage(p.i, x - corre, y, w, hh); caja = { x, y, w, h: hh }
          }
        }
        ctx.restore()
        if (caja) this._cajasEl.push({ el, ...caja })
      }
    },

    marcarElegido (sup, W, H) {
      if (this.modo !== 'elementos') return
      const el = this.elElegido(); if (!el) return
      const d = window.devicePixelRatio || 1
      sup.strokeStyle = COLORES[el.tipo]; sup.lineWidth = 2 * d
      if (el.tipo === 'zoom') {
        const x = el.x * W; const y = el.y * H
        sup.beginPath(); sup.arc(x, y, 12 * d, 0, 6.3); sup.moveTo(x - 18 * d, y); sup.lineTo(x + 18 * d, y); sup.moveTo(x, y - 18 * d); sup.lineTo(x, y + 18 * d); sup.stroke()
      } else {
        const c = (this._cajasEl || []).find(q => q.el === el)
        if (c) sup.strokeRect(c.x, c.y, c.w, c.h)
      }
    },

    eventosElementos () {
      const pos = e => { const r = this.cajaVert.getBoundingClientRect(); return { x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height, r } }
      let arr = null
      this.cajaVert.addEventListener('pointerdown', e => {
        if (this.modo !== 'elementos') return
        const p = pos(e); const W = this.cvVert.width; const H = this.cvVert.height
        const toque = [...(this._cajasEl || [])].reverse().find(c => p.x * W >= c.x && p.x * W <= c.x + c.w && p.y * H >= c.y && p.y * H <= c.y + c.h)
        const elegido = this.elElegido()
        if (elegido?.tipo === 'zoom' && !toque) {
          this.guardarDeshacer(); elegido.x = clamp(p.x, 0, 1); elegido.y = clamp(p.y, 0, 1)
          arr = { el: elegido, dx: 0, dy: 0, zoom: true }
        } else if (toque) {
          if (this.sel.elemento !== toque.el.id) { this.sel.elemento = toque.el.id; this.armarPanel() }
          this.guardarDeshacer()
          arr = { el: toque.el, dx: p.x - toque.el.x, dy: p.y - toque.el.y }
        } else return
        this.cajaVert.setPointerCapture(e.pointerId); this.dibujar()
      })
      this.cajaVert.addEventListener('pointermove', e => {
        if (!arr) return
        const p = pos(e)
        arr.el.x = Math.round(clamp(p.x - arr.dx, arr.zoom ? 0 : -0.3, arr.zoom ? 1 : 1.3) * 1000) / 1000
        arr.el.y = Math.round(clamp(p.y - arr.dy, arr.zoom ? 0 : -0.2, arr.zoom ? 1 : 1.2) * 1000) / 1000
        this.dibujar()
      })
      this.cajaVert.addEventListener('pointerup', () => { if (arr) { arr = null; this.marcarSucio() } })
    },

    // ------------------------------------------------ linea de tiempo
    dibujarCarrilElementos (ctx, yT, hT, d) {
      for (const el of this.elementos()) {
        const a = this.xTl(el.desde); const b = this.xTl(el.hasta); const on = el.id === this.sel.elemento
        ctx.fillStyle = COLORES[el.tipo]; ctx.globalAlpha = on ? 1 : 0.65
        ctx.fillRect(a, yT, Math.max(3, b - a), hT); ctx.globalAlpha = 1
        if (on) { ctx.strokeStyle = '#fff'; ctx.lineWidth = 2 * d; ctx.strokeRect(a, yT, Math.max(3, b - a), hT) }
        if (b - a > 54 * d) { ctx.fillStyle = el.tipo === 'lowerthird' ? '#111' : '#fff'; ctx.font = `600 ${11 * d}px system-ui`; ctx.fillText(el.tipo === 'lowerthird' ? (el.nombre || NOMBRES[el.tipo]) : NOMBRES[el.tipo], a + 5 * d, yT + 14 * d) }
      }
    },

    tomarElementoTl (px, t, d) {
      const cerca = 7 * d
      const lista = [...this.elementos()].sort((a, b) => (a.id === this.sel.elemento) - (b.id === this.sel.elemento)).reverse()
      for (const el of lista) {
        const a = this.xTl(el.desde); const b = this.xTl(el.hasta)
        if (px >= a - cerca && px <= b + cerca) {
          const lado = Math.abs(px - a) < cerca ? 'desde' : Math.abs(px - b) < cerca ? 'hasta' : 'mover'
          if (this.sel.elemento !== el.id) { this.sel.elemento = el.id; this.armarPanel() }
          return { que: 'el', el, lado, t0: t, desde: el.desde, hasta: el.hasta }
        }
      }
      return null
    },

    moverElementoTl (arr, t) {
      const { el, lado } = arr; const ini = this.l.inicio; const fin = this.l.fin
      if (lado === 'desde') el.desde = clamp(t, ini, el.hasta - 0.2)
      else if (lado === 'hasta') el.hasta = clamp(t, el.desde + 0.2, fin)
      else { const dur = arr.hasta - arr.desde; el.desde = clamp(arr.desde + t - arr.t0, ini, fin - dur); el.hasta = el.desde + dur }
      this.dibujar()
    }
  })
}
