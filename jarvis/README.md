# JARVIS

Local read-only graph index, Gmail reader, and voice console.
Python 3.10+ standard library; no packages to install.

From this directory:

```powershell
python data/generate.py
python -m agent.vault
```

The committed demo fixtures let you run just `python -m agent.vault`.
Use `--json` for the complete graph. Regeneration uses seed 42.

Demo is the default. All fixture content is invented and explicitly labeled.
Only `agent/data.py` reads the demo switch and accesses source folders.
To opt into real folders in PowerShell:

```powershell
$env:JARVIS_DEMO = '0'
$env:JARVIS_FOLDERS = 'C:\path\to\notes;C:\path\to\documents'
python -m agent.vault
```

Markdown and UTF-8 text are indexed recursively. PDF filenames become nodes;
PDF text extraction is unavailable in this stage and produces a visible warning.
No PDF content is claimed as read. Files over 2 MB, symlinks, `.git`,
`node_modules`, `.venv`, and Python cache directories are skipped.
Wikilinks create undirected edges; unresolved and ambiguous links are reported.
Source folders are never modified. The fixture generator writes only to data/demo.

The full canvas graph UI and permanent memory tools remain to be built.
The local Command Center brings speech, text conversation, and inbox summaries
into one interface.

## Email connection

Read-only Gmail sign-in is implemented for `sa3464@njit.edu`. It requires your
own Google **Desktop app** OAuth client; ChatGPT connector credentials cannot be
used by this local application. No password or API key goes into chat.

