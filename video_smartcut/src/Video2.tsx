import React, {useEffect, useState} from 'react';
import {AbsoluteFill, Img, continueRender, delayRender, staticFile, useCurrentFrame} from 'remotion';

// v2 con vox-style-animation: 24 fps, 12 fps solo en los golpes, cortes en movimiento, todo al centro, sin subtitulos repetidos.
const RED = '#E10600', YEL = '#FFD60A', INK = '#111', PAPEL = '#EFEADA';
// tiempos sacados de la alineacion por palabra de la toma de ElevenLabs
const CORTES = [0, 4, 9, 13, 17, 21.8, 25];
const GOLPES: [number, number][] = [[0.65, 1.15], [6.75, 7.15], [9, 9.3], [10.1, 10.4], [11.05, 11.35], [11.9, 12.2], [12.5, 12.8], [17.35, 18.35], [21.85, 22.35]];
const CX = 540, CY = 740; // centro de la zona segura de Reels

const useFonts = () => {
  const [h] = useState(() => delayRender('fonts'));
  useEffect(() => {
    Promise.all([new FontFace('HB', `url(${staticFile('Helvetica-Bold.ttf')})`).load(),
      new FontFace('IT', `url(${staticFile('InterTight.woff2')})`, {weight: '100 900'}).load()])
      .then((fs) => { fs.forEach((f) => (document.fonts as any).add(f)); continueRender(h); });
  }, [h]);
};

const clamp = (v: number, a = 0, b = 1) => Math.max(a, Math.min(b, v));
const outCubic = (x: number) => 1 - Math.pow(1 - clamp(x), 3);
const backOut = (x: number, s = 1.5) => { const t = clamp(x) - 1; return t * t * ((s + 1) * t + s) + 1; };
const inOut = (x: number) => { const t = clamp(x); return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; };
const kf = (T: number, keys: [number, number][]) => {
  if (T <= keys[0][0]) return keys[0][1];
  for (let i = 0; i < keys.length - 1; i++) {
    const [a, va] = keys[i], [b, vb] = keys[i + 1];
    if (T <= b) return va + (vb - va) * inOut((T - a) / (b - a));
  }
  return keys[keys.length - 1][1];
};

// color de la escena + papel al 25 %, con la mezcla que pide la skill: multiply en claros, screen en oscuros
const COLORES: Record<string, [string, 'multiply' | 'screen']> = {kraft: ['#C9A877', 'multiply'], amarillo: [YEL, 'multiply'], rojo: [RED, 'multiply'], cuadricula: [PAPEL, 'multiply'], oscuro: ['#141517', 'screen']};
const Fondo: React.FC<{src: string; T: number; a: number}> = ({src, T, a}) => {
  const k = clamp((T - a) / 5);
  const [color, modo] = COLORES[src];
  return (
    <AbsoluteFill style={{background: color}}>
      {src === 'cuadricula' && <AbsoluteFill style={{backgroundImage: 'linear-gradient(rgba(0,0,0,.07) 2px,transparent 2px),linear-gradient(90deg,rgba(0,0,0,.07) 2px,transparent 2px)', backgroundSize: '72px 72px'}} />}
      <Img src={staticFile('t_papel.jpg')} style={{position: 'absolute', left: -160 - k * 60, top: -140, width: 1400, height: 2200, transform: `scale(${1 + k * 0.05})`, mixBlendMode: modo, opacity: 0.25}} />
    </AbsoluteFill>
  );
};

// jerarquia fija: H1 es la idea (peso 900, muy grande), H2 da contexto (peso 400, mucho mas chico).
const H1 = {size: 150, peso: 900, aire: '-0.035em'}, H2 = {size: 66, peso: 400, aire: '-0.01em'};

