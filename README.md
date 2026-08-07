# Ink Traces WebUI

<p align="center">
  <img src="./Banner.png" alt="Ink Traces WebUI Banner" width="100%" />
</p>

<p align="center">
  <strong>An AI image and video generation workstation for Gemini, Seedream, and Seedance.</strong>
</p>

<p align="center">
  English · <a href="./doc/README.md">中文</a>
</p>

---

## Overview

Ink Traces WebUI is a local web workstation for prompt-driven image and video creation. It combines a React/Vite frontend with a Flask backend, supports multiple model providers, stores generation history in SQLite, and keeps private credentials and Prompt Vault data outside Git.

<p align="center">
  <img src="./screenshot.png" alt="Ink Traces WebUI Screenshot" width="100%" />
</p>

## Highlights

| Area | What it supports |
|---|---|
| Image generation | Text-to-image and image-to-image through one unified workflow |
| Video generation | Seedance 2.0/2.5 keyframe and multimodal reference workflows with image, video, and audio inputs |
| Providers | Google Vertex AI, Google AI Studio, BytePlus Ark Seedream 5.0 Pro, BytePlus Ark Seedance 2.0/2.5, Jiekou Seedance |
| Prompt workflow | Prompt Vault, fullscreen editor, multi-tab workspaces, reusable saved prompts |
| Runtime history | SQLite task queue for image/video results, local file recovery, task restore |
| Controls | Aspect ratio, resolution, thinking level, Google Search grounding, chat mode |
| Privacy | Real `config.json`, Prompt Vault data, logs, generated outputs, uploads, and DB files are ignored |

## Tech Stack

| Layer | Stack |
|---|---|
| Frontend | React 18, Vite, Tailwind CSS, Framer Motion, Lucide Icons |
| Backend | Python Flask, Flask-CORS, Pillow, Requests |
| Storage | SQLite task database plus local output folders |
| AI APIs | Gemini image generation, Ark Seedream image generation, Seedance video generation |

## Quick Start

### Requirements

- Python 3.8+
- Node.js 18+
- API credentials for at least one configured provider

### Install And Run

```bash
# Create local config from the committed template
cp config.json.example config.json

# Edit config.json and fill in your provider credentials

# Build the frontend and start the worker plus Gunicorn
./start.sh
```

Open the app at:

```text
http://localhost:4545
```

Stop services with:

```bash
./stop.sh
```

`start.sh` defaults to production mode: Gunicorn serves both the API and the
built SPA, so no Vite process stays resident. For frontend development with
hot reload, start with `NANOBANANA_FRONTEND_MODE=dev ./start.sh`.

## Configuration

Only templates are committed. Local runtime files are ignored by Git.

| File | Purpose | Git status |
|---|---|---|
| `config.json.example` | Public config template with empty credentials | Committed |
| `config.json` | Local credentials, ports, provider settings, auth settings | Ignored |
| `.flask_secret_key` | Auto-generated local Flask session secret when not set in config | Ignored |
| `prompts/video_prompt_rewriter.md` | System prompt used by quick one-click video prompt rewriting | Committed |
| `prompts/video_prompt_optimizer.md` | Skill-style system prompt used by the interactive video Prompt Agent | Committed |
| `server/prompts.json.example` | Sample Prompt Vault data | Committed |
| `server/prompts.json` | Legacy Prompt Vault data imported into SQLite on first use | Ignored |

Minimal image provider setup:

```json
{
  "api": {
    "default_provider": "ark",
    "ark": {
      "api_key": "<your-byteplus-ark-key>",
      "model": "seedream-5-0-pro",
      "endpoint": "https://ark.ap-southeast.bytepluses.com",
      "upload_timeout_seconds": 120,
      "request_timeout_seconds": 600
    }
  }
}
```

Ark image generation is synchronous upstream and may take more than two minutes. Reference uploads and response reads have separate timeouts because multi-image JSON requests can be large. Either timeout is treated as an unknown result and is not replayed automatically, which avoids duplicate generations when the provider accepted the original POST.

For video reference uploads through Ark, set `server.public_host`, `server.public_port`, and `server.public_scheme` so external services can fetch uploaded reference files.

