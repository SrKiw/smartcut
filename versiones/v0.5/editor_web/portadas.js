// MiOpusClip · portadas (v0.4). La imagen la dibuja el servidor con el mismo render de la exportacion:
// lo que ves es lo que sale. Aqui solo se editan los datos y se arrastran las capas.
const clamp = (v, a, b) => Math.max(a, Math.min(b, v))
const nuevoId = () => 'c' + Math.random().toString(36).slice(2, 8)

export function crearPortadas ({ $, $$, h, api, aviso, migas, modal, fmt, colorPts }) {
  const seguirTrabajo = async (job, alAvanzar) => {
    while (true) {
      await new Promise(r => setTimeout(r, 700))
      const t = await api(`/api/trabajo/${job}`)
      alAvanzar?.(t)
      if (t.estado === 'listo') return t
      if (t.estado === 'error') throw new Error(t.error || 'Falló')
    }
  }

  async function vistaPortadas (carpeta) {
    const url = encodeURIComponent(carpeta)
    const pr = await api(`/api/portadas/${url}`)
    migas(h('a', { href: '#/' }, 'Tus videos'), h('a', { href: `#/proyecto/${url}` }, pr.titulo), h('b', {}, 'Portadas'))
    const plantilla = h('select', {}, pr.plantillas.map(p => h('option', { value: p.id }, p.nombre)))
    const rehacer = h('input', { type: 'checkbox' })
    const generar = async () => {
      if (rehacer.checked && !confirm('Vas a rehacer TODAS las portadas y se pierde lo que editaste a mano. ¿Seguir?')) return
      const log = h('pre', { class: 'render-log' }, 'Empezando…')
      const est = h('b', {}, 'Generando las portadas…')
      const cerrar = modal(h('div', { style: { minWidth: '420px' } }, est, log))
      try {
        const { job } = await api(`/api/portadas/${url}/generar`, { method: 'POST', body: { plantilla: plantilla.value, rehacer: rehacer.checked } })
        await seguirTrabajo(job, t => { log.textContent = (t.log || []).slice(-8).join('\n') || t.estado })
        cerrar()
        aviso('Portadas listas', 'ok')
        await vistaPortadas(carpeta)
      } catch (e) { est.textContent = 'No se pudo: ' + e.message }
    }
    $('#acciones').replaceChildren(
      h('button', { class: 'btn', onclick: () => api(`/api/abrir/${url}`, { method: 'POST', body: { que: 'portadas' } }) }, 'Abrir carpeta'),
      h('label', { class: 'check', title: 'Vuelve a generar también las que ya editaste' }, rehacer, 'Rehacer todas'),
      plantilla, h('button', { class: 'btn pri', onclick: generar }, 'Generar portadas'))
    const faltan = pr.clips.filter(c => !c.imagen).length
    $('#vista').replaceChildren(h('h1', {}, 'Portadas'),
      h('p', { class: 'ayuda', style: { margin: '-8px 0 16px' } }, faltan
        ? `Faltan ${faltan} de ${pr.clips.length}. “Generar portadas” busca el mejor cuadro de cada clip, sin tocar las que ya editaste.`
        : 'Clic en una portada para editar el texto, el cuadro y los colores.'),
      h('div', { class: 'rejilla de-portadas' }, pr.clips.map(c => h('a', { class: 'tarjeta', href: `#/portada/${url}/${c.id}` },
        h('div', { class: 'mini', style: (c.imagen || c.miniatura) ? { backgroundImage: `url("${c.imagen || c.miniatura}")` } : null },
          h('span', { class: 'pts', style: { '--c': colorPts(c.puntuacion) } }, c.puntuacion || '–'),
          !c.imagen ? h('span', { class: 'ed gris' }, 'sin portada') : c.por_exportar ? h('span', { class: 'ed' }, 'sin exportar') : null),
        h('div', { class: 'info' }, h('b', {}, c.titulo))))))
  }

  class EditorPortada {
    constructor (carpeta, id) {
      this.carpeta = carpeta; this.id = id
      this.base = `${encodeURIComponent(carpeta)}/${id}`
      this.sel = null; this.pestana = 'texto'
      this.deshacer = []; this.rehacer = []
      this.sucio = false; this.enVuelo = false; this.otra = false
      this.cajas = []; this.fondoInfo = { vx: 1, vy: 1 }
      this.guias = true
      this._teclas = e => this.tecla(e)
      this._redim = () => this.medir()
    }

    async abrir () {
      $('#vista').replaceChildren(h('p', { class: 'cargando' }, 'Buscando los mejores cuadros del clip…'))
      const r = await api(`/api/portada/${this.base}`)
      this.r = r; this.d = r.diseno; this.marca = r.marca
      this.d.fondo = this.d.fondo || {}; this.d.capas = this.d.capas || []
      migas(h('a', { href: '#/' }, 'Tus videos'), h('a', { href: `#/proyecto/${encodeURIComponent(this.carpeta)}` }, r.titulo_proyecto),
        h('a', { href: `#/portadas/${encodeURIComponent(this.carpeta)}` }, 'Portadas'), h('b', {}, r.titulo))
      this.armar()
      document.addEventListener('keydown', this._teclas)
      window.addEventListener('resize', this._redim)
      window.onbeforeunload = () => (this.sucio ? 'Hay cambios sin guardar' : undefined)
      this.sel = (this.d.capas.find(c => c.tipo === 'texto') || {}).id || null
      this.armarPanel()
      await this.previa()
      this.cargarCandidatos()
    }

    // ------------------------------------------------ interfaz
    armar () {
      this.img = h('img', { alt: 'Portada', draggable: 'false' })
      this.capaGuias = h('div', { class: 'guias' })
      this.capaCajas = h('div', { class: 'cajas' })
      this.lienzo = h('div', { class: 'lienzo-portada' }, this.img, this.capaGuias, this.capaCajas)
      this.tira = h('div', { class: 'tira-cuadros' }, h('p', { class: 'ayuda' }, 'Buscando cuadros…'))
      this.panel = h('section', { class: 'panel' })
      const izq = h('section', { class: 'col-cuadros' }, h('div', { class: 'rotulo' }, 'Mejores cuadros'), this.tira)
      const centro = h('section', { class: 'col-lienzo' }, this.lienzo)
      $('#vista').replaceChildren(h('div', { class: 'editor-portada' }, izq, centro, this.panel))
      $('main').style.padding = '0'
      this.lblEstado = h('span', { class: 'estado' })
      this.btnExportar = h('button', { class: 'btn pri', onclick: () => this.exportar() }, 'Exportar JPG')
      this.chkGuias = h('input', { type: 'checkbox', checked: this.guias, onchange: e => { this.guias = e.target.checked; this.dibujarGuias() } })
      $('#acciones').replaceChildren(this.lblEstado,
        h('label', { class: 'check', title: 'Lo que se ve en el perfil (3:4) y dónde tapa la app' }, this.chkGuias, 'Guías'),
        h('button', { class: 'btn', title: 'Deshacer (Ctrl+Z)', onclick: () => this.deshacerUno() }, '↶'),
        h('button', { class: 'btn', title: 'Rehacer (Ctrl+Y)', onclick: () => this.rehacerUno() }, '↷'),
        h('button', { class: 'btn', title: 'Copia del clip con la portada al inicio', onclick: () => this.videoConPortada() }, 'Video con portada'),
        this.btnExportar)
      this.eventosLienzo()
      this.medir()
    }

    formato () { const [a, b] = (this.d.formato || this.r.formato_clip).split(':').map(Number); return a / b }

    medir () {
      const zona = this.lienzo.parentElement
      const altoMax = Math.max(320, zona.clientHeight - 24); const anchoMax = Math.max(240, zona.clientWidth - 24)
      const f = this.formato()
      const alto = Math.min(altoMax, anchoMax / f)
      Object.assign(this.lienzo.style, { width: Math.round(alto * f) + 'px', height: Math.round(alto) + 'px' })
      this.dibujarCajas(); this.dibujarGuias()
    }

    estado (t) { if (this.lblEstado) this.lblEstado.textContent = t }

    dibujarGuias () {
      this.capaGuias.replaceChildren()
      if (!this.guias) return
      const hijos = []
      if (this.formato() < 0.6) {
        hijos.push(h('i', { class: 'zona', style: { top: 0, height: '12.5%' } }), h('i', { class: 'zona', style: { bottom: 0, height: '12.5%' } }),
          h('span', { style: { top: '12.5%' } }, 'Perfil 3:4 · lo de afuera se corta'))
      }
      hijos.push(h('i', { class: 'centro' }))
      this.capaGuias.replaceChildren(...hijos)
    }

    capa () { return this.d.capas.find(c => c.id === this.sel) || null }

    armarPanel () {
      const tabs = [['texto', 'Texto y capas'], ['fondo', 'Fondo'], ['plantilla', 'Plantilla']]
      const cuerpo = h('div', { class: 'cuerpo' })
      if (this.pestana === 'texto') this.panelCapas(cuerpo)
      else if (this.pestana === 'fondo') this.panelFondo(cuerpo)
      else this.panelPlantilla(cuerpo)
      this.panel.replaceChildren(h('div', { class: 'pestanas' }, tabs.map(([k, n]) => h('button', { class: this.pestana === k ? 'on' : '', onclick: () => { this.pestana = k; this.armarPanel() } }, n))), cuerpo)
    }

    // ------------------------------------------------ controles
    deslizador (etq, valor, a, b, paso, al, unidad = '') {
      const lbl = h('b', {}, this.fmtValor(valor, unidad))
      return h('label', { class: 'campo deslizador' }, h('span', {}, etq, lbl),
        h('input', { type: 'range', min: a, max: b, step: paso, value: valor, oninput: e => { const v = Number(e.target.value); lbl.textContent = this.fmtValor(v, unidad); this.cambio(() => al(v), etq) } }))
    }

    fmtValor (v, u) { return u === '%' ? `${Math.round(v * 100)}%` : u === '°' ? `${Math.round(v)}°` : u === '×' ? `${v.toFixed(2)}×` : String(v) }

    selector (etq, valor, ops, al) {
      return h('div', { class: 'campo' }, h('span', {}, etq), h('select', { onchange: e => al(e.target.value) }, ops.map(([k, n]) => h('option', { value: k, selected: String(valor) === String(k) }, n))))
    }

    segmentos (etq, valor, ops, al) {
      return h('div', { class: 'campo' }, h('span', {}, etq), h('div', { class: 'seg' }, ops.map(([k, n]) => h('button', { class: String(valor) === String(k) ? 'on' : '', onclick: () => al(k) }, n))))
    }

    colores (etq, valor, al) {
      const inp = h('input', { type: 'color', value: /^#[0-9a-f]{6}$/i.test(valor || '') ? valor : '#ffffff', oninput: e => this.cambio(() => al(e.target.value), etq) })
      return h('div', { class: 'campo' }, h('span', {}, etq), h('div', { class: 'muestras' }, this.marca.colores.map(c => h('button', {
        class: (valor || '').toLowerCase() === c.toLowerCase() ? 'on' : '', title: c, style: { background: c },
        onclick: () => { this.cambio(() => al(c)); this.armarPanel() }
      })), inp))
    }

    checkbox (etq, valor, al) {
      return h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: !!valor, onchange: e => { this.cambio(() => al(e.target.checked)); this.armarPanel() } }), etq)
    }

    panelCapas (c) {
      const lista = h('div', { class: 'lista-capas' }, [...this.d.capas].reverse().map(x => {
        const nom = x.tipo === 'texto' ? (x.texto || '(texto vacío)').replace(/\*/g, '') : x.tipo === 'imagen' ? (x.ruta.split('/').pop() || 'Imagen') : 'Forma'
        return h('div', { class: x.id === this.sel ? 'on' : '', onclick: () => this.elegir(x.id) },
          h('i', {}, x.tipo === 'texto' ? 'T' : x.tipo === 'imagen' ? '▣' : '■'), h('span', {}, nom),
          h('button', { title: x.visible === false ? 'Mostrar' : 'Ocultar', onclick: e => { e.stopPropagation(); this.cambio(() => { x.visible = x.visible === false }); this.armarPanel() } }, x.visible === false ? '◌' : '●'),
          h('button', { title: 'Subir', onclick: e => { e.stopPropagation(); this.mover(x.id, 1) } }, '↑'),
          h('button', { title: 'Bajar', onclick: e => { e.stopPropagation(); this.mover(x.id, -1) } }, '↓'))
      }))
      const inp = h('input', { type: 'file', accept: 'image/*', style: { display: 'none' }, onchange: e => this.subir(e.target.files[0], false) })
      c.append(h('div', { class: 'fila' },
        h('button', { class: 'btn chico', onclick: () => this.agregarTexto() }, '+ Texto'),
        h('button', { class: 'btn chico', onclick: () => this.agregarForma() }, '+ Banda'),
        h('button', { class: 'btn chico', onclick: () => inp.click() }, '+ Foto'), inp), lista)
      if (this.marca.imagenes.length) {
        c.append(h('div', { class: 'campo' }, h('span', {}, 'Logos y personas del cliente (clic para agregar)'),
          h('div', { class: 'imagenes-marca' }, this.marca.imagenes.map(i => h('button', { title: i.nombre, onclick: () => this.agregarImagen(i) }, h('img', { src: i.url, alt: i.nombre, loading: 'lazy' }))))))
      }
      const x = this.capa()
      if (!x) { c.append(h('p', { class: 'ayuda' }, 'Elige una capa para editarla. Arrastra el fondo para reencuadrar y usa la rueda del ratón para el zoom.')); return }
      const caja = h('div', { class: 'caja-toma' })
      if (x.tipo === 'texto') this.controlesTexto(caja, x)
      else if (x.tipo === 'imagen') this.controlesImagen(caja, x)
      else this.controlesForma(caja, x)
      caja.append(this.deslizador('Opacidad', x.opacidad ?? 1, 0, 1, 0.01, v => { x.opacidad = v }, '%'))
      caja.append(h('div', { class: 'fila' },
        h('button', { class: 'btn chico', onclick: () => this.duplicar() }, 'Duplicar'),
        h('button', { class: 'btn chico', onclick: () => { this.cambio(() => { x.x = 0.5 }); this.previa() } }, 'Centrar'),
        h('button', { class: 'btn chico', onclick: () => this.borrarCapa() }, 'Borrar')))
      c.append(caja)
    }

    controlesTexto (caja, x) {
      this.areaTexto = h('textarea', {
        rows: 3,
        oninput: e => {
          this.cambio(() => { x.texto = e.target.value }, 'texto')
          const nom = $('.lista-capas > .on > span', this.panel)
          if (nom) nom.textContent = e.target.value.replace(/\*/g, '') || '(texto vacío)'
        }
      }, x.texto || '')
      caja.append(h('div', { class: 'campo' }, h('span', {}, 'Texto · *entre asteriscos* va resaltado'), this.areaTexto))
      const otros = (this.r.sugeridos || []).filter(s => s !== (x.texto || '').replace(/\*/g, ''))
      if (otros.length) caja.append(h('div', { class: 'sugeridos' }, otros.map(s => h('button', { title: 'Usar este texto', onclick: () => { this.cambio(() => { x.texto = s }); this.armarPanel() } }, s))))
      caja.append(h('button', {
        class: 'btn chico',
        title: 'Cuesta una fracción de centavo',
        onclick: async e => {
          e.target.disabled = true; e.target.textContent = 'Pensando…'
          try {
            const { titulos } = await api(`/api/portada/${this.base}/titulos`, { method: 'POST' })
            this.r.sugeridos = [...titulos, ...this.r.sugeridos]; this.armarPanel()
          } catch (err) { aviso(err.message, 'error'); e.target.disabled = false; e.target.textContent = '✦ Sugerir títulos con Claude' }
        }
      }, '✦ Sugerir títulos con Claude'))
      const fuentes = this.r.fuentes.includes(x.fuente) ? this.r.fuentes : [x.fuente, ...this.r.fuentes]
      caja.append(this.selector('Letra', x.fuente, fuentes.map(f => [f, f]), v => this.cambio(() => { x.fuente = v })))
      caja.append(this.deslizador('Tamaño', x.tam ?? 0.12, 0.03, 0.35, 0.002, v => { x.tam = v }))
      caja.append(this.deslizador('Ancho de la caja', x.ancho ?? 0.86, 0.2, 1.2, 0.01, v => { x.ancho = v }, '%'))
      caja.append(this.colores('Color', x.color, v => { x.color = v }))
      caja.append(this.colores('Color del resaltado', x.color_clave, v => { x.color_clave = v }))
      caja.append(this.segmentos('Resaltar con', x.clave_modo || 'color', [['color', 'Color'], ['caja', 'Recuadro']], v => { this.cambio(() => { x.clave_modo = v }); this.armarPanel() }))
      caja.append(this.segmentos('Alinear', x.alinear || 'centro', [['izquierda', 'Izquierda'], ['centro', 'Centro'], ['derecha', 'Derecha']], v => { this.cambio(() => { x.alinear = v }); this.armarPanel() }))
      caja.append(this.checkbox('MAYÚSCULAS', x.mayusculas !== false, v => { x.mayusculas = v }))
      caja.append(this.deslizador('Interlineado', x.interlineado ?? 1, 0.6, 1.6, 0.01, v => { x.interlineado = v }, '×'))
      caja.append(this.deslizador('Rotación', x.rotacion ?? 0, -30, 30, 0.5, v => { x.rotacion = v }, '°'))
      caja.append(this.deslizador('Contorno', x.contorno ?? 0, 0, 0.15, 0.005, v => { x.contorno = v }, '%'))
      if (x.contorno > 0) caja.append(this.colores('Color del contorno', x.color_contorno, v => { x.color_contorno = v }))
      caja.append(this.deslizador('Sombra', x.sombra ?? 0, 0, 1, 0.01, v => { x.sombra = v }, '%'))
      caja.append(this.segmentos('Fondo del texto', x.caja || 'no', [['no', 'Sin fondo'], ['linea', 'Por línea'], ['bloque', 'Un bloque']], v => { this.cambio(() => { x.caja = v }); this.armarPanel() }))
      if (x.caja === 'linea' || x.caja === 'bloque') {
        caja.append(this.colores('Color del fondo', x.color_caja, v => { x.color_caja = v }))
        caja.append(this.deslizador('Opacidad del fondo', x.opacidad_caja ?? 1, 0, 1, 0.01, v => { x.opacidad_caja = v }, '%'))
        caja.append(this.deslizador('Esquinas', x.radio_caja ?? 0.14, 0, 0.5, 0.01, v => { x.radio_caja = v }))
      }
    }

    controlesImagen (caja, x) {
      caja.append(this.deslizador('Tamaño', x.ancho ?? 0.3, 0.05, 1.2, 0.005, v => { x.ancho = v }, '%'))
      caja.append(h('div', { class: 'fila' },
        this.checkbox('Redonda', x.redondo, v => { x.redondo = v }),
        this.checkbox('Encuadrar en la cara', x.cara, v => { x.cara = v })))
      caja.append(this.deslizador('Borde', x.borde ?? 0, 0, 0.08, 0.002, v => { x.borde = v }))
      if (x.borde > 0) caja.append(this.colores('Color del borde', x.color_borde, v => { x.color_borde = v }))
      caja.append(this.deslizador('Rotación', x.rotacion ?? 0, -30, 30, 0.5, v => { x.rotacion = v }, '°'))
    }

    controlesForma (caja, x) {
      caja.append(this.colores('Color', x.color, v => { x.color = v }))
      caja.append(this.deslizador('Ancho', x.ancho ?? 1, 0.05, 1.3, 0.005, v => { x.ancho = v }, '%'))
      caja.append(this.deslizador('Alto', x.alto ?? 0.3, 0.01, 1, 0.005, v => { x.alto = v }, '%'))
      caja.append(this.deslizador('Esquinas', x.radio ?? 0, 0, 0.5, 0.01, v => { x.radio = v }))
      caja.append(this.deslizador('Rotación', x.rotacion ?? 0, -30, 30, 0.5, v => { x.rotacion = v }, '°'))
    }

    panelFondo (c) {
      const f = this.d.fondo
      const inp = h('input', { type: 'file', accept: 'image/*', style: { display: 'none' }, onchange: e => this.subir(e.target.files[0], true) })
      c.append(this.segmentos('Fondo', f.tipo || 'cuadro', [['cuadro', 'Cuadro del video'], ['imagen', 'Foto'], ['color', 'Color']], v => { this.cambio(() => { f.tipo = v }); this.armarPanel() }))
      if ((f.tipo || 'cuadro') === 'cuadro') {
        const lbl = h('b', {}, fmt((f.t || 0) - this.r.inicio))
        const paso = 1 / (this.r.fps || 30)
        const rango = h('input', { type: 'range', min: this.r.inicio, max: this.r.fin - 0.05, step: 0.04, value: f.t, oninput: e => this.irA(Number(e.target.value), lbl) })
        c.append(h('label', { class: 'campo deslizador' }, h('span', {}, 'Momento del clip', lbl), rango))
        c.append(h('div', { class: 'fila' },
          h('button', { class: 'btn chico', onclick: () => { const t = f.t - paso * 3; rango.value = t; this.irA(Number(rango.value), lbl) } }, '‹ Atrás'),
          h('button', { class: 'btn chico', onclick: () => { const t = f.t + paso * 3; rango.value = t; this.irA(Number(rango.value), lbl) } }, 'Adelante ›'),
          h('button', { class: 'btn chico', title: 'El mismo encuadre que tiene el clip en este momento', onclick: () => this.encuadreClip() }, '↻ Encuadre del clip')))
        c.append(this.segmentos('Encuadre', f.ajuste || 'cubrir', [['cubrir', 'Llenar'], ['completo', 'Completo'], ['split', 'Split']], v => { this.cambio(() => { f.ajuste = v }); this.armarPanel() }))
      } else if (f.tipo === 'imagen') {
        const fotos = [...this.marca.imagenes.filter(i => i.tipo === 'persona').map(i => ({ ...i, origen: 'cliente' })), ...this.r.medios.map(i => ({ ...i, origen: 'proyecto' }))]
        c.append(h('div', { class: 'fila' }, h('button', { class: 'btn chico', onclick: () => inp.click() }, 'Subir foto'), inp))
        if (fotos.length) {
          c.append(h('div', { class: 'imagenes-marca' }, fotos.map(i => h('button', {
            title: i.nombre, class: f.ruta === i.ruta ? 'on' : '',
            onclick: () => { this.cambio(() => { f.ruta = i.ruta; f.origen = i.origen; f.cx = 0.5; f.cy = 0.5; f.zoom = 1 }); this.armarPanel() }
          }, h('img', { src: i.url, alt: i.nombre, loading: 'lazy' })))))
        }
      } else c.append(this.colores('Color de fondo', f.color, v => { f.color = v }))
      if ((f.tipo || 'cuadro') !== 'color') {
        c.append(this.deslizador('Zoom', f.zoom ?? 1, 1, 3, 0.01, v => { f.zoom = v; f._manual = true }, '×'))
        c.append(this.deslizador('Más color y contraste', f.punch ?? 1, 0.7, 1.6, 0.01, v => { f.punch = v }, '×'))
        c.append(this.deslizador('Oscurecer', f.oscurecer ?? 0, 0, 0.9, 0.01, v => { f.oscurecer = v }, '%'))
        c.append(this.deslizador('Desenfocar', f.desenfoque ?? 0, 0, 1, 0.01, v => { f.desenfoque = v }, '%'))
        c.append(this.deslizador('Bajar el cuadro (espacio arriba)', f.bajar ?? 0, 0, 0.5, 0.005, v => { f.bajar = v }, '%'))
      }
      c.append(this.segmentos('Degradado', f.degradado || 'no', [['no', 'Sin'], ['abajo', 'Abajo'], ['arriba', 'Arriba'], ['ambos', 'Los dos']], v => { this.cambio(() => { f.degradado = v }); this.armarPanel() }))
      if (f.degradado && f.degradado !== 'no') {
        c.append(this.deslizador('Fuerza', f.fuerza_degradado ?? 0.8, 0, 1, 0.01, v => { f.fuerza_degradado = v }, '%'))
        c.append(this.deslizador('Alto del degradado', f.tam_degradado ?? 0.55, 0.1, 1, 0.01, v => { f.tam_degradado = v }, '%'))
        c.append(this.colores('Color del degradado', f.color_degradado || '#000000', v => { f.color_degradado = v }))
      }
    }

    panelPlantilla (c) {
      c.append(h('p', { class: 'ayuda' }, 'Una plantilla cambia colores, letra y posición con la marca del cliente. Tu texto y tu cuadro se quedan.'))
      c.append(h('div', { class: 'seg plantillas' }, [...this.r.plantillas, { id: 'propia', nombre: 'Mi plantilla' }].map(p => h('button', { class: this.d.plantilla === p.id ? 'on' : '', onclick: () => this.plantilla(p.id) }, p.nombre))))
      c.append(h('button', {
        class: 'btn',
        title: 'Los próximos videos de este cliente salen con este diseño',
        onclick: async () => { await api(`/api/portada/${this.base}/guardar_plantilla`, { method: 'POST', body: this.d }); aviso('Guardado como “Mi plantilla”', 'ok') }
      }, 'Guardar este diseño como mi plantilla'))
      c.append(this.selector('Formato', this.d.formato || this.r.formato_clip, this.r.formatos.map(x => [x, x]), async v => {
        this.guardarDeshacer(); this.d.formato = v; this.medir(); await this.plantilla(this.d.plantilla || 'titular', false)
      }))
      c.append(this.selector('Cliente (marca, colores y logos)', this.d.cliente || '', [['', '(ninguno)'], ...this.r.clientes.map(x => [x, x])], async v => {
        this.guardarDeshacer(); this.d.cliente = v
        this.marca = await api(`/api/portada_marca/${encodeURIComponent(v || '-')}`)
        await this.plantilla(this.d.plantilla || 'titular', false)
      }))
      if (this.r.exportada) c.append(h('a', { class: 'btn', href: this.r.exportada, download: '' }, 'Descargar la última exportación'))
    }

    // ------------------------------------------------ acciones sobre capas
    elegir (id) { this.sel = id; if (this.pestana !== 'texto') this.pestana = 'texto'; this.armarPanel(); this.dibujarCajas() }

    mover (id, dir) {
      const i = this.d.capas.findIndex(c => c.id === id); const j = i + dir
      if (i < 0 || j < 0 || j >= this.d.capas.length) return
      this.cambio(() => { const cs = this.d.capas; [cs[i], cs[j]] = [cs[j], cs[i]] })
      this.armarPanel()
    }

    agregarTexto () {
      const t = this.d.capas.find(c => c.tipo === 'texto') || {}
      const c = { id: nuevoId(), tipo: 'texto', texto: 'TEXTO', x: 0.5, y: 0.4, ancho: 0.8, tam: 0.09, fuente: t.fuente || this.marca.fuente, color: t.color || '#FFFFFF', color_clave: t.color_clave || this.marca.acento, color_caja: this.marca.caja, sombra: 0.55 }
      this.cambio(() => this.d.capas.push(c)); this.sel = c.id; this.armarPanel()
      this.areaTexto?.focus(); this.areaTexto?.select()
    }

    agregarForma () {
      const c = { id: nuevoId(), tipo: 'forma', x: 0.5, y: 0.5, ancho: 1, alto: 0.14, color: this.marca.caja }
      this.cambio(() => this.d.capas.unshift(c)); this.sel = c.id; this.armarPanel()
    }

    agregarImagen (i, origen = 'cliente') {
      const persona = i.tipo === 'persona'
      const c = { id: nuevoId(), tipo: 'imagen', origen, ruta: i.ruta, x: 0.5, y: persona ? 0.3 : 0.16, ancho: persona ? 0.32 : 0.3, redondo: persona, cara: persona, borde: persona ? 0.02 : 0, color_borde: this.marca.caja }
      this.cambio(() => this.d.capas.push(c)); this.sel = c.id; this.armarPanel()
    }

    async subir (archivo, comoFondo) {
      if (!archivo) return
      const fd = new FormData(); fd.append('archivo', archivo)
      try {
        this.estado('Subiendo…')
        const r = await api(`/api/subir/${encodeURIComponent(this.carpeta)}`, { method: 'POST', body: fd })
        this.estado('')
        if (r.tipo !== 'imagen') { aviso('Aquí solo sirven imágenes.', 'error'); return }
        this.r.medios.push({ nombre: archivo.name, ruta: r.ruta, url: r.url })
        if (comoFondo) { const f = this.d.fondo; this.cambio(() => { f.tipo = 'imagen'; f.ruta = r.ruta; f.origen = 'proyecto'; f.cx = 0.5; f.cy = 0.5; f.zoom = 1 }); this.armarPanel() } else this.agregarImagen({ ruta: r.ruta }, 'proyecto')
      } catch (e) { this.estado(''); aviso(e.message, 'error') }
    }

    duplicar () {
      const x = this.capa(); if (!x) return
      const c = { ...JSON.parse(JSON.stringify(x)), id: nuevoId(), x: clamp(x.x + 0.03, 0, 1), y: clamp(x.y + 0.03, 0, 1) }
      this.cambio(() => this.d.capas.push(c)); this.sel = c.id; this.armarPanel()
    }

    borrarCapa () {
      const x = this.capa(); if (!x) return
      this.cambio(() => { this.d.capas = this.d.capas.filter(c => c !== x) })
      this.sel = null; this.armarPanel()
    }

    async plantilla (nombre, conDeshacer = true) {
      try {
        if (conDeshacer) this.guardarDeshacer()
        this.d = await api(`/api/portada/${this.base}/plantilla`, { method: 'POST', body: { nombre, diseno: this.d } })
        this.sel = (this.d.capas.find(c => c.tipo === 'texto') || {}).id || null
        this.marcarSucio(); this.armarPanel(); this.medir(); this.pintarCandidatos(); this.previa()
      } catch (e) { aviso('No pude aplicar la plantilla: ' + e.message, 'error') }
    }

    irA (t, lbl) {
      const f = this.d.fondo
      if (lbl) lbl.textContent = fmt(t - this.r.inicio)
      this.cambio(() => { f.t = t; f.tipo = 'cuadro' }, 'momento')
      clearTimeout(this._enc)
      this._enc = setTimeout(() => this.encuadreClip(true), 250)  // la camara del clip pudo moverse
    }

    async encuadreClip (silencioso = false) {
      const f = this.d.fondo
      if (silencioso && f._manual) return
      const e = await api(`/api/portada/${this.base}/encuadre`, { method: 'POST', body: { t: f.t } })
      this.cambio(() => { Object.assign(f, e); delete f._manual }, silencioso ? 'momento' : undefined)
      if (!silencioso) this.armarPanel()
    }

    async cargarCandidatos () {
      try {
        const cs = await api(`/api/portada/${this.base}/candidatos`)
        if (this._muerto) return
        if (!cs.length) { this.tira.replaceChildren(h('p', { class: 'ayuda' }, 'No encontré cuadros claros. Elige el momento en la pestaña Fondo.')); return }
        this.candidatos = cs; this.pintarCandidatos()
      } catch (e) { this.tira.replaceChildren(h('p', { class: 'ayuda' }, 'No pude buscar cuadros: ' + e.message)) }
    }

    pintarCandidatos () {
      if (!this.candidatos) return
      this.tira.replaceChildren(...this.candidatos.map(c => h('button', {
        class: Math.abs((this.d.fondo.t || 0) - c.t) < 0.1 ? 'on' : '', title: `${fmt(c.t - this.r.inicio)} del clip`,
        onclick: () => {
          const f = this.d.fondo  // deshacer y las plantillas cambian el objeto: se lee al hacer clic
          this.cambio(() => { Object.assign(f, c.encuadre, { t: c.t, tipo: 'cuadro' }); delete f._manual })
          this.pintarCandidatos(); if (this.pestana === 'fondo') this.armarPanel()
        }
      }, h('img', { src: c.url, alt: '', loading: 'lazy' }), h('small', {}, fmt(c.t - this.r.inicio, 0)))))
    }

    // ------------------------------------------------ cajas y arrastre
    dibujarCajas () {
      if (!this.capaCajas) return
      this.capaCajas.replaceChildren(...this.cajas.filter(c => !c.oculta).map(c => {
        const on = c.id === this.sel
        const el = h('div', { class: 'caja-capa' + (on ? ' on' : ''), 'data-id': c.id, title: on ? '' : 'Clic para editar' })
        this.ponerCaja(el, c)
        if (on) {
          el.append(h('i', { class: 'asa esquina', 'data-asa': 'tam', title: 'Tamaño' }), h('i', { class: 'asa giro', 'data-asa': 'giro', title: 'Rotar' }))
          if (c.tipo === 'texto') el.append(h('i', { class: 'asa lado', 'data-asa': 'ancho', title: 'Ancho de la caja' }))
        }
        return el
      }))
    }

    ponerCaja (el, c) {
      Object.assign(el.style, { left: `${c.x * 100}%`, top: `${c.y * 100}%`, width: `${c.w * 100}%`, height: `${c.h * 100}%`, transform: `translate(-50%, -50%) rotate(${c.rot || 0}deg)` })
    }

    eventosLienzo () {
      this.lienzo.addEventListener('pointerdown', e => {
        const asa = e.target.dataset?.asa
        const elCaja = e.target.closest('.caja-capa')
        const R = this.lienzo.getBoundingClientRect()
        const ini = { px: e.clientX, py: e.clientY }
        e.preventDefault()
        if (!elCaja) {
          if (this.sel) { this.sel = null; this.dibujarCajas(); this.armarPanel() }
          const f = this.d.fondo
          if (f.tipo === 'color') return
          this.guardarDeshacer()
          const o = { cx: f.cx ?? 0.5, cy: f.cy ?? 0.5 }
          this.arrastre(e, ev => {
            const k = this.fondoInfo
            f.cx = clamp(o.cx - (ev.clientX - ini.px) / R.width * k.vx, 0, 1)
            f.cy = clamp(o.cy - (ev.clientY - ini.py) / R.height * k.vy, 0, 1)
            f._manual = true
            this.marcarSucio(); this.pedirPrevia()
          })
          return
        }
        const id = elCaja.dataset.id
        if (id !== this.sel) { this.sel = id; this.dibujarCajas(); this.armarPanel() }
        const x = this.capa(); const caja = this.cajas.find(c => c.id === id); if (!x) return
        const nodo = this.capaCajas.querySelector(`[data-id="${id}"]`)
        this.guardarDeshacer()
        const o = { x: x.x, y: x.y, tam: x.tam, ancho: x.ancho, alto: x.alto, rot: x.rotacion || 0 }
        const cx = R.left + x.x * R.width; const cy = R.top + x.y * R.height
        const d0 = Math.hypot(e.clientX - cx, e.clientY - cy) || 1
        this.arrastre(e, ev => {
          if (asa === 'tam') {
            const k = Math.hypot(ev.clientX - cx, ev.clientY - cy) / d0
            if (x.tipo === 'texto') x.tam = clamp(o.tam * k, 0.02, 0.5)
            else { x.ancho = clamp(o.ancho * k, 0.03, 1.6); if (x.tipo === 'forma') x.alto = clamp(o.alto * k, 0.005, 1.2) }
          } else if (asa === 'ancho') {
            x.ancho = clamp(o.ancho + (ev.clientX - ini.px) / R.width * 2, 0.1, 1.4)
          } else if (asa === 'giro') {
            let g = Math.atan2(ev.clientY - cy, ev.clientX - cx) * 180 / Math.PI + 90
            if (g > 180) g -= 360
            if (Math.abs(g) < 2.5) g = 0
            x.rotacion = Math.round(g * 2) / 2
          } else {
            let nx = o.x + (ev.clientX - ini.px) / R.width
            const ny = o.y + (ev.clientY - ini.py) / R.height
            if (Math.abs(nx - 0.5) < 0.012 && !ev.shiftKey) nx = 0.5  // se pega al centro (con Shift no)
            x.x = clamp(nx, -0.2, 1.2); x.y = clamp(ny, -0.1, 1.1)
            caja.x = x.x; caja.y = x.y
            if (nodo) this.ponerCaja(nodo, caja)
          }
          this.marcarSucio(); this.pedirPrevia()
        })
      })
      this.lienzo.addEventListener('wheel', e => {
        if (this.sel || this.d.fondo.tipo === 'color') return
        e.preventDefault()
        const f = this.d.fondo
        this.cambio(() => { f.zoom = clamp((f.zoom || 1) * (e.deltaY < 0 ? 1.04 : 0.96), 1, 3); f._manual = true }, 'zoom')
        clearTimeout(this._tRueda)
        this._tRueda = setTimeout(() => this.armarPanelSiHaceFalta(), 200)
      }, { passive: false })
    }

    arrastre (e, al) {
      const mover = ev => al(ev)
      const soltar = () => { window.removeEventListener('pointermove', mover); window.removeEventListener('pointerup', soltar); this.armarPanelSiHaceFalta() }
      window.addEventListener('pointermove', mover)
      window.addEventListener('pointerup', soltar)
    }

    armarPanelSiHaceFalta () {
      if (!document.activeElement?.closest?.('textarea, input, select')) this.armarPanel()
    }

    // ------------------------------------------------ deshacer, vista previa y guardar
    guardarDeshacer (tipo) {
      const ahora = Date.now()
      if (tipo && tipo === this._ultTipo && ahora - this._ultT < 900) { this._ultT = ahora; return }
      this._ultTipo = tipo; this._ultT = ahora
      this.deshacer.push(JSON.stringify(this.d))
      if (this.deshacer.length > 80) this.deshacer.shift()
      this.rehacer = []
    }

    deshacerUno () { if (this.deshacer.length) this.restaurar(this.deshacer, this.rehacer) }
    rehacerUno () { if (this.rehacer.length) this.restaurar(this.rehacer, this.deshacer) }

    restaurar (de, a) {
      a.push(JSON.stringify(this.d))
      this.d = JSON.parse(de.pop())
      this._ultTipo = null
      if (!this.capa()) this.sel = null
      this.marcarSucio(); this.medir(); this.armarPanel(); this.pintarCandidatos(); this.previa()
    }

    cambio (fn, tipo) { this.guardarDeshacer(tipo); fn(); this.marcarSucio(); this.pedirPrevia() }

    marcarSucio () {
      this.sucio = true; this.estado('Cambios sin guardar')
      clearTimeout(this._tGuardar)
      this._tGuardar = setTimeout(() => this.guardar(), 1500)
    }

    pedirPrevia () { if (this.enVuelo) { this.otra = true; return } this.previa() }

    async previa () {
      if (this._muerto) return
      this.enVuelo = true; this.otra = false
      try {
        const dpr = window.devicePixelRatio || 1
        const ancho = Math.round(this.lienzo.clientWidth * Math.min(dpr, 2))
        const r = await api(`/api/portada/${this.base}/previa`, { method: 'POST', body: { diseno: this.d, ancho } })
        if (this._muerto) return
        this.img.src = r.imagen
        this.cajas = r.cajas; this.fondoInfo = r.fondo
        if (!this.otra) this.dibujarCajas()
      } catch (e) { aviso('No pude dibujar la portada: ' + e.message, 'error') }
      this.enVuelo = false
      if (this.otra) this.previa()
    }

    async guardar (avisar = false) {
      clearTimeout(this._tGuardar)
      if (!this.sucio && !avisar) return
      try {
        this.estado('Guardando…')
        await api(`/api/portada/${this.base}`, { method: 'PUT', body: this.d })
        this.sucio = false; this.estado('Guardado ✓')
        if (avisar) aviso('Guardado', 'ok', 1500)
      } catch (e) { this.estado('No se pudo guardar'); aviso('No pude guardar: ' + e.message, 'error') }
    }

    async exportar () {
      this.btnExportar.disabled = true
      try {
        const r = await api(`/api/portada/${this.base}/exportar`, { method: 'POST', body: this.d })
        this.sucio = false; this.estado('Exportada ✓'); this.r.exportada = r.url
        clearTimeout(this._tGuardar)
        modal(h('div', { style: { display: 'grid', gap: '10px', justifyItems: 'center' } },
          h('b', {}, r.archivo), h('img', { src: r.url, alt: 'Portada', class: 'portada-lista' }),
          h('div', { class: 'fila' },
            h('button', { class: 'btn', onclick: () => api(`/api/abrir/${encodeURIComponent(this.carpeta)}`, { method: 'POST', body: { que: 'portadas' } }) }, 'Abrir carpeta'),
            h('a', { class: 'btn pri', href: r.url, download: r.archivo }, 'Descargar'))))
      } catch (e) { aviso('No pude exportar: ' + e.message, 'error') }
      this.btnExportar.disabled = false
    }

    async videoConPortada () {
      if (!this.r.tiene_video) { aviso('Primero renderiza este clip en el editor.', 'error'); return }
      await this.guardar()
      const log = h('pre', { class: 'render-log' }, 'Empezando…')
      const est = h('b', {}, 'Pegando la portada al inicio del video…')
      modal(h('div', { style: { minWidth: '420px' } }, est, log,
        h('p', { class: 'ayuda' }, 'Deja una copia con la portada en los primeros 0.1 s, para las apps donde la portada se elige de un cuadro del video. Tu clip original no cambia.')))
      try {
        const { job } = await api(`/api/portada/${this.base}/video`, { method: 'POST' })
        const t = await seguirTrabajo(job, x => { log.textContent = (x.log || []).slice(-6).join('\n') || x.estado })
        $('.contenido', $('#modal')).replaceChildren(h('div', { style: { display: 'grid', gap: '10px', justifyItems: 'center' } },
          h('b', {}, `Listo en ${t.segundos} s`), h('video', { src: t.resultado, controls: true }),
          h('a', { class: 'btn pri', href: t.resultado, download: '' }, 'Descargar')))
      } catch (e) { est.textContent = 'No se pudo: ' + e.message; est.style.color = '#ff6b6b' }
    }

    tecla (e) {
      if (e.target.closest('input, textarea, select')) return
      const k = e.key.toLowerCase()
      const ctrl = e.ctrlKey || e.metaKey
      if (ctrl && k === 'z') { e.preventDefault(); e.shiftKey ? this.rehacerUno() : this.deshacerUno(); return }
      if (ctrl && k === 'y') { e.preventDefault(); this.rehacerUno(); return }
      if (ctrl && k === 's') { e.preventDefault(); this.guardar(true); return }
      if (ctrl && k === 'd') { e.preventDefault(); this.duplicar(); return }
      if (ctrl || e.altKey) return
      const x = this.capa(); if (!x) return
      const paso = e.shiftKey ? 0.02 : 0.004
      const mov = { arrowleft: [-paso, 0], arrowright: [paso, 0], arrowup: [0, -paso], arrowdown: [0, paso] }[k]
      if (mov) { e.preventDefault(); this.cambio(() => { x.x += mov[0]; x.y += mov[1] }, 'flechas') } else if (k === 'delete' || k === 'backspace') { e.preventDefault(); this.borrarCapa() } else if (k === 'escape') { this.sel = null; this.dibujarCajas(); this.armarPanel() }
    }

    async salir () {
      this._muerto = true
      clearTimeout(this._enc)
      document.removeEventListener('keydown', this._teclas)
      window.removeEventListener('resize', this._redim)
      window.onbeforeunload = null
      if (this.sucio) await this.guardar()
      $('main').style.padding = ''
    }
  }

  return { vistaPortadas, EditorPortada }
}
