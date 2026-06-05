/**
 * Loads the real San front-end engine (app.js) under jsdom so the golden-eval
 * suite tests the *actual* shipped logic — respond(), classifyPersona(),
 * skepticScore(), recommend() — not a copy.
 *
 * All of app.js's setup lives inside its DOMContentLoaded handler, which never
 * fires here (the document is already "complete" when we inject the script), so
 * loading is side-effect-free: only the function/data definitions run.
 */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const ROOT = path.join(__dirname, '..');

function loadEngine() {
  const html = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8')
    // drop the external <script src="app.js"> — we inject it ourselves after stubbing
    .replace(/<script[^>]*src=["']app\.js["'][^>]*>\s*<\/script>/i, '');
  const appjs = fs.readFileSync(path.join(ROOT, 'app.js'), 'utf8');

  const dom = new JSDOM(html, {
    runScripts: 'dangerously',
    pretendToBeVisual: true,
    url: 'http://localhost/',
  });
  const { window } = dom;

  // --- stubs for browser APIs the engine may touch while building nodes ---
  const noop = () => {};
  window.requestAnimationFrame = (cb) => { return 0; };
  window.cancelAnimationFrame = noop;
  window.matchMedia = () => ({ matches: false, addEventListener: noop, removeEventListener: noop });
  window.fetch = () => Promise.reject(new Error('no network in eval'));
  window.AudioContext = window.webkitAudioContext = function () {
    return {
      state: 'running', currentTime: 0, sampleRate: 16000, destination: {},
      resume: noop, createGain: () => ({ connect: noop, gain: { value: 1 } }),
      createBufferSource: () => ({ connect: noop, start: noop, stop: noop, buffer: null }),
      createBuffer: () => ({ getChannelData: () => new Float32Array(1) }),
      decodeAudioData: () => Promise.reject(new Error('no decode in eval')),
    };
  };
  // a forgiving 2D context so waveform drawing never throws
  window.HTMLCanvasElement.prototype.getContext = function () {
    return new Proxy({}, { get: () => () => {}, set: () => true });
  };

  // inject app.js into the live window (dynamic inline scripts execute)
  const script = window.document.createElement('script');
  script.textContent = appjs;
  window.document.body.appendChild(script);

  return window;
}

module.exports = { loadEngine };
