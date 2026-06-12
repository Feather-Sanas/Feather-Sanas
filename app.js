/* ============================================================
   Sani — the Sanas.ai Speech AI Consultant  (Phase 1 / MVP)
   A working front-end prototype of the product specified in
   "The Sanas.ai Speech AI Consultant — Merged v1.0".

   Implements (client-side, no backend required):
     F1  Grounded Q&A with visible sources
     F2  Persona-aware register (Buyer-CX, Buyer-IT, Developer, Curious)
         + orthogonal skeptic-stance overlay
     F3  Speech Science Educator (Acoustic Reconstruction, Dual-Decoder)
     F4  Use-Case Recommendation Engine (decision tree)
     F5  Dual-mode audio: curated 3-scenario showroom + upload probe
     F6  ROI snapshot (3-input)
     F7  Developer quickstart (curl/Python/Node) + sandbox key
     F8  Human handoff
     F9  Session-scoped memory + session UUID (F11)
     F10 Eight-layer debug trace
     F11 Bot self-observability event stream (internal debug drawer)
     F12 Voice-principle guardrails (no emoji / no superlatives / refusals)

   Voice principles (§5): credible first, precise, active voice,
   evidence-oriented, calibrated confidence, no superlatives, no emoji.
   ============================================================ */

/* ---------- tiny helpers ---------- */
const $ = (sel, root = document) => root.querySelector(sel);
const el = (tag, props = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === 'class') n.className = v;
    else if (k === 'html') n.innerHTML = v;
    else if (k.startsWith('on') && typeof v === 'function') n.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined) n.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid == null) continue;
    n.appendChild(typeof kid === 'string' ? document.createTextNode(kid) : kid);
  }
  return n;
};
const uuid = () => 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
  const r = (Math.random() * 16) | 0;
  return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
});
const waveSVG = (fill = '#000') => `<svg viewBox="0 0 100 100" fill="${fill}" xmlns="http://www.w3.org/2000/svg"><path d="M50 50 A25 25 0 0 1 75 25 L75 50 Z"/><path d="M50 50 A25 25 0 0 0 25 75 L25 50 Z"/></svg>`;

/* ============================================================
   KNOWLEDGE BASE  — every Sani factual claim is traceable to a chunk.
   (F1: grounded retrieval; F3 educator content; §7.7 compliance.)
   Sourced from the product spec's stated architecture & claims.
   ============================================================ */
const KB = [
  { id: 'kb-models', src: 'Product Overview', url: '/products',
    tags: ['what','do','sanas','product','overview','models','reconstruct'],
    text: 'Sanas changes how a voice sounds in real time so agents and customers understand each other. The three core models are Accent Translation, Speech Enhancement, and Real-Time Translation. Sanas reconstructs the voice signal rather than filtering it, so the result sounds natural rather than processed.' },
  { id: 'kb-accent', src: 'Accent Translation spec', url: '/products/accent-translation',
    tags: ['accent','offshore','dialect','intelligibility','translation','manila','bpo'],
    text: 'Accent Translation modulates 480+ dialects into a target-market output (US, UK, or AU) in real time at sub-200ms latency, preserving the speaker’s vocal identity.' },
  { id: 'kb-enhance', src: 'Speech Enhancement spec', url: '/products/speech-enhancement',
    tags: ['noise','noisy','enhancement','background','ambient','cafe','isolate','16khz'],
    text: 'Speech Enhancement isolates the foreground voice from ambient noise and reconstructs it at 16kHz or higher, for agents in noisy home or open-plan environments.' },
  { id: 'kb-rtt', src: 'Real-Time Translation spec', url: '/products/real-time-translation',
    tags: ['language','translate','translation','multilingual','13','markets','prosody'],
    text: 'Real-Time Translation performs speech-to-speech translation that preserves full vocal identity and prosodic pattern, supporting enterprises scaling into 13+ language markets.' },
  { id: 'kb-reconstruct', src: 'Sanas Science: Acoustic Reconstruction', url: '/science/reconstruction',
    tags: ['reconstruct','reconstruction','filter','natural','science','how','signal','quality'],
    text: 'Acoustic Reconstruction: Sanas models reconstruct the voice signal rather than filtering it. Filtering removes content and degrades the signal; reconstruction rebuilds it, which is why the output sounds natural and not processed. This distinction is critical for managing expectations about audio quality.' },
  { id: 'kb-dualdecoder', src: 'Sanas Science: Dual-Decoder Architecture', url: '/science/dual-decoder',
    tags: ['dual','decoder','architecture','harmonic','noise','consonant','vowel','fricative','technical'],
    text: 'The Dual-Decoder architecture separates harmonic content (vowels, tonal structure) from noise-like content (consonants, fricatives, ambient interference). Each is processed through a separate decoder pathway, then recombined. Harmonic content carries vocal identity and is preserved; dialect-specific patterns are remapped.' },
  { id: 'kb-latency', src: 'Architecture: latency', url: '/architecture',
    tags: ['latency','200ms','fast','realtime','real-time','speed','ms'],
    text: 'Target real-time latency is under 200ms for the accent translation path. Latency by deployment topology and region is documented in the architecture pages.' },
  { id: 'kb-zk', src: 'Trust Center: Zero-Knowledge processing', url: '/security/zero-knowledge',
    tags: ['zero','knowledge','data','residency','on-prem','onprem','private','cloud','perimeter','security','store'],
    text: 'Zero-Knowledge deployment runs on-prem or in your private cloud. No audio is stored or transmitted externally during real-time processing; the audio never leaves your perimeter.' },
  { id: 'kb-iso', src: 'Trust Center: certifications', url: '/security/compliance',
    tags: ['iso','27001','soc','soc2','gdpr','compliance','certification','certified','security'],
    text: 'Sanas holds ISO 27001 certification and SOC 2 Type II, and operates under GDPR for EU personal data. Certifications are documented in the Trust Center.' },
  { id: 'kb-analytics', src: 'Analytics layer', url: '/products/analytics',
    tags: ['csat','aht','fcr','analytics','metrics','reporting','measure','impact','roi'],
    text: 'An integrated reporting layer correlates accent intelligibility with operational metrics including AHT (average handle time), CSAT, and FCR (first-call resolution).' },
  { id: 'kb-api', src: 'Developer docs: quickstart', url: '/docs/quickstart',
    tags: ['api','sdk','developer','code','curl','python','node','integrate','endpoint','sandbox'],
    text: 'The Sanas API exposes real-time streaming endpoints with SDKs for Python and Node. Sandbox keys are scoped, rate-limited, and disposable. Full reference is at /docs.' },
  { id: 'kb-debug', src: 'Observability: eight-layer model', url: '/docs/observability',
    tags: ['debug','trace','observability','layer','probe','latency','breakdown','eight'],
    text: 'Every request is traced across eight layers: client, transport, ingress, queue, inference, ASR, return, playback. Each layer reports measured latency and a health badge. This is the same probe data SREs see internally.' },
];

/* simple lexical retrieval over the KB (stands in for the RAG vector store) */
function retrieve(query, k = 3) {
  const q = query.toLowerCase();
  const words = q.split(/[^a-z0-9]+/).filter(w => w.length > 2);
  const scored = KB.map(chunk => {
    let score = 0;
    for (const t of chunk.tags) if (q.includes(t)) score += 2;
    for (const w of words) if (chunk.tags.includes(w)) score += 1;
    return { chunk, score };
  }).filter(s => s.score > 0).sort((a, b) => b.score - a.score);
  const top = scored.slice(0, k);
  // retrieval confidence: normalised top score (0..1)
  const confidence = top.length ? Math.min(1, top[0].score / 6) : 0;
  return { chunks: top.map(s => s.chunk), confidence };
}

/* ============================================================
   RECOMMENDATION ENGINE (F4) — decision tree from §7.4
   ============================================================ */
const RECS = [
  { match: ['offshore','accent','manila','understand','dialect','intelligib'],
    product: 'Accent Translation',
    why: 'Modulates 480+ dialects into US/UK/AU output in real time at sub-200ms latency.', src: 'kb-accent' },
  { match: ['noise','noisy','background','ambient','cafe','open-plan','open plan','home'],
    product: 'Speech Enhancement',
    why: 'Isolates foreground voice from ambient noise and reconstructs at 16kHz or higher.', src: 'kb-enhance' },
  { match: ['language','languages','multilingual','13','markets','translate to','spanish','tagalog','hindi'],
    product: 'Real-Time Translation',
    why: 'Speech-to-speech translation preserving full vocal identity and prosodic pattern.', src: 'kb-rtt' },
  { match: ['csat','aht','measure','data','impact','metrics','prove','roi','reduce handle'],
    product: 'Accent Translation + Analytics',
    why: 'Integrated reporting correlates accent intelligibility with AHT and CSAT.', src: 'kb-analytics' },
  { match: ['security','residency','on-prem','onprem','private cloud','data','compliance','store','perimeter'],
    product: 'Zero-Knowledge Deployment',
    why: 'On-prem or private-cloud topology; no audio stored or transmitted externally.', src: 'kb-zk' },
];
function recommend(text) {
  const t = text.toLowerCase();
  const hits = RECS.filter(r => r.match.some(m => t.includes(m)));
  return hits;
}

/* ============================================================
   PERSONA + SKEPTIC DETECTION (§3.5, F2)
   Combines: explicit chip selection + first-message intent.
   (Referrer/page-path signals are simulated via a selectable
    "entry page" in a real deploy; here intent + chip drive it.)
   ============================================================ */
const PERSONAS = {
  curious:  { label: 'Just looking', em: '○', register: 'plain-language explainers, soft CTA' },
  buyer_cx: { label: 'CX buyer',     em: '◆', register: 'quantified outcomes (AHT, CSAT, FCR), case studies' },
  buyer_it: { label: 'IT / Security',em: '■', register: 'architecture, certifications, deployment topology' },
  developer:{ label: 'Developer',    em: '▸', register: 'technical, code snippets, sandbox, latency' },
};
function classifyPersona(text, current) {
  const t = text.toLowerCase();
  if (/\b(api|sdk|curl|endpoint|latency|sandbox|integrat|code|python|node|deepgram|elevenlabs|krisp|wer)\b/.test(t)) return 'developer';
  if (/\b(iso|soc 2|soc2|gdpr|compliance|security|residency|on-?prem|architecture|certif|data)\b/.test(t)) return 'buyer_it';
  if (/\b(csat|aht|fcr|roi|seats|agents|bpo|call center|cost|savings|demo|pilot)\b/.test(t)) return 'buyer_cx';
  return current || 'curious';
}
function skepticScore(text) {
  const t = text.toLowerCase();
  let s = 0;
  if (/\b(really|actually|prove|proof|sure|claim|honest|noticeable?|notice)\b/.test(t)) s += 0.4;
  if (/\?$/.test(t.trim()) && t.split(' ').length <= 8) s += 0.3;
  if (/\b(too good|skeptic|doubt|gimmick|marketing|hype|works\??)\b/.test(t)) s += 0.4;
  return Math.min(1, s);
}

/* ============================================================
   AUDIO SHOWROOM (F5) — three curated scenarios.
   Audio is synthesised live via Web Audio so the before/after
   toggle genuinely plays without shipping media files.
   "before" = voice tone + scenario noise; "after" = clean,
   reconstructed-sounding tone. Demonstrates the mechanic.
   ============================================================ */
const SCENARIOS = {
  cafe:     { name: 'Noisy Cafe', desc: 'Broadband background noise — tests Speech Enhancement under espresso machines and ambient chatter.', noise: 'broadband' },
  floor:    { name: 'Call Center Floor', desc: 'Overlapping agent conversations — tests foreground voice isolation under competing speech.', noise: 'babble' },
  offshore: { name: 'Offshore Agent Baseline', desc: 'Raw audio from a target dialect region — the primary Accent Translation demo for CX leaders.', noise: 'accent' },
};
let _audioCtx = null;
const audioCtx = () => (_audioCtx ||= new (window.AudioContext || window.webkitAudioContext)());