// titular: palabra por palabra, sube desde la base con mascara y cae con leve overshoot
const Titulo: React.FC<{T: number; t: number; y: number; nivel: typeof H1; size?: number; color?: string; children: string}> = ({T, t, y, nivel, size: tam, color = '#fff', children}) => {
  const pal = children.split(' ');
  const size = tam || nivel.size;
  return (
    <div style={{position: 'absolute', left: 0, width: 1080, top: y, display: 'flex', justifyContent: 'center', columnGap: size * 0.22}}>
      {pal.map((w, i) => {
        const p = (T - t - i * 0.09) / 0.32;
        return (
          <span key={i} style={{display: 'inline-block', overflow: 'hidden', paddingTop: size * 0.12, lineHeight: 1.05}}>
            <span style={{display: 'inline-block', fontFamily: 'IT', fontWeight: nivel.peso, letterSpacing: nivel.aire, fontSize: size, color, whiteSpace: 'nowrap',
              transform: `translateY(${(1 - backOut(p)) * size * 1.15}px)`, opacity: p <= 0 ? 0 : 1}}>{w}</span>
          </span>
        );
      })}
    </div>
  );
};

const Resaltador: React.FC<{T: number; t: number; y: number; w: number; h: number}> = ({T, t, y, w, h}) => {
  const k = outCubic((T - t) / 0.3);
  if (k <= 0) return null;
  return <div style={{position: 'absolute', left: CX - w / 2, top: y, width: w * k, height: h, overflow: 'hidden', transform: 'rotate(-1.6deg)'}}><Img src={staticFile('marker_yellow.png')} style={{width: w, height: h}} /></div>;
};

const Clip: React.FC<{src: string; w: number; pos?: string; zoom?: number; zo?: string; children?: React.ReactNode; marco?: boolean}> = ({src, w, pos = '66% 50%', zoom = 1, zo = '50% 30%', children, marco = true}) => {
  const h = (w * 16) / 9;
  return (
    <div style={{position: 'relative', width: w, height: h, padding: marco ? 10 : 0, boxSizing: 'content-box', background: PAPEL, boxShadow: '14px 18px 0 rgba(0,0,0,.42)'}}>
      <div style={{position: 'relative', width: w, height: h, overflow: 'hidden', background: '#000'}}>
        <Img src={staticFile(src)} style={{width: w, height: h, objectFit: 'cover', objectPosition: pos, transform: `scale(${zoom})`, transformOrigin: zo}} />
        {children}
      </div>
    </div>
  );
};

const Centro: React.FC<{y?: number; s?: number; r?: number; x?: number; o?: number; children: React.ReactNode}> = ({y = CY, s = 1, r = 0, x = CX, o = 1, children}) => (
  <div style={{position: 'absolute', left: x, top: y, opacity: o, transform: `translate(-50%,-50%) rotate(${r}deg) scale(${s})`}}>{children}</div>
);

const Pelicula: React.FC<{x: number; y: number; alto?: number; r?: number; n?: number; cortes?: boolean}> = ({x, y, alto = 300, r = -3, n = 9}) => {
  const w = (alto - 50) * (16 / 9);
  return (
    <div style={{position: 'absolute', left: x, top: y, display: 'flex', gap: 10, padding: '25px 10px', background: '#0c0c0c', transform: `rotate(${r}deg)`, boxShadow: '12px 16px 0 rgba(0,0,0,.4)'}}>
      {Array.from({length: n}).map((_, i) => <Img key={i} src={staticFile(`h${(i % 4) + 1}.jpg`)} style={{width: w, height: alto - 50, objectFit: 'cover'}} />)}
      {[0, 1].map((k) => <div key={k} style={{position: 'absolute', left: 0, right: 0, [k ? 'bottom' : 'top']: 6, height: 13, backgroundImage: `repeating-linear-gradient(90deg,${PAPEL} 0 18px,transparent 18px 44px)`}} />)}
    </div>
  );
};

const Tijera: React.FC<{x: number; y: number; abre: number; s?: number}> = ({x, y, abre, s = 1}) => (
  <svg width={520} height={300} viewBox="0 0 520 300" style={{position: 'absolute', left: x - 260, top: y - 150, transform: `scale(${s})`, filter: 'drop-shadow(10px 14px 0 rgba(0,0,0,.4))'}}>
    {[1, -1].map((d) => (
      <g key={d} transform={`rotate(${d * abre} 300 150)`}>
        <path d={`M300 150 L500 ${150 - d * 14} L505 ${150 - d * 2} L300 ${150 + d * 20} Z`} fill="#1a1a1a" stroke={PAPEL} strokeWidth={4} />
        <circle cx={92} cy={150 + d * 58} r={58} fill="none" stroke={RED} strokeWidth={30} />
        <path d={`M300 ${150 - d * 4} L140 ${150 + d * 34}`} stroke={RED} strokeWidth={30} strokeLinecap="round" />
      </g>
    ))}
    <circle cx={300} cy={150} r={13} fill={PAPEL} stroke="#111" strokeWidth={4} />
  </svg>
);

