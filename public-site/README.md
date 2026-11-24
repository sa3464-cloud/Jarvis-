# Public JARVIS console

Live URL: https://seth-jarvis-command-center.sa3464.chatgpt.site

The public console includes the animated AI Core HUD and links to the local
Command Center and floating Windows assistant.

Buildless static deployment. `dist/` is the complete public payload. No local
credentials, profile, inbox, or Python source are included in the deployment.

The public console offers optional in-browser WebGPU inference using WebLLM and
Llama 3.2 1B. The explicit Load action downloads model files to the visitor's
device. Conversation state stays in page memory and clears on reload. Supported
WebGPU hardware, network access to the engine/model hosts, and adequate device
memory/storage are required. Model inference has no cloud API key.

**Use local PC** opens an embedded loopback console once JARVIS is running. The
user generates a one-time code in the standalone local console and enters it
inside the local frame. Voice, chat, and Gmail requests go directly to the PC
from that frame, which the public page cannot read. No local credentials are
uploaded to Sites. Open the published URL directly in Chrome and allow browser
loopback access if prompted.

Hosting identity is in `.openai/hosting.json`. Publish using the Sites workflow
helper and a temporary sanitized checkout; do not initialize a nested Git repo
here or include the parent repository's private runtime files.