/* ---- backend (Sanas SDK orchestrator) ---- */
const SAN_API = (window.SAN_API_BASE || '').replace(/\/$/, ''); // same-origin by default
async function fetchHealth() {
  try { const r = await fetch(SAN_API + '/api/health'); return r.ok ? await r.json() : null; }
  catch { return null; }
}
/* Route conversational prose through Claude (backend). Returns text, or null
   to signal the caller to use the deterministic rule-based reply instead. */
async function llmChat(history, persona, skeptic) {
  const msgs = history.filter(h => h.text)
    .map(h => ({ role: h.role === 'san' ? 'assistant' : 'user', content: h.text }));
  while (msgs.length && msgs[0].role !== 'user') msgs.shift();
  if (!msgs.length) return null;
  try {
    const r = await fetch(SAN_API + '/api/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: msgs.slice(-12), persona, skeptic }),
    });
    if (!r.ok) return null;
    const data = await r.json();
    return data.mode === 'llm' ? data.text : null;
  } catch { return null; }
}
/* Streaming variant: calls onDelta(text) as tokens arrive. Resolves with
   { text, sources } — text is null on fallback/error; sources are the cited
   sanas.ai pages ({title,url}) from the X-San-Sources header (present either way). */
async function llmChatStream(history, persona, skeptic, onDelta) {
  const msgs = history.filter(h => h.text)
    .map(h => ({ role: h.role === 'san' ? 'assistant' : 'user', content: h.text }));
  while (msgs.length && msgs[0].role !== 'user') msgs.shift();
  if (!msgs.length) return { text: null, sources: [] };
  try {
    const r = await fetch(SAN_API + '/api/chat/stream', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: msgs.slice(-12), persona, skeptic }),
    });
    let sources = [];
    try { sources = JSON.parse(r.headers.get('X-San-Sources') || '[]'); } catch {}
    if (!r.ok || r.headers.get('X-San-Mode') !== 'llm' || !r.body) return { text: null, sources };
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let full = '';
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      const chunk = dec.decode(value, { stream: true });
      if (chunk) { full += chunk; onDelta(chunk); }
    }
    return { text: full.trim() || null, sources };
  } catch { return { text: null, sources: [] }; }
}
const decodeAudio = (arrBuf) => audioCtx().decodeAudioData(arrBuf.slice(0));
function playBuffer(buffer) {
  const ctx = audioCtx(); if (ctx.state === 'suspended') ctx.resume();
  const src = ctx.createBufferSource(); src.buffer = buffer; src.connect(ctx.destination); src.start();
  return src;
}

const PLAY_SVG = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>';
const STOP_SVG = '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="1.5"/></svg>';

/* reusable Play + Stop control over a buffer (getBuffer is called on each play,
   so it always plays the currently-selected before/after side). Only one global
   source plays at a time. */
let _activeHalt = null;
function audioControls(getBuffer, onPlay) {
  let src = null;
  const play = el('button', { class: 'pp-btn play', 'aria-label': 'Play', html: PLAY_SVG });
  const stop = el('button', { class: 'pp-btn stop', 'aria-label': 'Stop', html: STOP_SVG });
  stop.disabled = true;
  const halt = () => {
    if (src) { try { src.onended = null; src.stop(); } catch {} src = null; }
    stop.disabled = true; play.classList.remove('on');
    if (_activeHalt === halt) _activeHalt = null;
  };
  play.addEventListener('click', () => {
    if (_activeHalt) _activeHalt();           // stop whatever else is playing
    const buf = getBuffer(); if (!buf) return;
    src = playBuffer(buf); _activeHalt = halt;
    stop.disabled = false; play.classList.add('on');
    src.onended = () => { src = null; stop.disabled = true; play.classList.remove('on'); if (_activeHalt === halt) _activeHalt = null; };
    if (onPlay) onPlay();
  });
  stop.addEventListener('click', halt);
  const wrap = el('div', { class: 'pp' }, play, stop);
  wrap.halt = halt;
  return wrap;
}

/* POST a clip to the SDK backend through a specific model; decode both sides. */
async function processClip(input, model) {
  const fd = new FormData();
  fd.append('file', toBlob(input), 'clip.wav');
  const url = SAN_API + '/api/process' + (model ? `?model=${encodeURIComponent(model)}` : '');
  const resp = await fetch(url, { method: 'POST', body: fd });
  if (!resp.ok) throw new Error('process ' + resp.status);
  const procArr = await resp.arrayBuffer();
  const h = resp.headers;
  const meta = {
    mode: h.get('X-Sanas-Mode'), model: h.get('X-Sanas-Model'),
    snr: h.get('X-Sanas-SNR-dB'), sr: h.get('X-Sanas-Sample-Rate'), dur: h.get('X-Sanas-Duration'),
    tInfer: parseFloat(h.get('X-Sanas-T-Inference')), tIngress: parseFloat(h.get('X-Sanas-T-Ingress')),
    truncated: h.get('X-Sanas-Truncated') === '1', limit: h.get('X-Sanas-Clip-Limit-S'),
  };
  const origArr = input instanceof Blob ? await input.arrayBuffer()
    : (input instanceof ArrayBuffer ? input : null);
  const [origBuf, procBuf] = await Promise.all([
    origArr ? decodeAudio(origArr.slice(0)) : Promise.resolve(null),
    decodeAudio(procArr.slice(0)),
  ]);
  return { origBuf, procBuf, meta, origBytes: origArr, procBytes: procArr };
}

/* microphone capture via MediaRecorder; returns a record/stop toggle button. */
function recordButton(onClip) {
  const btn = el('button', { class: 'pg-input-btn' }, '● Record');
  let rec = null, stream = null, chunks = [];
  btn.addEventListener('click', async () => {
    if (rec && rec.state === 'recording') { rec.stop(); return; }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      onClip(null, 'Microphone not available in this browser.'); return;
    }
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
    catch { onClip(null, 'Microphone permission denied.'); return; }
    chunks = []; rec = new MediaRecorder(stream);
    rec.ondataavailable = e => { if (e.data.size) chunks.push(e.data); };
    rec.onstop = () => {
      stream.getTracks().forEach(t => t.stop());
      btn.classList.remove('recording'); btn.textContent = '● Record';
      onClip(new Blob(chunks, { type: rec.mimeType || 'audio/webm' }));
    };
    rec.start(); btn.classList.add('recording'); btn.textContent = '■ Stop recording';
  });
  return btn;
}
/* draw the actual min/max peaks of a decoded clip */
function drawBufferWaveform(canvas, buffer, color) {
  const ctx = canvas.getContext('2d');
  const W = canvas.width = canvas.offsetWidth * 2, H = canvas.height = canvas.offsetHeight * 2;
  ctx.clearRect(0, 0, W, H);
  const data = buffer.getChannelData(0);
  const step = Math.max(1, Math.floor(data.length / W));
  ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.beginPath();
  for (let x = 0; x < W; x++) {
    let min = 1, max = -1;
    for (let j = 0; j < step; j++) { const v = data[x * step + j] || 0; if (v < min) min = v; if (v > max) max = v; }
    ctx.moveTo(x, H / 2 + min * H * 0.45); ctx.lineTo(x, H / 2 + max * H * 0.45);
  }
  ctx.stroke();
}

function playScenario(key, processed, canvas) {
  const ctx = audioCtx();
  if (ctx.state === 'suspended') ctx.resume();
  const now = ctx.currentTime;
  const dur = 2.4;
  const master = ctx.createGain();
  master.gain.value = 0.0001;
  master.connect(ctx.destination);
  master.gain.exponentialRampToValueAtTime(0.5, now + 0.05);
  master.gain.setValueAtTime(0.5, now + dur - 0.2);
  master.gain.exponentialRampToValueAtTime(0.0001, now + dur);

  // "voice": a couple of formant-like tones, vibrato to feel speech-ish
  const voiceGain = ctx.createGain();
  voiceGain.gain.value = processed ? 0.5 : 0.32;
  voiceGain.connect(master);
  const baseF = SCENARIOS[key].noise === 'accent' ? (processed ? 150 : 118) : 140;
  [1, 2.4, 3.1].forEach((mult, i) => {
    const o = ctx.createOscillator();
    o.type = i === 0 ? 'sawtooth' : 'triangle';
    o.frequency.value = baseF * mult;
    const g = ctx.createGain();
    g.gain.value = [0.6, 0.25, 0.15][i] * (processed ? 1 : 0.85);
    // vibrato
    const lfo = ctx.createOscillator(); lfo.frequency.value = 5.5;
    const lfoG = ctx.createGain(); lfoG.gain.value = baseF * mult * 0.012;
    lfo.connect(lfoG); lfoG.connect(o.frequency); lfo.start(now); lfo.stop(now + dur);
    o.connect(g); g.connect(voiceGain); o.start(now); o.stop(now + dur);
  });

  // scenario noise (only audible in "before"; reconstruction removes it)
  if (!processed) {
    const noiseGain = ctx.createGain();
    noiseGain.gain.value = SCENARIOS[key].noise === 'accent' ? 0.05 : 0.22;
    noiseGain.connect(master);
    const buf = ctx.createBuffer(1, ctx.sampleRate * dur, ctx.sampleRate);
    const data = buf.getChannelData(0);
    for (let i = 0; i < data.length; i++) data[i] = (Math.random() * 2 - 1);
    const noise = ctx.createBufferSource(); noise.buffer = buf;
    const filt = ctx.createBiquadFilter();
    if (SCENARIOS[key].noise === 'babble') { filt.type = 'bandpass'; filt.frequency.value = 1200; filt.Q.value = 0.7; }
    else { filt.type = 'highpass'; filt.frequency.value = 600; }
    noise.connect(filt); filt.connect(noiseGain); noise.start(now); noise.stop(now + dur);
  } else {
    // processed path: gentle warmth filter on the voice to feel "reconstructed"
    const warm = ctx.createBiquadFilter(); warm.type = 'lowpass'; warm.frequency.value = 5200;
    voiceGain.disconnect(); voiceGain.connect(warm); warm.connect(master);
  }
  if (canvas) animateWaveform(canvas, processed, dur);
}

/* Prefer real curated audio files when present (assets/<key>_{before,after}.wav);
   fall back to live Web-Audio synthesis when they're absent. Drop real voice
   recordings into assets/ (see scripts/build_scenarios.sh) and they play here. */
const SCENARIO_BUFFERS = {};
async function loadScenarioAudio(key) {
  if (SCENARIO_BUFFERS[key] !== undefined) return SCENARIO_BUFFERS[key];
  try {
    const [b, a] = await Promise.all([
      fetch(`assets/${key}_before.wav`).then(r => r.ok ? r.arrayBuffer() : Promise.reject()),
      fetch(`assets/${key}_after.wav`).then(r => r.ok ? r.arrayBuffer() : Promise.reject()),
    ]);
    const [before, after] = await Promise.all([decodeAudio(b), decodeAudio(a)]);
    SCENARIO_BUFFERS[key] = { before, after };
  } catch { SCENARIO_BUFFERS[key] = 'synth'; }
  return SCENARIO_BUFFERS[key];
}
let _scnSrc = null;
async function playScenarioBest(key, processed, canvas) {
  const buf = await loadScenarioAudio(key);
  if (buf === 'synth') { playScenario(key, processed, canvas); return; }
  if (_scnSrc) { try { _scnSrc.stop(); } catch {} }
  _scnSrc = playBuffer(processed ? buf.after : buf.before);
  drawBufferWaveform(canvas, processed ? buf.after : buf.before, processed ? '#16c47f' : '#a7a7a7');
}

