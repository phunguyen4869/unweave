import React from 'react';
import {AbsoluteFill, Easing, Sequence, interpolate, interpolateColors, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {BODY, C, DISPLAY, STEMS, noise, useScale, useVertical} from './theme';

// Scene timing in frames (30 fps). Neighbours overlap by FADE so they cross-fade.
const FADE = 15;
// Key moments sit on a 138.5 BPM grid (one beat every BEAT frames, beat 0 at frame -4)
// so music added in an editor can be cut to them.
export const BEAT = 13;
export const beatFrame = (beat: number) => -4 + beat * BEAT;
export const SCENES = {
  split: {from: 0, duration: 240},
  progress: {from: 225, duration: 165},
  mixer: {from: 375, duration: 152},
  features: {from: 512, duration: 108},
  outro: {from: 605, duration: 115},
};
export const INTRO_FRAMES = 720;
// Key moments, in global frames.
export const BEATS = {
  split: beatFrame(8),
  done: beatFrame(28),
  drumsMute: [beatFrame(32), beatFrame(35)] as const,
  vocalSolo: [beatFrame(35), beatFrame(38)] as const,
  slams: [40, 42, 44, 46].map(beatFrame),
  outro: beatFrame(48),
};

const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;
const GRAD = 'linear-gradient(135deg, #ffb35c 0%, #ff8a3d 45%, #ff5c6c 100%)';

/* ---------- shared pieces ---------- */

const Fade: React.FC<{duration: number; first?: boolean; last?: boolean; children: React.ReactNode}> = ({duration, first, last, children}) => {
  const frame = useCurrentFrame();
  const fadeIn = first ? 1 : interpolate(frame, [0, FADE], [0, 1], clamp);
  const fadeOut = last ? 1 : interpolate(frame, [duration - FADE, duration], [1, 0], clamp);
  return <AbsoluteFill style={{opacity: Math.min(fadeIn, fadeOut)}}>{children}</AbsoluteFill>;
};

/** Word-by-word reveal: each word rises out of a blur; `accent` words get the brand gradient. */
const Kinetic: React.FC<{text: string; start: number; end: number; top: number; size?: number; accent?: string[]}> = ({text, start, end, top, size = 64, accent = []}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const s = useScale();
  const out = interpolate(frame, [end - 10, end], [0, 1], clamp);
  if (frame < start - 1 || frame > end) return null;
  return (
    <div style={{position: 'absolute', top: top * s, left: 0, right: 0, display: 'flex', justifyContent: 'center', flexWrap: 'wrap',
      gap: `0 ${size * 0.26 * s}px`, padding: `0 ${60 * s}px`, fontFamily: DISPLAY, fontWeight: 700, fontSize: size * s,
      letterSpacing: -size * 0.03 * s, lineHeight: 1.1}}>
      {text.split(' ').map((word, i) => {
        const p = spring({frame: frame - start - i * 3, fps, config: {damping: 200, stiffness: 140}});
        const lit = accent.includes(word);
        return (
          <span key={i} style={{display: 'inline-block', opacity: p * (1 - out), filter: `blur(${(1 - p) * 14 + out * 10}px)`,
            transform: `translateY(${((1 - p) * 40 - out * 20) * s}px)`,
            ...(lit ? {background: GRAD, WebkitBackgroundClip: 'text', backgroundClip: 'text', color: 'transparent'} : {color: C.text})}}>
            {word}
          </span>
        );
      })}
    </div>
  );
};

const ORB: [number, string][] = [[0, C.accent], [240, '#5ec8ff'], [390, '#b48cff'], [540, '#4fe0a8'], [640, C.accent]];

const Backdrop: React.FC = () => {
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();
  const s = useScale();
  const orb = interpolateColors(frame, ORB.map(o => o[0]), ORB.map(o => o[1]));
  const drift = Math.sin(frame / 50) * 8;
  const fade = 'linear-gradient(to top, rgba(0,0,0,0.55), transparent 85%)';
  return (
    <AbsoluteFill style={{background: C.bg, overflow: 'hidden'}}>
      <AbsoluteFill style={{background: `radial-gradient(55% 45% at ${50 + drift}% 42%, ${orb}30, transparent 70%)`}} />
      <AbsoluteFill style={{background: `radial-gradient(35% 35% at ${75 - drift}% 85%, ${orb}18, transparent 70%)`}} />
      {/* receding floor grid for depth */}
      <div style={{position: 'absolute', left: -width * 0.5, right: -width * 0.5, bottom: -height * 0.15, height: height * 0.6,
        transform: 'perspective(900px) rotateX(70deg)', transformOrigin: 'bottom',
        backgroundImage: `linear-gradient(${C.line} 1px, transparent 1px), linear-gradient(90deg, ${C.line} 1px, transparent 1px)`,
        backgroundSize: `${80 * s}px ${80 * s}px`, backgroundPosition: `0 ${(frame * 1.2 * s) % (80 * s)}px`,
        maskImage: fade, WebkitMaskImage: fade}} />
      {Array.from({length: 46}, (_, i) => {
        const speed = 0.3 + noise(i + 99) * 0.9;
        const y = (noise(i + 7) * height - frame * speed * s + height * 2) % height;
        const size = (1.5 + noise(i + 33) * 3.5) * s;
        const twinkle = 0.25 + 0.5 * (0.5 + 0.5 * Math.sin(frame / 9 + i));
        return <div key={i} style={{position: 'absolute', left: noise(i) * width + Math.sin(frame / 40 + i) * 12 * s, top: y, width: size, height: size,
          borderRadius: 99, background: i % 3 ? C.text : orb, opacity: twinkle * 0.5, boxShadow: `0 0 ${size * 3}px ${orb}`}} />;
      })}
    </AbsoluteFill>
  );
};

const Overlay: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{pointerEvents: 'none'}}>
      <AbsoluteFill style={{background: 'radial-gradient(75% 75% at 50% 50%, transparent 55%, rgba(0,0,0,0.6))'}} />
      <svg width="100%" height="100%" style={{position: 'absolute', opacity: 0.07, mixBlendMode: 'overlay'}}>
        <filter id="grain"><feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed={frame % 8} /></filter>
        <rect width="100%" height="100%" filter="url(#grain)" />
      </svg>
    </AbsoluteFill>
  );
};

