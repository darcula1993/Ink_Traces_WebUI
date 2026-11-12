# Cupsy Seedance 2.5 Compatibility

Verified against `https://cupsy.io` on 2026-08-22. Secrets and signed URLs are
intentionally omitted.

## Seed Audio 1.0

- Model id: `seed-audio-1.0`.
- Asynchronous endpoints: `POST /v1/audio/generations`, status and content at
  `/v1/audio/generations/{id}` and `/v1/audio/generations/{id}/content`.
- Output formats: `mp3`, `wav`, `ogg_opus`; sample rates: 8, 16, 24, 32, 44.1,
  and 48 kHz; maximum generated duration: 120 seconds.
- Inputs are text-only, up to three ordered audio/speaker references, or one
  image reference. Audio and image references cannot be mixed.
- Generated audio remains a short-lived artifact at Cupsy and is downloaded to
  local task storage. It is not automatically imported into Cupsy Assets.

## Model contract

`GET /v1/models` reports the following contract for `seedance-2.5`:

- `seedance-2.5`: standard model.
- `seedance-2.5-moderated`: the same declared capabilities with enhanced moderation.

| Capability | Cupsy behavior |
| --- | --- |
| Resolutions | `480p`, `720p`, `1080p` |
| Ratios | `16:9`, `4:3`, `1:1`, `3:4`, `9:16`, `21:9`, `adaptive` |
| Durations | Whole seconds from 4 through 30; default 5 |
| Content types | `text`, `image_url`, `video_url`, `audio_url` |
| Asset roles | `first_frame`, `last_frame`, `reference_image`, `reference_video`, `reference_audio` |
| `generate_audio` | Supported |
| `watermark` | Supported |
| `seed` | Explicitly unsupported |
| `camera_fixed` | Explicitly unsupported |
| `duration=-1` | Passed through by explicit product choice; the provider may reject it with `422 validation_failed` |
| `frames` | Not declared; do not send |
| `return_last_frame` | Not declared; accepted but ignored in a live generation test |
| `output_format` | Not declared; do not send |
| `callback_url` | Not declared; do not send |
| `priority` | Not declared; do not send |
| `execution_expires_after` | Not declared; do not send |

The customer pricing catalog version `2026-08-20-text-json-object` defines a
separate 1080p tier for both models. At 480p/720p, other inputs cost USD 10.70
and video inputs cost USD 6.40 per million completion tokens. At 1080p, those
rates are USD 11.70 and USD 7.00 respectively. The enhanced-moderation model
uses the same rates as the standard model.

Unknown fields were not rejected ahead of an intentionally invalid ratio, so
acceptance alone does not prove that Cupsy honors them. The adapter therefore
sends only capabilities declared by `/v1/models`.

A live `480p`, four-second, no-audio generation with
`return_last_frame=true` completed successfully. Its final response contained
one `video/mp4` artifact and a video content URL, with no image artifact or last
frame URL. The content endpoint also returned only `video/mp4`. Cupsy therefore
accepts but does not honor this parameter as of the verification date.

Completed outputs are downloaded through `/v1/artifacts/{id}/content`, which
redirects to object storage. The task-specific video content proxy can transfer
large files very slowly despite continuing to return data, so it is retained
only as a compatibility fallback when the response has no artifact id. The
downloaded byte count is checked against the artifact's declared `size_bytes`
before a task is marked complete.

## Asset contract

All Cupsy generation references are durable Assets. The application does not
send Base64 or direct HTTPS references in a video request.

Observed lifecycle:

1. `POST /v1/assets` returns `202`, `status=pending`, an `asset_...` id,
   `asset://asset_...` URI, and an import task id.
2. `GET /v1/assets/{id}` returns `status=active`, `usable=true`, MIME type, and
   size after Cupsy has fetched the source URL.
3. `GET /v1/assets/{id}/content` returns a temporary `307` redirect.
4. `DELETE /v1/assets/{id}` returns the Asset with `status=deleted`.

The source URL must be publicly reachable over HTTP or HTTPS and the create
body must include both `type` and `source_url`. This deployment uses HTTPS on
the public IP. Generated video results remain task outputs: they are downloaded
to local storage and are never imported into Cupsy Assets.

## Seedream 5.0 Pro images (2026-10-27)

The independent `cupsy` image endpoint uses `seedream-5.0-pro` and shares the
`providers.cupsy` account (`api_key`, `endpoint`, `request_timeout_seconds`) and the
`deployment.cupsy_source` public asset source with video and audio (config v2). The image
polling limit lives at `generation.image.cupsy.poll_max_attempts`.

The live `/v1/models` response and portal API reference confirm
`POST /v1/images/generations`, PNG/JPEG output, watermark control, and image
references through the `image` array of `asset://` URIs. The UI exposes 1K/2K
presets for 1:1, 4:3, 3:4, 16:9 and 9:16. Cupsy preset pixel dimensions are
mapped independently of Ark. Custom dimensions are enabled per the requested
integration, with the same multiple-of-16, pixel-count, and aspect-ratio checks
as the official Seedream endpoint. The public model listing enumerates presets
but does not document custom-size bounds; no paid live generation was run.

Auto size, background control and layer decomposition are not sent to this
endpoint.

HTTP 202 means generation continues remotely. Persist the exact body and a
unique idempotency key before submission, then replay them after Retry-After
to retrieve the final image response. Transport failures use that same key.
The worker releases its execution slot between requests and resumes polling
after restart. Local cancellation stops result retrieval; the public image API
does not document a remote cancellation operation.

Generated image bytes are saved locally without re-encoding; only thumbnails
are transformed. Generated outputs are never imported as Assets. Unit tests
mock generation, downloads, 202 replay and timeouts to avoid paid requests.
