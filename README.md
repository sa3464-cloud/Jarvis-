# JARVIS

Local assistant for Seth. Open the [local Command Center](http://127.0.0.1:8767)
for voice, text conversation, and read-only Gmail in one interface. See
[setup and current capabilities](jarvis/README.md).

Public console: **https://seth-jarvis-command-center.sa3464.chatgpt.site**

The public console runs optional AI in the visitor's browser using WebGPU.
Gmail and ElevenLabs voice remain in the desktop app. Public hosting source
and deployment notes are in [public-site](public-site/README.md).

Run the stage-one demo index from the repository root:

```powershell
python -m jarvis.agent.vault
```
