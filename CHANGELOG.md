# Changelog

## 2.4.1 - 2026-11-21

Storage garbage collection and completed deletion compaction (`STORAGE-GC-COMPACT-20261121`).

- **Completed Deletion Compaction**: Added idempotent `compact_completed_deletions()` (run on deletion completion and in Worker maintenance) to compact `completed=1` `canvas_workflows.document` records into minimal node provenance stubs (`id`/`type`/`title`/`task.id`) and strip bloated fields from `canvas_deletions.manifest` while preserving Cost Ledger attribution, Generation History provenance, `removed_library_ids`, and `cleanup_assets=False` retention obligations; never touches `completed=0` pending deletions.
- **Deleted Layer Project Compaction**: Added `compact_deleted_layer_projects()` to clear orphaned `layer_projects.document` and unreferenced `layer_revisions` after deletion while strictly preserving `layer_revisions` referenced by any surviving task.
- **Orphan & Workspace Disk GC**: Extended `cleanup_orphans()` and `cleanup_workspace_assets_all()` to reclaim orphaned `output/layer/<task_id>/` directories, soft-deleted/unreferenced `workspace_assets/layer_projects/<id>/` directories, unreferenced `workspace_assets/cupsy_assets/` files and emptied subdirectories, orphaned `workspace_assets/<state_key>/` directories without active `workspace_state` rows, and emptied legacy `canvas_assets/` subdirectories while strictly protecting `canvas_assets/media/`, active references, grace windows, and symlink boundaries.

## 2.4.0 - 2026-11-21

End-to-end reliability fixes, short-drama canvas productivity upgrades, scene asset export packaging, read-only sequence playback preview, and cost/history observability.

- **Wave 1 · Reliability & Trust Foundations**:
  - Added Seedance video-reference/extend `ratio=adaptive` inline guardrail with one-click switch, expandable/copyable sanitized error display, and strict allowlisted Chinese parameter fix hints (never recommending retries on `result_unknown`, 5xx, or network failures).
  - Added explicit Ark `capability_model` declaration (Seedream 5.5 / 5.0 Pro) in Interface Management with zero-cost preflight auto-scroll and accurate 5.5 pricing/1.5K capability unlocking, plus human-readable profile names in Cost Ledger instead of raw `ep-***`.
  - Fixed standalone Image tool profile switching to sanitize incompatible parameters immediately, surface validation errors right above the Generate button, remove duplicate model displays, and display 3-decimal USD cost estimates.
  - Upgraded Layer Studio with Ark profile selection (frozen revision per task), automatic canvas project Cost Ledger attribution when launched from canvas, default `max_images` lowered from `30` to `12` with range cost estimate, session project restoration, fixed save-to-library radio alignment, and one-click return of saved composites back to the source canvas.
  - Added browser URL route persistence (`?project=...&canvas=...`) so refreshes and multi-tab sessions preserve active canvases, plus high-frequency UI fixes (narrow 1:1 cost badge visibility, auto-collapsing floating rail on new canvas focus, incremental node naming & port-aware placement, non-blocking toast placement, duplicate copy cleanup).
- **Wave 2 · Canvas & Short-Drama Creation Productivity**:
  - Collapsed leading `@character` prompt blocks into a compact 1-line badge strip inside node cards while keeping submitted plaintext byte-identical and expandable inline or in the full editor; added one-step image selection when creating new Character Cards.
  - Added 2–4 candidate side-by-side Version Comparison Modal (linked image zoom; muted-by-default synced video playback with per-column mute & scrub) plus node/version 「定稿」 badges and sidebar 「仅看定稿」 filtering.
  - Added one-click 「延长此视频」 / 「编辑此视频」 follow-up video node actions (auto-wired with `ratio=adaptive` for extensions, never auto-submitting paid tasks) and durable user-saved Node Group Structural Templates (`/api/canvas/templates`, zero bundled creative presets, explicit warnings on disabled/deleted provider bindings without auto-switching accounts).
