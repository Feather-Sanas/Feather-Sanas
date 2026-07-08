# Sanas.AI — Sanas.ai Speech AI Chatbot: What It Is & How to Use It

---

## What Is Sanas.AI?

**Sanas.AI** is an AI-powered Speech AI consultant and chatbot built as a brand-accurate prototype for Sanas.ai. It lives at `http://127.0.0.1:8000/` and combines a polished marketing surface with an always-on chat panel that answers real questions about Sanas technology, demonstrates the audio engine live, and routes interested users to a book-a-demo / human-handoff form.

The chatbot is powered by **Claude** (Anthropic) when an `ANTHROPIC_API_KEY` is configured, grounded against a crawled index of sanas.ai content. Without a key, a deterministic rule engine takes over seamlessly — the UI looks and behaves identically either way.

---

## 1. The Landing Page

When you first open `http://127.0.0.1:8000/`, you land on the Sanas marketing surface. From here you have two main entry points:

- **Open the Playground** — jumps directly to the audio processing tool inside the chat panel
- **Play a before/after** — opens the chat and triggers an audio comparison card
- The **Sanas icon button** in the bottom-right corner opens Sanas.AI's chat panel at any time

> **Tip:** Deep-link directly to any view: `/?open=chat`, `/?open=playground`, or `/?open=demo`.

---

## 2. The Chat Panel

Click the circular Sanas icon in the bottom-right corner of the page. The chat panel slides in from the right.

### 2a. The Chat Header Controls

| Control | What it does |
|---|---|
| **# button** | Opens the internal session-trace drawer (read-only) |
| **X button** | Closes the chat panel |
| **I'M A… dropdown** | Sets your persona — changes Sanas.AI's register and focus |
| **Industry… dropdown** | Filters responses and case studies to a specific vertical |
| **Test a model** | Opens the Playground inline |
| **More Information** | Triggers the demo-booking/lead-capture flow |

### 2b. Setting Your Persona

Click the **"Just looking"** dropdown to choose who you are. Sanas.AI's language, depth, and examples change immediately.

- **Just looking** — accessible, general-purpose tone (the default)
- **CX / Contact Center buyer** — focuses on AHT, CSAT, agent experience metrics
- **Telco / Carrier** — uses MOS/PESQ, codec latency, in-path deployment language
- **IT / Security** — emphasizes data handling, Zero-Knowledge processing, compliance posture
- **Developer** — SDK quickstarts, curl examples, backend status, code blocks
- **Data Scientist** — speech science depth: STFT, WER, MFCC, VAD; grounded in /science articles
- **Partner** — co-sell framing and partner application flow

### 2c. Setting an Industry

Click the **Industry…** dropdown. Available: **Healthcare, Financial Services, Retail, Travel & Hospitality, Telecom**. Selecting one primes Sanas.AI with that industry's content and adds a "Customer stories" chip with real sanas.ai case studies.

### 2d. Suggestion Chips & Typing a Message

Sanas.AI pre-fills 3–4 clickable chips based on your current persona and context. Click any chip to fire it as a message, or type freely in the text box at the bottom. Click the **upload arrow** button to attach an audio file for live processing.

### 2e. Reading Sanas.AI's Answers

Sanas.AI's replies stream token-by-token and finalize with full markdown formatting. At the bottom of each answer, **source pills** link back to the exact sanas.ai pages used to ground the response. Click any pill to open that source directly.

---

## 3. The Playground

Access via `?open=playground`, the **Open the Playground** button, or **Test a model** in chat.

1. **Choose a Capability** — *Speech Enhancement* or *Noise Cancellation*
2. Click **Record** (live mic) or **Upload** (file from disk)
3. Wait for the backend to process your clip through the real Sanas SDK
4. Use the **Before / After** toggle to compare original and processed audio
5. Switch the **Model** dropdown to re-run the same clip through a different Sanas model — waveform and spectrogram update instantly
6. Click **Analyze recognition (ASR)** to compare speech recognition accuracy before and after

---

## 4. The Audio Showroom

Click **"Play a before/after"** in chat to open a curated audio comparison card. Three real-world clips stream from the Sanas media CDN:

| Scenario | What you hear |
|---|---|
| **Accent Translation** | Gabriel Rivera's voice: degraded to native-clarity reconstruction |
| **Ambient Noise** | Speech with rain noise: OFF to ON (noise removed) |
| **Background Voices & Music** | Music background: OFF to ON (voice isolated) |

Click **Play**, then toggle the **raw / Sanas** pill mid-play to hear the transition live.

---

## 5. The Session-Trace Drawer

Click the **#** button in the top-right of the chat header. It shows the live per-turn event stream: turn ID, timestamp, event type, detected persona, and page context. It is **read-only** — there is no admin login or upload here.

**Admin console (separate page).** Knowledge-base management and marketing analytics live at **`/admin.html`** on the backend, not in the chat. Sign in with `RAG_ADMIN_PASSWORD` (`server/.env`) to drag-and-drop unstructured documents (PDF / DOCX / TXT / MD) that become grounding context for every visitor, manage/clear the index, and view marketing analytics (visitor profiles, events, chat threads, first-touch attribution, and an events.jsonl export).

---

## 6. Quick Reference

### URL Deep-Links

| URL | What opens |
|---|---|
| `http://127.0.0.1:8000/` | Landing page |
| `http://127.0.0.1:8000/?open=chat` | Landing page + chat open |
| `http://127.0.0.1:8000/?open=playground` | Landing page + Playground open |
| `http://127.0.0.1:8000/?open=demo` | Landing page + book-a-demo open |
| `http://127.0.0.1:8000/?persona=developer` | Chat open, Developer persona pre-set |
| `http://127.0.0.1:8000/api/health` | Backend health JSON (SDK mode, LLM, ASR status) |
| `http://127.0.0.1:8000/api/models` | Available Sanas models list |

### Tips

- **Persona shapes everything.** Switching from *Just looking* to *Developer* or *Data Scientist* fundamentally changes depth, vocabulary, and examples.
- **Source pills are clickable.** Every answer shows pills below the reply; click to open the source page in a new tab.
- **The Before/After toggle works mid-play.** Flip it while audio is playing to hear the transition live.
- **The model picker re-processes without re-uploading.** Switching the Analyze against dropdown immediately re-runs the same original file.
- **Runs without the SDK — but never fakes audio.** Chat (Claude or the rule-based engine) and the curated before/after demos work without the SDK; live audio processing reports as unavailable (`/api/process` returns 503) rather than producing mock results.
- **The spectrogram is browser-native.** The frequency-time heatmap runs as a client-side STFT calculation — no extra dependencies needed.