const Flash: React.FC<{at: number; color?: string; strength?: number}> = ({at, color = '#fff', strength = 0.45}) => {
  const frame = useCurrentFrame();
  const o = interpolate(frame, [at, at + 2, at + 16], [0, strength, 0], clamp);
  return o > 0 ? <AbsoluteFill style={{background: `radial-gradient(50% 50% at 50% 50%, ${color}, transparent 75%)`, opacity: o}} /> : null;
};

const Shockwave: React.FC<{at: number; x: number; y: number; color: string}> = ({at, x, y, color}) => {
  const frame = useCurrentFrame();
  const s = useScale();
  const t = interpolate(frame, [at, at + 28], [0, 1], {...clamp, easing: Easing.out(Easing.cubic)});
  if (frame < at || t >= 1) return null;
  const r = t * 900 * s;
  return <div style={{position: 'absolute', left: x - r, top: y - r, width: r * 2, height: r * 2, borderRadius: '50%',
    border: `${(1 - t) * 6 * s}px solid ${color}`, opacity: 1 - t, boxShadow: `0 0 ${40 * s}px ${color}`}} />;
};

const Burst: React.FC<{at: number; x: number; y: number}> = ({at, x, y}) => {
  const frame = useCurrentFrame();
  const s = useScale();
  const t = interpolate(frame, [at, at + 30], [0, 1], {...clamp, easing: Easing.out(Easing.quad)});
  if (frame < at || t >= 1) return null;
  return (
    <>
      {Array.from({length: 28}, (_, i) => {
        const a = (i / 28) * Math.PI * 2 + noise(i) * 0.3;
        const d = (120 + noise(i + 5) * 260) * s * t;
        const color = STEMS[i % STEMS.length].color;
        const size = (4 + noise(i + 9) * 6) * s * (1 - t * 0.6);
        return <div key={i} style={{position: 'absolute', left: x + Math.cos(a) * d - size / 2, top: y + Math.sin(a) * d - size / 2,
          width: size, height: size, borderRadius: 99, background: color, opacity: 1 - t, boxShadow: `0 0 ${12 * s}px ${color}`}} />;
      })}
    </>
  );
};