const Logo: React.FC<{size: number; tinta?: string}> = ({size, tinta = INK}) => (
  <div style={{display: 'flex', alignItems: 'baseline', justifyContent: 'center', fontFamily: 'IT', fontWeight: 300, letterSpacing: '-0.03em', fontSize: size, color: tinta, whiteSpace: 'nowrap'}}>Smart<span style={{fontWeight: 900, color: RED}}>Cut</span></div>
);

/* ---------- 1: la pelicula de una hora se corta en clips ---------- */
const E1: React.FC<{T: number}> = ({T}) => {
  const salen = clamp((T - 2.65) / 0.45);
  const tx = -1500 + T * 310;
  return (
    <AbsoluteFill>
      <Fondo src="kraft" T={T} a={0} />
      {T < 1.5 ? <>
        <Titulo T={T} t={0.05} y={330} nivel={H2} color={INK}>¿Un video de</Titulo>
        {T >= 0.65 && <Centro y={540} s={T < 1.15 ? 1.08 : 1}><div style={{fontFamily: 'IT', fontWeight: 900, letterSpacing: '-0.04em', wordSpacing: '0.14em', fontSize: 215, color: RED, whiteSpace: 'nowrap'}}>1 hora?</div></Centro>}
      </> : <Centro y={360} s={backOut((T - 1.5) / 0.3)}><Logo size={140} /></Centro>}
      {T < 2.65 ? <>
        <Pelicula x={tx} y={790} n={10} />
        {T > 1.5 && <Tijera x={kf(T, [[1.5, -280], [2.65, 800]])} y={940} abre={8 + 14 * Math.abs(Math.sin(T * 13))} />}
      </> : [['f1', 240, -8, 0.82], ['f2', 840, 8, 0.82], ['f3', 540, 0, 1]].map(([s, x, r, e], i) => (
        <Centro key={i} x={CX + ((x as number) - CX) * outCubic(salen)} y={800 + (1 - backOut(salen)) * 300} r={(r as number) * outCubic(salen)} s={e as number}><Clip src={`${s}.jpg`} w={320} pos={s === 'f2' ? '50% 50%' : '66% 50%'} /></Centro>
      ))}
    </AbsoluteFill>
  );
};

/* ---------- 2: mejores momentos, puntuacion y seguir a quien habla ---------- */
const E2: React.FC<{T: number}> = ({T}) => {
  const zoom = kf(T, [[4, 1.45], [5.7, 1]]);
  const crece = kf(T, [[8.4, 0], [8.95, 1]]);
  const foto = T < 8.05 ? 'f1' : 'f2';
  const rx = kf(T, [[7.7, 40], [8, 480], [8.12, 90], [8.4, 330]]);
  const r = 2 * Math.PI * 92, d = clamp((T - 6.75) / 0.3);
  return (
    <AbsoluteFill>
      <Fondo src="oscuro" T={T} a={4} />
      {crece < 0.3 && <div style={{position: 'absolute', inset: 0, opacity: 1 - crece / 0.3}}>
        <Titulo T={T} t={5.05} y={285} nivel={H2}>Los mejores</Titulo>
        <Titulo T={T} t={5.73} y={365} nivel={H1} size={140} color={YEL}>momentos</Titulo>
      </div>}
      {crece < 1 && <Centro y={800} s={zoom * (1 - crece * 0.08)}>
        <div style={{position: 'relative', width: 920, height: 518, border: `10px solid ${PAPEL}`, overflow: 'hidden', background: '#000', boxShadow: '14px 18px 0 rgba(0,0,0,.5)'}}>
          <Img src={staticFile(`${foto}.jpg`)} style={{width: 920, height: 518, objectFit: 'cover'}} />
          {T > 7.6 && <>
            <div style={{position: 'absolute', inset: 0, background: 'rgba(0,0,0,.55)', opacity: clamp((T - 7.6) / 0.2)}} />
            <div style={{position: 'absolute', left: rx + (crece * (310 - rx)), top: 0, width: 291, height: 518, overflow: 'hidden', outline: `8px solid ${YEL}`}}>
              <Img src={staticFile(`${foto}.jpg`)} style={{position: 'absolute', left: -rx - (crece * (310 - rx)), top: 0, width: 920, height: 518, objectFit: 'cover'}} />
            </div>
          </>}
        </div>
      </Centro>}
      {T >= 6.75 && T < 7.6 && <Centro y={800} s={T < 7.15 ? 1.06 : 1} r={-8}>
        <svg width={260} height={260} style={{position: 'absolute', left: -130, top: -130}}><circle cx={130} cy={130} r={92} fill={INK} /><path d="M46 130 C 42 62, 110 26, 160 40 C 224 58, 234 150, 190 196 C 148 240, 54 226, 46 130" fill="none" stroke={YEL} strokeWidth={12} strokeLinecap="round" strokeDasharray={r * 1.1} strokeDashoffset={r * 1.1 * (1 - d)} /></svg>
        <div style={{fontFamily: 'HB', fontSize: 92, color: YEL, position: 'relative', transform: 'translate(-50%,-50%)'}}>85</div>
      </Centro>}
      {crece > 0 && <Centro y={800 - 60 * crece} s={0.5 + 0.5 * crece}><Clip src="f2.jpg" w={430} pos="50% 50%" /></Centro>}
    </AbsoluteFill>
  );
};

