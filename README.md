# M.A.L.I.C.E.

**Mostly Altruistic Logic & Intelligence for Campus Engagement.** A personal AI assistant for
Google Student Ambassador work that runs entirely on your own Windows PC, for $0.

It reads and summarises your GSA mail, reads the ambassador dashboard and its tasks, follows your
batch Discord server and the GSA WhatsApp group, posts and replies for you, and handles general PC
jobs. You talk to it by typing or by voice ("Malice, brief me"), and it answers in a calm,
sardonic, faintly menacing machine voice. The attitude is aimed at your deadlines, never at you.

```
 you ──voice/text──▶  HUD (Edge app window) / terminal / Discord DM
                          │
                  ┌───────▼────────┐   tools   ┌──────────────────────────────────────┐
                  │  agent loop    │──────────▶│ Gmail (IMAP) · Dashboard (browser)   │
                  │  Qwen3-8B via  │◀──────────│ Discord bot · WhatsApp bridge        │
                  │  Ollama (GPU)  │           │ tasks · reminders · web · PowerShell │
                  └───────┬────────┘           └──────────────────────────────────────┘
          Whisper (STT) ◀─┴─▶ Kokoro + effects chain (TTS)
```

## What it can do

| Area | Examples |
|---|---|
| Mail | "Summarise my GSA mail from this week" · "Draft a reply to the report reminder saying I'll submit Thursday" · "Send it" |
| Dashboard | "What's on my dashboard?" · "How many engagements do I have this month?" · "Mark the photo upload task done" |
| WhatsApp group | "What did I miss in the GSA group?" · "Tell the group I've booked the seminar hall for Friday 4pm" |
| Discord | "Summarise the batch server since yesterday" · "Post in #announcements that the Gemini workshop moved to Saturday" |
| Briefing | "Brief me" · a spoken morning briefing at 08:30 · alerts when program mail, new dashboard tasks or @mentions arrive |
| Tasks & memory | "Add a task: share slides with Riya by Thursday 6pm" · "Remind me in 40 minutes to call the POC" · "Remember that Riya is my co-lead" |
| PC | "Open Discord" · "Pause the music" · "System status" · "What's in my Downloads folder?" · "Run ipconfig" · "Lock the PC" |
| Web | "Search for Gemini student ambassador report guidelines" · "Read this page: …" |

DM the bot on Discord from your phone and it answers as Malice, with the same tools.

## The voice and personality

The persona was researched from James Spader's Ultron. Whedon cast Spader for a voice that is
"calm and compelling yet human and funny". Marvel said they "did not hire James Spader to do a
robot voice": it was his natural delivery, with sound design layered on afterwards. Malice copies
the recipe, **not the actor's voice** (cloning a real person's voice is off the table):

* **Delivery** (`malice/brain/persona.py`): measured, articulate, dry wit, one flourish at most,
  never flustered, menacing toward inefficiency and loyal to you.
* **Voice** (`malice/voice/tts.py`): Kokoro-82M, an Apache-2.0 model running locally on the CPU.
  It blends the deep American male voices `am_onyx` and `am_michael` at 0.92 speed.
* **Sound design** (`malice/voice/fx.py`): pitch down about 1.6 semitones, a quiet octave-down
  double, a faint 46 Hz ring-mod shimmer, chorus doubling, low-shelf weight and a small metallic room.
  Set `voice.menace` from `0` (clean) to `3` (full machine). Try it:
  `.\.venv\Scripts\python.exe -m malice say "Your report is due Friday." --menace 3`

### No AI slop
* The system prompt bans the usual tells: "Certainly!", "I hope this finds you well", "delve",
  "feel free to", emoji walls, em-dash chains.
* `malice/brain/antislop.py` strips them from every reply. It also re-writes anything going to
  other people (mail, Discord, WhatsApp) before you see the preview.
* Anything sent in your name is written as **you**: a friendly, organised ambassador, never in
  Malice's villain voice.

## Install (Windows 11, about 20 minutes, mostly downloads)

1. Download this repo (Code → Download ZIP, or `git clone`) to e.g. `C:\MALICE`.
2. Right-click `setup.ps1` → **Run with PowerShell**, or run:
   ```
   powershell -ExecutionPolicy Bypass -File .\setup.ps1
   ```
   It installs Python 3.12, Node.js and Ollama with winget, all Python and Node packages, the voice
   models and `qwen3:8b`, then starts a wizard that asks for the details below.
3. Sign in to the dashboard once: `.\.venv\Scripts\python.exe -m malice login-dashboard`
4. Double-click **MALICE** on the desktop. The HUD opens; scan the WhatsApp QR the first time.
5. Anything not working? `.\.venv\Scripts\python.exe -m malice doctor` names each problem and its fix.

### What the wizard asks for

<details><summary><b>Gmail App Password</b> (2 minutes)</summary>

1. Turn on 2-Step Verification for the Google account that gets GSA mail.
2. Open https://myaccount.google.com/apppasswords, create one called "Malice", and copy the 16 letters.
3. In Gmail → Settings → Forwarding and POP/IMAP, make sure IMAP is enabled.

