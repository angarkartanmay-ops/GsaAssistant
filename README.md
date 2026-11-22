# H.A.V.O.C.

**Helpful Assistant, Very Occasionally Chaotic.** A personal assistant for Google Student Ambassador work. It runs on
your own Windows PC for $0, and you can reach it from your phone wherever you are.

It reads and summarises your GSA mail, reads the ambassador dashboard and its tasks, follows your
batch Discord and the GSA WhatsApp group, and **posts your work for you**: text, photos and files, to
Discord, WhatsApp and email. You can type, talk to it at the PC ("Havoc, brief me"), DM it on Discord,
or use the phone app. It answers in a warm, quick, FRIDAY-style voice, calls you **Sir**, and has
opinions about your deadlines. The name is a warning label, not a design goal.

```
 phone ──Discord DM / Tailscale app──┐
 you at the PC ──voice / HUD─────────┤
                              ┌──────▼───────┐  tools  ┌──────────────────────────────────────┐
                              │  agent loop  │────────▶│ Gmail (read + official sender)       │
                              │  Qwen3-8B on │◀────────│ Dashboard · Discord (posts as you)   │
                              │  Ollama/GPU  │         │ WhatsApp (your number) · tasks · PC  │
                              └──────┬───────┘         └──────────────────────────────────────┘
               Whisper (speech in) ◀─┴─▶ Kokoro (speech out)
```

## What it can do

| Area | Say or type |
|---|---|
| Post your work | "Send these photos to the GSA group: today's Gemini workshop" · "Post the recap in #announcements" · "Email the report to the POC" |
| Undo | "Undo that" deletes the last Discord or WhatsApp post for everyone. Email can't be unsent. |
| Mail | "Summarise my GSA mail from this week" · "Draft a reply saying I'll submit Thursday" |
| Dashboard | "What's on my dashboard?" · "How many engagements this month?" · "Mark the photo task done" |
| Chats | "What did I miss in the GSA group?" · "Summarise the batch Discord since yesterday" |
| Briefing | "Brief me" · a spoken morning briefing at 08:30 · alerts for program mail, new tasks, @mentions |
| Tasks & memory | "Add a task: slides to Riya by Thursday 6pm" · "Remind me in 40 minutes" · "Remember Riya is my co-lead" |
| PC | "Open Discord" · "Pause the music" · "System status" · "Run ipconfig" · "Lock the PC" |

**It posts straight away.** You asked for no confirmation step on email, Discord or WhatsApp.
PowerShell commands outside a read-only list, and shutdown/restart, still ask first, because those
protect the PC rather than slow down posting. To get a preview before email goes out, set
`safety.confirm_email_send: true`.

## Using it from your phone

The PC does the work, so **it has to be on and awake**. `setup.ps1` offers to turn off sleep on AC
power. There are two ways in; use either or both.

**1. Discord DM (nothing to install).** DM your bot from the Discord app.
* Text works like typing to Havoc.
* **Photos and files** you attach are saved to Havoc's inbox. Say what to do with them, e.g.
  "post these in the GSA group".
* **Voice notes** are transcribed on your PC. The reply comes back as text plus a short spoken clip.

**2. The phone app (private, over Tailscale).** You get the same HUD with a phone mic button and a
paperclip for photos.
1. `setup.ps1` installs Tailscale, a free private network for your own devices, and the wizard runs
   `tailscale serve`. Your PC gets an address like `https://my-pc.tail1234.ts.net`. Only devices
   signed in to *your* Tailscale account can open it.
2. On the phone, install Tailscale from the app store and sign in with the same account.
3. Open that address, enter your PIN, then use **Add to Home screen**.
4. Tap the mic to talk and tap again to send, or tap the paperclip to attach photos.

If `tailscale serve` complains about HTTPS, turn on **HTTPS certificates** in the Tailscale admin
console (DNS page) and re-run `python -m havoc setup`. The phone mic only works over https.

