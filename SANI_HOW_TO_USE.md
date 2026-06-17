# Sani — Sanas.ai Speech AI Chatbot: What It Is & How to Use It

---

## What Is Sani?

**Sani** is an AI-powered Speech AI consultant and chatbot built as a brand-accurate prototype for Sanas.ai. It lives at `http://127.0.0.1:8000/` and combines a polished marketing surface with an always-on chat panel that answers real questions about Sanas technology, demonstrates the audio engine live, and can connect users to phone calls or human agents.

The chatbot is powered by **Claude** (Anthropic) when an `ANTHROPIC_API_KEY` is configured, grounded against a crawled index of sanas.ai content. Without a key, a deterministic rule engine takes over seamlessly — the UI looks and behaves identically either way.

---

## 1. The Landing Page

When you first open `http://127.0.0.1:8000/`, you land on the Sanas marketing surface. From here you have two main entry points:

- **Open the Playground** — jumps directly to the audio processing tool inside the chat panel
- **Play a before/after** — opens the chat and triggers an audio comparison card
- The **Sanas icon button** in the bottom-right corner opens Sani's chat panel at any time

> **Tip:** Deep-link directly to any view: `/?open=chat`, `/?open=playground`, or `/?open=connect`.

---

## 2. The Chat Panel

Click the circular Sanas icon in the bottom-right corner of the page. The chat panel slides in from the right.

### 2a. The Chat Header Controls

| Control | What it does |
|---|---|
| **# button** | Opens the internal observability/admin drawer |
| **X button** | Closes the chat panel |
| **I'M A… dropdown** | Sets your persona — changes Sani's register and focus |
| **Industry… dropdown** | Filters responses and case studies to a specific vertical |
| **Test a model** | Opens the Playground inline |
| **Speak live** | Starts a live mic streaming session |
| **More Information** | Triggers the demo-booking/lead-capture flow |

### 2b. Setting Your Persona

Click the **"Just looking"** dropdown to choose who you are. Sani's language, depth, and examples change immediately.

- **Just looking** — accessible, general-purpose tone (the default)
- **CX / Contact Center buyer** — focuses on AHT, CSAT, agent experience metrics
- **Telco / Carrier** — uses MOS/PESQ, codec latency, in-path deployment language
- **IT / Security** — emphasizes data handling, Zero-Knowledge processing, compliance posture
- **Developer** — SDK quickstarts, curl examples, backend status, code blocks
- **Data Scientist** — speech science depth: STFT, WER, MFCC, VAD; grounded in /science articles
- **Partner** — co-sell framing and partner application flow

### 2c. Setting an Industry

Click the **Industry…** dropdown. Available: **Healthcare, Financial Services, Retail, Travel & Hospitality, Telecom**. Selecting one primes Sani with that industry's content and adds a "Customer stories" chip with real sanas.ai case studies.

### 2d. Suggestion Chips & Typing a Message

Sani pre-fills 3–4 clickable chips based on your current persona and context. Click any chip to fire it as a message, or type freely in the text box at the bottom. Click the **upload arrow** button to attach an audio file for live processing.

### 2e. Reading Sani's Answers

Sani's replies stream token-by-token and finalize with full markdown formatting. At the bottom of each answer, **source pills** link back to the exact sanas.ai pages used to ground the response. Click any pill to open that source directly.

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

## 5. Connect by Voice

Access via `?open=connect` or by typing "Speak to a person" in chat. Connects you to a real phone call with Sanas processing audio in-path in real time (requires Twilio — see `TWILIO_SETUP.md`).

- **Talk to a human** — Twilio calls your phone and connects you to a human agent
- **Dial-in bridge** — call the Twilio number, key in any destination; DTMF mid-call switches models (1=NC, 2=SE, 3=Voice Isolation, 0=off)
- **Browser voice / Speak live** — WebRTC in the page; blank number = hear yourself through Sanas; enter a number to call them

Enter your phone number, select a mode, pick a Sanas model, then click **Call me**.

---

## 6. The Observability / Admin Drawer

Click the **#** button in the top-right of the chat header.

**Knowledge base (RAG)** — Admins log in with `RAG_ADMIN_PASSWORD` (`server/.env`) to unlock document upload. Uploaded PDFs, DOCX, or text files become grounding context for every visitor — cited as "from your documents" chips.

**Session trace** — Live per-turn event stream (§7.8 schema): turn ID, timestamp, event type, detected persona, and page context.

---

## 7. Quick Reference

### URL Deep-Links

| URL | What opens |
|---|---|
| `http://127.0.0.1:8000/` | Landing page |
| `http://127.0.0.1:8000/?open=chat` | Landing page + chat open |
| `http://127.0.0.1:8000/?open=playground` | Landing page + Playground open |
| `http://127.0.0.1:8000/?open=connect` | Landing page + Connect by voice open |
| `http://127.0.0.1:8000/?persona=developer` | Chat open, Developer persona pre-set |
| `http://127.0.0.1:8000/api/health` | Backend health JSON (SDK mode, LLM, ASR status) |
| `http://127.0.0.1:8000/api/models` | Available Sanas models list |

### Tips

- **Persona shapes everything.** Switching from *Just looking* to *Developer* or *Data Scientist* fundamentally changes depth, vocabulary, and examples.
- **Source pills are clickable.** Every answer shows pills below the reply; click to open the source page in a new tab.
- **The Before/After toggle works mid-play.** Flip it while audio is playing to hear the transition live.
- **The model picker re-processes without re-uploading.** Switching the Analyze against dropdown immediately re-runs the same original file.
- **Mock mode is fully functional.** Without the SDK or API key the app still runs end-to-end with clearly labeled mock results.
- **The spectrogram is browser-native.** The frequency-time heatmap runs as a client-side STFT calculation — no extra dependencies needed.
