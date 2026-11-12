# Runtime performance

## Changes (2026-11-04)

- Task lists return a 200-character prompt preview, display parameters, media
  URLs and thumbnails. `summary: true` identifies these records. Full prompts,
  references and provider source URLs remain available from task detail GET.
- The gallery polls only loaded active task IDs in batches of at most 100.
  Requests do not overlap, hidden tabs pause, and unchanged cards retain their
  identities. Search matches are decided by the backend, not truncated previews.
- Reference images preview immediately using owned object URLs. Inspection,
  autosave and generation share one workspace upload promise per File. The
  upload returns canonical dimensions, alpha information and a thumbnail URL.
- Cupsy Assets uses 30-item pages, lazy 320-pixel image thumbnails and targeted
  polling of pending imports. Explicit select-all still covers the whole library.
- JSON and frontend text assets negotiate gzip. Responses under 1 KiB, media,
  range downloads and streaming PNG metadata are not compressed. Static gzip
  work is cached in a bounded in-process cache.
- Ark/Cupsy URL-based image outputs stream to local files instead of buffering
  and Base64 round-tripping. Provider bytes and alpha channels are preserved.
- Generation, audio/video polling and asset import use separate bounded pools.
  Filesystem cleanup runs in one background maintenance executor, no longer in
  prompt autosave requests or the scheduler's heartbeat loop.

## Worker settings

Under `server` in local `config.json`:

- `worker_concurrency`: generation concurrency, default 3.
- `generation_concurrency`: optional explicit override of the above.
- `polling_concurrency`: audio/video polling concurrency, default 2.
- `asset_concurrency`: asset import/poll concurrency, default 1.

`WORKER_CONCURRENCY` continues to override generation concurrency. There are no
unbounded executor queues; tasks are claimed only for available slots. Do not
raise all limits indiscriminately on a small-memory server. Remote model latency
is outside these local optimizations.

## Measurements

Local authenticated GET samples, 2026-11-04, 30 image tasks per page:

| Metric | Before | After |
| --- | ---: | ---: |
| Decoded list response | about 790 KB | about 41 KB |
| List wire response | about 790 KB | about 4.8 KB gzip |
| Main JavaScript wire response | about 525 KB | about 165 KB gzip |

The live task collection changed slightly between samples. These are observed
payload sizes, not a claim that remote generation or all interactions become a
fixed percentage faster. Loopback latency excludes users' network latency.

## Verification

- `pytest -q server/tests`
- `npm --prefix client run build`
- From `client`: `npx playwright test --project=desktop --workers=1`

Dedicated tests cover thin summaries, gzip/ETag/range negotiation, byte-preserving
streamed image downloads, pool isolation, upload races and retries, object URL
lifetime, whole-library selection, pagination, hidden tabs and status batching.
Generation requests in tests are mocked; performance work requires no paid calls.
