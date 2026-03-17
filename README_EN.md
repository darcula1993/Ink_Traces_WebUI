# Ink Traces WebUI

<p align="center">
  <img src="./Banner.png" alt="Ink Traces WebUI Banner" width="100%" />
</p>

> Where words become pixels — AI image generation powered by Google Gemini.

[中文](./README.md) · English

---

A coding ide-styled AI image generation workstation. Type a prompt, get an image. Upload references, iterate on them. Powered by Google Gemini multimodal models, with a React frontend and Flask backend — ready to run out of the box.

## Features

<p align="center">
  <img src="./screenshot.png" alt="Ink Traces WebUI Screenshot" width="100%" />
</p>

| Feature | Description |
|---|---|
| **Unified Text & Image Generation** | Upload reference images → image-to-image. No images → text-to-image. Zero manual switching. |
| **Multi-turn Chat** | Iteratively refine images in chat mode, converging on the perfect result |
| **Adjustable Thinking Depth** | Minimal (fast) / High (deep reasoning) — switch on the fly |
| **Prompt Vault** | Save, edit, search, and reuse your favorite prompts with one click |
| **Fullscreen Editor** | Double-click the tab to open an IDE-style fullscreen prompt editor with line numbers and built-in Vault sidebar |
| **Dual Provider** | Switch between Vertex AI and Google AI Studio at runtime |
| **Dual Model** | Gemini 3.1 Flash (speed) / Gemini 3 Pro (quality) — switchable at runtime |
| **Google Search Grounding** | Optionally enhance generation with real-time search results |
| **14 Aspect Ratios x 4 Resolutions** | From 1:1 to 21:9, from 0.5K to 4K — mix and match freely |
| **Draggable Layout** | Resize the left panel by dragging its edge, adapting to any screen |

## Tech Stack

```
Frontend    React 18 · Vite · Tailwind CSS · Framer Motion · Lucide Icons
Backend     Python Flask
AI Engine   Google Gemini API (Vertex AI / AI Studio)
```

## Quick Start

### Prerequisites

- Python 3.8+
- Node.js 18+
- Google Gemini API key ([Vertex AI](https://cloud.google.com/vertex-ai) or [AI Studio](https://aistudio.google.com/))

### Launch

```bash
# 1. Configure your API key
cp config.json.example config.json
# Edit config.json with your credentials

# 2. Start (auto-installs dependencies)
./start.sh

# 3. Open your browser → http://localhost:4545
```

### Stop

```bash
./stop.sh
```

### config.json Example

```json
{
  "api": {
    "default_provider": "vertex",
    "vertex": {
      "key": "<your-vertex-api-key>",
      "project_id": "<your-gcp-project-id>",
      "endpoint": "aiplatform.googleapis.com"
    },
    "ai_studio": {
      "key": "<your-ai-studio-api-key>",
      "endpoint": "generativelanguage.googleapis.com"
    }
  }
}
```

## Project Structure

```
ink-traces/
├── config.json              # Config (keys, ports, safety policy)
├── start.sh / stop.sh       # One-click start / stop
├── server/
│   ├── app.py               # Flask backend — unified /api/generate endpoint
│   ├── prompts.json          # Vault saved data
│   └── requirements.txt
├── client/
│   └── src/
│       ├── App.jsx           # Main component (layout, state, API calls)
│       └── components/
│           ├── TextToImage.jsx      # Prompt input area
│           ├── ImageToImage.jsx     # Reference image upload (up to 14)
│           ├── ResultDisplay.jsx    # Canvas output + fullscreen lightbox
│           └── PromptCollection.jsx # Vault collection
└── error_logs/              # API error logs (auto-recorded)
```

## API

Unified generation endpoint — mode is auto-detected:

```
POST /api/generate
```

| Request Type | Mode |
|---|---|
| JSON body (no files) | Text-to-Image |
| multipart/form-data (with images) | Image-to-Image |

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `prompt` | string | — | Image description (required) |
| `aspect_ratio` | string | `1:1` | Aspect ratio |
| `resolution` | string | `2K` | Resolution |
| `think_level` | string | `minimal` | Thinking depth: `minimal` / `high` |
| `use_search` | bool | `false` | Enable Google Search grounding |
| `enable_chat` | bool | `false` | Enable multi-turn chat |
| `session_id` | string | — | Chat session ID |
| `images` | file[] | — | Reference images (up to 14) |

**Other Endpoints:**

| Endpoint | Description |
|---|---|
| `GET/POST /api/provider` | Get / switch provider |
| `GET/POST /api/model` | Get / switch model |
| `GET/POST /api/prompts` | Get / save prompts |
| `PUT/DELETE /api/prompts/:id` | Edit / delete saved prompt |

## FAQ

**Q: What's the difference between Vertex AI and AI Studio?**
A: AI Studio is Google's free developer platform — great for personal experiments but rate-limited. Vertex AI is GCP's enterprise service with pay-per-use pricing, higher rate limits, and additional configuration options (e.g. `personGeneration`). Both call the same underlying Gemini model.

**Q: Why did generation fail?**
A: Common causes: (1) Invalid or expired API key; (2) Gemini's safety filter blocked the content (even `BLOCK_NONE` has a hard baseline filter); (3) The model returned text but no image — try rephrasing your prompt. All errors are automatically logged to the `error_logs/` directory.

**Q: What's the difference between Chat mode and normal mode?**
A: Normal mode treats each request independently with no context. Chat mode preserves conversation history, so you can make incremental edits like "change the background to blue" based on the previous image. Sessions are stored in server memory and lost on restart.

**Q: What does setting think_level to High do?**
A: In High mode, the model performs deeper reasoning before generating, which typically produces better results but takes longer. Minimal is best for rapid iteration; High is best for final renders. The thinking process is displayed in the Runtime Log overlay on the canvas.

**Q: How many reference images can I upload?**
A: Up to 14. Images are base64-encoded and sent to the Gemini API, so more images means larger request payloads and longer processing times. For best results, 3-5 images is recommended.

**Q: What image formats are supported?**
A: PNG, JPG, and WebP. All uploads are converted to PNG before being sent to the API. The total file size limit per request is 100MB.

**Q: How do I adjust the safety filter level?**
A: Edit the `safety` field in `config.json`. Options: `BLOCK_NONE` (no filtering), `BLOCK_ONLY_HIGH`, `BLOCK_MEDIUM_AND_ABOVE`, `BLOCK_LOW_AND_ABOVE`. Note that even with `BLOCK_NONE`, Gemini still enforces a non-disableable baseline filter.

**Q: Can I deploy this to a remote server?**
A: Yes. The `server.host` and `client.host` in `config.json` default to `0.0.0.0`, which listens on all network interfaces. Just make sure your firewall allows ports 4545 and 5000. For production, an Nginx reverse proxy with HTTPS is recommended.

## Known Limitations

- Chat sessions are stored in memory — lost on server restart
- Safety filters are disabled by default (`BLOCK_NONE`) — adjust in `config.json` as needed
- Backend runs in single-process mode, not suitable for high-concurrency scenarios

## License

MIT
