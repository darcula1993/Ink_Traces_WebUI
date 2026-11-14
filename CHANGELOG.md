# Changelog

## 1.5.2 - 2026-11-14

- Clicking an asset node now pans the canvas when needed so the node and its panel below are both visible, the same as generation nodes. Double-click still centres and zooms in.

## 1.5.1 - 2026-11-14

- Fixed: the prompt box in the image tool had collapsed to one or two lines; it fills its panel again.
- Fixed: the image output settings could be cut off at the top (only options from "Custom size" down were visible), notably on smaller or Retina-scaled screens. The panel now always stays inside the visible canvas, scrolling inside only when the canvas itself is too short.
- The node input panel now always sits directly below its node instead of jumping to the side or above.

## 1.5.0 - 2026-11-14

- Paste from the clipboard onto the canvas: images, videos and audio (including screenshots) become asset nodes at the pointer. Without files, Ctrl+V still pastes copied canvas nodes; plain text is ignored. Pasting inside text fields works as usual.
- Connect nodes by dragging from an output port and releasing over the target node (anywhere on it) or its input; releasing on empty canvas or pressing Escape cancels. Click-to-connect still works.
- Delete or Backspace removes the selected nodes (or the selected connection) in one undoable step; nodes that are generating are skipped with a notice.
- Double-clicking a node smoothly centres it and zooms to 300% (less if it would not fit). Maximum canvas zoom is now 800%. Reduced-motion settings jump without animation.
- The node menu has a "Preview" entry for images, video and audio; video and audio asset nodes now play inside the node.
- The image output settings panel shows every option at once without inner scrolling.
- When the generate button is disabled, hovering it explains why.
- Fixed: after deleting a reference's asset node and connecting a new image, `@图片1` stayed bound to the removed image and the generate button stayed disabled. A reference whose image was removed now points to the image at the same position (with a notice, undoable).
- Dropping or pasting several files adds all nodes at once after uploading, as one undo step.

## 1.4.0 - 2026-11-14

- Prompt references now use the `@图片1` / `@视频1` / `@音频1` form (per media type, in reference order), matching the Seedance 2.5 prompt guide. References behave as one unit: Backspace/Delete removes the whole reference, arrow keys and clicks never stop inside it, double-click selects it, and undo still works. Valid references are highlighted green, broken ones amber; hovering a reference previews its thumbnail. The old `[Image1]` form is no longer recognised and is treated as plain text.
- Reordering references still renumbers them in the prompt and now says so (undoable).
- Audio nodes expose voice (Vivi, Mindy, Kian, Jess, Opal or automatic), format (MP3/WAV/OGG Opus), sample rate and subtitles; length is decided by the content (up to 120 s).
- Canvas generation results are named "node name_task id" (with _2, _3… for extra images) in the asset library, cross-canvas import and downloads. Files on disk and older results keep their names.
- Duplicating a generation node keeps its references and upstream connections (not its results or stale marker).
- Refreshing returns to the last project and canvas.
- New projects ask for a name; the name dialogs accept Enter and Escape; long project names no longer squeeze the canvas name.
- Newly added nodes find free space instead of overlapping other nodes or groups.
- The "upstream updated" marker clears when the upstream returns to the original version.
- Fixed: remote asset cards overlapped their ID and status text; the last row was hidden behind the pager at 2560px.
- Fixed: the node-overlap hint blocked the connection ports beneath it.
- Fixed: progress updates saved the canvas on every tick, which could make a second open window report a conflict and leave a node stuck as generating.
- Keyframe groups show "尾帧" once both frames are set; asset library dates use local time like the task center.

## 1.3.2 - 2026-11-14

- Fixed: a canvas could stop saving while a generation was running, and permanently after a generation failed (task progress was sent with the document). Affected canvases save normally again.
- Audio asset nodes keep the note icon on the same line as the file name.
- On screens 2200px and wider the top bar now lines up with the sidebar and canvas edges.

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