/* ---------- 3: el mismo clip, cada golpe cambia una cosa ---------- */
const PIELES = [
  {f: 'kraft', et: 'Tu marca', etc: RED, txt: '', peso: 800, act: YEL},
  {f: 'amarillo', et: 'Subtítulos', etc: INK, txt: 'TU MARCA', peso: 800, act: YEL},
  {f: 'rojo', et: 'Colores', etc: PAPEL, txt: 'TU MARCA', peso: 800, act: YEL},
  {f: 'cuadricula', et: 'Letra', etc: RED, txt: 'Tu marca', peso: 300, act: '#fff'},
  {f: 'oscuro', et: 'Logo', etc: YEL, txt: 'TU MARCA', peso: 800, act: YEL},
];
const E3: React.FC<{T: number}> = ({T}) => {
  const PASOS = [9, 10.1, 11.05, 11.9, 12.5]; // cada cambio cae sobre su palabra
  const i = Math.max(0, PASOS.filter((a) => T >= a).length - 1);
  const p = PIELES[i], t = T - PASOS[i];
  return (
    <AbsoluteFill>
      <Fondo src={p.f} T={T} a={9} />
      <Centro y={700} s={1 + (t < 0.3 ? 0.05 * (1 - t / 0.3) : 0)}>
        <Clip src="f2.jpg" w={430} pos="50% 50%">
          <div style={{position: 'absolute', left: 0, right: 0, top: 500, textAlign: 'center', fontFamily: 'IT', fontWeight: p.peso, letterSpacing: '-0.02em', fontSize: 66, color: p.act, whiteSpace: 'nowrap', textShadow: '0 4px 0 #000,0 -4px 0 #000,4px 0 0 #000,-4px 0 0 #000'}}>{p.txt}</div>
          {i === 4 && <Img src={staticFile('logo_btc.png')} style={{position: 'absolute', left: 65, top: 620, width: 300, opacity: clamp(t / 0.15)}} />}
        </Clip>
      </Centro>
      <Centro y={1155} s={backOut(t / 0.25)} r={-2}><div style={{fontFamily: 'IT', fontWeight: 900, letterSpacing: '-0.03em', fontSize: 96, color: p.etc, whiteSpace: 'nowrap'}}>{p.et}</div></Centro>
    </AbsoluteFill>
  );
};