function animateWaveform(canvas, processed, dur) {
  const ctx = canvas.getContext('2d');
  const W = canvas.width = canvas.offsetWidth * 2;
  const H = canvas.height = canvas.offsetHeight * 2;
  const start = performance.now();
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  function frame(t) {
    const elapsed = (t - start) / 1000;
    ctx.clearRect(0, 0, W, H);
    ctx.lineWidth = 3;
    ctx.strokeStyle = processed ? '#16c47f' : '#a7a7a7';
    ctx.beginPath();
    for (let x = 0; x < W; x++) {
      const phase = x / W * Math.PI * 14 + (reduced ? 0 : elapsed * 6);
      const env = Math.sin(x / W * Math.PI);
      // "before": noisy jitter on top of the wave; "after": clean
      const jitter = processed ? 0 : (Math.random() - 0.5) * H * 0.28 * env;
      const amp = (processed ? 0.34 : 0.22) * H * env;
      const y = H / 2 + Math.sin(phase) * amp + jitter;
      x === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    }
    ctx.stroke();
    if (!reduced && elapsed < dur) requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

/* ============================================================
   APP STATE + INSTRUMENTATION (§7.8 / F11)
   ============================================================ */
const state = {
  sessionId: uuid(),
  persona: null,        // null until detected/selected
  personaExplicit: false,
  skeptic: 0,
  turn: 0,
  history: [],          // session-scoped memory (F9)
  events: [],           // self-observability event stream (F11)
  ctaTurnsAgo: 99,      // for "no more than 1 CTA per 3 turns" guardrail
};

function emit(evt) {
  const e = Object.assign({
    session_id: state.sessionId,
    turn_id: state.turn,
    ts: new Date().toISOString(),
  }, evt);
  state.events.push(e);
  renderDebug();
  return e;
}

/* ============================================================
   RESPONSE GENERATION
   Each handler returns { text, sources?, nodes?, suggestions?, cta? }
   honouring voice principles: no emoji, no superlatives, active voice.
   ============================================================ */

function srcChips(ids) {
  const pills = ids.map(id => {
    const c = KB.find(k => k.id === id) || { src: id, url: '#' };
    return el('span', { class: 'source-pill', title: c.text || '' },
      c.src, el('span', { class: 'conf' }, c.url));
  });
  return pills.length ? el('div', { class: 'sources' }, ...pills) : null;
}

/* clickable links to real sanas.ai pages cited for an answer (F1, live index) */
const LINK_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.07 0l2.5-2.5a5 5 0 0 0-7.07-7.07L11 5"/><path d="M14 11a5 5 0 0 0-7.07 0L4.43 13.5a5 5 0 0 0 7.07 7.07L13 19"/></svg>';
function linkChips(sources) {
  if (!sources || !sources.length) return null;
  const row = el('div', { class: 'src-links' });
  sources.forEach(s => {
    const a = el('a', { class: 'src-link', href: s.url, target: '_blank', rel: 'noopener noreferrer', title: s.url },
      el('span', { class: 'sl-ico', html: LINK_SVG }), document.createTextNode(s.title || s.url));
    a.addEventListener('click', () => emit({ event: 'source_click', url: s.url }));
    row.appendChild(a);
  });
  return el('div', { class: 'src-links-wrap' }, el('div', { class: 'src-links-label' }, 'Sources · sanas.ai'), row);
}

/* the canonical opening, persona-tunable (§5.3) */
function opening(persona) {
  if (persona === 'developer')
    return { text: "Hello. I'm Sani, Sanas's Speech AI specialist. The fastest path is the `sanas_remote_sdk` package — init with your endpoint and account credentials, then stream PCM through a model. Want the code, the eight-layer latency trace, or to upload a clip and hear it processed?" };
  return { text: "Hello. I'm Sani — Sanas's Speech AI specialist. Before we get into product fit, what's the actual problem you're trying to solve? A noisy environment, accent intelligibility, or something at the codec level? Tell me what you're hearing, and I'll show you what the signal looks like after we're done with it." };
}

/* ---------- ASR recognition comparison (real Whisper, via backend) ---------- */
const toBlob = (x) => (x instanceof Blob ? x : new Blob([x], { type: 'audio/wav' }));

function asrSection(loadInputs) {
  const mount = el('div', { class: 'asr-mount' });
  const btn = el('button', { class: 'asr-btn' }, 'Analyze recognition (ASR)');
  btn.addEventListener('click', async () => {
    btn.disabled = true; btn.textContent = 'Analyzing…';
    try { await runAsr(await loadInputs(), mount); emit({ event: 'asr_run' }); }
    catch { mount.innerHTML = ''; mount.appendChild(el('div', { class: 'asr-note' }, 'Could not load the audio to analyze.')); }
    finally { btn.disabled = false; btn.textContent = 'Re-run ASR'; }
  });
  return el('div', { class: 'asr-section' }, btn, mount);
}

async function runAsr(inputs, mount) {
  mount.innerHTML = '';
  mount.appendChild(el('div', { class: 'asr-loading' }, 'Transcribing before & after with Whisper…'));
  const fd = new FormData();
  fd.append('before', toBlob(inputs.before), 'before.wav');
  fd.append('after', toBlob(inputs.after), 'after.wav');
  if (inputs.reference) fd.append('reference_audio', toBlob(inputs.reference), 'reference.wav');
  let data;
  try {
    const r = await fetch(SAN_API + '/api/asr', { method: 'POST', body: fd });
    data = await r.json();
  } catch {
    mount.innerHTML = '';
    mount.appendChild(el('div', { class: 'asr-note' }, 'ASR backend unreachable — start the Sani server.'));
    return;
  }
  mount.innerHTML = '';
  mount.appendChild(asrResult(data));
}

function transcriptRow(label, t) {
  const text = t && t.text ? t.text : '(no speech detected)';
  return el('div', { class: 'asr-row' },
    el('span', { class: 'asr-lab' }, label),
    el('span', { class: 'asr-conf' }, t ? `conf ${t.confidence}` : ''),
    el('span', { class: 'asr-text' }, `“${text}”`));
}

function asrResult(data) {
  if (!data || !data.available)
    return el('div', { class: 'asr-note' },
      'ASR isn’t enabled on this backend. Add faster-whisper (it’s in requirements.txt) and restart to compute live recognition metrics.');
  const wrap = el('div', { class: 'asr-panel' });
  if (data.wer_delta != null && data.wer_before != null) {
    const wb = Math.round(data.wer_before * 100), wa = Math.round(data.wer_after * 100);
    const better = wa <= wb;
    wrap.appendChild(el('div', { class: 'asr-metric' },
      el('span', { class: 'asr-k' }, 'Word Error Rate vs clean source'),
      el('span', { class: 'asr-v' }, `${wb}% → ${wa}%`),
      el('span', { class: `asr-delta ${better ? 'good' : 'bad'}` }, `${better ? '−' : '+'}${Math.abs(wb - wa)} pts`)));
    const max = Math.max(wb, wa, 1);
    wrap.appendChild(el('div', { class: 'asr-bars' },
      el('div', { class: 'asr-bar' }, el('span', { class: 'asr-bl' }, 'before'),
        el('span', { class: 'asr-track' }, el('i', { class: 'gray', style: `width:${(wb / max) * 100}%` })), el('span', { class: 'asr-bv' }, `${wb}%`)),
      el('div', { class: 'asr-bar' }, el('span', { class: 'asr-bl' }, 'after'),
        el('span', { class: 'asr-track' }, el('i', { class: 'green', style: `width:${(wa / max) * 100}%` })), el('span', { class: 'asr-bv' }, `${wa}%`))));
  } else if (typeof data.confidence_delta === 'number') {
    const cb = data.before.confidence, ca = data.after.confidence, up = ca >= cb;
    wrap.appendChild(el('div', { class: 'asr-metric' },
      el('span', { class: 'asr-k' }, 'ASR recognition confidence'),
      el('span', { class: 'asr-v' }, `${cb} → ${ca}`),
      el('span', { class: `asr-delta ${up ? 'good' : 'bad'}` }, `${up ? '+' : ''}${ca - cb}`)));
    wrap.appendChild(el('div', { class: 'asr-subnote' },
      'An uploaded clip has no clean reference, so this is Whisper’s own confidence (higher = more recognizable), not WER.'));
  }
  wrap.appendChild(transcriptRow('Before', data.before));
  wrap.appendChild(transcriptRow('After', data.after));
  wrap.appendChild(el('div', { class: 'asr-foot' }, `Measured live with faster-whisper · ${data.model} · ${data.asr_ms}ms`));
  return wrap;
}

/* build the audio showroom node for a scenario (F5) */
function showroomNode(key) {
  const scn = SCENARIOS[key];
  const canvas = el('canvas', { class: 'waveform', 'aria-label': `Waveform for ${scn.name}` });
  const toggle = el('div', { class: 'sanas-toggle', role: 'group', 'aria-label': 'Before and after comparison' });
  let on = false;
  const play = el('button', { class: 'tg-play', 'aria-label': 'Play sample',
    html: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>' });
  const track = el('div', { class: 'tg-track', role: 'switch', 'aria-checked': 'false', tabindex: '0' },
    el('span', { class: 'state-off' }, 'Before'),
    el('span', { class: 'state-on' }, 'After'),
    el('span', { class: 'knob', html: waveSVG('#16c47f') }));
  const setOn = (v) => { on = v; toggle.classList.toggle('on', on); track.setAttribute('aria-checked', String(on)); };
  track.addEventListener('click', () => { setOn(!on); playScenarioBest(key, on, canvas); emit({ event: 'audio_toggle', scenario_played: key, processed: on }); });
  track.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); track.click(); } });
  play.addEventListener('click', () => { playScenarioBest(key, on, canvas); emit({ event: 'scenario_played', scenario_played: key, processed: on }); });
  toggle.append(play, track, el('span', { class: 'tg-label' }, 'raw ↔ Sanas'));
  // real WER delta: before/after vs the clean voice bed as reference
  const asr = asrSection(async () => {
    const grab = (u) => fetch(u).then(r => (r.ok ? r.arrayBuffer() : Promise.reject(new Error(u))));
    const [before, after, reference] = await Promise.all([
      grab(`assets/${key}_before.wav`), grab(`assets/${key}_after.wav`),
      grab('assets/raw/_voice.wav').catch(() => null),
    ]);
    return { before, after, reference };
  });
  return el('div', { class: 'showroom rich' },
    el('div', { class: 'scn-name' }, scn.name),
    el('div', { class: 'scn-desc' }, scn.desc),
    canvas, toggle, asr);
}

/* real before/after on the user's uploaded clip (F5 live path, via the SDK backend) */
function realShowroomNode(origBuf, procBuf, meta, rawBytes) {
  const canvas = el('canvas', { class: 'waveform', 'aria-label': 'Your clip waveform' });
  const toggle = el('div', { class: 'sanas-toggle', role: 'group', 'aria-label': 'Before and after' });
  let on = false;
  const track = el('div', { class: 'tg-track', role: 'switch', 'aria-checked': 'false', tabindex: '0' },
    el('span', { class: 'state-off' }, 'Before'),
    el('span', { class: 'state-on' }, 'After'),
    el('span', { class: 'knob', html: waveSVG('#16c47f') }));
  const draw = () => drawBufferWaveform(canvas, on ? procBuf : origBuf, on ? '#16c47f' : '#a7a7a7');
  const controls = audioControls(() => (on ? procBuf : origBuf));
  const setOn = v => { on = v; toggle.classList.toggle('on', on); track.setAttribute('aria-checked', String(on)); draw(); };
  track.addEventListener('click', () => { controls.halt(); setOn(!on); emit({ event: 'audio_toggle', processed: on, sanas_mode: meta.mode }); });
  track.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); track.click(); } });
  toggle.append(track, el('span', { class: 'tg-label' }, meta.mode === 'real' ? ('Sanas ' + meta.model) : 'raw ↔ cleaned'), controls);
  requestAnimationFrame(draw);
  const node = el('div', { class: 'showroom rich' },
    el('div', { class: 'scn-name' }, 'Your clip'),
    el('div', { class: 'scn-desc' }, meta.mode === 'real'
      ? `Processed live by Sanas ${meta.model} at ${meta.sr} Hz · switch Before↔After, then Play/Stop`
      : 'Mock processing — install the SDK for live Sanas output'),
    canvas, toggle);
  if (rawBytes && rawBytes.before && rawBytes.after) {
    node.appendChild(asrSection(async () => ({ before: rawBytes.before, after: rawBytes.after })));
  }
  return node;
}