const Logo: React.FC<{size: number; pulse?: number}> = ({size, pulse = 0}) => {
  const bars = [[8, 13, 19], [12, 9, 23], [16, 12, 20], [20, 7, 25], [24, 11, 21]];
  return (
    <svg viewBox="0 0 32 32" width={size} height={size}>
      <defs><linearGradient id="logo" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#ffb35c" /><stop offset="0.45" stopColor="#ff8a3d" /><stop offset="1" stopColor="#ff5c6c" /></linearGradient></defs>
      <rect width="32" height="32" rx="9" fill="url(#logo)" />
      <g stroke={C.onAccent} strokeWidth="2.4" strokeLinecap="round">
        {bars.map(([x, y1, y2], i) => {
          const grow = Math.sin(pulse / 5 + i * 1.3) * 1.6 * Math.min(1, pulse / 10);
          return <line key={x} x1={x} x2={x} y1={y1 - grow} y2={y2 + grow} />;
        })}
      </g>
    </svg>
  );
};

/* ---------- 1-2: one waveform splits into stems ---------- */

const WaveSplit: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps, width} = useVideoConfig();
  const s = useScale();
  const vertical = useVertical();
  const bars = vertical ? 48 : 72;
  const area = Math.min(1460 * s, width - 180 * s);
  const barGap = area / bars;
  const laneGap = (vertical ? 150 : 104) * s;
  const centreY = vertical ? 1000 * s : 600 * s;
  const appear = interpolate(frame, [0, 34], [0, 1], {...clamp, easing: Easing.out(Easing.cubic)});
  const push = interpolate(frame, [0, 240], [0.94, 1.06]);
  const tilt = interpolate(frame, [0, 120], [24, 4], {...clamp, easing: Easing.out(Easing.cubic)});
  const exit = interpolate(frame, [205, 240], [0, 1], {...clamp, easing: Easing.in(Easing.cubic)});
  const sweep = interpolate(frame, [30, 90], [-0.2, 1.2], clamp);
  return (
    <AbsoluteFill>
      <Kinetic text="One song." start={8} end={BEATS.split - 3} top={vertical ? 360 : 160} size={vertical ? 110 : 96} accent={['song.']} />
      <Kinetic text="Every part, separated." start={BEATS.split + 16} end={215} top={vertical ? 330 : 100} size={vertical ? 92 : 80} accent={['separated.']} />
      <AbsoluteFill style={{perspective: 1400 * s, opacity: 1 - exit, filter: `blur(${exit * 16}px)`}}>
        <AbsoluteFill style={{transform: `rotateX(${tilt}deg) scale(${push + exit * 0.4})`, transformOrigin: `50% ${centreY}px`}}>
          {STEMS.map((stem, lane) => {
            const split = spring({frame: frame - BEATS.split - lane * 3, fps, config: {damping: 14, stiffness: 80}});
            const y = centreY + split * (lane - 2.5) * laneGap;
            const maxH = interpolate(split, [0, 1], [300 * s, laneGap * 0.72], {extrapolateRight: 'extend'});
            const color = interpolateColors(Math.min(split, 1), [0, 1], [C.text, stem.color]);
            const label = spring({frame: frame - BEATS.split - 16 - lane * 4, fps, config: {damping: 200}});
            return (
              <React.Fragment key={stem.id}>
                <div style={{position: 'absolute', inset: 0, opacity: interpolate(split, [0, 1], [0.32, 1], clamp),
                  filter: `drop-shadow(0 0 ${10 * Math.min(split, 1) * s}px ${stem.color})`}}>
                  {Array.from({length: bars}, (_, j) => {
                    const shape = 0.45 + 0.55 * Math.sin(Math.PI * (j + 0.5) / bars);
                    const wobble = 0.55 + 0.45 * Math.sin(frame / 5 + j * 0.47 + lane * 1.7);
                    const enter = interpolate(appear * bars * 1.4 - j * 0.4, [0, 1], [0, 1], clamp);
                    const glint = Math.max(0, 1 - Math.abs(j / bars - sweep) * 9) * Math.max(0, 1 - split);
                    const h = Math.max(4 * s, maxH * shape * wobble * (0.3 + 0.7 * noise(j * 7 + lane * 131)) * enter);
                    return (
                      <div key={j} style={{position: 'absolute', left: (width - area) / 2 + j * barGap, top: y - h / 2,
                        width: barGap * 0.55, height: h, borderRadius: barGap,
                        background: glint > 0.05 ? interpolateColors(glint, [0, 1], [color, C.accent]) : color}} />
                    );
                  })}
                </div>
                <div style={{position: 'absolute', opacity: label, filter: `blur(${(1 - label) * 8}px)`, fontFamily: BODY, fontWeight: 700,
                  fontSize: 24 * s, color: stem.color, transform: `translateX(${(1 - label) * -30 * s}px)`,
                  ...(vertical
                    ? {left: (width - area) / 2, top: y - laneGap * 0.5 - 6 * s}
                    : {right: width - (width - area) / 2 + 24 * s, top: y - 16 * s})}}>
                  {stem.label}
                </div>
              </React.Fragment>
            );
          })}
        </AbsoluteFill>
      </AbsoluteFill>
      <Shockwave at={BEATS.split} x={width / 2} y={centreY} color={C.accent} />
      <Flash at={BEATS.split} color={C.accent} strength={0.35} />
    </AbsoluteFill>
  );
};

