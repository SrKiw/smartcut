import React, {useEffect, useState} from 'react';
import {AbsoluteFill, Img, continueRender, delayRender, random, staticFile, useCurrentFrame} from 'remotion';

const RED = '#E10600', YEL = '#FFD60A', INK = '#111';
const CORTES = [0, 4, 9, 13, 17, 22, 25];

const useFonts = () => {
  const [h] = useState(() => delayRender('fonts'));
  useEffect(() => {
    const f1 = new FontFace('HB', `url(${staticFile('Helvetica-Bold.ttf')})`);
    const f2 = new FontFace('DS', `url(${staticFile('DirtyStains-DEMO.otf')})`);
    Promise.all([f1.load(), f2.load()]).then((fs) => { fs.forEach((f) => (document.fonts as any).add(f)); continueRender(h); });
  }, [h]);
};

const steps = (T: number, t: number, n: number, dt = 0.1) => Math.max(0, Math.min(n, Math.floor((T - t) / dt + 1e-6) + 1));
const pop = (T: number, t: number, big = 1.14) => (T < t ? 0 : T < t + 0.1 ? big : 1);
const ease = (x: number) => (x < 0 ? 0 : x > 1 ? 1 : x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);
const kf = (T: number, keys: [number, number][]) => {
  if (T <= keys[0][0]) return keys[0][1];
  for (let i = 0; i < keys.length - 1; i++) {
    const [t1, v1] = keys[i], [t2, v2] = keys[i + 1];
    if (T <= t2) return v1 + (v2 - v1) * ease((T - t1) / (t2 - t1));
  }
  return keys[keys.length - 1][1];
};

const HB: React.CSSProperties = {fontFamily: 'HB', textTransform: 'uppercase', color: '#fff', lineHeight: 1.08, whiteSpace: 'nowrap', textAlign: 'center'};

// cada dibujo tiembla 1-2 px: el "boil" de tu estilo
const Boil: React.FC<{id: string; children: React.ReactNode; amp?: number}> = ({id, children, amp = 2}) => {
  const f = useCurrentFrame();
  return <div style={{position: 'absolute', inset: 0, transform: `translate(${(random(id + 'x' + f) - 0.5) * 2 * amp}px, ${(random(id + 'y' + f) - 0.5) * 2 * amp}px)`}}>{children}</div>;
};

const Pop: React.FC<{T: number; t: number; x?: number; y: number; rot?: number; children: React.ReactNode}> = ({T, t, x = 540, y, rot = 0, children}) => {
  const s = pop(T, t);
  if (!s) return null;
  return <div style={{position: 'absolute', left: x, top: y, transform: `translate(-50%, -50%) rotate(${rot}deg) scale(${s})`}}>{children}</div>;
};

// palabra sobre una pasada de marcador amarillo que se dibuja en 3 trazos
const Marcado: React.FC<{T: number; t: number; x?: number; y: number; size: number; w: number; rot?: number; children: React.ReactNode}> = ({T, t, x = 540, y, size, w, rot = -2, children}) => {
  const k = steps(T, t, 3) / 3;
  if (!k) return null;
  const h = size * 1.7;
  return (
    <div style={{position: 'absolute', left: x - w / 2, top: y - h / 2, width: w, height: h, transform: `rotate(${rot}deg)`}}>
      <div style={{position: 'absolute', left: 0, top: 0, width: w * k, height: h, overflow: 'hidden'}}><Img src={staticFile('marker_yellow.png')} style={{width: w, height: h}} /></div>
      <div style={{...HB, position: 'absolute', inset: 0, fontSize: size, color: INK, display: 'grid', placeItems: 'center', opacity: k >= 0.66 ? 1 : 0}}>{children}</div>
    </div>
  );
};

const Fondo: React.FC<{color?: string}> = ({color}) => (
  <AbsoluteFill>
    {color && <AbsoluteFill style={{background: color}} />}
    <Img src={staticFile('paper_dark.jpg')} style={{width: 1080, height: 1920, objectFit: 'cover', ...(color ? {filter: 'grayscale(1) contrast(1.6)', mixBlendMode: 'overlay' as const, opacity: 0.55} : {})}} />
  </AbsoluteFill>
);