Dreamina Seedance 2.5 reuses `video.ark.api_key`. Configure its endpoint ID in `video.ark.seedance_2_5_model`; `config.json.example` includes the current default. The UI applies the model-specific limits for resolution, duration, output format, and reference counts.

Set `auth.secret_key` or `INK_TRACES_SECRET_KEY` for controlled deployments. If neither is set, the backend creates an ignored local `.flask_secret_key` file so browser sessions survive restarts without committing secrets.

For video prompt optimization, set `openai.api_key` in `config.json` or export `OPENAI_API_KEY`. Quick Fix uses `prompts/video_prompt_rewriter.md`; Prompt Agent uses the skill-style workflow in `prompts/video_prompt_optimizer.md`.

## Project Layout

```text
Ink_Traces_WebUI/
├── README.md                    # English GitHub landing README
├── config.json.example          # Public configuration template
├── start.sh / stop.sh           # Service lifecycle scripts
├── clean.sh                     # Local cleanup script
├── client/                      # React frontend
│   └── src/
│       ├── App.jsx              # Main UI, tabs, image/video workflows
│       └── components/          # Uploaders, result viewers, vault, task queue
├── server/
│   ├── app.py                   # Flask API and provider adapters
│   ├── worker.py                # Leased image execution and video polling worker
│   ├── tasks.py                 # SQLite tasks, assets, prompts, and worker state
│   ├── storage.py               # Atomic media writes and lifecycle cleanup
│   ├── maintenance.py           # Cleanup, legacy compaction, and VACUUM commands
│   ├── prompts.json.example     # Public Prompt Vault sample
│   └── requirements.txt
├── doc/
│   ├── README.md                # Chinese README
│   ├── Agents.md                # Development notes
│   ├── image_doc.md             # Image API notes
│   ├── video_doc.md             # Video API notes
│   └── price.md                 # Pricing notes
└── output/                      # Local generated assets, ignored
```

## API Overview

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | Compatibility health check |
| `GET /api/live` / `GET /api/ready` | Process and dependency health checks |
| `GET/POST /api/provider` | Get or switch image provider |
| `GET/POST /api/model` | Get or switch image model |
| `POST /api/generate` | Queue image generation; chat mode remains synchronous |
| `GET/POST /api/prompts` | List or save Prompt Vault entries |
| `PUT/DELETE /api/prompts/:id` | Edit or delete Prompt Vault entries |
| `GET/POST /api/video/provider` | Get or switch video provider |
| `POST /api/video/generate` | Submit video generation task |
| `GET /api/video/task` | Legacy-compatible local video status lookup |
| `GET /api/tasks` | List local task history |
| `GET/DELETE /api/tasks/:id` | Restore or delete local task |
| `POST /api/upload_video` | Upload reference video for external provider access |

## Runtime Data

These paths are intentionally ignored:

- `config.json`
- `.flask_secret_key`
- `server/prompts.json`
- `tasks.db`, `tasks.db-shm`, `tasks.db-wal`
- `output/`
- `upload_video/`
- `error_logs/`
- `*.log`
- `node_modules/`
- `client/dist/`

This keeps API keys, prompt collections, generated media, logs, uploaded references, and local task history out of Git.

Backend maintenance can be run while the services are stopped:

```bash
python3 server/maintenance.py all --grace-hours 24
```

This removes expired/orphaned media, strips legacy inline Base64 results, checkpoints WAL, and compacts SQLite.

## Notes

- Chat sessions are stored in memory and are lost when the Flask process restarts.
- Normal image generation and video polling run in the bounded SQLite-leased worker started by `start.sh`.
- Generated media stays on disk; SQLite stores task and asset metadata rather than Base64 payloads.
- Ark reference-video workflows require a public URL that the provider can download.
- The Flask backend restricts CORS to configured/local origins by default; set `server.cors_origins` when serving the UI from another host.
- Gunicorn serves both the production SPA and API with a separate task worker; the stack remains intended for local or controlled deployments.
- Safety filters can be configured in `config.json`, but provider-side baseline safety enforcement may still apply.

## License

MIT
