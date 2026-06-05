/**
 * Golden-eval gate for San's deterministic engine (§7.4 F12).
 *
 * No prompt/engine change ships if these fail. They lock in the load-bearing
 * behaviours: guardrail refusals, persona routing, recommendation fit, skeptic
 * detection, and brand-voice rules (no emoji, no empty superlatives).
 *
 * Run: npm run eval   (or: node --test evals/)
 */
const { test, before } = require('node:test');
const assert = require('node:assert/strict');
const { loadEngine } = require('./engine');

let W;
before(() => { W = loadEngine(); });

// Brand voice — "no empty superlatives" (Brand Book, Voice Pillars: Visionary).
const BANNED = ['game-changing', 'game changing', 'unmatched', 'revolutionary',
  'best-in-class', 'best in class', 'world-class', 'cutting-edge', 'next-generation'];
// emoji-by-default pictographs (😀) or any emoji-presentation (VS16) usage — but
// NOT text-default typographic symbols like the ↔ in the brand's "Before ↔ After".
const EMOJI = /\p{Emoji_Presentation}|\uFE0F/u;

const PROBES = [
  'what does sanas do', 'how does reconstruction work', 'tell me about the dual decoder',
  'our offshore agents struggle with accents', 'is it secure and gdpr compliant',
  'how much does it cost', 'are you fedramp authorized', 'how do you compare to krisp',
  'we have background noise in the call center', 'does this actually work or is it hype',
  'i need the api and sdk', 'play a before and after',
];

test('guardrail: pricing questions refuse and never improvise a number', () => {
  const r = W.respond('how much does it cost per seat, can I get a discount');
  assert.equal(r.refusal, 'pricing');
  assert.doesNotMatch(r.text, /\$\s?\d/);                 // no dollar figure
  assert.doesNotMatch(r.text, /\b\d{1,3}\s?(%|percent)\b/); // no invented discount
  assert.ok(r.suggestions.includes('Talk to a human'));
});

test('guardrail: uncertified compliance (FedRAMP/HIPAA/PCI) routes to security', () => {
  for (const q of ['are you fedramp authorized', 'is this hipaa compliant', 'do you support PCI']) {
    const r = W.respond(q);
    assert.equal(r.refusal, 'uncertified_compliance', `for: ${q}`);
    assert.ok(r.suggestions.some(s => /security/i.test(s)), `routes to security: ${q}`);
  }
});

test('guardrail: certified compliance (ISO/SOC2/GDPR) answers and cites the trust center', () => {
  const r = W.respond('are you iso 27001 and soc 2 certified, and gdpr compliant');
  assert.ok(!r.refusal, 'should answer, not refuse');
  assert.ok(r.sources.includes('kb-iso'), 'cites certifications source');
});

test('recommendation: offshore-accent intent surfaces Accent Translation', () => {
  const hits = W.recommend('our offshore agents in manila are hard to understand');
  assert.ok(hits.some(h => h.product === 'Accent Translation'));
  const r = W.respond('our offshore agents in manila are hard to understand');
  assert.ok(r.sources.includes('kb-accent'));
  assert.ok(Array.isArray(r.nodes) && r.nodes.length, 'renders a recommendation node');
});

test('recommendation: noise intent surfaces Speech Enhancement', () => {
  const hits = W.recommend('lots of background noise in our open-plan office');
  assert.ok(hits.some(h => h.product === 'Speech Enhancement'));
});

test('education: reconstruction answer is grounded and cited', () => {
  const r = W.respond('how does reconstruction work');
  assert.match(r.text, /reconstruct/i);
  assert.ok(r.sources.includes('kb-reconstruct'));
});

test('persona routing: developer / IT / CX / curious', () => {
  assert.equal(W.classifyPersona('I need the API, SDK and latency numbers', null), 'developer');
  assert.equal(W.classifyPersona('what about SOC 2, GDPR and data residency', null), 'buyer_it');
  assert.equal(W.classifyPersona('we want to reduce AHT across our call center agents', null), 'buyer_cx');
  assert.equal(W.classifyPersona('hi, just looking around', null), 'curious');
});

test('skeptic detection: doubt language scores >= 0.5', () => {
  assert.ok(W.skepticScore('this sounds too good to be true, does it actually work') >= 0.5);
  assert.ok(W.skepticScore('what does sanas do') < 0.5);
});

test('brand voice: no emoji in any canned reply', () => {
  for (const q of PROBES) {
    const r = W.respond(q);
    assert.doesNotMatch(r.text, EMOJI, `emoji in reply to: ${q}`);
  }
});

test('brand voice: no empty superlatives in any canned reply', () => {
  for (const q of PROBES) {
    const t = W.respond(q).text.toLowerCase();
    for (const b of BANNED) assert.ok(!t.includes(b), `"${b}" in reply to: ${q}`);
  }
});

test('every reply carries a forward path (suggestions) and a defined intent', () => {
  for (const q of PROBES) {
    const r = W.respond(q);
    assert.ok(typeof r.text === 'string' && r.text.trim().length > 0, `non-empty text: ${q}`);
    assert.ok(Array.isArray(r.suggestions) && r.suggestions.length > 0, `has suggestions: ${q}`);
  }
});