/* ---------- app window chrome shared by the two UI scenes ---------- */

const windowTop = (frameH: number, height: number, s: number, vertical: boolean) => (frameH - height * s) / 2 + (vertical ? 60 : 70) * s;

const Window: React.FC<{height: number; from: [number, number]; children: React.ReactNode}> = ({height, from, children}) => {
  const frame = useCurrentFrame();
  const {fps, width, height: frameH} = useVideoConfig();
  const s = useScale();
  const vertical = useVertical();
  const w = Math.min(1180 * s, width - 100 * s);
  const top = windowTop(frameH, height, s, vertical);
  const pop = spring({frame, fps, config: {damping: 18, stiffness: 70}});
  const rx = interpolate(pop, [0, 1], [from[0], 5]) + Math.sin(frame / 30) * 1.5;
  const ry = interpolate(pop, [0, 1], [from[1], 0]) + Math.sin(frame / 40) * 3;
  const sheen = interpolate(frame, [0, 90], [-40, 130]);
  return (
    <AbsoluteFill style={{perspective: 1600 * s}}>
      <div style={{position: 'absolute', left: (width - w) / 2, top: top + height * s * 0.9, width: w, height: 140 * s,
        background: 'radial-gradient(50% 50% at 50% 50%, rgba(255,138,61,0.28), transparent 70%)', opacity: pop, filter: `blur(${30 * s}px)`}} />
      <div style={{position: 'absolute', left: (width - w) / 2, top, width: w, height: height * s,
        background: `linear-gradient(180deg, ${C.surface2}, ${C.surface} 30%)`, border: `1px solid ${C.line}`, borderRadius: 18 * s, overflow: 'hidden',
        boxShadow: '0 60px 140px -40px rgba(0,0,0,0.9)',
        transform: `translateZ(${(1 - pop) * -500 * s}px) rotateX(${rx}deg) rotateY(${ry}deg)`, opacity: Math.min(1, pop * 1.4)}}>
        <div style={{height: 46 * s, background: '#000', display: 'flex', alignItems: 'center', gap: 10 * s, padding: `0 ${16 * s}px`}}>
          <Logo size={18 * s} />
          <span style={{fontFamily: BODY, fontSize: 15 * s, color: C.text2}}>Unweave</span>
        </div>
        <div style={{position: 'relative', height: (height - 46) * s}}>{children}</div>
        {/* glass sheen sliding across the window */}
        <div style={{position: 'absolute', inset: 0, pointerEvents: 'none',
          background: `linear-gradient(105deg, transparent ${sheen}%, rgba(255,255,255,0.07) ${sheen + 10}%, transparent ${sheen + 20}%)`}} />
      </div>
    </AbsoluteFill>
  );
};

/* ---------- 3: step-first progress ---------- */

