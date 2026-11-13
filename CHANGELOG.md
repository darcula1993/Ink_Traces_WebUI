# Changelog

## 1.3.1 - 2026-11-14

- Audio asset nodes stack the file name above the play button instead of overlapping it.
- The sidebar project name uses the free width next to the canvas name before truncating (full name still on hover).

## 1.3.0 - 2026-11-14

- Image and video nodes now follow the real aspect ratio of their result (or the chosen ratio before generation); connections, tidy layout, selection, dragging and node groups use the new sizes. Opening an older canvas whose nodes now overlap shows a one-time hint to tidy the canvas (undoable); nodes are never moved automatically.
- Themed audio and video player on nodes and in asset previews, keyboard accessible.
- The node panel places itself below, right, left or above the node to avoid covering other nodes and stays in view while panning and zooming.
- Video parameter pills always show ratio, resolution and duration in full.
- Panning or zooming the canvas no longer marks it as unsaved.
- At low zoom, nodes show only their icon and title, and titles stay readable.
- Batch-adding assets lays nodes out by their real sizes without overlaps.
- Themed dropdowns replace native selects in the asset library and provider settings; folders use compact rows; empty folders have no expand arrow; the library grid adapts to large screens.
- Screens 2200px and wider scale the whole shell (top bars, toolbars, sidebar, dialogs) consistently.
- The provider setting formerly called "default for this generation type" is now "initial preselection for new nodes": it only applies when you have not picked a provider for that node type yet.

## 1.2.0 - 2026-11-14

- New design language: restrained neutral near-black base with green used only as an accent (focus, selection, primary actions, generating state); glass effects limited to floating panels and menus.
- Unified button system (primary, secondary, ghost, danger, icon) with consistent sizing and subtle hover, press and focus states.
- Readable canvas zoom: locating a node zooms to 100%, fit-all never goes below 75%, node text is at least 12px; failed and generating nodes show their state directly on the node.
- Node panel parameters are a single row of compact pills with themed dropdowns and a round generate button; the panel is now fully opaque.
- Sidebar node rows show thumbnails or type icons with status dots; the assets tab shows the asset count; the more-actions menu is grouped.
- Layouts adapt to 1280×800 through 2560×1440 screens; the asset library grid scrolls independently with pagination always visible.

## 1.1.1 - 2026-11-13

- Canvas status alerts now sit above the bottom toolbar and can be dismissed, so they no longer cover node titles.
- Node status messages wrap up to three lines and show the full text on hover or focus.

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
