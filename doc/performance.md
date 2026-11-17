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
- Cupsy Assets (remote) uses 30-item pages, lazy 320-pixel image thumbnails and
  targeted polling of pending imports. Explicit select-all still covers the whole
  remote library.
- JSON and frontend text assets negotiate gzip. Responses under 1 KiB, media,
  range downloads and streaming PNG metadata are not compressed. Static gzip
  work is cached in a bounded in-process cache.
- Ark/Cupsy URL-based image outputs stream to local files instead of buffering
  and Base64 round-tripping. Provider bytes and alpha channels are preserved.
- Generation, audio/video polling and asset import use separate bounded pools.
  Filesystem cleanup runs in one background maintenance executor, no longer in
  prompt autosave requests or the scheduler's heartbeat loop.

## Task search (2026-11-14, FIX-B3B)

Gallery search (`q` on task list, id list and navigation) is a substring match
so Chinese text without word breaks ("红色", "橘猫") and model names
("seedream", "seedance") are found. Each whitespace term must occur in the
prompt, provider or model text (Ark image/layer tasks, which store an endpoint
id, also match "seedream"); the whole query also matches favorite group names
and an exact task id. Matching uses `instr()`, so `%` and `_` are literal.

This replaces the FTS5 prefix match for filtering (the `task_search` table and
triggers are kept, unused by filtering, so no schema change). A substring scan
cannot use an index, so it is bounded instead: input is cut to 100 characters
and 8 terms, and the scan runs after the type/deleted/favorite filters.
Synthetic benchmark (image tab, 20–120 term prompts, page of 50 plus count):
5,000 tasks about 4–8 ms (FTS prefix: under 1 ms), 50,000 tasks about
40–85 ms. Pagination, counts and select-all ids are still computed by the
server with the same filter. Revisit with a trigram index if the task table
grows well beyond 50,000 rows.

## Global library (2.0)

- One `media` table for all projects. Lists are paged on the server
  (`limit` up to 200, default 50, newest first) and filtered there by folder,
  kind, name and origin; select-all asks the server for the matching ids
  (at most 5,000) instead of loading every page.
- Image thumbnails are 320-pixel WebP made on request and cached briefly by the
  browser; video and audio have no thumbnail. Files are streamed with
  conditional requests.
- Generation results enter the library as hard links of the task output, so
  they take no extra disk space on the same file system (a copy is made only
  across file systems). Content is deduplicated by SHA-256, so identical uploads
  and results share one file.
- Canvases store library ids instead of copies; writing a result back to a
  canvas no longer copies files.

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

- `pytest -q server/tests` (from a checkout without `config.json`)
- `npm --prefix client run build`
- Browser (Playwright, desktop project) tests run through an isolated fixture
  harness that is not part of the public distribution.

Dedicated tests cover thin summaries, gzip/ETag/range negotiation, byte-preserving
streamed image downloads, pool isolation, upload races and retries, object URL
lifetime, whole-library selection, pagination, hidden tabs and status batching.
Generation requests in tests are mocked; performance work requires no paid calls.