const ProgressScene: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps, width, height: frameH} = useVideoConfig();
  const s = useScale();
  const vertical = useVertical();
  const doneAt = BEATS.done - SCENES.progress.from;
  const pct = interpolate(frame, [22, doneAt], [0, 100], {...clamp, easing: Easing.inOut(Easing.cubic)});
  const done = pct >= 100;
  const step = pct < 14 ? 'Preparing audio' : pct < 88 ? 'Separating stems' : done ? 'Done' : 'Writing stems';
  const r = 112;
  const circ = 2 * Math.PI * r;
  const head = (pct / 100) * Math.PI * 2 - Math.PI / 2;
  const glow = done ? interpolate(frame - doneAt, [0, 4, 30], [0, 1, 0.35], clamp) : 0;
  const ringScale = done ? 1 + 0.08 * Math.sin(Math.min(1, (frame - doneAt) / 10) * Math.PI) : 1;
  const winH = 600;
  const ringCentreY = windowTop(frameH, winH, s, vertical) + (46 + 80 + 150) * s;
  return (
    <AbsoluteFill>
      <Kinetic text="Drop in a file or a YouTube link." start={2} end={165} top={vertical ? 380 : 90} size={vertical ? 72 : 64} accent={['YouTube']} />
      <Window height={winH} from={[35, -20]}>
        <div style={{position: 'absolute', top: 28 * s, left: 32 * s, right: 32 * s, display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          fontFamily: BODY, fontSize: 20 * s, color: C.text}}>
          <span>demo-track.wav <span style={{color: C.text3}}>· 3:42</span></span>
          <span style={{padding: `${6 * s}px ${14 * s}px`, borderRadius: 999, background: 'rgba(255,138,61,0.12)', color: C.accent, fontSize: 16 * s, fontWeight: 600}}>6 stems</span>
        </div>
        <svg width={300 * s} height={300 * s} viewBox="0 0 300 300" style={{position: 'absolute', left: '50%', top: 80 * s, marginLeft: -150 * s,
          overflow: 'visible', transform: `scale(${ringScale})`, filter: `drop-shadow(0 0 ${(14 + glow * 26) * s}px rgba(255,138,61,0.6))`}}>
          <defs>
            <linearGradient id="ring" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor="#ffb35c" /><stop offset="45%" stopColor="#ff8a3d" /><stop offset="100%" stopColor="#ff5c6c" />
            </linearGradient>
          </defs>
          {Array.from({length: 60}, (_, i) => {
            const a = (i / 60) * Math.PI * 2 - Math.PI / 2;
            return <line key={i} x1={150 + Math.cos(a) * 132} y1={150 + Math.sin(a) * 132} x2={150 + Math.cos(a) * 139} y2={150 + Math.sin(a) * 139}
              stroke={i / 60 < pct / 100 ? C.accent : C.line} strokeWidth="2" />;
          })}
          <circle cx="150" cy="150" r={r} fill="none" stroke={C.surface2} strokeWidth="16" />
          <circle cx="150" cy="150" r={r} fill="none" stroke="url(#ring)" strokeWidth="16" strokeLinecap="round"
            strokeDasharray={circ} strokeDashoffset={circ * (1 - pct / 100)} transform="rotate(-90 150 150)" />
          {pct > 1 && !done && <circle cx={150 + Math.cos(head) * r} cy={150 + Math.sin(head) * r} r="10" fill="#fff" />}
          <text x="150" y="168" textAnchor="middle" fill={done ? '#4fe0a8' : C.text} style={{fontFamily: DISPLAY, fontWeight: 700, fontSize: 56}}>
            {done ? '✓' : `${Math.floor(pct)}%`}
          </text>
        </svg>
        <div style={{position: 'absolute', top: 400 * s, left: 0, right: 0, textAlign: 'center', fontFamily: BODY, fontWeight: 600,
          fontSize: 24 * s, color: done ? '#4fe0a8' : C.text}}>{step}</div>
        <div style={{position: 'absolute', top: 460 * s, left: 0, right: 0, display: 'flex', justifyContent: 'center', gap: 10 * s, flexWrap: 'wrap'}}>
          {STEMS.map((stem, i) => {
            const at = 22 + (doneAt - 22) * (0.88 + i * 0.02);
            const lit = frame >= at;
            const kick = lit ? Math.sin(Math.min(1, (frame - at) / 8) * Math.PI) : 0;
            return (
              <span key={stem.id} style={{padding: `${6 * s}px ${14 * s}px`, borderRadius: 999, fontFamily: BODY, fontSize: 16 * s, fontWeight: 600,
                border: `1px solid ${lit ? stem.color : C.line}`, color: lit ? stem.color : C.text3, background: lit ? `${stem.color}1f` : 'transparent',
                transform: `scale(${1 + 0.2 * kick})`, boxShadow: lit ? `0 0 ${18 * s}px ${stem.color}66` : 'none'}}>
                {stem.label}
              </span>
            );
          })}
        </div>
      </Window>
      <Burst at={doneAt} x={width / 2} y={ringCentreY} />
    </AbsoluteFill>
  );
};