/* eight-layer debug trace (F10) */
/* ---------- Playground (mimics sanas.ai/#playground, real SDK models) ---------- */
function pgMetricLine(meta) {
  const bits = [];
  if (meta.snr) bits.push(`SNR ~${meta.snr} dB`);
  if (meta.sr) bits.push(`${meta.sr} Hz`);
  if (isFinite(meta.tInfer)) bits.push(`${Math.round(meta.tInfer)}ms real-time`);
  if (meta.truncated) bits.push(`trimmed to ${meta.limit}s`);
  return bits.join(' · ');
}

/* compact before/after card with switch + play/stop, reused for single + compare */
function resultCard(label, res) {
  const { origBuf, procBuf, meta } = res;
  let on = true;                                   // default to After
  const tag = el('span', { class: 'rc-side' }, 'After');
  const sw = el('button', { class: 'rc-switch' }, 'Before ↔ After');
  const pp = audioControls(() => (on ? procBuf : origBuf));
  sw.addEventListener('click', () => { pp.halt(); on = !on; tag.textContent = on ? 'After' : 'Before'; });
  return el('div', { class: 'rc' },
    el('div', { class: 'rc-head' }, el('span', { class: 'rc-name' }, label), tag),
    el('div', { class: 'rc-meta' }, pgMetricLine(meta) || (meta.mode === 'mock' ? 'mock mode' : '')),
    el('div', { class: 'rc-ctl' }, sw, pp));
}

function playgroundNode() {
  const root = el('div', { class: 'playground rich' });
  const tabs = el('div', { class: 'pg-tabs' });
  const langRow = el('div', { class: 'pg-lang' }); langRow.hidden = true;
  const inputRow = el('div', { class: 'pg-inputs' });
  const inputPlayer = el('div', { class: 'pg-input-player' });
  const status = el('div', { class: 'pg-status' });
  const resultMount = el('div', { class: 'pg-result' });
  const comparison = el('div', { class: 'pg-compare' });
  const modelsMount = el('div', { class: 'pg-models' });
  const liveMount = el('div', { class: 'pg-live' });
  root.append(
    el('div', { class: 'pg-title' }, 'Playground'),
    el('div', { class: 'pg-sub' }, 'Record or upload a clip, then transform it with the live Sanas models. Switch Before↔After and Play/Stop to compare.'),
    tabs, langRow, inputRow, inputPlayer, status, resultMount, modelsMount, liveMount);

  const state = { features: [], models: [], feature: null, model: null, input: null };
  const fileInput = el('input', { type: 'file', accept: 'audio/*' }); fileInput.hidden = true;
  root.appendChild(fileInput);
  const setStatus = (msg, busy) => { status.textContent = msg || ''; status.classList.toggle('busy', !!busy); };
  const modelLabel = (name) => { const m = state.models.find(x => x.name === name); return m ? m.label : name; };

  async function transform() {
    const feat = state.features.find(f => f.key === state.feature);
    if (feat && (!feat.available || !state.model)) {
      resultMount.innerHTML = '';
      resultMount.appendChild(el('div', { class: 'pg-note' }, (feat.note || 'Not available in this SDK build.') + ' Try Speech Enhancement or Noise Cancellation.'));
      return;
    }
    if (!state.input) { setStatus('Record, upload, or pick a sample first.'); return; }
    setStatus(`Transforming with ${state.model}… (runs in real time, ~clip length)`, true);
    try {
      const res = await processClip(state.input, state.model);
      resultMount.innerHTML = '';
      resultMount.appendChild(resultCard(modelLabel(state.model), res));
      resultMount.appendChild(asrSection(async () => ({ before: res.origBytes, after: res.procBytes })));
      setStatus(res.meta.mode === 'real' ? `Done · live Sanas ${res.meta.model}` : 'Done · mock mode (SDK not active)');
      emit({ event: 'playground_transform', model: state.model, sanas_mode: res.meta.mode });
    } catch { setStatus('Processing failed — is the backend running?'); }
  }

  function gotInput(blob, err) {
    if (err) { setStatus(err); return; }
    if (!blob) return;
    state.input = blob;
    inputPlayer.innerHTML = '';
    inputPlayer.appendChild(el('span', { class: 'pg-il' }, 'Your input'));
    blob.arrayBuffer().then(ab => decodeAudio(ab.slice(0)))
      .then(buf => inputPlayer.appendChild(audioControls(() => buf)))
      .catch(() => inputPlayer.appendChild(el('span', { class: 'pg-il' }, '(captured)')));
    transform();
  }

  const rec = recordButton(gotInput);
  const up = el('button', { class: 'pg-input-btn' }, '⤓ Upload');
  up.addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', () => { if (fileInput.files[0]) gotInput(fileInput.files[0]); });
  const sampleSel = el('select', { class: 'pg-sample' },
    el('option', { value: '' }, 'Sample…'),
    el('option', { value: 'cafe' }, 'Noisy cafe'),
    el('option', { value: 'floor' }, 'Call-center floor'),
    el('option', { value: 'offshore' }, 'Offshore agent'));
  sampleSel.addEventListener('change', async () => {
    const k = sampleSel.value; if (!k) return;
    setStatus('Loading sample…', true);
    try { const ab = await fetch(`assets/${k}_before.wav`).then(r => r.arrayBuffer()); gotInput(new Blob([ab], { type: 'audio/wav' })); }
    catch { setStatus('Could not load sample.'); }
  });
  const liveBtn = el('button', { class: 'pg-input-btn live',
    html: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-3px"><rect x="9" y="2.5" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0"/><line x1="12" y1="18" x2="12" y2="21.5"/></svg> Speak live' });
  liveBtn.addEventListener('click', () => {
    if (liveMount.firstChild) { liveMount.innerHTML = ''; liveBtn.classList.remove('open'); return; }
    liveMount.appendChild(liveNode()); liveBtn.classList.add('open');
    liveMount.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  });
  inputRow.append(rec, up, sampleSel, liveBtn);

  async function testAll() {
    if (!state.input) { setStatus('Record, upload, or pick a sample first.'); return; }
    const real = state.models;
    comparison.innerHTML = '';
    comparison.appendChild(el('div', { class: 'pg-compare-head' }, `Testing ${real.length} models on your clip — sequential, each runs in real time…`));
    emit({ event: 'playground_test_all', count: real.length });
    for (const m of real) {
      const slot = el('div', { class: 'pg-compare-slot' }, el('span', { class: 'pg-cs-name' }, `${m.label} …`));
      comparison.appendChild(slot);
      try { const res = await processClip(state.input, m.name); slot.innerHTML = ''; slot.appendChild(resultCard(m.label, res)); }
      catch { slot.innerHTML = ''; slot.appendChild(el('div', { class: 'pg-note' }, `${m.label} — failed`)); }
    }
    comparison.appendChild(el('div', { class: 'pg-foot' }, 'Same input through every model; switch Before↔After per row.'));
  }

  function renderModels() {
    modelsMount.innerHTML = '';
    const testBtn = el('button', { class: 'pg-testall' }, 'Test all models');
    testBtn.addEventListener('click', testAll);
    modelsMount.appendChild(el('div', { class: 'pg-models-head' }, el('span', {}, `Models (${state.models.length})`), testBtn));
    const list = el('div', { class: 'pg-model-list' });
    state.models.forEach(m => {
      const row = el('div', { class: 'pg-model-row' + (m.name === state.model ? ' active' : '') },
        el('span', { class: 'pg-m-name' }, m.label),
        el('span', { class: 'pg-m-cat' }, m.category),
        el('span', { class: 'pg-m-sr' }, `${m.sample_rate} Hz`));
      row.addEventListener('click', () => { state.model = m.name; renderModels(); transform(); });
      list.appendChild(row);
    });
    modelsMount.append(list, comparison);
  }

  function selectFeature(key) {
    state.feature = key;
    const feat = state.features.find(f => f.key === key);
    [...tabs.children].forEach(c => c.classList.toggle('active', c.dataset.key === key));
    langRow.hidden = key !== 'language_translation';
    state.model = (feat && feat.available && feat.models.length) ? feat.models[0] : null;
    renderModels();
    resultMount.innerHTML = '';
    if (feat && !feat.available) resultMount.appendChild(el('div', { class: 'pg-note' }, feat.note));
    else if (state.input) transform();
  }

  fetch(SAN_API + '/api/models').then(r => r.json()).then(data => {
    state.features = data.features || [];
    state.models = data.models || [];
    state.features.forEach(f => {
      const t = el('button', { class: 'pg-tab' + (f.available ? '' : ' off'), 'data-key': f.key }, f.label,
        f.available ? null : el('span', { class: 'pg-badge' }, 'n/a'));
      t.addEventListener('click', () => selectFeature(f.key));
      tabs.appendChild(t);
    });
    const lf = state.features.find(f => f.key === 'language_translation');
    if (lf && lf.languages) {
      langRow.append(el('span', { class: 'pg-il' }, 'From'),
        el('select', { class: 'pg-langsel' }, ...lf.languages.source.map(l => el('option', {}, l))),
        el('span', { class: 'pg-il' }, 'to'),
        el('select', { class: 'pg-langsel' }, ...lf.languages.target.map(l => el('option', {}, l))));
    }
    const first = state.features.find(f => f.available) || state.features[0];
    if (first) selectFeature(first.key);
  }).catch(() => setStatus('Could not reach the backend (/api/models).'));

  return root;
}

function openPlayground() {
  openPanel();
  addMessage('san', 'Here’s the Playground — transform your own audio with the live Sanas models, list them, and test them all side by side.',
    { nodes: [playgroundNode()] });
  emit({ event: 'playground_opened' });
}

/* ---------- Live mic → models (real-time WebSocket streaming) ---------- */
function floatToInt16(f32) {
  const out = new Int16Array(f32.length);
  for (let i = 0; i < f32.length; i++) { const s = Math.max(-1, Math.min(1, f32[i])); out[i] = s < 0 ? s * 0x8000 : s * 0x7fff; }
  return out;
}
const rmsLevel = (f32) => { let s = 0; for (let i = 0; i < f32.length; i++) s += f32[i] * f32[i]; return Math.sqrt(s / f32.length); };
function concatFloat(chunks, total) { const d = new Float32Array(total); let o = 0; for (const c of chunks) { d.set(c, o); o += c.length; } return d; }
/* encode mono float32 [-1,1] as a 16-bit PCM WAV ArrayBuffer */
function encodeWav(f32, sampleRate) {
  const n = f32.length, buf = new ArrayBuffer(44 + n * 2), v = new DataView(buf);
  const w = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  w(0, 'RIFF'); v.setUint32(4, 36 + n * 2, true); w(8, 'WAVE'); w(12, 'fmt '); v.setUint32(16, 16, true);
  v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, sampleRate, true);
  v.setUint32(28, sampleRate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  w(36, 'data'); v.setUint32(40, n * 2, true);
  let o = 44; for (let i = 0; i < n; i++) { const s = Math.max(-1, Math.min(1, f32[i])); v.setInt16(o, s < 0 ? s * 0x8000 : s * 0x7fff, true); o += 2; }
  return buf;
}

function liveNode() {
  const root = el('div', { class: 'live rich' });
  const startBtn = el('button', { class: 'pg-input-btn' }, '● Start mic');
  const modelSel = el('select', { class: 'pg-langsel' });
  const onToggle = el('button', { class: 'live-toggle on' }, 'Model: ON');
  const status = el('div', { class: 'pg-status' }, 'Idle — click Start mic and allow microphone access.');
  const inBar = el('i'), outBar = el('i');
  const meters = el('div', { class: 'live-meters' },
    el('div', { class: 'live-meter' }, el('span', { class: 'lm-l' }, 'in'), el('span', { class: 'lm-track' }, inBar)),
    el('div', { class: 'live-meter' }, el('span', { class: 'lm-l' }, 'out'), el('span', { class: 'lm-track' }, outBar)));
  root.append(
    el('div', { class: 'pg-title' }, 'Speak live to the models'),
    el('div', { class: 'pg-sub' }, 'Talk into your mic and hear it transformed in real time. Toggle the model On/Off to A/B against your raw voice, and switch models on the fly.'),
    el('div', { class: 'live-ctrls' }, startBtn, modelSel, onToggle), meters, status);
  const recMount = el('div', { class: 'live-rec' });
  root.appendChild(recMount);

  let ws = null, ctx = null, mic = null, cap = null, src = null, sink = null;
  let running = false, enabled = true, playAt = 0, sr = 16000;
  const JITTER = 0.15;
  const MAX_REC = 16000 * 90;                 // cap session recording at ~90s
  let inChunks = [], outChunks = [], inLen = 0, outLen = 0;
  const setMeter = (bar, v) => { bar.style.width = Math.min(100, Math.round(v * 240)) + '%'; };

  fetch(SAN_API + '/api/models').then(r => r.json()).then(d => {
    (d.models || []).forEach(m => modelSel.appendChild(el('option', { value: m.name }, m.label)));
    if (d.default) modelSel.value = d.default;
  }).catch(() => {});

  modelSel.addEventListener('change', () => { if (ws && ws.readyState === 1) ws.send(JSON.stringify({ type: 'config', model: modelSel.value })); });
  onToggle.addEventListener('click', () => {
    enabled = !enabled; onToggle.classList.toggle('on', enabled); onToggle.textContent = 'Model: ' + (enabled ? 'ON' : 'OFF');
    if (ws && ws.readyState === 1) ws.send(JSON.stringify({ type: 'config', enabled }));
  });
  startBtn.addEventListener('click', () => running ? stop() : start());

  const wsUrl = () => (SAN_API || location.origin).replace(/^http/, 'ws') + '/api/stream';
  function schedule(i16) {
    if (!ctx) return;
    const f = new Float32Array(i16.length);
    for (let i = 0; i < i16.length; i++) f[i] = i16[i] / 32768;
    setMeter(outBar, rmsLevel(f));
    if (outLen < MAX_REC) { outChunks.push(f); outLen += f.length; }   // record model output
    const buf = ctx.createBuffer(1, f.length, sr); buf.getChannelData(0).set(f);
    const s = ctx.createBufferSource(); s.buffer = buf; s.connect(ctx.destination);
    const now = ctx.currentTime;
    if (playAt < now + 0.02) playAt = now + JITTER;       // re-arm jitter buffer if we underran
    s.start(playAt); playAt += buf.duration;
  }

  async function start() {
    try { mic = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: false, autoGainControl: false } }); }
    catch { status.textContent = 'Microphone permission denied.'; return; }
    ctx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
    sr = ctx.sampleRate;
    ws = new WebSocket(wsUrl()); ws.binaryType = 'arraybuffer';
    ws.onopen = () => ws.send(JSON.stringify({ type: 'config', model: modelSel.value, enabled }));
    ws.onmessage = (ev) => {
      if (typeof ev.data === 'string') {
        try { const m = JSON.parse(ev.data); if (m.type === 'ready') { sr = m.sample_rate || sr; status.textContent = `Live · ${m.mode}${m.mode === 'real' ? '' : ' (mock: passthrough)'} · ${m.model}` + (m.error ? ` · ${m.error}` : ''); } } catch {}
        return;
      }
      schedule(new Int16Array(ev.data));
    };
    ws.onclose = () => { if (running) stop(); };
    ws.onerror = () => { status.textContent = 'Stream connection failed — is the backend running?'; };
    src = ctx.createMediaStreamSource(mic);
    cap = ctx.createScriptProcessor(1024, 1, 1);
    cap.onaudioprocess = (e) => {
      const f = e.inputBuffer.getChannelData(0);
      setMeter(inBar, rmsLevel(f));
      if (inLen < MAX_REC) { inChunks.push(new Float32Array(f)); inLen += f.length; }  // record raw mic (copy: buffer is reused)
      if (ws && ws.readyState === 1) ws.send(floatToInt16(f).buffer);
    };
    sink = ctx.createGain(); sink.gain.value = 0;        // keeps the processor firing without echoing raw mic
    src.connect(cap); cap.connect(sink); sink.connect(ctx.destination);
    playAt = ctx.currentTime + JITTER;
    inChunks = []; outChunks = []; inLen = 0; outLen = 0; recMount.innerHTML = '';   // fresh recording
    running = true; startBtn.textContent = '■ Stop mic'; startBtn.classList.add('recording');
    emit({ event: 'live_start', model: modelSel.value });
  }
  function stop() {
    running = false; startBtn.textContent = '● Start mic'; startBtn.classList.remove('recording');
    try { if (ws) ws.close(); } catch {}
    try { if (cap) { cap.onaudioprocess = null; cap.disconnect(); } if (src) src.disconnect(); if (sink) sink.disconnect(); } catch {}
    try { if (mic) mic.getTracks().forEach(t => t.stop()); } catch {}
    try { if (ctx) ctx.close(); } catch {}
    ws = ctx = mic = cap = src = sink = null;
    setMeter(inBar, 0); setMeter(outBar, 0);
    showRecording();
    status.textContent = inLen ? 'Stopped — play back your recording below.' : 'Stopped.';
    emit({ event: 'live_stop', seconds: +(inLen / (sr || 16000)).toFixed(1) });
  }

  /* after stopping, render a Raw↔Model before/after of the whole session + ASR */
  function showRecording() {
    recMount.innerHTML = '';
    if (!inLen) return;
    const rate = sr || 16000;
    const inFloat = concatFloat(inChunks, inLen);
    const outFloat = outLen ? concatFloat(outChunks, outLen) : inFloat;
    const inputBuf = audioCtx().createBuffer(1, inLen, rate); inputBuf.getChannelData(0).set(inFloat);
    const modelBuf = audioCtx().createBuffer(1, outFloat.length, rate); modelBuf.getChannelData(0).set(outFloat);
    let on = true;
    const tag = el('span', { class: 'rc-side' }, 'Model output');
    const sw = el('button', { class: 'rc-switch' }, 'Raw ↔ Model');
    const pp = audioControls(() => (on ? modelBuf : inputBuf));
    sw.addEventListener('click', () => { pp.halt(); on = !on; tag.textContent = on ? 'Model output' : 'Raw (your voice)'; });
    recMount.appendChild(el('div', { class: 'rc' },
      el('div', { class: 'rc-head' }, el('span', { class: 'rc-name' }, 'Your recording'), tag),
      el('div', { class: 'rc-meta' }, `${(inLen / rate).toFixed(1)}s captured · switch Raw↔Model, then Play/Stop`),
      el('div', { class: 'rc-ctl' }, sw, pp)));
    recMount.appendChild(asrSection(async () => ({
      before: encodeWav(inFloat, rate), after: encodeWav(outFloat, rate),
    })));
  }
  return root;
}

