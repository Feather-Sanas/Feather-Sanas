/**
 * Invariants on San's LLM system prompt (server/llm.py). The Claude path must
 * stay grounded in the same facts and bound by the same guardrails/voice as the
 * deterministic engine — these are static string checks (no API key needed).
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');

const SRC = fs.readFileSync(path.join(__dirname, '..', 'server', 'llm.py'), 'utf8');
const lower = SRC.toLowerCase();

test('system prompt grounds the core KB facts', () => {
  for (const fact of ['reconstruct', 'Dual-Decoder', 'Accent Translation', 'Speech Enhancement',
    'Real-Time Translation', '480+', 'sub-200ms', 'ISO 27001', 'SOC 2', 'GDPR', 'Zero-Knowledge']) {
    assert.ok(SRC.includes(fact), `missing KB fact: ${fact}`);
  }
});

test('system prompt enforces the guardrails', () => {
  assert.match(lower, /pricing/);
  assert.match(lower, /fedramp|hipaa|pci/);          // uncertified compliance routed out
  assert.match(lower, /competitor/);
  assert.match(lower, /not sure|cannot ground|loop in/); // low-confidence -> human
});

test('system prompt encodes the brand voice rules', () => {
  assert.match(lower, /no emoji/);
  assert.match(lower, /active voice/);
  assert.match(lower, /superlative/);                // explicitly bans empty superlatives
});

test('system prompt itself uses no empty superlatives', () => {
  for (const b of ['game-changing', 'best-in-class', 'world-class', 'revolutionary', 'cutting-edge']) {
    // allowed only inside the explicit ban list; flag stray promotional use
    const idx = lower.indexOf(b);
    if (idx !== -1) {
      const ctx = lower.slice(Math.max(0, idx - 120), idx);
      assert.match(ctx, /no |never |avoid |without |ban|superlative/, `stray superlative "${b}"`);
    }
  }
});

test('all four personas have a register block', () => {
  for (const p of ['buyer_cx', 'buyer_it', 'developer', 'curious']) {
    assert.match(SRC, new RegExp(`["']${p}["']\\s*:`), `missing persona block: ${p}`);
  }
});
