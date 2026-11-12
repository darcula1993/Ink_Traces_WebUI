# Changelog

## 1.1.0 - 2026-11-13

- Every image, video and audio generation node now chooses its own provider. The project-level default provider and the "inherit project default" option were removed; new nodes preselect the provider you last chose for that node type (BytePlus first, Cupsy for audio). Generating from a node without a provider is rejected with a clear message.

## 1.0.1 - 2026-11-13

- Layer decomposition now always uses the BytePlus image model (`generation.image.byteplus.model`); the separate `generation.layer` config section was removed. Existing v2 configs that still contain an empty `generation.layer` section can be cleaned with `scripts/config-drop-layer.py --apply`.

## 1.0.0 - 2026-11-13

First major release.

- Project → canvas → node workspace: multiple canvases per project, draggable image, video and audio generation nodes, explicit reference wiring (including video to video).
- Image and video generation through BytePlus Ark (Seedream 5.5 / Seedance) and Cupsy; audio generation through Cupsy (Seed Audio).
- Interface management: multiple named provider configurations, per-node selection with project defaults, immutable revisions for submitted tasks.
- Layer studio on BytePlus Ark Seedream 5.5: 2–100 layers, optional OCR, version restore and export.
- Asset library with asset groups and local assets, including select-all and permanent delete.
- Task center backed by real server-side tasks: search, pagination, favorites, trash and bulk download.
- Duplicate-billing protection: requests with an unknown provider outcome are never replayed automatically.
- Prompt Vault and fullscreen prompt editor.
- Configuration uses the `config.json` v2 format (`config_version: 2`): accounts under `providers.byteplus` / `providers.cupsy`, per-capability models under `generation`, deployment settings under `deployment`. The server only reads v2 and refuses to start on an invalid or older file; `scripts/migrate-config-v2.py` converts a pre-release v1 file (dry run by default).