/* ---------- Twilio voice handoff (talk to a human / IVR, Sanas in the call) ---------- */
function twilioConnectNode() {
  const root = el('div', { class: 'twilio rich' });
  root.append(
    el('div', { class: 'pg-title' }, 'Connect by voice'),
    el('div', { class: 'pg-sub' }, 'Reach a specialist or the IVR. The call audio runs through the Sanas telephony model in real time — you hear the line cleaned mid-call.'));
  const body = el('div', { class: 'tw-body' }, el('div', { class: 'pg-status' }, 'Checking Twilio…'));
  root.appendChild(body);
  fetch(SAN_API + '/api/twilio/config').then(r => r.json()).then(render)
    .catch(() => { body.innerHTML = ''; body.appendChild(el('div', { class: 'pg-note' }, 'Could not reach the backend Twilio config.')); });

  const statusLine = () => el('div', { class: 'pg-status' });

  /* mid-call on/off — flips Sanas processing on the live call by CallSid */
  /* payload is {call_sid} (single-leg) or {bridge_id} (in-path bridge) */
  function callToggle(payload) {
    let enabled = true;
    const b = el('button', { class: 'live-toggle on' }, 'Model: ON');
    b.addEventListener('click', async () => {
      enabled = !enabled;
      b.classList.toggle('on', enabled); b.textContent = 'Model: ' + (enabled ? 'ON' : 'OFF');
      try {
        await fetch(SAN_API + '/api/twilio/toggle', { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...payload, enabled }) });
      } catch {}
      emit({ event: 'twilio_toggle', enabled });
    });
    return el('div', { class: 'tw-row tw-callctl' }, el('span', { class: 'tw-toggle-l' }, 'Sanas on the call:'), b);
  }

  async function placeCall(to, mode, status, toggleMount) {
    if (!to) { status.textContent = 'Enter your phone number in E.164 format (e.g. +14155551234).'; return; }
    status.textContent = 'Calling your phone…';
    if (toggleMount) toggleMount.innerHTML = '';
    try {
      const r = await fetch(SAN_API + '/api/twilio/call', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ to, mode }) });
      const d = await r.json();
      if (d.ok) {
        status.textContent = `Calling you now — pick up to ${mode === 'human' ? 'reach a specialist' : mode === 'sanas' ? 'hear Sanas enhance the line' : 'use the IVR'}. [${d.status || 'queued'}]`;
        if (d.sid && toggleMount && mode !== 'human') toggleMount.appendChild(callToggle({ call_sid: d.sid }));
      } else if (/21219|unverified|trial account/i.test(d.detail || '')) {
        // Twilio trial: outbound calls only reach verified numbers
        status.innerHTML = "That number isn’t verified on your Twilio trial, so it can’t be dialed. " +
          'Verify it under <a href="https://console.twilio.com/us1/develop/phone-numbers/manage/verified" target="_blank" rel="noopener">Verified Caller IDs</a> ' +
          '(or upgrade the account) — or use <strong>Talk in the browser</strong> below, which needs no verification.';
      } else {
        status.textContent = 'Could not place the call: ' + (d.detail || 'error');
      }
      emit({ event: 'twilio_call', mode, ok: !!d.ok });
    } catch { status.textContent = 'Call request failed — is the backend running?'; }
  }

  function render(cfg) {
    body.innerHTML = '';
    body.appendChild(el('div', { class: 'tw-meta' }, `Sanas model on the call: ${cfg.model}${cfg.sanas_in_call ? '' : ' (needs the SDK + audioop to enhance)'}`));
    if (!cfg.phone_callback && !cfg.browser_voice) {
      body.appendChild(el('div', { class: 'pg-note' },
        'Twilio isn’t configured yet. Add TWILIO_* and PUBLIC_BASE_URL to server/.env and point your Twilio number’s Voice webhook at {PUBLIC_BASE_URL}/api/twilio/voice, then reload. Until then, Sani hands off with your transcript by email (below).'));
      return;
    }
    if (cfg.phone_callback) {
      const phone = el('input', { class: 'tw-phone', type: 'tel', placeholder: '+1 415 555 1234', 'aria-label': 'Your phone number' });
      const st = statusLine();
      const human = el('button', { class: 'pg-input-btn' }, 'Talk to a human');
      const ivr = el('button', { class: 'pg-input-btn' }, 'Speak to the IVR');
      const demo = el('button', { class: 'pg-input-btn' }, 'Hear Sanas on the call');
      const toggleMount = el('div', { class: 'tw-toggle-mount' });
      if (!cfg.human_dial) { human.disabled = true; human.title = 'Set TWILIO_HUMAN_NUMBER to enable'; }
      human.addEventListener('click', () => placeCall(phone.value, 'human', st, toggleMount));
      ivr.addEventListener('click', () => placeCall(phone.value, 'ivr', st, toggleMount));
      demo.addEventListener('click', () => placeCall(phone.value, 'sanas', st, toggleMount));
      body.append(el('div', { class: 'tw-row' }, phone), el('div', { class: 'tw-row' }, human, ivr, demo), st, toggleMount);
    }
    if (cfg.browser_voice) body.appendChild(browserVoice());
  }

  function browserVoice() {
    const wrap = el('div', { class: 'tw-browser' });
    const toInput = el('input', { class: 'tw-phone', type: 'tel',
      placeholder: '+1 206 555 0123 — number to call (blank = hear yourself)', 'aria-label': 'Number to call' });
    const modelSel = el('select', { class: 'pg-langsel', 'aria-label': 'Sanas model' });
    const inpath = el('input', { type: 'checkbox', id: 'tw-inpath' });
    const inpathRow = el('label', { class: 'tw-inpath', for: 'tw-inpath' }, inpath,
      el('span', {}, 'Sanas in-path — the person hears your voice cleaned (beta)'));
    const st = statusLine();
    const tgl = el('div', { class: 'tw-toggle-mount' });
    const btn = el('button', { class: 'pg-input-btn live' }, 'Talk in the browser');
    let device = null, conn = null;

    // model picker — test different models on the call
    fetch(SAN_API + '/api/models').then(r => r.json()).then(d => {
      (d.models || []).forEach(m => modelSel.appendChild(el('option', { value: m.name }, m.label)));
      modelSel.value = 'AGENTIC_VI_GT_NC';                       // telephony model by default
      if (!modelSel.value && d.models && d.models[0]) modelSel.value = d.models[0].name;
    }).catch(() => {});

    btn.addEventListener('click', async () => {
      if (conn) { try { conn.disconnect(); } catch {} return; }
      st.textContent = 'Loading the Voice SDK…';
      try {
        await loadTwilioSDK();
        const t = await (await fetch(SAN_API + '/api/twilio/token')).json();
        if (!t.ok) { st.textContent = t.detail || 'Token unavailable.'; return; }
        device = new Twilio.Device(t.token, { logLevel: 'error' });
        const to = toInput.value.trim();
        const model = modelSel.value;
        let params, togglePayload = null;
        if (to && inpath.checked) {
          const bid = 'br-' + uuid();
          params = { mode: 'bridge', bridge: bid, To: to, model };
          togglePayload = { bridge_id: bid };
        } else if (to) {
          params = { To: to, model, mode: 'dial' };
        } else {
          params = { model, mode: 'sanas' };
        }
        st.textContent = to ? `Calling ${to}…` : 'Connecting…';
        conn = await device.connect({ params });
        btn.textContent = '■ Hang up';
        st.textContent = !to ? `In call — hearing yourself through Sanas ${model}.`
          : (inpath.checked ? `Bridging to ${to} — they hear your voice cleaned by Sanas ${model} (beta).`
                            : `In call with ${to} — speak through the app (Sanas ${model} on the audio).`);
        const csid = conn.parameters && conn.parameters.CallSid;
        tgl.innerHTML = '';
        if (togglePayload) tgl.appendChild(callToggle(togglePayload));
        else if (csid) tgl.appendChild(callToggle({ call_sid: csid }));
        conn.on('error', (e) => { st.textContent = 'Call error: ' + (e.message || e); });
        conn.on('disconnect', () => { conn = null; btn.textContent = 'Talk in the browser'; st.textContent = 'Call ended.'; tgl.innerHTML = ''; });
      } catch (e) { st.textContent = 'Browser call failed: ' + (e.message || e); }
    });
    wrap.append(
      el('div', { class: 'tw-or' }, 'or talk right here — through the app'),
      el('div', { class: 'tw-row' }, toInput),
      inpathRow,
      el('div', { class: 'tw-row' }, el('span', { class: 'tw-toggle-l' }, 'Model:'), modelSel, btn),
      st, tgl);
    return wrap;
  }

  let _sdkP = null;
  function loadTwilioSDK() {
    if (window.Twilio && window.Twilio.Device) return Promise.resolve();
    if (_sdkP) return _sdkP;
    // sdk.twilio.com returns 403 for direct <script> loads; jsDelivr serves the
    // same @twilio/voice-sdk UMD build (exposes global Twilio.Device).
    const urls = [
      'https://cdn.jsdelivr.net/npm/@twilio/voice-sdk@2.12.4/dist/twilio.min.js',
      'https://unpkg.com/@twilio/voice-sdk@2.12.4/dist/twilio.min.js',
    ];
    const tryLoad = (i) => new Promise((res, rej) => {
      if (i >= urls.length) return rej(new Error('SDK load failed'));
      const s = document.createElement('script');
      s.src = urls[i];
      s.onload = () => (window.Twilio && window.Twilio.Device)
        ? res() : tryLoad(i + 1).then(res, rej);
      s.onerror = () => tryLoad(i + 1).then(res, rej);
      document.head.appendChild(s);
    });
    _sdkP = tryLoad(0).catch((e) => { _sdkP = null; throw e; });  // allow retry without reload
    return _sdkP;
  }
  return root;
}