- **Wave 3 · Delivery Packaging, Read-Only Playback & Cost Observability**:
  - Added one-click Scene Export Pack (`POST /api/canvas/workflows/<wid>/export-pack[/preview]` + top-bar dialog): streaming `ZIP_STORED` media archive renamed by shot sequence plus sanitized `shotlist.csv` / `shotlist.json` (zero credentials, signed URLs, `ep-` IDs, or host paths; no transcoding or compositing).
  - Added a read-only in-browser Shot Sequence Playback Preview modal (`CanvasSequencePreviewModal`) for sequential playback of selected/finalized video nodes with optional single-audio overlay (no editing, trimming, subtitles, or video export).
  - Added fine-grained processing stage signals (`uploading` → `queued` → `generating` → `downloading`), 30-day local P50 duration hints (`GET /api/tasks/duration-stats`), and canvas active-task parallel counts without fake progress bars.
  - Added top-bar Cost Ledger shortcut, per-project soft budget warning thresholds (`GET/PUT /api/cost-ledger/budget`, non-blocking yellow warnings with unknown costs itemized separately), and read-only Project/Canvas/Finalized filters with sanitized hover provenance in Global Library 「生成历史」.

## 2.3.1 - 2026-11-21

Unified provider profile equality and documentation refresh.

- **Equalized Provider Profiles**: Removed the legacy "system default" (`系统默认` / `（默认）`) distinction between config-imported and user-created provider profiles across the API and WebUI; all profiles now share uniform naming, sorting, key-sync defaults, and save/delete copy while preserving tombstone protection against re-import or `config.json` credential fallback after deletion.
- **Renamed Default Toggle**: Renamed the per-type first-preselection switch in Interface Management to **「默认配置」**, allowing any enabled profile of each media type to serve as the default choice when no last-used selection is stored.
- **Documentation Refresh**: Updated `doc/development.md` to reflect v2.3.x capabilities (Global Task Center, unified provider management, Layer Studio library bridge, and Micro-Ink Precision visual assets).

## 2.3.0 - 2026-11-21

Full-site desktop IDE layout unification, unified web provider management, global aggregated task center, bidirectional Layer Studio integration, canvas workflow upgrades, and a refined visual identity.

- **Full-Bleed Desktop IDE Layout**: Unified the 48px header and left rails across Canvas, Image, Layer, Video, Audio, and Global Task Center (`left: 0`, 48px Layer rail, removed legacy Liquid Glass surfaces and fragmented 2560px local zoom), aligned standalone tool forms to 36px single-column Linear controls, unified modal radii (`8px / 10px`), and fixed tooltip viewport clamping.
- **Global Aggregated Task Center & Unified Trash**: Added a top-level Task Center aggregating image, video, audio, and layer tasks with server-side pagination, search, filters, favorites/groups, and a unified Trash view with cross-type delete preview and v2.2.0 generation-history lifecycle protection.
- **Unified Provider Management**: Imported default `config.json` providers into database-backed provider profiles editable in the WebUI without restarts (with same-provider API key sync, safe soft-delete for custom and default profiles, image/video/audio grouping, zero-cost static configuration precheck, standalone tool profile selection, 3-decimal USD estimates, and extended `ep-` endpoint ID redaction in errors).
- **Canvas Workflow Upgrades**: Added single-node task cancellation in canvas properties and task panel, cross-canvas copy/paste and one-click duplicate canvas, homogeneous multi-select batch parameter editing (undoable), single reference removal and lightbox preview, audio node toolbar, expanded prompt `@character` insertion, task-to-canvas node locate, ledger `#taskId` jump, blank-canvas context menu actions, and fixed floating rail resizer and full-height prompt panel list.
- **Layer Studio ↔ Global Library & Canvas Bridge**: Pick source images directly from the global library (hard-link isolated without re-upload), send canvas image nodes directly to Layer Studio without auto-running paid decomposition, save composites or individual layers back to the global library, and replaced native `window.confirm` with in-app dialogs.
- **Global Library, Projects & Character Cards**: Drag-and-drop media onto folders (copies from generation history while keeping originals; moves uploads), 6-way sorting with resolution/duration metadata, read-only reference inspection dialog, bulk project deletion with active-task safety and card counts/timestamps, and a redesigned Character Card profile sheet with search, kind filter, unsaved-change guard, unified save, and image lightbox.
- **Visual Identity & Micro-Ink Precision Assets**: Added bespoke `<BrandMark />` SVG and favicon suite, subtle feathered dark ink-wash ambient texture for login, architectural fine-line empty-state SVGs, organic audio waveforms, viewfinder waiting slots and distinct trashed vs. deleted hatched placeholders, unified dark transparency checkerboard tokens, canvas file-drop overlay, and refreshed README banner and workspace screenshot.

