# Public JARVIS console

Live URL: https://seth-jarvis-command-center.sa3464.chatgpt.site

Sites version 1 deployed successfully with public access. Static script syntax
and runtime CDN availability were checked. Browser automation was unavailable,
so visual rendering and live WebGPU inference remain unverified on this device.

Buildless static deployment. `dist/` is the complete public payload. No local
credentials, profile, inbox, or Python source are included in the deployment.

The public console offers optional in-browser WebGPU inference using WebLLM and
Llama 3.2 1B. The explicit Load action downloads model files to the visitor's
device. Conversation state stays in page memory and clears on reload. Supported
WebGPU hardware, network access to the engine/model hosts, and adequate device
memory/storage are required. Model inference has no cloud API key.

Email and ElevenLabs voice remain desktop features. The public site does not
expose the localhost backend or copy provider secrets. A full hosted voice/email
assistant needs separately authenticated server-side integrations and compute.

Hosting identity is in `.openai/hosting.json`. Publish using the Sites workflow
helper and a temporary sanitized checkout; do not initialize a nested Git repo
here or include the parent repository's private runtime files.