function traceNode() {
  // ingress is a real measured prep latency from the last /api/process call;
  // the rest stay illustrative (the batch path can't measure per-frame first-byte).
  const t = state.lastTrace;
  const measured = new Set();
  const ing = (t && isFinite(t.ingress)) ? (measured.add('ingress'), Math.round(t.ingress)) : 11;
  const layers = [
    ['client', 8], ['transport', 142], ['ingress', ing], ['queue', 6],
    ['inference', 89], ['ASR', 138], ['return', 7], ['playback', 9],
  ];
  const badge = ms => (ms < 60 ? 'green' : ms < 160 ? 'yellow' : 'red');
  const total = layers.reduce((a, [, ms]) => a + ms, 0);
  const max = Math.max(...layers.map(l => l[1]));
  const live = el('div', { class: 'total' }, el('span', {}, 'backend'), el('span', {}, 'checking…'));
  fetchHealth().then(h => {
    live.lastChild.textContent = h
      ? (h.mode === 'real' ? `live · ${h.model} · ${h.active_processors} active` : `mock · ${h.last_error || 'no SDK'}`)
      : 'offline';
  });
  const footer = t
    ? el('div', { class: 'total' }, el('span', {}, 'measured (your clip)'),
        el('span', {}, `ingress ${Math.round(t.ingress)}ms · processing ${Math.round(t.inference)}ms real-time`))
    : el('div', { class: 'total' }, el('span', {}, 'measured'), el('span', {}, 'process a clip to populate'));
  return el('div', { class: 'trace rich' },
    el('div', { class: 'ttl' }, el('span', {}, 'Layer trace'), el('span', {}, `${state.sessionId.slice(0, 8)}`)),
    ...layers.map(([name, ms]) =>
      el('div', { class: 'trace-row' },
        el('span', { class: `badge ${badge(ms)}` }),
        el('span', { class: 'layer' }, name),
        el('span', { class: 'bar' }, el('i', { style: `width:${(ms / max) * 100}%` })),
        el('span', { class: 'ms' }, measured.has(name) ? `${ms}ms ·live` : `${ms}ms`))),
    el('div', { class: 'total' }, el('span', {}, 'total first-byte'), el('span', {}, `~${total}ms`)),
    footer, live);
}

/* developer code block (F7) */
function codeNode() {
  const samples = {
    'SDK (Python)': `import os, sanas_remote_sdk\n\nsdk = sanas_remote_sdk.CreateRemoteSDK()\n\ninit = sanas_remote_sdk.InitParams()\ninit.remoteEndpoint  = os.environ["SANAS_ENDPOINT"]      # e.g. sip.sanas.ai\ninit.accountId       = os.environ["SANAS_ACCOUNT_ID"]\ninit.accountSecret   = os.environ["SANAS_ACCOUNT_SECRET"]\ninit.secureMedia     = True\nsdk.Initialize(init)\n\nap = sanas_remote_sdk.AudioParams()\nap.modelName  = "SE2.2"   # Speech Enhancement\nap.sampleRate = 16000\nproc, res = sdk.CreateAudioProcessor(ap, on_state)\nout = proc.ProcessSamples(input_audio)   # mono int16 PCM\nsdk.DestroyAudioProcessor(proc); sdk.Shutdown()`,
    'This app (curl)': `# the Sani backend wraps the SDK; credentials stay server-side\ncurl -F "file=@call.wav" \\\n     "http://localhost:8000/api/process?model=SE2.2" \\\n     -o cleaned.wav`,
    'This app (JS)': `const form = new FormData();\nform.append("file", file);            // user's clip\nconst r = await fetch("/api/process?model=SE2.2", {\n  method: "POST", body: form,\n});\nconst cleaned = await r.blob();        // Sanas-processed WAV\nnew Audio(URL.createObjectURL(cleaned)).play();`,
  };
  const keys = Object.keys(samples);
  const body = el('pre', { class: 'code-body' }, samples[keys[0]]);
  const tabs = el('div', { class: 'code-tabs' });
  keys.forEach((k, i) => {
    const b = el('button', { class: i === 0 ? 'active' : '' }, k);
    b.addEventListener('click', () => {
      [...tabs.children].forEach(c => c.classList.remove('active'));
      b.classList.add('active'); body.textContent = samples[k];
    });
    tabs.appendChild(b);
  });
  const block = el('div', { class: 'code-block rich' }, tabs, body);
  const wrap = el('div', { class: 'rich' }, block);
  // surface live backend status (real SDK vs mock) so devs know what they're hitting
  const status = el('div', { class: 'sandbox-key' }, 'Checking backend…');
  wrap.appendChild(status);
  fetchHealth().then(h => {
    if (!h) { status.textContent = 'Backend offline — run `docker compose up` (holds the SDK + your SANAS_* creds).'; return; }
    status.textContent = h.mode === 'real'
      ? `Backend live · Sanas ${h.model} @ ${h.sample_rate} Hz · ${h.active_processors} active processors`
      : `Backend in mock mode · ${h.last_error || 'SDK tarball not installed'}`;
    emit({ event: 'backend_health', sanas_mode: h.mode, model: h.model });
  });
  return wrap;
}

/* ROI snapshot (F6) */
function roiNode() {
  const seats = el('input', { type: 'number', min: '1', placeholder: 'e.g. 500', value: '500' });
  const aht = el('input', { type: 'number', min: '1', placeholder: 'seconds, e.g. 420', value: '420' });
  const csat = el('input', { type: 'number', min: '1', max: '100', placeholder: '%, e.g. 72', value: '72' });
  const out = el('div', {});
  const go = el('button', { class: 'roi-go' }, 'Estimate');
  go.addEventListener('click', () => {
    const s = +seats.value || 0, a = +aht.value || 0;
    // directional model: ~8% AHT reduction is a conservative published-range figure
    const ahtCut = 0.08, secSaved = a * ahtCut;
    const minsPerSeatDay = (secSaved * 60); // assume ~60 calls/seat/day rough
    const annualHours = (minsPerSeatDay / 60) * s * 240;
    const dollars = Math.round(annualHours * 28); // ~$28 loaded agent hour
    out.innerHTML = '';
    out.appendChild(el('div', { class: 'roi-out' },
      el('div', { class: 'num' }, '$' + dollars.toLocaleString()),
      el('div', {}, `directional annual capacity saved at ~${Math.round(secSaved)}s lower AHT across ${s} seats`),
      el('div', { class: 'disc' }, 'This is directional. Let’s confirm against your real call mix on a demo.')));
    emit({ event: 'roi_computed', recommendation_made: true });
  });
  return el('div', { class: 'roi rich' },
    el('label', {}, 'Agent seats'), seats,
    el('label', {}, 'Average handle time (seconds)'), aht,
    el('label', {}, 'Current CSAT (%)'), csat,
    go, out);
}

