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
| Video generation | Keyframe mode and reference mode for video, image, and audio inputs |
| Providers | Google Vertex AI, Google AI Studio, BytePlus Ark Seedream, BytePlus Ark/Jiekou Seedance |
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

# Start backend and frontend
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

## Configuration

Only templates are committed. Local runtime files are ignored by Git.

| File | Purpose | Git status |
|---|---|---|
| `config.json.example` | Public config template with empty credentials | Committed |
| `config.json` | Local credentials, ports, provider settings, auth settings | Ignored |
| `server/prompts.json.example` | Sample Prompt Vault data | Committed |
| `server/prompts.json` | Local Prompt Vault data created by the app | Ignored |

Minimal image provider setup:

```json
{
  "api": {
    "default_provider": "ai_studio",
    "ai_studio": {
      "key": "<your-ai-studio-key>",
      "model_id": "gemini-3.1-flash-image-preview",
      "endpoint": "generativelanguage.googleapis.com"
    }
  }
}
```

For video reference uploads through Ark, set `server.public_host`, `server.public_port`, and `server.public_scheme` so external services can fetch uploaded reference files.

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
│   ├── app.py                   # Flask API, providers, video polling
│   ├── tasks.py                 # SQLite task queue helpers
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
| `GET /api/health` | Backend health check |
| `GET/POST /api/provider` | Get or switch image provider |
| `GET/POST /api/model` | Get or switch image model |
| `POST /api/generate` | Unified image generation endpoint |
| `GET/POST /api/prompts` | List or save Prompt Vault entries |
| `PUT/DELETE /api/prompts/:id` | Edit or delete Prompt Vault entries |
| `GET/POST /api/video/provider` | Get or switch video provider |
| `POST /api/video/generate` | Submit video generation task |
| `GET /api/video/task` | Query external video task status |
| `GET /api/tasks` | List local task history |
| `GET/DELETE /api/tasks/:id` | Restore or delete local task |
| `POST /api/upload_video` | Upload reference video for external provider access |

## Runtime Data

These paths are intentionally ignored:

- `config.json`
- `server/prompts.json`
- `tasks.db`, `tasks.db-shm`, `tasks.db-wal`
- `output/`
- `upload_video/`
- `error_logs/`
- `*.log`
- `node_modules/`
- `client/dist/`

This keeps API keys, prompt collections, generated media, logs, uploaded references, and local task history out of Git.

## Notes

- Chat sessions are stored in memory and are lost when the Flask process restarts.
- Video generation is asynchronous; the backend polls provider task status in background threads.
- Ark reference-video workflows require a public URL that the provider can download.
- The Flask backend is intended for local or controlled deployments, not high-concurrency production traffic.
- Safety filters can be configured in `config.json`, but provider-side baseline safety enforcement may still apply.

## License

MIT