/* ---------- 4: se arrastra de izquierda a derecha hasta el clip ---------- */
const CHIPS = [{n: 'ZOOM', a: 13.1, c: INK, tc: '#fff'}, {n: 'IMAGEN', a: 14, c: RED, tc: '#fff'}, {n: 'LOWER THIRD', a: 14.9, c: YEL, tc: INK}];
const E4: React.FC<{T: number}> = ({T}) => {
  const activo = T < 14 ? 0 : T < 14.9 ? 1 : 2;
  const c = CHIPS[activo];
  const p = clamp((T - c.a) / 0.5); // cada uno se suelta sobre su palabra
  const x = -120 + inOut(p) * 660;
  const y = 1105 - inOut(p) * 330;
  const zoom = 1 + 0.4 * clamp((T - 13.6) / 0.25) * (T < 14 ? 1 : 1 - clamp((T - 14) / 0.2));
  return (
    <AbsoluteFill>
      <Fondo src="cuadricula" T={T} a={13} />
      <div style={{position: 'absolute', left: -40, right: -40, top: 1090, height: 110, background: '#222', filter: 'blur(5px)', opacity: 0.8}} />
      <Centro y={680}>
        <Clip src="f3.jpg" w={430} zoom={zoom} zo="62% 32%">
          {T >= 14.5 && T < 15.4 && <Img src={staticFile('thumb.jpg')} style={{position: 'absolute', left: 40, top: 110, width: 350, border: `7px solid ${PAPEL}`, transform: `rotate(-4deg) scale(${backOut((T - 14.5) / 0.25)})`}} />}
          {T >= 15.4 && <div style={{position: 'absolute', left: 22 - (1 - outCubic((T - 15.4) / 0.3)) * 450, top: 500, background: 'rgba(12,12,14,.94)', borderLeft: `12px solid ${YEL}`, padding: '12px 22px'}}><div style={{fontFamily: 'HB', fontSize: 36, color: '#fff'}}>TU INVITADO</div><div style={{fontFamily: 'HB', fontSize: 23, color: YEL}}>FUNDADOR</div></div>}
        </Clip>
      </Centro>
      {p < 1 && <div style={{position: 'absolute', left: x - 90, top: y + 70, background: c.c, color: c.tc, fontFamily: 'HB', fontSize: 42, padding: '12px 26px', whiteSpace: 'nowrap', boxShadow: '8px 10px 0 rgba(0,0,0,.35)'}}>{c.n}</div>}
      <svg width={190} height={230} viewBox="0 0 90 110" style={{position: 'absolute', left: T > 15.45 ? x + (T - 15.45) * 1200 : x, top: y - 30, filter: 'drop-shadow(8px 10px 0 rgba(0,0,0,.35))'}}><path d="M8 6 L8 84 L28 66 L44 100 L60 92 L44 60 L72 58 Z" fill={INK} stroke={PAPEL} strokeWidth={6} strokeLinejoin="round" /></svg>
    </AbsoluteFill>
  );
};

/* ---------- 5: portadas e interruptores de intro y outro ---------- */
const Interruptor: React.FC<{T: number; t: number; texto: string}> = ({T, t, texto}) => {
  const k = outCubic((T - t) / 0.2);
  return (
    <div style={{textAlign: 'center', width: 340}}>
      <div style={{fontFamily: 'IT', fontWeight: 400, fontSize: 66, color: INK}}>{texto}</div>
      <div style={{position: 'relative', width: 180, height: 84, margin: '8px auto 0', borderRadius: 42, background: k > 0.5 ? RED : '#8c8473', border: `6px solid ${INK}`}}>
        <div style={{position: 'absolute', top: 5, left: 6 + 92 * k, width: 62, height: 62, borderRadius: 31, background: PAPEL, border: `4px solid ${INK}`}} />
      </div>
    </div>
  );
};
const E5: React.FC<{T: number}> = ({T}) => {
  const fase2 = T >= 18.85;
  return (
    <AbsoluteFill>
      <Fondo src={fase2 ? 'cuadricula' : 'kraft'} T={T} a={17} />
      {!fase2 ? <>
        <Titulo T={T} t={17.05} y={285} nivel={H2} color={INK}>Cada clip, su</Titulo>
        <Titulo T={T} t={18} y={365} nivel={H1} size={140} color={RED}>portada</Titulo>
        {[['p1', -1, -10, 17.39], ['p3', 1, 10, 17.69], ['p2', 0, 0, 18.04]].map(([s, l, r, t]) => {
          const k = backOut((T - (t as number)) / 0.3);
          return (T >= (t as number)) ? <Centro key={s as string} x={CX + (l as number) * 270} y={830 + (l ? 30 : 0)} r={(r as number)} s={k * 0.82}><div style={{background: PAPEL, padding: 10, boxShadow: '14px 18px 0 rgba(0,0,0,.42)'}}><Img src={staticFile(`${s}.jpg`)} style={{width: 360, height: 640, objectFit: 'cover', display: 'block'}} /></div></Centro> : null;
        })}
      </> : <>
        <Centro y={385}><div style={{display: 'flex', gap: 60}}><Interruptor T={T} t={18.97} texto="Intro" /><Interruptor T={T} t={19.61} texto="Outro" /></div></Centro>
        {T >= 19.85 && <Centro y={830} s={backOut((T - 19.85) / 0.3)} r={-1.2}>
          <div style={{width: 740, background: '#0E131F', padding: '26px 34px', border: `10px solid ${PAPEL}`, boxShadow: '14px 18px 0 rgba(0,0,0,.42)', textAlign: 'center'}}>
            <Img src={staticFile('logo_btc.png')} style={{width: 380, marginBottom: 20}} />
            <Img src={staticFile('thumb.jpg')} style={{width: 660, display: 'block', margin: '0 auto 18px'}} />
            <div style={{fontFamily: 'HB', fontSize: 42, color: '#fff'}}>DISPONIBLE EN YOUTUBE</div>
          </div>
        </Centro>}
      </>}
    </AbsoluteFill>
  );
};

