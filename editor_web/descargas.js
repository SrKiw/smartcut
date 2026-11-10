// SmartCut · apartado de descargas (v0.5): ver y bajar varios clips a la vez, de uno o varios videos.
const mb = n => n > 1e9 ? `${(n / 1e9).toFixed(1)} GB` : `${Math.round(n / 1e6)} MB`

export function crearDescargas ({ $, h, api, aviso, migas, modal, fmt }) {
  const elegidos = new Map() // "carpeta/id" -> clip

  async function vistaDescargas (abierta) {
    migas(h('a', { href: '#/' }, 'Tus videos'), h('b', {}, 'Descargas'))
    const lista = (await api('/api/proyectos')).filter(p => p.editable !== undefined)
    const portadas = h('input', { type: 'checkbox', checked: true })
    const textos = h('input', { type: 'checkbox', checked: true })
    const conIntro = h('input', { type: 'checkbox' })
    const formatoOutro = h('select', {}, [['', 'Sin outro'], ['logo', 'Solo el logo'], ['miniatura', 'Logo y miniatura del video'], ['titulo', 'Isologo, título y logo'], ['texto', 'Con texto']].map(([k, n]) => h('option', { value: k }, n)))
    const textoOutro = h('input', { type: 'text', placeholder: 'Disponible en YouTube', maxlength: 90 })
    const linkYt = h('input', { type: 'text', placeholder: 'Link del video en YouTube (para su miniatura real)' })
    const previa = h('img', { class: 'outro-previa', alt: 'Vista previa del outro', hidden: true })
    let elegida = abierta || null
    let tPrevia = null
    const verPrevia = () => {
      clearTimeout(tPrevia)
      tPrevia = setTimeout(() => {
        const f = formatoOutro.value
        previa.hidden = !f || !elegida
        linkYt.parentElement.hidden = f !== 'miniatura'
        textoOutro.parentElement.hidden = !['miniatura', 'texto'].includes(f)
        if (f && elegida) previa.src = `/api/outro/${encodeURIComponent(elegida)}?formato=${f}&texto=${encodeURIComponent(textoOutro.value)}&t=${Date.now()}`
      }, 250)
    }
    formatoOutro.onchange = verPrevia; textoOutro.oninput = verPrevia
    previa.onerror = () => { previa.hidden = true; if (formatoOutro.value) aviso('Este video no tiene cliente: el outro usa su logo y colores.') }
    linkYt.onchange = async () => {
      if (!linkYt.value.trim() || !elegida) return
      try { await api(`/api/outro/${encodeURIComponent(elegida)}/link`, { method: 'POST', body: { url: linkYt.value.trim() } }); aviso('Miniatura de YouTube lista', 'ok'); verPrevia() } catch (e) { aviso(e.message, 'error') }
    }
    const opcionesUrl = c => `/api/descarga/${encodeURIComponent(c.carpeta)}/${c.id}?intro=${conIntro.checked ? 1 : 0}&outro=${formatoOutro.value}&texto=${encodeURIComponent(textoOutro.value)}`
    const resumen = h('span', { class: 'estado' })
    const boton = h('button', { class: 'btn pri', disabled: true }, 'Descargar')
    const pintar = () => {
      const tam = [...elegidos.values()].reduce((s, c) => s + (c.tam || 0), 0)
      resumen.textContent = elegidos.size ? `${elegidos.size} clips · ${mb(tam)}` : 'Elige los clips'
      boton.disabled = !elegidos.size
    }
    boton.onclick = async () => {
      boton.disabled = true; boton.textContent = 'Preparando…'
      try {
        const r = await api('/api/zip', { method: 'POST', body: { clips: [...elegidos.values()].map(c => ({ carpeta: c.carpeta, id: c.id })), portadas: portadas.checked, textos: textos.checked, intro: conIntro.checked, outro: formatoOutro.value, texto_outro: textoOutro.value } })
        const a = h('a', { href: r.url, download: '' }); document.body.append(a); a.click(); a.remove()
        aviso(`Bajando ${r.clips} clips (${mb(r.tam)})`, 'ok')
      } catch (e) { aviso(e.message, 'error') }
      boton.textContent = 'Descargar'; pintar()
    }
    $('#acciones').replaceChildren(resumen,
      h('label', { class: 'check', title: 'Pone la intro del cliente al principio de cada clip (tarda unos segundos por clip)' }, conIntro, 'Con intro'),
      h('label', { class: 'check' }, portadas, 'Portadas'), h('label', { class: 'check' }, textos, 'Textos'), boton)

    const grupo = p => {
      const filas = h('div', { class: 'filas-clip' })
      let cargado = false
      const cargar = async () => {
        if (cargado) return; cargado = true
        filas.replaceChildren(h('p', { class: 'ayuda' }, 'Cargando…'))
        const pr = await api(`/api/proyecto/${encodeURIComponent(p.carpeta)}`)
        p.clipsDatos = pr.clips.filter(c => c.video).map(c => ({ ...c, carpeta: p.carpeta, con_intro: pr.intro }))
        filas.replaceChildren(...(p.clipsDatos.length ? p.clipsDatos.map(c => {
          const k = `${p.carpeta}/${c.id}`
          const chk = h('input', { type: 'checkbox', checked: elegidos.has(k), onchange: e => { e.target.checked ? elegidos.set(k, c) : elegidos.delete(k); pintar() } })
          c._chk = chk
          return h('div', { class: 'fila-clip' }, chk,
            h('button', { class: 'mini-play', style: { backgroundImage: (c.portada || c.miniatura) ? `url("${c.portada || c.miniatura}")` : null }, title: 'Ver', onclick: () => verClip(c) }, '▶'),
            h('div', { class: 'datos' }, h('b', {}, c.titulo), h('small', {}, `${c.puntuacion || '–'} pts · ${fmt(c.duracion, 0)} · ${mb(c.tam || 0)}`)),
            h('a', { class: 'btn chico', href: urlDescarga(c, false), download: '', onclick: e => { e.currentTarget.href = opcionesUrl(c) } }, 'Bajar'))
        }) : [h('p', { class: 'ayuda' }, 'Sin clips renderizados.')]))
      }
      const marcar = async () => {
        await cargar()
        const todos = p.clipsDatos.every(c => elegidos.has(`${p.carpeta}/${c.id}`))
        for (const c of p.clipsDatos) {
          const k = `${p.carpeta}/${c.id}`
          todos ? elegidos.delete(k) : elegidos.set(k, c)
          if (c._chk) c._chk.checked = !todos
        }
        pintar()
      }
      const det = h('details', { class: 'grupo-clips', ontoggle: e => { if (e.target.open) { cargar(); elegida = p.carpeta; verPrevia() } } },
        h('summary', {}, h('b', {}, p.titulo), h('small', {}, `${p.clips} clips · ${p.fecha}`),
          h('button', { class: 'btn chico', onclick: e => { e.preventDefault(); det.open = true; marcar() } }, 'Todos')), filas)
      if (p.carpeta === abierta) { det.open = true; marcar() }
      return det
    }
    $('#vista').replaceChildren(h('h1', {}, 'Descargas'),
      h('p', { class: 'ayuda', style: { margin: '-8px 0 16px' } }, 'Abre un video, mira los clips y marca los que quieras. Sale un solo .zip, también desde la Mac.'),
      h('div', { class: 'descargas-cols' }, h('div', { class: 'grupos' }, lista.map(grupo)),
        h('aside', { class: 'caja-toma panel-outro' }, h('b', {}, 'Outro al descargar'),
          h('p', { class: 'ayuda' }, 'Se agrega al final de los clips que bajes. El clip original no cambia.'),
          h('label', { class: 'campo' }, h('span', {}, 'Formato'), formatoOutro),
          h('label', { class: 'campo' }, h('span', {}, 'Texto'), textoOutro),
          h('label', { class: 'campo' }, h('span', {}, 'Si no ves la miniatura real'), linkYt),
          previa)))
    verPrevia()
    pintar()
  }

  function verClip (c) {
    modal(h('div', { style: { display: 'grid', gap: '10px', justifyItems: 'center' } }, h('b', {}, c.titulo),
      h('video', { src: c.video, controls: true, autoplay: true, playsinline: true }),
      h('div', { class: 'fila' },
        h('a', { class: 'btn pri', href: urlDescarga(c, false), download: '' }, 'Descargar'),
        c.con_intro ? h('a', { class: 'btn', href: urlDescarga(c, true), download: '', title: 'Tarda unos segundos la primera vez' }, 'Descargar con intro') : null)))
  }

  function urlDescarga (c, intro) {
    const carpeta = c.carpeta || decodeURIComponent(location.hash.split('/')[2] || '')
    return `/api/descarga/${encodeURIComponent(carpeta)}/${c.id}${intro ? '?intro=1' : ''}`
  }

  return { vistaDescargas, verClip }
}