// foto recortada en vertical, con marco de papel, sombra y cinta
const Vertical: React.FC<{src: string; w: number; rot?: number; pos?: string; zoom?: number; zy?: string; cinta?: boolean; children?: React.ReactNode}> = ({src, w, rot = 0, pos = '66% 50%', zoom = 1, zy = '50% 30%', cinta = true, children}) => {
  const h = (w * 16) / 9;
  return (
    <div style={{position: 'relative', width: w + 20, height: h + 20, background: '#ece6d8', padding: 10, transform: `rotate(${rot}deg)`, boxShadow: '0 22px 34px rgba(0,0,0,.6)'}}>
      <div style={{position: 'relative', width: w, height: h, overflow: 'hidden', background: '#000'}}>
        <Img src={staticFile(src)} style={{width: w, height: h, objectFit: 'cover', objectPosition: pos, transform: `scale(${zoom})`, transformOrigin: zy}} />
        {children}
      </div>
      {cinta && <Img src={staticFile('tape.png')} style={{position: 'absolute', left: w / 2 - 60, top: -24, width: 140, transform: 'rotate(-4deg)'}} />}
    </div>
  );
};

const Nota: React.FC<{T: number; t: number; x: number; y: number; rot?: number; color?: string; children: React.ReactNode}> = ({T, t, x, y, rot = 0, color = RED, children}) => {
  const s = pop(T, t, 1.25);
  if (!s) return null;
  return <div style={{position: 'absolute', left: x, top: y, width: 124, height: 124, marginLeft: -62, marginTop: -62, borderRadius: 62, border: `9px solid ${color}`, background: '#101010', display: 'grid', placeItems: 'center', transform: `rotate(${rot}deg) scale(${s})`, boxShadow: '0 12px 18px rgba(0,0,0,.6)'}}><span style={{...HB, fontSize: 56, color}}>{children}</span></div>;
};