Security:
* The HUD only listens on `127.0.0.1`. Tailscale is the only way in from outside.
* Every non-local request needs the PIN. After 5 wrong tries that device is locked out for 15 minutes.
* Requests with any other hostname are refused.
* Attachments can only come from Havoc's inbox (things you sent from the phone), so a misheard
  request can't send arbitrary files from the PC.

## Voice and personality

* **Personality** (`havoc/brain/persona.py`): FRIDAY's competence (she took over from JARVIS as a
  direct, warm operations assistant, voiced by Kerry Condon) plus a sarcastic, fun, expressive streak.
  * Havoc leads with the facts, then adds the attitude. It celebrates wins, is openly appalled by
    newsletters pretending to be urgent, and teases your procrastination.
  * Turn it up or down with `assistant.sass`: `0` none, `1` light, `2` regular (default), `3` full sass.
  * It drops the jokes when something is urgent, failed, or you sound stressed.
  * It always calls you **Sir** (`assistant.address_as`), and a final check adds "Sir" if the model forgets.
* **Posts in your name** are expressive but never sarcastic. Announcements get energy, an
  exclamation and a fitting emoji or two on WhatsApp/Discord; emails stay polite. "Make it exciting"
  changes the wording only. It never invents dates, numbers or perks you didn't give.
* **No made-up facts:** questions about your mail, tasks, chats or your day are always answered from
  the real data. If the model tries to answer from imagination, it's sent back to check. If it still
  won't, Havoc runs the right tool itself and makes the model answer from the result.
* **Voice** (`havoc/voice/tts.py`): Kokoro-82M (Apache-2.0) running locally. The default is a blend
  of the warm British female voices `bf_emma` (60%) and `bf_isabella` (40%) at a brisk 1.05 speed. No free local model has
  an Irish voice, so this is the closest warm, quick option. It doesn't imitate the actress.
  To audition others: `python -m havoc say "Morning, Sir." --voice bf_isabella`
  (also `bf_emma`, `bf_alice`, `bf_lily`).
* **No AI slop:** filler like "Certainly!", "I hope this finds you well", "delve" and "feel free to"
  is banned in the prompt and stripped by `havoc/brain/antislop.py`. Anything posted in your name is
  rewritten to sound like you, not like Havoc.

## Install (Windows 11, about 20 minutes, mostly downloads)

1. Download this repo to e.g. `C:\HAVOC`.
2. Run `powershell -ExecutionPolicy Bypass -File .\setup.ps1`. It installs Python 3.12, Node.js,
   Ollama and Tailscale via winget, then the packages, the voice models and `qwen3:8b`. Then it runs
   a wizard for the details below.
3. Sign in to the dashboard once: `.\.venv\Scripts\python.exe -m havoc login-dashboard`
4. Double-click **HAVOC** on the desktop and scan the WhatsApp QR the first time.
5. Run `.\.venv\Scripts\python.exe -m havoc doctor` whenever something seems off. It names the problem and the fix.

**Secrets (passwords, tokens, PIN) go into the wizard or `.env` on your PC, never into a chat.**
What you can safely share is non-secret: addresses, channel names, group names.

<details><summary><b>Mail: your inbox and the official address you send from</b></summary>

* **Reading:** `GMAIL_ADDRESS` + an App Password for the inbox that receives GSA mail.
  Turn on 2-Step Verification, create the password at https://myaccount.google.com/apppasswords,
  and make sure IMAP is on in Gmail settings.
* **Sending:** set `OFFICIAL_MAIL_ADDRESS` if you send from a different (official) address. If
  it's a normal Gmail, give it an App Password too.
* **College / Workspace accounts often block App Passwords.** Use OAuth instead (free):
  1. In https://console.cloud.google.com create a project, enable the **Gmail API**, then add an
     **OAuth client ID** of type *Desktop app*. Download the JSON as `data/google_oauth_client.json`.
  2. Under *OAuth consent screen*, add your address as a test user.
  3. Set `gmail.official_auth: oauth` in `config.yaml` (or `gmail.auth: oauth` for the reading
     inbox), then run `python -m havoc login-mail` once.

  If your college admin blocks third-party apps entirely, Google won't allow either route. In that
  case, forward GSA mail to a personal Gmail and send from that.
