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

## The apps: one brain, three ways in

HAVOC's brain (the model, memory, accounts and conversation) runs on your PC. Every way of reaching
it talks to that same brain, so they all share one conversation. Ask something on your phone and the
PC window shows it; open the phone later and it has the whole thread, Discord DMs included.

| | What it is | Get it |
|---|---|---|
| **HAVOC.exe** (Windows) | Runs the brain + WhatsApp bridge in the background, shows the HUD, lives in the tray, can start with Windows. | `HAVOC-1.0.0-portable.exe` (no install), or the installer from GitHub Actions |
| **HAVOC.apk** (Android) | The same HUD on your phone, plus "Hey Havoc", a Quick Settings tile and a "Talk to Havoc" shortcut. | `app-release.apk` (sideload) |
| **Discord DM** | Message your bot from anywhere: text, photos, voice notes. | Nothing to install |

The PC does the thinking, so **it has to be on and awake**; the setup offers to stop it sleeping on AC power.

### Phone setup (once)
1. On the PC: **Connections → Phone**. Set a PIN, then press **Set up phone access**. This signs the
   PC in to Tailscale, a free private network between your own devices, and publishes HAVOC at an
   address like `https://my-pc.tail1234.ts.net`. Only devices signed in to *your* Tailscale can open it.
2. On the phone: install **Tailscale** from the Play Store and sign in with the same account.
3. Install the **HAVOC APK**: open the file and allow "install unknown apps" for that one time.
4. Open HAVOC, paste the PC address, enter the PIN. You get the same screen as on the PC.

If Tailscale complains about HTTPS, turn on **HTTPS certificates** in the Tailscale admin console
(DNS page) and press the button again. The phone mic needs https.

### "Hey Havoc"
* Turn it on under **Today → This phone** in the app, or in the app's phone settings. Say
  **"Hey Havoc"**, wait for the beep, then speak. HAVOC answers in a notification and out loud.
* It's HAVOC's own wake word, recognised **on the phone, offline** by Vosk. It downloads a 40 MB
  speech model the first time. Nothing is sent anywhere until after the beep.
* **Google Assistant is untouched.** HAVOC doesn't register as an assistant or change any Google
  setting, and "Hey Google" keeps working. On a few phones the system pauses other apps' microphones
  while Google is listening; HAVOC just resumes afterwards.
* Listening all the time costs some battery. Use **Only while charging** if that bothers you. The
  Quick Settings tile and the home-screen shortcut ("Talk to Havoc") work without the wake word.
* Android requires a visible notification while any app listens; that's the "Listening for Hey
  Havoc" notification. After a phone restart, open HAVOC once to resume listening (Android doesn't
  let apps start the mic on their own at boot).

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
  * Turn it up or down with `assistant.sass`: `0` none, `1` light (default), `2` regular, `3` full sass.
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

## Install (Windows 11)

**Easiest: the app.** Run `HAVOC-1.0.0-portable.exe`. The first launch installs Python, Ollama,
Tailscale and the AI model (about 6 GB; a progress window shows each step), then HAVOC opens. Your
settings and data live in `%LOCALAPPDATA%\HAVOC`, so replacing the app never touches them. The tray
icon has **Start with Windows**, the data folder and the log.

**From source** (for tinkering): `powershell -ExecutionPolicy Bypass -File .\setup.ps1`, then `start.bat`.

### Connect your accounts
Open **Connections** (top right in HAVOC, on the PC). Everything is entered there and saved only on
this PC. Passwords and tokens go into `.env` and are never shown again, not even in Connections.
Connections can't be opened from the phone, so a lost phone can't read or swap your keys.

| Account | What to do |
|---|---|
| Inbox (reads GSA mail) | Address + a Gmail App Password (needs 2-Step Verification) |
| Official address (sends) | Pick **Open as Gmail draft** (no password: HAVOC writes the mail and opens it in that account, you press Send), or **Send directly** with an App Password / Sign in with Google |
| GSA dashboard | Paste the URL, press **Sign in on this PC**, log in once |
| Discord | Bot token, server ID, your username (or ID); default channel as a name, ID or channel link; then use the **Invite the bot** link it shows |
| WhatsApp | Scan the QR in Connections from WhatsApp → Linked devices |
| Phone | PIN + **Set up phone access** |

Press **Save**, then **Restart now**. Run `python -m havoc doctor` (or look at Today → Systems) to see what's connected.

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
  server/     FastAPI + WebSocket, PIN gate, Connections API, uploads, voice notes
  settings.py   Connections: config.yaml + .env (secrets write-only)
  tailscale.py  phone access
  scheduler.py  alerts, reminders, morning briefing
ui/               the interface (React + Tailwind + a procedural three.js core); builds into havoc/server/static/app
desktop/          Electron app: HAVOC.exe (first-run setup, background brain + bridge, tray)
android/          Kotlin app: HAVOC.apk (HUD WebView, "Hey Havoc" via Vosk, tile, shortcut)
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

* UI: `cd ui && npm install && npm run dev` (proxies to a running HAVOC), `npm run build` to update the bundled copy.
* Desktop: `cd desktop && npm install && npx electron-builder --win portable` (the NSIS installer needs Windows or Wine).
* Android: `cd android && ./gradlew assembleRelease` (needs the Android SDK; set `sdk.dir` in `local.properties`).
* Or run **Actions → Build apps** on GitHub to get the installer, portable exe and APK as downloads.