const Logo: React.FC<{size: number; tinta?: string; cut?: string}> = ({size, tinta = '#fff', cut = RED}) => (
  <div style={{...HB, fontSize: size, color: tinta, display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
    SMART<span style={{fontFamily: 'DS', color: cut, display: 'inline-block', transform: 'scaleX(0.75)', transformOrigin: 'left center', marginRight: -size * 0.45, fontSize: size * 0.98}}>CUT</span>
  </div>
);

/* ---------- 1. El video largo se vuelve clips (0-4 s) ---------- */
const E1: React.FC<{T: number}> = ({T}) => {
  const dx = kf(T, [[0, 120], [2.1, -180]]);
  const cortado = T >= 2.3;
  const trazos = steps(T, 1.8, 4);
  return (
    <AbsoluteFill>
      <Fondo />
      <Boil id="e1">
        {T < 2.5 ? <>
          <Pop T={T} t={0.1} y={345}><div style={{...HB, fontSize: 84}}>¿UN VIDEO DE</div></Pop>
          <Marcado T={T} t={0.6} y={500} size={150} w={760}>1 HORA?</Marcado>
        </> : <>
          <Pop T={T} t={2.5} y={380}><Logo size={138} /></Pop>
          <Pop T={T} t={2.9} y={510}><div style={{...HB, fontSize: 56}}>LO VUELVE CLIPS</div></Pop>
        </>}
        {!cortado && (
          <div style={{position: 'absolute', left: dx - 200, top: 680, width: 1700, height: 360, background: '#0b0b0b', display: 'flex', gap: 14, padding: '38px 14px', transform: 'rotate(-3deg)', boxShadow: '0 20px 30px rgba(0,0,0,.6)'}}>
            {['f1', 'f3', 'f2', 'f4', 'f1', 'f3'].map((s, i) => <Img key={i} src={staticFile(`${s}.jpg`)} style={{width: 500, height: 284, objectFit: 'cover'}} />)}
            {[0, 1].map((k) => <div key={k} style={{position: 'absolute', left: 0, right: 0, [k ? 'bottom' : 'top']: 10, height: 18, backgroundImage: 'repeating-linear-gradient(90deg,#ece6d8 0 22px,transparent 22px 54px)'}} />)}
          </div>
        )}
        {!cortado && trazos > 0 && (
          <svg width={1080} height={1920} style={{position: 'absolute', left: 0, top: 0}}>
            {[300, 560, 820].slice(0, trazos).map((x) => <path key={x} d={`M${x + 22} 630 L${x - 22} 1090`} stroke={RED} strokeWidth={12} strokeDasharray="30 22" fill="none" />)}
          </svg>
        )}
        {cortado && [['f1', 250, -7, 2.3], ['f3', 540, 2, 2.4], ['f2', 830, 7, 2.5]].map(([s, x, r, t]) => (
          <Pop key={s as string} T={T} t={t as number} x={x as number} y={830} rot={r as number}><Vertical src={`${s}.jpg`} w={250} pos={s === 'f2' ? '50% 50%' : '66% 50%'} /></Pop>
        ))}
      </Boil>
    </AbsoluteFill>
  );
};

/* ---------- 2. Encuentra los momentos y sigue a quien habla (4-9 s) ---------- */
const FRASES = ['Y entonces le dije que no', 'A 200 clientes por dia', 'Mi reputacion vale mas', 'Por eso fui mas lento'];
const E2: React.FC<{T: number}> = ({T}) => {
  const fase2 = T >= 6.5;
  const rx = kf(T, [[6.7, 170], [7.1, 170], [7.4, 480], [7.8, 480], [8.1, 380]]);
  const foto = T < 7.3 ? 'f1' : 'f2';
  return (
    <AbsoluteFill>
      <Fondo />
      <Boil id="e2">
        {!fase2 ? <>
          <Marcado T={T} t={4.1} y={330} size={84} w={930}>LOS MEJORES</Marcado>
          <Pop T={T} t={4.3} y={460}><div style={{...HB, fontFamily: 'DS', fontSize: 104, color: RED, transform: 'scaleX(.75)'}}>MOMENTOS</div></Pop>
          <div style={{position: 'absolute', left: 80, top: 560, width: 920, height: 520, transform: 'rotate(-1.5deg)'}}>
            <Img src={staticFile('sheet_wide.png')} style={{position: 'absolute', inset: 0, width: 920, height: 520}} />
            {FRASES.map((l, i) => {
              const marcada = i === 1 && T >= 4.9;
              return (
                <div key={l} style={{position: 'absolute', left: 60, top: 80 + i * 92, height: 68, width: 620, display: 'grid', alignItems: 'center'}}>
                  {marcada && <div style={{position: 'absolute', left: -12, top: -6, width: 640 * (steps(T, 4.9, 3) / 3), height: 80, overflow: 'hidden'}}><Img src={staticFile('marker_yellow.png')} style={{width: 640, height: 80}} /></div>}
                  <span style={{position: 'relative', fontFamily: 'HB', fontSize: 36, color: i === 1 ? INK : '#555', whiteSpace: 'nowrap', opacity: T >= 4.3 + i * 0.1 ? 1 : 0}}>{l}</span>
                </div>
              );
            })}
            <Nota T={T} t={5.3} x={810} y={120} rot={-6}>85</Nota>
            <Nota T={T} t={5.6} x={810} y={262} rot={5} color="#b89400">80</Nota>
            <Nota T={T} t={5.9} x={810} y={404} rot={-3} color="#555">79</Nota>
          </div>
        </> : <>
          <Marcado T={T} t={6.5} y={335} size={70} w={930}>SIGUE A QUIEN HABLA</Marcado>
          <div style={{position: 'absolute', left: 60, top: 470, width: 960, height: 540, boxShadow: '0 22px 34px rgba(0,0,0,.6)', transform: 'rotate(-1deg)', background: '#000', overflow: 'hidden', border: '10px solid #ece6d8'}}>
            <Img src={staticFile(`${foto}.jpg`)} style={{width: 960, height: 540, objectFit: 'cover'}} />
            <div style={{position: 'absolute', inset: 0, background: 'rgba(0,0,0,.45)'}} />
            <div style={{position: 'absolute', left: rx, top: 0, width: 304, height: 540, overflow: 'hidden', outline: `9px solid ${YEL}`}}>
              <Img src={staticFile(`${foto}.jpg`)} style={{position: 'absolute', left: -rx, top: 0, width: 960, height: 540, objectFit: 'cover'}} />
            </div>
          </div>
          <Pop T={T} t={7.1} x={rx + 212} y={1062}><div style={{...HB, fontSize: 40, color: YEL}}>16:9 → 9:16</div></Pop>
        </>}
      </Boil>
    </AbsoluteFill>
  );
};

/* ---------- 3. Tu marca: el mismo clip cambia de piel (9-13 s) ---------- */
const PIELES = [
  {bg: YEL, etiqueta: 'SUBTITULOS', foto: 'f1', fuente: 'HB', color: '#fff', activo: YEL, logo: '', tx: 'TU MARCA'},
  {bg: '#E10600', etiqueta: 'COLORES', foto: 'f3', fuente: 'HB', color: '#fff', activo: '#FFD60A', logo: '', tx: 'TUS COLORES'},
  {bg: '#EFEADA', etiqueta: 'LETRA', foto: 'f4', fuente: 'DS', color: '#E10600', activo: '#E10600', logo: '', tx: 'TU LETRA'},
  {bg: '#2b3f7a', etiqueta: 'LOGO', foto: 'f2', fuente: 'HB', color: '#fff', activo: '#FCA311', logo: 'logo_btc.png', tx: 'TU LOGO'},
];
const E3: React.FC<{T: number}> = ({T}) => {
  const i = Math.min(3, Math.floor((T - 9) / 1));
  const p = PIELES[i];
  const golpe = T - 9 - i < 0.1 ? 1.05 : 1;
  return (
    <AbsoluteFill>
      <Fondo color={p.bg} />
      <Boil id="e3">
        <div style={{position: 'absolute', left: 540, top: 690, transform: `translate(-50%,-50%) rotate(${i % 2 ? 2.5 : -2.5}deg) scale(${golpe})`}}>
          <Vertical src={`${p.foto}.jpg`} w={420} pos={p.foto === 'f2' ? '50% 50%' : '66% 50%'}>
            <div style={{...HB, position: 'absolute', left: 0, right: 0, top: 450, fontFamily: p.fuente, fontSize: p.fuente === 'DS' ? 56 : 62, color: p.activo, transform: p.fuente === 'DS' ? 'scaleX(.75)' : undefined, textShadow: '0 3px 0 #000,0 -3px 0 #000,3px 0 0 #000,-3px 0 0 #000'}}>{p.tx}</div>
            {p.logo && <Img src={staticFile(p.logo)} style={{position: 'absolute', left: 60, top: 620, width: 300}} />}
          </Vertical>
        </div>
        <div style={{position: 'absolute', left: 540, top: 1120, transform: 'translate(-50%,-50%) rotate(-3deg)', background: '#111', padding: '8px 26px'}}><span style={{...HB, fontSize: 52}}>{p.etiqueta}</span></div>
      </Boil>
    </AbsoluteFill>
  );
};

/* ---------- 4. Zooms, imagenes y lower thirds arrastrando (13-17 s) ---------- */
const CHIPS = [['ZOOM', '#3b82f6', 13.3, 90], ['IMAGEN', RED, 14.4, 370], ['LOWER THIRD', YEL, 15.5, 650]] as const;
const E4: React.FC<{T: number}> = ({T}) => {
  const zoom = kf(T, [[13.6, 1], [13.9, 1.45], [14.3, 1.45], [14.5, 1]]);
  const objetivo = T < 14.4 ? 0 : T < 15.5 ? 1 : 2;
  const ini = CHIPS[objetivo][2] as number;
  const cx = kf(T, [[ini, 980], [ini + 0.45, (CHIPS[objetivo][3] as number) + 120]]);
  const cy = kf(T, [[ini, 860], [ini + 0.45, 1075]]);
  return (
    <AbsoluteFill>
      <Fondo />
      <Boil id="e4">
        <div style={{position: 'absolute', left: 540, top: 625, transform: 'translate(-50%,-50%) rotate(-1.5deg)'}}>
          <Vertical src="f3.jpg" w={370} zoom={zoom} zy="58% 32%">
            {T >= 14.8 && T < 15.5 && <Img src={staticFile('thumb.jpg')} style={{position: 'absolute', left: 30, top: 70, width: 310, border: '6px solid #fff', transform: `rotate(-4deg) scale(${pop(T, 14.8)})`, boxShadow: '0 10px 16px rgba(0,0,0,.6)'}} />}
            {T >= 15.9 && <div style={{position: 'absolute', left: 16, top: 410, background: 'rgba(12,12,14,.92)', borderLeft: `10px solid ${YEL}`, padding: '10px 18px', transform: `translateX(${T < 16.1 ? -60 : 0}px)`}}><div style={{...HB, textAlign: 'left', fontSize: 28}}>TU INVITADO</div><div style={{...HB, textAlign: 'left', fontSize: 18, color: YEL}}>FUNDADOR</div></div>}
          </Vertical>
        </div>
        <div style={{position: 'absolute', left: 40, top: 1020, width: 1000, height: 110, background: '#ece6d8', transform: 'rotate(-.6deg)', boxShadow: '0 14px 20px rgba(0,0,0,.55)'}}>
          <div style={{position: 'absolute', left: 16, right: 16, top: 54, height: 4, background: '#999'}} />
          {CHIPS.map(([n, c, t, x], k) => T >= (t as number) + 0.45 && (
            <div key={n} style={{...HB, position: 'absolute', left: x as number, top: 22, width: 250, padding: '16px 0', fontSize: n === 'LOWER THIRD' ? 26 : 30, background: c as string, color: c === YEL ? INK : '#fff', transform: `scale(${pop(T, (t as number) + 0.45)})`}}>{n}</div>
          ))}
        </div>
        <svg width={90} height={110} style={{position: 'absolute', left: cx, top: cy}}>
          <path d="M8 6 L8 84 L28 66 L44 100 L60 92 L44 60 L72 58 Z" fill="#fff" stroke="#111" strokeWidth={6} strokeLinejoin="round" />
        </svg>
      </Boil>
    </AbsoluteFill>
  );
};

/* ---------- 5. Portadas, y la intro y el outro a tu eleccion (17-22 s) ---------- */
const Interruptor: React.FC<{T: number; t: number; x: number; texto: string}> = ({T, t, x, texto}) => {
  const on = T >= t;
  return (
    <div style={{position: 'absolute', left: x, top: 340, width: 400, textAlign: 'center'}}>
      <div style={{...HB, fontSize: 66, marginBottom: 12}}>{texto}</div>
      <div style={{position: 'relative', width: 190, height: 90, margin: '0 auto', borderRadius: 45, background: on ? YEL : '#444', border: '7px solid #fff'}}>
        <div style={{position: 'absolute', top: 4, left: on ? 104 : 6, width: 68, height: 68, borderRadius: 34, background: on ? INK : '#ddd'}} />
      </div>
    </div>
  );
};
const E5: React.FC<{T: number}> = ({T}) => (
  <AbsoluteFill>
    <Fondo />
    <Boil id="e5">
      {T < 19.5 ? <>
        <Marcado T={T} t={17.1} y={345} size={72} w={990}>CADA CLIP, SU PORTADA</Marcado>
        {[['p1', 250, -8, 17.4], ['p2', 540, 1, 17.7], ['p3', 830, 8, 18.0]].map(([s, x, r, t]) => (
          <Pop key={s as string} T={T} t={t as number} x={x as number} y={790} rot={r as number}>
            <div style={{position: 'relative', background: '#ece6d8', padding: 9, boxShadow: '0 20px 30px rgba(0,0,0,.65)'}}>
              <Img src={staticFile(`${s}.jpg`)} style={{width: 300, height: 533, objectFit: 'cover', display: 'block'}} />
              <Img src={staticFile('tape.png')} style={{position: 'absolute', left: 90, top: -22, width: 130}} />
            </div>
          </Pop>
        ))}
      </> : <>
        <Interruptor T={T} t={19.9} x={100} texto="INTRO" />
        <Interruptor T={T} t={20.4} x={580} texto="OUTRO" />
        <Pop T={T} t={20.7} y={850} rot={-1.5}>
          <div style={{width: 760, background: '#0E131F', padding: '30px 36px', border: '9px solid #ece6d8', boxShadow: '0 22px 34px rgba(0,0,0,.6)', textAlign: 'center'}}>
            <Img src={staticFile('logo_btc.png')} style={{width: 400, marginBottom: 24}} />
            <Img src={staticFile('thumb.jpg')} style={{width: 660, display: 'block', margin: '0 auto 22px'}} />
            <div style={{...HB, fontSize: 40}}>DISPONIBLE EN YOUTUBE</div>
          </div>
        </Pop>
      </>}
    </Boil>
  </AbsoluteFill>
);

/* ---------- 6. Cierre (22-25 s) ---------- */
const E6: React.FC<{T: number}> = ({T}) => {
  const k = steps(T, 22.5, 4) / 4;
  return (
    <AbsoluteFill>
      <Fondo color={YEL} />
      <Boil id="e6">
        <Pop T={T} t={22.1} y={610}><Logo size={138} tinta={INK} /></Pop>
        {k > 0 && <svg width={1080} height={1920} style={{position: 'absolute', left: 0, top: 0}}><path d="M130 740 C 360 716, 720 760, 950 726" fill="none" stroke={RED} strokeWidth={16} strokeLinecap="round" strokeDasharray={860} strokeDashoffset={860 * (1 - k)} /></svg>}
        <Pop T={T} t={23.1} y={860} rot={-2}><div style={{background: INK, padding: '14px 34px'}}><span style={{...HB, fontSize: 64}}>TUS VIDEOS, TU MARCA.</span></div></Pop>
      </Boil>
    </AbsoluteFill>
  );
};

/* ---------- Subtitulos de la voz: palabra por palabra, en la zona segura ---------- */
const VOZ = [
  {a: 0.1, b: 3.9, t: '¿Un video de una hora? SmartCut lo vuelve clips listos para publicar.'},
  {a: 4.1, b: 8.8, t: 'Encuentra los mejores momentos, los puntúa y sigue a quien habla.'},
  {a: 9.1, b: 12.8, t: 'Todo a tu marca: subtítulos, colores, letra y logo.'},
  {a: 13.1, b: 16.8, t: 'Agrega zooms, imágenes y lower thirds con solo arrastrar.'},
  {a: 17.1, b: 21.8, t: 'Cada clip trae su portada; intro y outro, tú decides.'},
  {a: 22.1, b: 24.7, t: 'SmartCut. Tus videos, tu marca.'},
];
const Subtitulo: React.FC<{T: number}> = ({T}) => {
  const v = VOZ.find((x) => T >= x.a && T <= x.b + 0.2);
  if (!v) return null;
  const pal = v.t.split(' ');
  const dt = (v.b - v.a) / pal.length;
  const i = Math.min(pal.length - 1, Math.floor((T - v.a) / dt));
  const bloque = Math.floor(i / 3) * 3;
  return (
    <div style={{position: 'absolute', left: 65, right: 65, top: 1178, display: 'flex', justifyContent: 'center', columnGap: 16}}>
      {pal.slice(bloque, bloque + 3).map((w, k) => (
        <span key={k} style={{...HB, fontSize: 52, opacity: bloque + k <= i ? 1 : 0, color: bloque + k === i ? YEL : '#fff', textShadow: '0 4px 0 #000,0 -4px 0 #000,4px 0 0 #000,-4px 0 0 #000,3px 3px 0 #000,-3px -3px 0 #000,3px -3px 0 #000,-3px 3px 0 #000'}}>{w}</span>
      ))}
    </div>
  );
};

// papel rasgado entre escenas: el lado rasgado sube en 4 dibujos
const BORDE = (() => {
  const pts: number[] = [];
  let y = 0;
  for (let x = 0; x <= 1080; x += 27) { y = Math.max(-26, Math.min(26, y + (random('b' + x) - 0.5) * 34)); pts.push(x, y); }
  return pts;
})();
const clipArriba = (ey: number) => {
  const p = ['0px 0px', '1080px 0px'];
  for (let i = BORDE.length - 2; i >= 0; i -= 2) p.push(`${BORDE[i]}px ${ey + BORDE[i + 1]}px`);
  return `polygon(${p.join(',')})`;
};
const ESCENAS = [E1, E2, E3, E4, E5, E6];

export const Video: React.FC = () => {
  useFonts();
  const T = useCurrentFrame() / 10;
  const n = Math.max(0, CORTES.findIndex((c, k) => T >= c && T < CORTES[k + 1]));
  const Actual = ESCENAS[n];
  const Previa = n > 0 ? ESCENAS[n - 1] : null;
  const k = steps(T, CORTES[n], 4);
  const ey = [1500, 1000, 480, -60][k - 1] ?? -60;
  return (
    <AbsoluteFill style={{background: '#000'}}>
      <Actual T={T} />
      {Previa && ey > -60 && <AbsoluteFill style={{background: '#ece6d8', clipPath: clipArriba(ey + 16)}} />}
      {Previa && ey > -60 && <AbsoluteFill style={{clipPath: clipArriba(ey)}}><Previa T={CORTES[n] - 0.05} /></AbsoluteFill>}
      <Subtitulo T={T} />
    </AbsoluteFill>
  );
};