* `gmail.sender_name` sets the name people see. Drafts go to Gmail **Drafts**. Sent mail is
  plain text plus attachments.
</details>

<details><summary><b>Discord bot (posts under your name)</b></summary>

1. At https://discord.com/developers/applications click **New Application**, then on the **Bot** tab
   **Reset Token** and copy it. Turn on **Message Content Intent**.
2. Invite it with your Application ID:
   `https://discord.com/oauth2/authorize?client_id=YOUR_APP_ID&scope=bot&permissions=536939520`
   (View Channels, Send Messages, Read Message History, **Manage Webhooks**).
3. Turn on Developer Mode in Discord. Copy your **Server ID** and your own **User ID** for the wizard.

Posts go through a channel webhook, so they show **your name and avatar** (Discord adds a small
APP tag). If the bot lacks Manage Webhooks in a channel, it posts as itself there. Posting from
your personal account itself (a "self-bot") isn't supported: Discord bans accounts for it.
DMs you send the bot become commands to Havoc.
</details>

<details><summary><b>WhatsApp (sends from your own number)</b></summary>

A local bridge links your WhatsApp as a **linked device**, like WhatsApp Web, using the
open-source Baileys library. It listens only on `127.0.0.1` and stores the session in `data/whatsapp`.
It can send text, photos (with captions) and documents to the group, and delete its own recent
messages for undo.

**This is unofficial and against WhatsApp's Terms of Service.** There's a small risk of the number
being restricted, especially with bulk or spammy sending, so keep it human-sized.
To link, scan the QR shown in the HUD or the bridge window via WhatsApp → Settings → Linked devices.
</details>

<details><summary><b>Ambassador dashboard</b></summary>

Set `dashboard.url` and run `python -m havoc login-dashboard` once. Sign in with Google, then close
the window. After that Havoc reads the dashboard in the background, turns it into a task list, and
alerts you to new tasks.

If Google refuses the sign-in, start Chrome with `--remote-debugging-port=9222`, sign in there,
and set `dashboard.cdp_url: http://127.0.0.1:9222`.
</details>

## At the PC

* **Voice:** say **"Havoc, …"**. After it answers you have about 7 seconds for a follow-up without the
  wake word. **Ctrl+Alt+M** (or the mic button) talks, or cuts it off mid-sentence.
* **Typing:** use the HUD, or the terminal: `python -m havoc chat`.
* **Knowledge:** put program facts (POC, targets, deadlines) in `knowledge/gsa.md`.

## Hardware (RTX 5060, 8 GB)

| Part | Runs on | VRAM |
|---|---|---|
| Qwen3-8B (Q4) via Ollama | GPU | ~5.5 GB |
| Whisper `small.en` (speech in) | GPU float16, automatic CPU fallback | ~0.6 GB |
| Whisper `tiny.en` (wake word) | CPU | 0 |
| Kokoro-82M (speech out) | CPU, faster than real time | 0 |

RTX 50 cards need CUDA 12.8-era software. Ollama handles that itself. Whisper test-runs on the
GPU at startup and quietly falls back to CPU if needed; `doctor` shows which it used. If VRAM is
tight, set `llm.model: qwen3:4b`.

## Layout

```
havoc/
  brain/      agent loop, persona, anti-slop (+ "Sir"), Ollama client, SQLite memory
  tools/      every capability the model can call (one @tool function each)
  connectors/ gmail_imap (+ google_oauth), dashboard_browser, discord_bot, whatsapp_client
  voice/      VAD + wake word + Whisper, Kokoro TTS, the voice loop
  server/     HUD + phone app (FastAPI, WebSocket, PIN gate, uploads, voice notes)
  scheduler.py  alerts, reminders, morning briefing
whatsapp-bridge/  Node + Baileys linked-device bridge (127.0.0.1:3777)
knowledge/        notes Havoc reads every turn
data/             database, logs, models, inbox, sessions (git-ignored; keep private)
```

## Development

```
pip install -r requirements-dev.txt
pytest
```
The tests use a scripted fake LLM and mock connectors, so they need no GPU, accounts or network.