/* ---------- 6: logo, tijera y vuelta al inicio ---------- */
const E6: React.FC<{T: number}> = ({T}) => (
  <AbsoluteFill>
    <Fondo src="amarillo" T={T} a={21.8} />
    <Centro y={590} s={T < 21.85 ? 0.2 : T < 22.35 ? 1.08 : 1}><Logo size={200} /></Centro>
    {T >= 23.05 && <Centro y={740} s={backOut((T - 23.05) / 0.3)}><div style={{fontFamily: 'IT', fontWeight: 400, fontSize: 66, color: INK, whiteSpace: 'nowrap'}}>Tus videos, tu marca.</div></Centro>}
    <Pelicula x={-1400 + (T - 22) * 290} y={920} n={10} r={-3} />
  </AbsoluteFill>
);

/* ---------- la tira borrosa que cruza de izquierda a derecha y esconde cada corte ---------- */
const Cruce: React.FC<{T: number}> = ({T}) => {
  const c = CORTES.find((x) => Math.abs(T - x) < 0.26);
  if (c === undefined) return null;
  const x = -1700 + ((T - c + 0.26) / 0.52) * 2980;
  return (
    <div style={{position: 'absolute', left: x, top: -120, width: 1700, height: 2160, background: '#0b0b0b', transform: 'rotate(-5deg)', filter: 'blur(5px)'}}>
      {[0, 1].map((k) => <div key={k} style={{position: 'absolute', top: 0, bottom: 0, [k ? 'right' : 'left']: 34, width: 44, backgroundImage: `repeating-linear-gradient(0deg,${PAPEL} 0 56px,transparent 56px 130px)`}} />)}
    </div>
  );
};

const ESCENAS = [E1, E2, E3, E4, E5, E6];

export const Video2: React.FC = () => {
  useFonts();
  const R = useCurrentFrame() / 24;
  const T = GOLPES.some(([a, b]) => R >= a && R < b) ? Math.floor(R * 12) / 12 : R; // 12 fps solo en los golpes
  const n = Math.max(0, CORTES.findIndex((c, k) => T >= c && T < CORTES[k + 1]));
  const Actual = ESCENAS[n];
  return (
    <AbsoluteFill style={{background: '#000', overflow: 'hidden'}}>
      <Actual T={T} />
      <Img src={staticFile('o_comic.jpg')} style={{position: 'absolute', inset: 0, width: 1080, height: 1920, mixBlendMode: 'hard-light', opacity: 0.16}} />
      {R < 1 && <AbsoluteFill style={{background: '#000', opacity: Math.floor(R * 12) % 3 === 0 ? 0.05 : 0}} />}
      <Cruce T={R} />
    </AbsoluteFill>
  );
};