## 2.2.0 - 2026-11-20

- Results in generation history follow their tasks into and out of the trash. Permanent deletion previews affected references and removes the history entries. Copies in other folders remain available.
- Copy a generation result to another folder while keeping its original in history. Copies use hard links when supported.
- Canvas generation and group runs submit library references by ID. The server snapshots inputs and preserves the existing provider payload.
- Recover staged library files after an interrupted delete and return a deleted status when a media read races with removal.
- The first start updates the SQLite media table to allow independent copies of the same content. Back up the database before upgrading.

## 2.1.0 - 2026-11-18

Canvas layout redesign (inspired by ImagineArt's node canvas), performance work and a one-click trash.

- **Right properties panel**: interface, model and generation parameters move from the floating panel under the node to a fixed panel on the right. Single column, full-width controls, an "Advanced" group (custom size, background, watermark) and a sticky cost estimate with the Generate button; selecting several nodes shows "Run selected".
- **Prompt inside the node card**: a fixed-height text area (14px, scrolls inside, never grows past the card) editable at any zoom, with a tool row: prompt library, @character cards (lists character cards only), expand to a large editor, cost estimate and a Generate button on every generation card.
- **Typed reference ports**: generation nodes list their inputs on the left by type (image circle, video square, audio diamond); one empty port appears after the used ones until the model limit; the port number is the reference order and matches @图片N; over-limit references are marked and can be removed in one step (undoable). Port names appear on selection, hover or while dragging.
- **Left icon rail** with pop-out panels (project/canvas, library, character cards, prompt library, this canvas's tasks) that can be pinned; minimap, undo/redo and zoom in the bottom-left corner.
- **Node toolbar** above the selected image or video node: edit, rotate, annotate, download, preview, version history (now a popover; removed from the right panel), and for video capture current/last frame. Results are saved as new library items.
- Nodes can be resized from the bottom-right corner (media keeps its aspect; double-click resets). New video nodes default to 480p.
- **Empty trash**: the image, video and audio task centres can empty their trash in one step (per type, with a count in the confirmation). Library files are never deleted; tasks that are still cancelling or running are skipped.
- **Performance**: node cards no longer re-render while another node is dragged; zoom styles are scoped; long task and sidebar media lists are windowed; search is debounced and fetched once; the annotation tool and other heavy parts load on demand; sidebar video thumbnails no longer load the video itself.
- Fixes: the version-history button did nothing on generation nodes; the prompt editor could extend outside the node; known flaky browser tests fixed.

## 2.0.2 - 2026-11-17

- Library rules: the "生成历史" folder and its 图片/视频/音频 sub-folders only accept generation results (uploads cannot be moved in; generation results can be moved out); folder names may not contain "/" and may not repeat among siblings (case-insensitive; existing folders are left as they are).
- Rename library items from the library dialog and the canvas sidebar.
- Uploading content that is already in the library (sidebar and library dialog) tells you which folder it is in, with "locate" and "move here".
- The canvas sidebar, node menu and version list use the library's "move to folder" dialog: it preselects the item's current folder and disables "生成历史" for uploads.
- Deleted placeholders on canvas nodes can be replaced from the library as well as by uploading.
- The sidebar refreshes when a generation finishes; uploading with a folder selected puts the file in that folder; a non-empty folder's delete action is disabled with the reason.
- Dialogs submit with Enter, focus the name field when opened and return focus when closed; success notices for deletes and renames; folder paths shown as "parent / child"; accessibility fixes for the folder tree and menus.
- Cost ledger wording now matches what is estimated (image, layer and video estimated; audio unknown).

## 2.0.1 - 2026-11-17

- The 2.0.0 package was missing `scripts/migrate-library-global.py`, which the upgrade from 1.x needs. It is now included. No other changes.

## 2.0.0 - 2026-11-17

Breaking: the asset library model changes and existing data is migrated (see "Upgrading").

- **One global library**: every project shares a single library. Uploads and all generation results are managed there and organised only by sub-folders. The per-project library, the "this project / all projects" switch and tags are removed (existing tags are deleted).
- **Generation results live in the library**: every successful result is added automatically to the fixed "生成历史" folder, split into 图片 / 视频 / 音频 (hard links, no extra disk space). These system folders cannot be renamed, moved or deleted; results inside them can be moved or deleted. Default folders 音效 / 角色 / 场景 / 物品 / 风格 are created once. "Add to local assets" is replaced by "Show in library" and "Move to folder".
- **Canvases reference the library directly**: nodes store library ids instead of per-canvas copies. Pasted, captured-frame, edited and directly uploaded files go into the library. Deleting a library item shows a "deleted" placeholder on nodes that used it, removes it from references, and the task card shows "result deleted"; deleting tasks, emptying the trash, cleanup or deleting a project/canvas never deletes library files.
- **Library tools**: folder tree with sub-folders, move/rename, upload to a chosen folder (or create one on the spot), global asset groups, server-side select-all, delete preview listing affected canvases, a notice with "locate" / "move here" when an upload already exists in the library.
- Character cards reference library images; legacy tool uploads (and BMP/TIFF converted to PNG) are registered in the library.
- Fixes: the API no longer fails to boot when the API and Worker add a new column at the same time; ledger wording; sidebar refresh after generation; several focus and layout fixes.

### Upgrading from 1.x
Stop the API and Worker, then run `python3 scripts/migrate-library-global.py --db tasks.db --make-backup <dir>`, review the dry run, apply with `--apply --backup-dir <dir>` and check with `--verify`. Copies held only by already-deleted canvases/projects are removed. Keep the backup until you have checked the new library; `--new-since` exports anything added after the migration if you need to roll back.

## 1.9.2 - 2026-11-16

- Add generation results to local assets: from the generation history (single or multi-select), a canvas node's right-click menu or its version list (current or all versions), and task cards, batch selection or task details. The result is kept as an independent copy (a hard link on the same disk, so no extra space) with no project ownership, like uploads; deleting the task, emptying the trash or cleaning a project keeps it, and deleting it keeps the task output and canvas. Adding the same result again does not create a second copy, and identical files share one local asset. Tags already on the result are carried over; the add dialog lets you pick tags and create a new tag on the spot. Tagging directly in the generation history is replaced by this flow.
- Tag pickers can create a new tag on the spot.
- The character library is now called "角色卡" everywhere, separate from the "角色" folder category in local assets.

## 1.9.1 - 2026-11-15

- Fix: upgrading to 1.9.0 could leave the API down on first start because the API and the Worker added the new task column at the same time ("duplicate column name: stage"). Start-up now tolerates the column already added by the other process; other migration errors still stop start-up.

## 1.9.0 - 2026-11-15

- Run a whole node group: the group bar gets "运行组内全部". A confirmation lists the nodes in upstream order with per-node estimates (unknown prices listed separately, never zero) and marks nodes that will be re-run. The server then submits independent nodes together and each downstream node only after its upstream succeeds, using the new upstream result, so the run continues with the page closed. A normal failure blocks only its downstream; an unknown result stops the whole group without resubmitting. If a recalculated estimate exceeds the confirmed amount (or becomes unknown) the run pauses for a new confirmation. Cancelling stops only nodes not yet submitted. Manually editing a member node or its upstream during a run blocks that branch; single-node generation and retry of member nodes are refused while the run is active.
- Generation nodes show the latest task number, elapsed time and estimated cost; clicking the task number opens it in the task center.
- Video and audio nodes show a server-reported "下载写回" stage while the result is being downloaded.
- Media preview pages through node versions or group media with ←/→, shows n/N and downloads the local file.
- Server-side write-back now rebinds @ image numbers in downstream prompts the same way the browser does, so results are the same with the page open or closed.
- Estimates: the Seedream 5.5 / 5.0 Pro decision follows the node's interface model on both sides; reference-video seconds are matched to the right file; ledger amounts use three decimals.
- Canvas audio submissions are checked against the saved node and refused before any upload if they differ; result names drop Unicode bidirectional controls and avoid Windows reserved names; the legacy audio tool now defaults to 48 kHz.
- Provider error messages no longer expose endpoint IDs (shown as ep-***).

## 1.8.0 - 2026-11-14

- Image and layer cost estimates from the official BytePlus price list: canvas image nodes show "预估 $x USD" with the model, output size, pixel tier and reference-image price on hover; the layer tool shows the per-layer price before submission and the ledger prices each output layer by its actual size. Seedream 5.5 layers below 921,600 pixels are counted at the lowest tier and marked as derived. Unknown prices are never shown as zero. Small amounts show three decimals.
- Signed provider URLs are no longer sent to the browser: task lists and details, canvas documents and layer projects show only the host (layer `source_url` fields are restored server-side on save; user text containing URLs is kept as typed). Copy actions copy the local result link.
- Deleting a local asset lists the affected projects and canvases (with node counts) first and highlights references from other projects. Uploads made from a character are labelled with the character in All projects.
- Canvas: "Fit all nodes" now fits every node; unsaved input is sent when the page is closed or hidden; leaving after a failed save warns again; if the server rejects the final save, the next visit offers to restore or discard the local draft, merged field by field so finished results are never lost. New nodes land in view and selected; panels no longer cover focus targets or the prompt library.
- Canvas feedback: completion notices dismiss themselves, carry the task number and no longer cover the cost or generate button; node-group rename commits on Enter and the group bar stays usable at low zoom; larger connection hit areas; video progress shows stages instead of a fixed 50%; previews fit the window by default; per-type placeholders and consistent model names.
- Library and legacy tools: folder menus are no longer clipped; dialogs trap focus and return it on Esc (nested dialogs close one at a time); native confirms replaced; tags shown on cards; legacy task search matches substrings and model names; the layer studio shows the loaded source and lists the project immediately (marked 未分解 until decomposed); the cost ledger shows failed and cancelled tasks as not billed, with project/canvas and submit time.
- Each browser tab remembers its own project and canvas; new tabs open the most recent canvas.
- Consistent danger buttons and notice placement across the app.

## 1.7.0 - 2026-11-14

- Character library (Asset library → Characters, shared across all projects): each character has a text description, up to 8 reference images and an optional voice reference (WAV/MP3, up to 30 s). Images and audio are local assets referenced by the character, not copies; uploads made in the character library also appear in Local assets. Right-click an image node and choose "Add to character" to add a result.
- Choosing a character from the @ menu in a node prompt imports its images (and, for video and audio nodes, its voice reference) as ordinary references and writes a visible, editable 【人物】 block at the top of the prompt, following the Seedance 2.5 prompt guide (one line per character, multiple references declared as one person, voice usage stated, "not interchangeable" note for several characters). The character's name is inserted at the caret. Nothing is expanded or hidden at submit time.
- Nodes that used a character show when it has been updated (one click to sync) or deleted.
- Permanently deleting a local asset used by a character lists the affected characters first and then removes it from them.
- Fixed: prompts submitted with references reached the provider with Windows line endings; line breaks are now normalised for all generation routes.

## 1.6.0 - 2026-11-14

- Generation results are now written into the canvas by the server when a task finishes. A canvas open in two windows no longer reports "updated in another window" when a result arrives; edits made meanwhile are kept, and genuine edits in both windows still raise a conflict. Downstream "upstream updated" markers and reference ids are saved with the result.
- Video frame capture: "Capture last frame" and "Capture current frame" on video nodes create an image asset node (full resolution) next to the video, ready to start the next shot.
- Project cost ledger (Project menu → Cost (estimates)): estimated costs by canvas, node, type and date for canvas and legacy-tool tasks. Tasks without price data are counted as unknown and never as zero; failed, cancelled, result-unknown and in-progress tasks are listed separately. Estimates only, not actual charges.
- Long-task notifications: an in-page notice when a task succeeds, fails, is cancelled or has an unknown result (click to jump to the node), an unread count in the tab title while in the background, and optional system notifications (asked in-page first; can be turned off). While the tab is hidden the canvas checks task status every 30 seconds.
- Prompt library in canvas nodes: search and insert saved prompts at the caret, or save the current prompt; shared with the legacy tools.
- Test suite: all previously quarantined browser tests fixed (outdated assertions and shared fixture state).

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