/* ---------- 4: mixer ---------- */

const MixerScene: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const s = useScale();
  const vertical = useVertical();
  const local = (n: number) => n - SCENES.mixer.from;
  const [muteA, muteB] = BEATS.drumsMute.map(local);
  const [soloA, soloB] = BEATS.vocalSolo.map(local);
  const muted = (id: string) => frame >= muteA && frame < muteB && id === 'drums';
  const solo = frame >= soloA && frame < soloB ? 'vocals' : null;
  const splitIn = spring({frame: frame - soloB, fps, config: {damping: 15}});
  const head = interpolate(frame, [0, SCENES.mixer.duration], [0.04, 0.96]);
  const bars = vertical ? 46 : 70;
  const rowH = 72;
  const fixed = (150 + 14 * 3 + 34 * 2) * s;
  return (
    <AbsoluteFill>
      <Kinetic text="Mute, solo and mix every stem." start={2} end={soloB + 4} top={vertical ? 380 : 90} size={vertical ? 72 : 64} accent={['every', 'stem.']} />
      <Kinetic text="Even split guitar into lead & rhythm." start={soloB + 2} end={SCENES.mixer.duration} top={vertical ? 380 : 90} size={vertical ? 72 : 64} accent={['lead', 'rhythm.']} />
      <Window height={46 + 40 + STEMS.length * rowH} from={[20, 30]}>
        <div style={{position: 'absolute', inset: `${20 * s}px ${28 * s}px`}}>
          <div style={{position: 'absolute', top: -8 * s, bottom: 0, zIndex: 2, width: 2 * s, background: '#fff',
            boxShadow: `0 0 ${14 * s}px #fff, 0 0 ${30 * s}px ${C.accent}`, left: `calc(${fixed}px + (100% - ${fixed}px) * ${head})`}} />
          {STEMS.map((stem, i) => {
            const audible = solo ? solo === stem.id : !muted(stem.id);
            const enter = spring({frame: frame - 6 - i * 4, fps, config: {damping: 18, stiffness: 110}});
            const level = audible ? 0.3 + 0.7 * Math.abs(Math.sin(frame / 3 + i * 2)) * (0.5 + noise(Math.floor(frame / 2) + i * 50) * 0.5) : 0;
            return (
              <div key={stem.id} style={{position: 'absolute', top: i * rowH * s, left: 0, right: 0, height: (rowH - 10) * s,
                display: 'flex', alignItems: 'center', gap: 14 * s, opacity: Math.min(enter, 1),
                transform: `translateX(${(1 - enter) * 120 * s}px)`, filter: `blur(${Math.max(0, 1 - enter) * 10}px)`}}>
                <div style={{width: 150 * s, display: 'flex', alignItems: 'center', gap: 12 * s, fontFamily: BODY, fontWeight: 600, fontSize: 19 * s,
                  color: audible ? C.text : C.text3}}>
                  <span style={{width: 6 * s, height: 30 * s, borderRadius: 3 * s, background: C.surface2, position: 'relative', overflow: 'hidden'}}>
                    <span style={{position: 'absolute', bottom: 0, left: 0, right: 0, height: `${level * 100}%`, background: stem.color, boxShadow: `0 0 ${8 * s}px ${stem.color}`}} />
                  </span>
                  {stem.label}
                </div>
                {(['M', 'S'] as const).map(b => {
                  const lit = (b === 'M' && muted(stem.id)) || (b === 'S' && solo === stem.id);
                  const pulse = lit ? interpolate(frame - (b === 'M' ? muteA : soloA), [0, 4, 12], [1, 1.25, 1], clamp) : 1;
                  return (
                    <span key={b} style={{width: 34 * s, height: 34 * s, borderRadius: 8 * s, display: 'grid', placeItems: 'center',
                      fontFamily: BODY, fontSize: 14 * s, fontWeight: 700, border: `1px solid ${lit ? stem.color : C.line}`, transform: `scale(${pulse})`,
                      background: lit ? stem.color : C.surface2, color: lit ? C.onAccent : C.text3, boxShadow: lit ? `0 0 ${20 * s}px ${stem.color}` : 'none'}}>{b}</span>
                  );
                })}
                <div style={{flex: 1, height: '100%', position: 'relative', display: 'flex', alignItems: 'center', gap: 3 * s, opacity: audible ? 1 : 0.22}}>
                  {Array.from({length: bars}, (_, j) => {
                    const near = audible ? Math.max(0, 1 - Math.abs(j / bars - head) * 30) : 0;
                    return (
                      <div key={j} style={{flex: 1, height: `${(18 + 78 * noise(j * 3 + i * 97) * (0.5 + 0.5 * Math.sin(j / 4 + i))) * (1 + near * 0.25)}%`,
                        borderRadius: 4, background: stem.color, opacity: j / bars < head ? 0.95 : 0.35}} />
                    );
                  })}
                  {stem.id === 'guitar' && splitIn > 0.01 && (
                    <div style={{position: 'absolute', right: 0, top: 0, bottom: 0, display: 'flex', alignItems: 'center', gap: 8 * s,
                      paddingLeft: 40 * s, background: `linear-gradient(90deg, transparent, ${C.surface} 30%)`,
                      opacity: Math.min(splitIn, 1), transform: `translateX(${(1 - splitIn) * 30 * s}px)`}}>
                      {['Lead', 'Rhythm'].map((t, k) => (
                        <span key={t} style={{padding: `${5 * s}px ${12 * s}px`, borderRadius: 999, background: C.bg, border: '1px solid #4fe0a8',
                          color: '#7ef0c6', fontFamily: BODY, fontWeight: 600, fontSize: 15 * s, boxShadow: `0 0 ${16 * s}px rgba(79,224,168,0.5)`,
                          transform: `translateY(${(1 - splitIn) * (k ? 14 : -14) * s}px)`}}>{t}</span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </Window>
    </AbsoluteFill>
  );
};

/* ---------- 5: feature slams ---------- */

const FEATURES = ['Runs on your PC.', 'GPU accelerated.', 'YouTube import.', 'Free & open source.'];
const FEATURE_COLORS = ['#ff8a3d', '#5ec8ff', '#4fe0a8', '#b48cff'];

const FeaturesScene: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();
  const s = useScale();
  const vertical = useVertical();
  const slams = BEATS.slams.map(f => f - SCENES.features.from);
  const each = slams[1] - slams[0];
  const idx = Math.max(0, slams.filter(f => frame >= f).length - 1);
  const local = frame - slams[idx];
  const color = FEATURE_COLORS[idx];
  const p = spring({frame: local, fps, config: {damping: 14, stiffness: 160}});
  const leaving = idx < FEATURES.length - 1 ? interpolate(local, [each - 6, each], [0, 1], clamp) : 0;
  const wipe = interpolate(local, [0, 12], [-0.6, 0.6], {...clamp, easing: Easing.out(Easing.cubic)});
  return (
    <AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', overflow: 'hidden'}}>
      <div style={{position: 'absolute', width: width * 1.6, height: height * 0.42, left: -width * 0.3, top: height * 0.29,
        background: `linear-gradient(90deg, transparent, ${color}2e, transparent)`, transform: `rotate(-8deg) translateX(${wipe * width}px)`}} />
      <div style={{position: 'absolute', top: height / 2 - 150 * s, fontFamily: BODY, fontWeight: 700, fontSize: 22 * s, letterSpacing: 6 * s, color}}>
        {String(idx + 1).padStart(2, '0')} / 04
      </div>
      <div style={{fontFamily: DISPLAY, fontWeight: 700, fontSize: (vertical ? 118 : 140) * s, letterSpacing: -5 * s, color: C.text, textAlign: 'center',
        lineHeight: 1, padding: `0 ${50 * s}px`, opacity: Math.min(p, 1) * (1 - leaving), filter: `blur(${Math.max(0, 1 - p) * 18 + leaving * 14}px)`,
        transform: `scale(${1.35 - 0.35 * p - leaving * 0.08})`, textShadow: `0 0 ${60 * s}px ${color}66`}}>
        {FEATURES[idx]}
      </div>
      <div style={{position: 'absolute', top: height / 2 + (vertical ? 170 : 110) * s, width: 260 * s * Math.min(p, 1) * (1 - leaving), height: 5 * s,
        borderRadius: 9, background: color, boxShadow: `0 0 ${20 * s}px ${color}`}} />
    </AbsoluteFill>
  );
};

/* ---------- 6: bars converge into the logo ---------- */

const OutroScene: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();
  const s = useScale();
  const logoSize = 170 * s;
  const cx = width / 2;
  const cy = height / 2 - 110 * s;
  const hit = BEATS.outro - SCENES.outro.from;
  const gather = interpolate(frame, [0, hit + 1], [0, 1], {...clamp, easing: Easing.in(Easing.cubic)});
  const pop = spring({frame: frame - hit + 1, fps, config: {damping: 11, stiffness: 120}});
  const word = 'Unweave';
  const shine = interpolate(frame, [45, 80], [-20, 120]);
  return (
    <AbsoluteFill>
      {frame <= hit + 2 && Array.from({length: 36}, (_, i) => {
        const stem = STEMS[i % STEMS.length];
        const sx = noise(i + 300) * width;
        const sy = noise(i + 400) * height;
        const tx = cx + ((i % 5) - 2) * logoSize * 0.125;
        const h = (40 + noise(i) * 70) * s * (1 - gather * 0.6);
        return <div key={i} style={{position: 'absolute', left: sx + (tx - sx) * gather - 4 * s, top: sy + (cy - sy) * gather - h / 2, width: 8 * s, height: h,
          borderRadius: 9, background: stem.color, boxShadow: `0 0 ${14 * s}px ${stem.color}`}} />;
      })}
      <Flash at={hit} color={C.accent} strength={0.5} />
      <Shockwave at={hit} x={cx} y={cy} color={C.accent} />
      <div style={{position: 'absolute', left: cx - logoSize / 2, top: cy - logoSize / 2, transform: `scale(${pop})`,
        filter: `drop-shadow(0 0 ${(30 + 20 * Math.sin(frame / 8)) * s}px rgba(255,138,61,0.6))`}}>
        <Logo size={logoSize} pulse={Math.max(0, frame - hit)} />
      </div>
      <div style={{position: 'absolute', top: cy + logoSize / 2 + 30 * s, left: 0, right: 0, display: 'flex', justifyContent: 'center',
        fontFamily: DISPLAY, fontWeight: 700, fontSize: 130 * s, letterSpacing: -5 * s, lineHeight: 1.1}}>
        {word.split('').map((ch, i) => {
          const p = spring({frame: frame - hit - 7 - i * 2, fps, config: {damping: 14, stiffness: 140}});
          const pos = (i + 0.5) / word.length * 100;
          const lightness = Math.max(0, 1 - Math.abs(pos - shine) / 14);
          return <span key={i} style={{display: 'inline-block', opacity: Math.min(p, 1), transform: `translateY(${(1 - p) * 50 * s}px)`,
            filter: `blur(${Math.max(0, 1 - p) * 10}px)`, color: interpolateColors(lightness, [0, 1], [C.text, '#ffc58f']),
            textShadow: `0 0 ${30 * lightness * s}px rgba(255,170,100,0.8)`}}>{ch}</span>;
        })}
      </div>
      <div style={{position: 'absolute', top: cy + logoSize / 2 + 195 * s, left: 0, right: 0, textAlign: 'center', fontFamily: BODY, fontSize: 34 * s,
        color: C.text2, opacity: interpolate(frame, [hit + 22, hit + 36], [0, 1], clamp)}}>Split any song into stems.</div>
      <div style={{position: 'absolute', top: cy + logoSize / 2 + 255 * s, left: 0, right: 0, textAlign: 'center', fontFamily: BODY, fontWeight: 600,
        fontSize: 26 * s, color: C.accent}}>
        {'github.com/um1chc5/unweave'.slice(0, Math.floor(interpolate(frame, [hit + 32, hit + 54], [0, 26], clamp)))}
      </div>
    </AbsoluteFill>
  );
};

export const Intro: React.FC = () => (
  <AbsoluteFill>
    <Backdrop />
    <Sequence {...SCENES.split}><Fade duration={SCENES.split.duration} first><WaveSplit /></Fade></Sequence>
    <Sequence {...SCENES.progress}><Fade duration={SCENES.progress.duration}><ProgressScene /></Fade></Sequence>
    <Sequence {...SCENES.mixer}><Fade duration={SCENES.mixer.duration}><MixerScene /></Fade></Sequence>
    <Sequence {...SCENES.features}><Fade duration={SCENES.features.duration}><FeaturesScene /></Fade></Sequence>
    <Sequence {...SCENES.outro}><Fade duration={SCENES.outro.duration} last><OutroScene /></Fade></Sequence>
    <Overlay />
  </AbsoluteFill>
);