/* ---------- the router: turn text -> response ---------- */
function respond(text) {
  const t = text.toLowerCase().trim();
  const skeptic = skepticScore(text);
  state.skeptic = skeptic;

  // ---- Live mic (speak to the models in real time) ----
  if (/\b(speak|talk)\b.*\b(live|real-?time|mic|microphone)\b|\blive\b.*\b(mic|audio|models?|stream)\b|real-?time (audio|mic|voice)|\bagentic\b/.test(t)) {
    return { text: "Go ahead — speak into your mic and you'll hear it transformed in real time. Toggle the model On/Off to A/B against your raw voice, and switch models on the fly.",
      nodes: [liveNode()], sources: ['kb-models'],
      suggestions: ['List the models', 'How does reconstruction work?', 'Talk to a human'] };
  }

  // ---- Playground (list / test models, try it on your own audio) ----
  if (/\b(playground|try it|test (all )?(the )?models|list (the )?models|all models|which models|mimic)\b/.test(t)) {
    return { text: 'Here’s the Playground — record or upload a clip, pick a feature, and transform it with the live Sanas models. You can list every model and test them all on the same clip.',
      nodes: [playgroundNode()], sources: ['kb-models'],
      suggestions: ['How does reconstruction work?', 'Show the 8-layer trace', 'Talk to a human'] };
  }

  // ---- Guardrails / refusals (§7.7) ----
  if (/\b(price|pricing|cost per|quote|discount|how much)\b/.test(t)) {
    return { text: "I keep to published pricing tiers and won't improvise a quote. I can outline what drives cost — seats, languages, deployment topology — and put real numbers in front of you with our team. Want me to set that up, or run an ROI snapshot first?",
      sources: [], suggestions: ['Run an ROI snapshot', 'Talk to a human'], refusal: 'pricing' };
  }
  if (/\b(fedramp|hipaa|pci)\b/.test(t)) {
    return { text: "I won't speculate on certifications that aren't in my knowledge base. At MVP, Sanas documents ISO 27001, SOC 2 Type II, and GDPR. For FedRAMP, HIPAA, or PCI I'd rather loop in our security team than guess — they can speak to current status and roadmap.",
      sources: ['kb-iso'], suggestions: ['Talk to security', 'Zero-Knowledge deployment'], refusal: 'uncertified_compliance' };
  }
  if (/\b(deepgram|elevenlabs|krisp|competitor|vs\.?|compare to|better than)\b/.test(t)) {
    return { text: "I'll compare on facts, not knock anyone. Where Sanas is specific: we reconstruct the voice signal rather than filtering it, run accent translation under 200ms, and publish our own layer-by-layer latency trace. A side-by-side WER and latency comparison against your current vendor is on the V2 roadmap. For a head-to-head today, our SE team can run it with you.",
      sources: ['kb-reconstruct', 'kb-latency'], suggestions: ['How does reconstruction work?', 'Talk to a human'] };
  }

  // ---- Human handoff (F8) ----
  if (/\b(talk to (a )?human|speak to (someone|sales|a person)|book a demo|schedule|sales rep|account exec)\b/.test(t)) {
    state.ctaTurnsAgo = 0;
    return { text: "I can connect you by voice — to a specialist or our IVR — and route the call audio through Sanas so the line is cleaned in real time. Pick an option below, or I can hand off with your transcript by email.",
      sources: [], handoff: true, nodes: [twilioConnectNode()],
      suggestions: ['Book a callback', 'Keep exploring first'] };
  }

  // ---- Developer / API / sandbox / debug (F7, F10) ----
  if (/\b(debug|trace|latency breakdown|eight.?layer|layer trace|why.*slow)\b/.test(t)) {
    return { text: "Here's the layer breakdown — the same eight-layer probe SREs see internally. The two big chunks are usually transport (endpoint distance) and ASR. Pick a region closer to your traffic and both drop sharply. The live status below comes from your Sani backend.",
      sources: ['kb-debug'], nodes: [traceNode()], suggestions: ['Show me the SDK code', 'What latency should I expect?'] };
  }
  if (/\b(api|sdk|curl|code|snippet|sandbox|integrat|endpoint|python|node)\b/.test(t)) {
    return { text: "Here's the real path. The `sanas_remote_sdk` package initializes with your endpoint + account ID + secret, you create an AudioProcessor for a model (SE2.2 for Speech Enhancement), and stream PCM frames through ProcessSamples. Your Sani backend already wraps that, so from the browser you just POST a clip to /api/process — credentials never leave the server.",
      sources: ['kb-api'], nodes: [codeNode()], suggestions: ['Show the 8-layer trace', 'Upload a clip to process', 'What latency should I expect?'] };
  }

  // ---- Security / compliance / Zero-Knowledge (Buyer-IT) ----
  if (/\b(residency|on-?prem|private cloud|where.*data|data.*store|zero.?knowledge|perimeter)\b/.test(t)) {
    return { text: "Two options. Sanas can deploy in Zero-Knowledge mode — on-prem or your private cloud — where no audio is stored or transmitted externally during real-time processing; the audio never leaves your perimeter. We hold ISO 27001 and SOC 2 Type II and operate under GDPR for EU data, all documented in the Trust Center.",
      sources: ['kb-zk', 'kb-iso'], suggestions: ['Walk me through the Dual-Decoder', 'Deployment topology'] };
  }
  if (/\b(iso|soc ?2|gdpr|compliance|certif|secur)\b/.test(t)) {
    return { text: "On certifications: ISO 27001 and SOC 2 Type II, and we operate under GDPR for EU personal data — all in the Trust Center. For real-time processing we run Zero-Knowledge: no audio stored or transmitted externally. If you need something not on file, I'll route you to security rather than guess.",
      sources: ['kb-iso', 'kb-zk'], suggestions: ['Zero-Knowledge deployment', 'Talk to security'] };
  }

  // ---- Educator: Dual-Decoder (F3) ----
  if (/\b(dual.?decoder|architecture|harmonic|how.*built|how.*work.*technical|signal.*process)\b/.test(t)) {
    return { text: "The Dual-Decoder architecture splits the signal in two. Harmonic content — vowels and tonal structure, the part that makes a voice sound like *that* person — goes down one decoder pathway. Noise-like content — consonants, fricatives, ambient interference — goes down another. They're processed separately and recombined. That's how we remap dialect-specific patterns while preserving vocal identity.",
      sources: ['kb-dualdecoder'], nodes: [showroomNode('offshore')], suggestions: ['Why reconstruct instead of filter?', 'What latency does that add?'] };
  }
  // ---- Educator: Acoustic Reconstruction (F3) ----
  if (/\b(reconstruct|filter|natural|sound.*process|how.*natural|science|signal)\b/.test(t)) {
    return { text: "The key distinction: we reconstruct the voice signal rather than filter it. Filtering removes content — it subtracts, and the result degrades and sounds processed. Reconstruction rebuilds the signal, so the output sounds natural. It's also why we can be honest about audio quality: we're not papering over a degraded input, we're rebuilding it.",
      sources: ['kb-reconstruct'], suggestions: ['Show me the Dual-Decoder', 'Play a before/after'] };
  }

  // ---- ROI (F6) ----
  if (/\b(roi|savings|save money|payback|cost.*saving|business case)\b/.test(t)) {
    state.ctaTurnsAgo = 0;
    return { text: "Three inputs and I'll give you a directional number you can sanity-check. This isn't a quote — it's a back-of-envelope estimate we'd confirm against your real call mix on a demo.",
      sources: ['kb-analytics'], nodes: [roiNode()] };
  }

  // ---- Audio demo / showroom (F5) ----
  if (/\b(hear|listen|demo|sample|play|audio|before.?after|sound like)\b/.test(t)) {
    // pick scenario by context
    let key = 'offshore';
    if (/\b(noise|noisy|cafe|background|ambient)\b/.test(t)) key = 'cafe';
    else if (/\b(call center|floor|overlap|babble)\b/.test(t)) key = 'floor';
    return { text: `Listen, then judge. Here's the ${SCENARIOS[key].name} scenario. Hit play, then toggle Before ↔ After — same voice, same words. The reason it sounds natural is that we reconstruct the signal rather than filter it. If you have a clip from your own floor, you can upload it and I'll run that too.`,
      sources: ['kb-reconstruct'], nodes: [showroomNode(key)], suggestions: ['Play the Noisy Cafe one', 'How does reconstruction work?', 'I have a clip to upload'] };
  }

  // ---- Recommendation engine (F4) ----
  const recs = recommend(text);
  if (recs.length) {
    state.ctaTurnsAgo = 0;
    const lead = recs.length > 1
      ? "That's a compound challenge, so I'd combine deployments. Here's the fit and the reason for each:"
      : "That maps cleanly to one of our models. Here's the fit and the reason:";
    const cards = recs.map(r => el('div', { class: 'rec-card' },
      el('div', { class: 'tag' }, 'recommended'),
      el('div', { class: 'prod' }, r.product),
      el('div', { class: 'why' }, r.why)));
    return { text: lead, sources: recs.map(r => r.src),
      nodes: cards, suggestions: ['Play a relevant before/after', 'What would this cost?', 'Talk to a human'] };
  }

  // ---- "what does Sanas do" / overview ----
  if (/\b(what.*(sanas|you).*do|what is sanas|tell me about|overview|products?)\b/.test(t) || t === 'hi' || t === 'hello') {
    return { text: "In one line: we change how a voice sounds in real time so agents and customers understand each other. More precisely, we reconstruct the voice signal — we don't filter it — so the result sounds natural. Three core models: Accent Translation, Speech Enhancement, and Real-Time Translation. What's the actual problem on your end — offshore agents and US customers, ambient noise, language coverage, or something else?",
      sources: ['kb-models'], suggestions: ['Offshore agents, noisy floor', 'Play a before/after', "I'm a developer"] };
  }

  // ---- Grounded fallback with low-confidence honesty (§7.7) ----
  const { chunks, confidence } = retrieve(text);
  if (confidence >= 0.34 && chunks.length) {
    return { text: chunks[0].text, sources: chunks.map(c => c.id),
      suggestions: ['Play a before/after', 'Recommend a model for my case', 'Talk to a human'], retrieval_confidence: confidence };
  }
  // low confidence -> say so, offer a human (hallucination containment)
  return { text: "I'm not sure, and I'd rather be right than fast. That one isn't in what I can ground an answer on. Want me to loop in our team, or can I point you at a before/after demo or a model recommendation in the meantime?",
    sources: [], suggestions: ['Talk to a human', 'Play a before/after', 'What does Sanas do?'], retrieval_confidence: confidence, refusal: 'low_confidence' };
}

/* ============================================================
   RENDERING
   ============================================================ */
const log = () => $('#sanLog');

/* light markdown: *italic*, **bold**, `code`, paragraphs (input is escaped first) */
function renderMarkdown(content) {
  return content
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`(.+?)`/g, '<code>$1</code>')
    .split('\n\n').map(p => `<p>${p}</p>`).join('');
}

function addMessage(role, content, extras = {}) {
  const wrap = el('div', { class: 'bubble-wrap' });
  if (typeof content === 'string') {
    wrap.appendChild(el('div', { class: 'bubble', html: renderMarkdown(content) }));
  }
  if (extras.sources && extras.sources.length) {
    const chips = srcChips(extras.sources); if (chips) wrap.appendChild(chips);
  }
  if (extras.links && extras.links.length) {
    const c = linkChips(extras.links); if (c) wrap.appendChild(c);
  }
  (extras.nodes || []).forEach(n => wrap.appendChild(n));
  if (extras.handoff) {
    wrap.appendChild(el('div', { class: 'privacy-note' }, 'Transcript + detected persona will be attached to the handoff. Uploaded audio is processed in-memory and deleted within 24h by default.'));
  }
  const msg = el('div', { class: `msg ${role}` });
  if (role === 'san') msg.appendChild(el('div', { class: 'av', html: waveSVG('#0a0a0a') }));
  msg.appendChild(wrap);
  log().appendChild(msg);
  log().scrollTop = log().scrollHeight;
}

/* a Sani message whose bubble fills token-by-token during streaming */
function addStreamingMessage() {
  const wrap = el('div', { class: 'bubble-wrap' });
  const bubble = el('div', { class: 'bubble' });
  wrap.appendChild(bubble);
  const msg = el('div', { class: 'msg san' },
    el('div', { class: 'av', html: waveSVG('#0a0a0a') }), wrap);
  log().appendChild(msg);
  log().scrollTop = log().scrollHeight;
  let raw = '';
  return {
    append(t) { raw += t; bubble.textContent = raw; log().scrollTop = log().scrollHeight; },
    finalize(fullText, extras = {}) {
      bubble.innerHTML = renderMarkdown(fullText);
      if (extras.sources && extras.sources.length) {
        const c = srcChips(extras.sources); if (c) wrap.appendChild(c);
      }
      if (extras.links && extras.links.length) {
        const c = linkChips(extras.links); if (c) wrap.appendChild(c);
      }
      log().scrollTop = log().scrollHeight;
    },
    remove() { msg.remove(); },
  };
}