Malice reads mail over IMAP and sends over SMTP. Drafts it writes appear in your Gmail **Drafts** folder.
Tune what counts as GSA mail with `gmail.gsa_query` in `config.yaml`, written exactly like a Gmail
search (add your program manager's address there).
</details>

<details><summary><b>Discord bot</b> (5 minutes)</summary>

1. https://discord.com/developers/applications → **New Application** → name it *Malice*.
2. **Bot** tab → **Reset Token** → copy it (the wizard asks for it).
   On the same page enable **Message Content Intent**.
3. Invite it to your batch server. Open this URL with your Application ID from the General
   Information tab: `https://discord.com/oauth2/authorize?client_id=YOUR_APP_ID&scope=bot&permissions=68608`
   (View Channels, Send Messages, Read Message History).
4. Discord → Settings → Advanced → **Developer Mode** on. Right-click the server → *Copy Server ID*,
   then right-click yourself → *Copy User ID*. The wizard asks for both.
</details>

<details><summary><b>WhatsApp</b> (1 minute, read this first)</summary>

The bridge links your WhatsApp as a **linked device**, the same mechanism as WhatsApp Web, using the
open-source Baileys library. It runs only on `127.0.0.1` and stores the session in `data/whatsapp`.

**This is unofficial and against WhatsApp's Terms of Service.** There is a small risk of the number
being restricted, especially with bulk or spammy sending. Keep usage human-sized. You chose
auto-send, so `wa_send` goes out without a confirm step. Set `safety.confirm_whatsapp_send: true`
if you change your mind.

To link: start Malice. A QR code appears in the HUD's Systems panel and in the bridge window. Scan it
from WhatsApp → Settings → Linked devices → Link a device. To unlink, remove it in WhatsApp, or delete
`data/whatsapp/auth`.
</details>

<details><summary><b>Ambassador dashboard</b></summary>

Put the dashboard URL in `config.yaml` (`dashboard.url`) and run `malice login-dashboard`. A browser
window opens: sign in with Google, then close it. Malice keeps that profile in `data/browser-profile`
and reads the dashboard headlessly from then on. The local model turns the page into a task list, so
it copes with whatever layout the web app has. New tasks trigger an alert.

**If Google refuses the sign-in** ("this browser may not be secure"), attach Malice to your normal
Chrome instead:
1. Close Chrome, then start it with `chrome.exe --remote-debugging-port=9222` and sign in to the
   dashboard normally.
2. Set `dashboard.cdp_url: http://127.0.0.1:9222`.
</details>

## Using it

* **Voice:** say **"Malice, …"** and keep talking. After it answers you have about 7 seconds for a
  follow-up without the wake word. Or press **Ctrl+Alt+M** (or the mic button) to talk. Pressing it
  while Malice is speaking cuts it off.
* **Type:** in the HUD, or in a terminal: `.\.venv\Scripts\python.exe -m malice chat`.
* **Approvals:** emails, Discord posts, non-read-only PowerShell commands, overwriting files, and
  sleep/restart/shutdown all show the exact text first and wait for "yes".
* **Knowledge:** put program facts in `knowledge/gsa.md` (POC, targets, deadlines). Malice reads
  that folder on every turn.

## Hardware notes (RTX 5060, 8 GB)

| Part | Runs on | VRAM |
|---|---|---|
| Qwen3-8B (Q4) via Ollama | GPU | ~5.5 GB |
| Whisper `small.en` (STT) | GPU (float16), automatic CPU fallback | ~0.6 GB |
| Whisper `tiny.en` (wake word) | CPU | 0 |
| Kokoro-82M + effects (TTS) | CPU, faster than real time | 0 |

* RTX 50 (Blackwell) needs CUDA 12.8-era software. Ollama's Windows build handles that itself.
  For Whisper, Malice runs a test decode on the GPU at startup and quietly drops to CPU int8 if the
  kernels are missing; `doctor` shows which one it used. Keep the NVIDIA driver current.
* VRAM tight (games open)? Set `llm.model: qwen3:4b` and/or `voice.stt_device: cpu`.

## Layout

```
malice/
  brain/      agent loop, persona, anti-slop, Ollama client, SQLite memory
  tools/      every capability the model can call (one @tool function each)
  connectors/ gmail_imap, dashboard_browser, discord_bot, whatsapp_client
  voice/      VAD + wake word + Whisper STT, Kokoro TTS + effects, the voice loop
  server/     FastAPI + WebSocket HUD
  scheduler.py  mail/dashboard/WhatsApp alerts, reminders, morning briefing
whatsapp-bridge/  Node + Baileys linked-device bridge (127.0.0.1:3777)
knowledge/        notes Malice reads every turn
data/             your database, logs, models, browser profile, WhatsApp session (git-ignored)
```

**Adding a capability:** write an async function in `malice/tools/` with `@tool(...)` and it
becomes callable. Add keywords to `ROUTES` in `brain/agent.py` so the router offers it.

## Privacy

Everything runs locally: the language model, speech recognition, the voice, the database and the
browser profile. Network traffic goes only to the services themselves (Gmail, Discord, WhatsApp, the
dashboard) and to DuckDuckGo when you ask for a web search. `.env`, `config.yaml` and `data/` are
git-ignored; don't share them.

## Development

```
pip install -r requirements-dev.txt
pytest
```
The tests use a scripted fake LLM and mock connectors, so they need no GPU, accounts or network.