1. In [Google Cloud Console](https://console.cloud.google.com/), create or select
   a project and enable the **Gmail API**.
2. Configure Google Auth Platform branding, audience, and data access for
   `https://www.googleapis.com/auth/gmail.readonly`. If the app is external and
   in testing, add `sa3464@njit.edu` as a test user. NJIT may require administrator
   approval for third-party access; the app cannot bypass that policy.
3. Create an OAuth client with application type **Desktop app**. Download the
   JSON and put it at `jarvis/.secrets/google-oauth.json` (gitignored), or pass
   its existing location using `--client`.
4. From the repository root, run:

```powershell
$env:JARVIS_DEMO = '0'
python -m jarvis.agent.email
# Or: python -m jarvis.agent.email --client 'C:\path\to\downloaded-client.json'
```

Google opens a browser sign-in. Select your NJIT account and review the read-only
permission. After authorization, the terminal shows up to 10 unread inbox
messages, including sender, subject, date, and preview. It does not mark them read.
The connection is not complete until sign-in and the inbox request succeed.
No real mailbox is accessed in demo mode. No packages are installed.

Tokens and mail stay in process memory, with no disk cache. This first integration
requires sign-in for each run; it is not a persistent background connection.
It cannot send, delete, archive, or modify mail. It makes no model or voice calls.
Mail previews are untrusted content and must never be executed as instructions.
Do not commit your OAuth JSON or grant broader permissions to work around an error.

Protocol references: [Google desktop OAuth](https://developers.google.com/identity/protocols/oauth2/native-app)
and [Gmail scopes](https://developers.google.com/workspace/gmail/api/auth/scopes).

## Floating desktop core (Windows)

Double-click `JARVIS.pyw` at the repository root, or run
`python -B -m jarvis.agent.desktop` with the local Command Center server running.
The launcher starts the local server if it is stopped. Ollama is still required
for general conversation. The overlay does not launch automatically at Windows
sign-in.

- Drag the core to move across your desktop. Select **Panel** to open chat and
  inbox controls, and **Dismiss** to retract it.
- Select **Minimize** for the compact orb and tap it to restore. Use **Hide** or
  **Ctrl+Alt+J** to hide/show JARVIS. **Exit** is in the panel.
- Check **Enable voice**, then tap the core to talk. Silence sends the turn, and
  tapping again finishes it early. Escape stops microphone or reply audio.
  Audio stays in memory. ElevenLabs transcribes the microphone. Reply text goes
  to the configured speech provider, with Windows speech as a fallback.
- The waveform and speaking ring follow Windows' real playback position.
  Browser and Gmail tasks show activity and move the core aside. Gmail remains
  read-only and may open your browser for Google authentication.

## Local Command Center

To use the local console on the main JARVIS site, open the
[hosted Command Center](https://seth-jarvis-command-center.sa3464.chatgpt.site)
directly in Chrome on the Windows PC running JARVIS. Choose **Use local PC** and
allow loopback access if Chrome asks. Use **Get a pairing code** to open the local
pairing controls in another tab, generate a code, and paste it into the local
frame on the hosted page. Codes are single-use and expire after five minutes.
The session ends on disconnect, server restart, or after four hours. The local
console's **Disconnect hosted session** button also revokes access. The hosted
page can check availability, but browser isolation keeps local chat, audio,
Gmail, and the pairing code inside the local frame.

JARVIS can speak with ElevenLabs or Fish Audio. For Fish Audio, set
`JARVIS_TTS_PROVIDER=fish_audio`, your Fish Audio secret `FISH_API_KEY`, and
`FISH_AUDIO_REFERENCE_ID` (the ID of your Fish Audio voice) in `jarvis/.env`.
JARVIS sends the reference ID to Fish Audio's free `s2.1-pro-free` engine.
To use ElevenLabs for replies, set `JARVIS_TTS_PROVIDER=elevenlabs` and select
`ELEVENLABS_VOICE_ID`. The installed Windows voice can read replies when
the cloud provider is unavailable. Fish Audio setup does not change microphone
transcription.
If ElevenLabs transcription credits run out, the Windows console retries the
microphone recording with the installed Windows speech recognizer. Local
recognition uses the Windows speech language and may be less accurate.

From the repository root:

```powershell
$env:JARVIS_DEMO = '0'  # Only needed for actual inbox access
python -m jarvis.agent.main
```

Open **http://127.0.0.1:8767**. The server binds only to your computer. A voice key
has been configured in `jarvis/.env`, which is gitignored and is never served to
the browser. For a fresh installation, copy `.env.example` to `.env` and set
`ELEVENLABS_API_KEY`. Environment variables override file settings. Never paste
the key into browser code or commit it. Windows file permissions follow your
user account; POSIX installations should use `chmod 600 jarvis/.env`.

- Click **Start microphone** to enable voice and approve voice provider use
  for the current page session. No separate checkbox step is needed. Uncheck
  **Voice enabled for this session** to revoke that approval and stop the mic.
- **Speak text** sends up to 4,000 characters to the selected speech provider.
- **Start microphone** records WAV audio. Actual microphone levels
  drive the bars; 900 ms of silence after speech ends the turn. Transcripts appear
  after each turn, not as real-time partial words. Continuous listening resumes
  after transcription. Silence with no speech stops recording after 30 seconds.
- The mic is physically stopped during playback. Mic, Space (outside text input),
  or Escape provides explicit interruption. **Stop / mute** stops audio and mic.
- **Read unread email** starts Google authorization, fetches up to five unread
  messages, and displays sender, subject, and date. With voice approved it speaks
  sender/subject summaries. It does not read full message bodies. Those names and
  subjects go to the speech provider for the requested readout.

The endpoints are `/api/speak` (JSON text → MP3 or Windows fallback WAV),
`/api/listen` (recording → JSON transcript), and `/api/listen/local`
(WAV → Windows transcript). All require same-origin and per-process request tokens.
Only the Python server reads the voice API keys. Audio and mail are not saved.
Local model conversation is available through Ollama (see below).

ElevenLabs consumes account credits for generated speech and transcribed audio;
charges/allowances depend on your plan, model, and usage. The application does not
purchase credits or enable automatic top-ups. Review your account quota before
enabling voice. Default models are `eleven_multilingual_v2` and requested
`scribe_v1`; override the STT setting if your account no longer supports that model.
Failures are shown on screen, without exposing provider response bodies or keys.

References: [Fish Audio setup](https://docs.fish.audio/developer-guide/getting-started/api-key),
[ElevenLabs speech generation](https://elevenlabs.io/docs/api-reference/text-to-speech/convert),
and [ElevenLabs transcription](https://elevenlabs.io/docs/api-reference/speech-to-text/convert).

## Local questions and conversation

JARVIS uses **Ollama / llama3.2:3b** to answer general questions, explain concepts,
draft text, and discuss recent email summaries. Install Ollama and run
`ollama pull llama3.2:3b` once; start Ollama before using JARVIS. The model download
is approximately 2 GB. Set `OLLAMA_MODEL` in `.env` to use a different installed
local model. No paid model API key is needed. Inference uses your computer's CPU
or GPU and may take longer on slower hardware.

This laptop is configured with `OLLAMA_NUM_GPU=0` because its GPU path timed out
during verification. CPU inference was responsive. Remove that setting to retry
automatic GPU selection later.

Type a question and click **Ask JARVIS** or press Enter (Shift+Enter adds a line).
With microphone and voice enabled, each recorded turn is
transcribed, answered locally, then spoken. Listening resumes after playback.
The last 10 turns stay in page memory for follow-ups such as “why?” or “the second
one.” Reloading the page or **New conversation** clears that context.

Voice approval is optional for typed chat. When enabled, questions' audio goes
to ElevenLabs for transcription, and generated reply text goes to the selected
speech provider. Model prompts, profile, and recent conversation are sent only to the
loopback Ollama service. There is no live web search; current facts need external
verification. Answers can be wrong, especially with a small local model.

An explicit question about “my notes” or “my files” includes matching file
excerpts. Other questions are ordinary conversation. Retrieved content is marked
as untrusted. The model cannot send mail, spend, execute code, or write files.
Inbox access requires an explicit button action or direct user command. If Ollama is missing, the page
labels the limited fallback rather than presenting keyword search as AI reasoning.

Verification: `python -m unittest discover -s jarvis/tests`.
Protocol: [Ollama chat API](https://docs.ollama.com/api/chat).

## Spoken and typed commands (desktop)

The desktop console routes the same commands from typed input and microphone
transcripts:

- “Read my unread email” or “Check my inbox”: Google authorization followed by
  up to five unread sender/subject summaries and detailed cards. No mail is sent
  or marked read. Authorization may be required on each request.
- “Plan my day”: asks for unknown priorities or proposes up to five actions from
  the conversation. This is a suggested plan; the calendar is not connected.
- “Open YouTube”, “Open Google”, or “Go to https://example.com”: asks the default
  browser on the server computer to open a public web address. A link is also
  displayed. Only HTTP/HTTPS domains are supported; no scripts, files, credentials,
  IP addresses, or custom ports are accepted.
- Other questions continue to local Ollama, with recent conversation context.

Only the direct user utterance is routed. Retrieved notes, emails, conversation
history, and generated model replies cannot execute actions. No shell command
execution is implemented. These actions are desktop features; the public static
site connects to your computer only through the paired local frame.

ElevenLabs microphone transcription requires the **secret ElevenLabs API key**.
Fish Audio speech requires a separate **Fish Audio API key** in `FISH_API_KEY`.
Save provider secrets in your gitignored `jarvis/.env`. Keep them out of chat and
Git. Typed commands work even when speech credentials are unavailable.