function showTyping() {
  const t = el('div', { class: 'msg san', id: 'typing' },
    el('div', { class: 'av', html: waveSVG('#0a0a0a') }),
    el('div', { class: 'bubble' }, el('div', { class: 'typing' }, el('span'), el('span'), el('span'))));
  log().appendChild(t); log().scrollTop = log().scrollHeight;
}
const hideTyping = () => $('#typing')?.remove();

function setSuggestions(items) {
  const bar = $('#suggestions'); bar.innerHTML = '';
  (items || []).forEach(s => {
    const b = el('button', {}, s);
    b.addEventListener('click', () => handleUserInput(s));
    bar.appendChild(b);
  });
}

function setPersona(p, explicit) {
  if (!p) return;
  const changed = state.persona !== p;
  state.persona = p; if (explicit) state.personaExplicit = true;
  // reflect in chip UI
  document.querySelectorAll('.persona-bar .chip').forEach(c =>
    c.classList.toggle('active', c.dataset.persona === p));
  // reflect register in header
  $('#sanRole').textContent = 'Speech AI specialist · ' + (PERSONAS[p]?.label || 'concierge');
  if (changed) emit({ event: 'persona_set', persona_detected: p, explicit: !!explicit, sub_persona: p });
}

/* ---------- main input handler ---------- */
let busy = false;
async function handleUserInput(text) {
  text = (text || '').trim();
  if (!text || busy) return;
  // "upload a clip" style prompts open the file picker instead of sending text
  if (/upload/i.test(text) && /\b(clip|audio|file)\b/i.test(text)) { $('#sanFile').click(); return; }
  state.turn++;
  state.ctaTurnsAgo++;
  addMessage('user', text);
  state.history.push({ role: 'user', text });

  // persona + skeptic detection
  const detected = classifyPersona(text, state.persona);
  if (!state.personaExplicit) setPersona(detected, false);
  const sk = skepticScore(text);

  busy = true; showTyping();
  const r = respond(text);

  // skeptic overlay: lead with the showroom regardless of base persona (§3.4)
  if (sk >= 0.5 && !r.nodes && !r.handoff) {
    r.nodes = [showroomNode(state.persona === 'curious' ? 'cafe' : 'offshore')];
    r.text = r.text + "\n\nYou sound like you want proof, not promises — so here's the audio first.";
  }

  const emitTurn = (source) => emit({
    event: 'turn',
    intent_classified: r.refusal || (r.handoff ? 'handoff' : r.nodes ? 'rich' : 'answer'),
    persona_detected: state.persona, sub_persona: state.persona,
    skeptic_stance_score: +sk.toFixed(2),
    retrieval_confidence: r.retrieval_confidence ?? null,
    refused_bool: !!r.refusal, refusal_reason: r.refusal || null,
    response_source: source,
    audio_uploaded_bool: false,
    scenario_played: r.nodes ? 'shown' : null,
    recommendation_made: /rec-card/.test((r.nodes || []).map(n => n.className).join(' ')),
    cta_presented: r.handoff ? 'handoff' : null,
    handoff_triggered: !!r.handoff,
    outcome_tag: r.handoff ? 'handoff' : 'engaged',
  });

  // Conversational turns (no rich component, handoff, or fixed-wording refusal)
  // stream LLM-generated grounded prose token-by-token into a live bubble.
  // Everything else keeps deterministic copy so interactive components stay crisp.
  if (!r.nodes && !r.handoff && !r.refusal) {
    hideTyping();
    const sm = addStreamingMessage();
    let res = { text: null, sources: [] };
    try { res = await llmChatStream(state.history, state.persona, sk, t => sm.append(t)); }
    catch { res = { text: null, sources: [] }; }
    if (res && res.text) {
      sm.finalize(res.text, { links: res.sources });   // real sanas.ai source links
      state.history.push({ role: 'san', text: res.text });
      setSuggestions(r.suggestions);
      emitTurn('llm');
      busy = false;
      return;
    }
    sm.remove();  // LLM unavailable/empty — fall through to the canned reply
    if (res && res.sources && res.sources.length) r.links = res.sources;  // still cite pages
  }

  emitTurn('rule');
  hideTyping();
  addMessage('san', r.text, { sources: r.sources, nodes: r.nodes, handoff: r.handoff, links: r.links });
  state.history.push({ role: 'san', text: r.text });
  setSuggestions(r.suggestions);
  busy = false;
}

/* ---------- audio upload (F5 live path via the Sanas SDK backend) ---------- */
async function handleUpload(file) {
  if (!file) return;
  state.turn++;
  addMessage('user', 'Uploaded: ' + file.name);
  showTyping(); busy = true;
  emit({ event: 'audio_upload', audio_uploaded_bool: true });
  try {
    const arrBuf = await file.arrayBuffer();
    const form = new FormData(); form.append('file', file);
    const resp = await fetch(SAN_API + '/api/process', { method: 'POST', body: form });
    if (!resp.ok) throw new Error('process failed: ' + resp.status);
    const procArr = await resp.arrayBuffer();
    const h = resp.headers;
    const meta = {
      mode: h.get('X-Sanas-Mode') || 'mock', model: h.get('X-Sanas-Model') || 'SE2.2',
      snr: h.get('X-Sanas-SNR-dB'), clip: h.get('X-Sanas-Clip-Rate'), sr: h.get('X-Sanas-Sample-Rate'),
      vad: h.get('X-Sanas-VAD'), dur: h.get('X-Sanas-Duration'),
      truncated: h.get('X-Sanas-Truncated') === '1', limit: h.get('X-Sanas-Clip-Limit-S'),
    };
    // remember measured layer timings so the 8-layer trace can show real numbers
    state.lastTrace = {
      mode: meta.mode, model: meta.model,
      ingress: parseFloat(h.get('X-Sanas-T-Ingress')),
      inference: parseFloat(h.get('X-Sanas-T-Inference')),
    };
    const [origBuf, procBuf] = await Promise.all([decodeAudio(arrBuf), decodeAudio(procArr)]);
    hideTyping();
    const modeNote = meta.mode === 'real'
      ? `Processed live through the Sanas ${meta.model} model.`
      : `Heads up: the backend is in mock mode (no SDK installed yet) — this is a stand-in cleanup, not the Sanas model. Run the real-SDK backend to hear the real thing.`;
    const truncNote = meta.truncated
      ? ` I trimmed it to the first ${meta.limit}s — the engine runs in real time, so longer clips take proportionally longer.`
      : '';
    addMessage('san',
      `Ran your clip through the same ingress quality probe the speech engine uses in production, then the model.${truncNote}\n\n**SNR** ~${meta.snr} dB · **clip rate** ${meta.clip}% · **sample rate** ${meta.sr} Hz · **VAD** ${meta.vad} · **${meta.dur}s**.\n\n${modeNote} Toggle Before ↔ After to compare. Your audio is processed in-memory and deleted within 24h by default.`,
      { sources: ['kb-enhance', 'kb-reconstruct'], nodes: [realShowroomNode(origBuf, procBuf, meta, { before: arrBuf, after: procArr })] });
    setSuggestions(['How does reconstruction work?', 'Show the 8-layer trace', 'Talk to a human']);
    emit({ event: 'audio_processed', audio_uploaded_bool: true, sanas_mode: meta.mode, model: meta.model });
  } catch (err) {
    hideTyping();
    addMessage('san',
      "I couldn't reach the Sanas processing backend. Start the Sani server (`docker compose up`) — it holds the SDK and your credentials, and the browser never sees them. Here's a curated before/after in the meantime.",
      { nodes: [showroomNode('cafe')] });
    emit({ event: 'audio_process_error', error: String(err) });
  } finally {
    busy = false;
  }
}

/* ---------- debug / observability drawer (F11) ---------- */
function renderDebug() {
  const d = $('#debugBody'); if (!d) return;
  d.innerHTML = '';
  state.events.slice().reverse().forEach(e => {
    const rows = Object.entries(e).filter(([k]) => !['session_id'].includes(k))
      .map(([k, v]) => `<span class="k">${k}</span>: ${v}`).join('  ·  ');
    d.appendChild(el('div', { class: 'evt', html: rows }));
  });
}

/* ============================================================
   BOOTSTRAP UI
   ============================================================ */
function openPanel() {
  $('#sanPanel').hidden = false;
  $('#sanLauncher').hidden = true;
  if (!state.opened) {
    state.opened = true;
    const op = opening(state.persona);
    addMessage('san', op.text);
    setSuggestions(['Offshore agents, US customers', 'Play a before/after', "I'm a developer", 'Is it really natural?']);
    emit({ event: 'session_start', persona_detected: state.persona });
  }
  $('#sanInput').focus();
}
function closePanel() { $('#sanPanel').hidden = true; $('#sanLauncher').hidden = false; }

document.addEventListener('DOMContentLoaded', () => {
  // launcher + close
  $('#sanLauncher').addEventListener('click', openPanel);
  $('#sanClose').addEventListener('click', closePanel);
  // hero demo button opens chat into a before/after
  document.querySelectorAll('[data-open-san]').forEach(b =>
    b.addEventListener('click', () => { openPanel(); setTimeout(() => handleUserInput('Play a before/after'), 300); }));
  document.querySelectorAll('[data-open-playground]').forEach(b =>
    b.addEventListener('click', () => { setTimeout(openPlayground, 150); }));
  document.querySelectorAll('[data-open-person]').forEach(b =>
    b.addEventListener('click', () => { openPanel(); setTimeout(() => handleUserInput('Speak to a person'), 200); }));

  // session id display
  $('#sanSession').textContent = state.sessionId.slice(0, 8);

  // persona chips
  document.querySelectorAll('.persona-bar .chip').forEach(chip =>
    chip.addEventListener('click', () => {
      setPersona(chip.dataset.persona, true);
      const intro = {
        developer: "Noted — I'll keep it technical. Want the SDK code, the eight-layer latency trace, or to upload a clip and hear it processed through the model?",
        buyer_cx: "Got it. I'll lead with outcomes — AHT, CSAT, FCR. What's the setup: how many seats, and what's the main complaint from customers today?",
        buyer_it: "Understood. I'll focus on architecture and compliance. Want the Dual-Decoder walkthrough, deployment topology, or the certification list first?",
        curious: "No problem — I'll keep it plain. The fastest way to get it is to hear it. Want a before/after, or a one-line explanation of what we do?",
      }[chip.dataset.persona];
      addMessage('san', intro);
      const sg = {
        developer: ['Show the SDK code', 'Show the 8-layer trace', 'Upload a clip to process'],
        buyer_cx: ['500 seats, offshore complaints', 'Run an ROI snapshot', 'Play a before/after'],
        buyer_it: ['Walk me through Dual-Decoder', 'Data residency for EU', 'List certifications'],
        curious: ['What does Sanas do?', 'Play a before/after'],
      }[chip.dataset.persona];
      setSuggestions(sg);
    }));

  // composer
  const input = $('#sanInput');
  const send = () => { const v = input.value; input.value = ''; input.style.height = 'auto'; handleUserInput(v); };
  $('#sanSend').addEventListener('click', send);
  input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } });
  input.addEventListener('input', () => { input.style.height = 'auto'; input.style.height = Math.min(120, input.scrollHeight) + 'px'; });

  // upload
  $('#sanUpload').addEventListener('click', () => $('#sanFile').click());
  $('#sanFile').addEventListener('change', e => handleUpload(e.target.files[0]));

  // debug drawer (internal, SSO-gated in production)
  $('#sanDebugBtn').addEventListener('click', () => {
    const dr = $('#debugDrawer'); dr.hidden = !dr.hidden;
    $('#sanDebugBtn').classList.toggle('active', !dr.hidden);
  });
  $('#debugClose').addEventListener('click', () => { $('#debugDrawer').hidden = true; $('#sanDebugBtn').classList.remove('active'); });

  // rolling-word hero animation
  const words = ['Magic', 'Clarity', 'Opportunity', 'Progress', 'Sanas'];
  let wi = 0; const roll = $('#rollWord');
  if (roll && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    setInterval(() => { wi = (wi + 1) % words.length; roll.textContent = words[wi]; }, 2200);
  }
});
