# Installation Guide

This guide covers installing, configuring, starting and testing Ink Traces WebUI on a single Linux or macOS host.

## 1. Requirements

- Python 3.10+
- Node.js 18+ and npm
- ffmpeg (`ffprobe` must be on `PATH`; it checks uploaded audio/video and is required by the 2.0 library migration)
- API credentials for at least one provider (BytePlus Ark and/or Cupsy)

## 2. Install

```bash
./setup.sh
```

`setup.sh` checks the toolchain, creates `config.json` from `config.json.example` when missing, and installs backend (`server/requirements.txt`) and frontend (`client/`) dependencies. Manual equivalent:

```bash
cp config.json.example config.json
pip install -r server/requirements.txt
(cd client && npm install)
```

## 3. Configure

Edit `config.json` (never committed; it holds your credentials). It uses the v2 layout of `config.json.example` (`"config_version": 2`): accounts live under `providers`, the account and model each capability uses under `generation`, and deployment settings under `deployment`.

- Accounts: `providers.byteplus.api_key` (BytePlus Ark) and/or `providers.cupsy.api_key`, each with its `endpoint` and timeouts.
- Seedance 2.5 on BytePlus: put your own endpoint ID (`ep-…` from the BytePlus console) in `providers.byteplus.endpoint_ids.seedance_2_5`; the example ships the placeholder `ep-your-endpoint-id`, which counts as not configured.
- Image: `generation.image.default` (`byteplus` or `cupsy`) and `generation.image.byteplus.model`. Video: `generation.video.byteplus.model` / `fast_model` and `generation.video.cupsy.model`. Audio: `generation.audio.cupsy.model`. Layer decomposition uses the BytePlus image model (`generation.image.byteplus.model`); there is no separate layer setting. If a 1.0.0 file still has a `generation.layer` section, delete that section.
- Ark reference video uploads: set `deployment.public_base_url` to the public origin of this application.
- Cupsy references: `deployment.cupsy_source.base_url`, a public HTTP(S) origin that routes back to this application.
- Sessions: set `auth.secret_key` (or env `INK_TRACES_SECRET_KEY`); otherwise an ignored `.flask_secret_key` file is generated.

Validate the file with `python3 server/config_v2.py check`; `start.sh` runs the same check and does not start anything when it fails. The server only reads this v2 layout; unknown keys, old sections or a missing `config_version` stop start-up with an error naming the key path.

See the [README](README.md) and [Cupsy notes](doc/cupsy_compatibility.md) for details.

## 4. Start and stop

```bash
./start.sh      # builds the frontend, starts the task worker and Gunicorn
./stop.sh
```

Open `http://localhost:4545`. For frontend hot reload use `NANOBANANA_FRONTEND_MODE=dev ./start.sh`. Check for active generation tasks before stopping or restarting; interrupted paid requests are not replayed automatically. Set `NANOBANANA_SKIP_PUBLIC_SOURCE_DEPLOY=1` to skip public-source (Nginx/Certbot) automation on start.

## 5. Optional: HTTPS for public sources

Cupsy must fetch reference media from a public HTTPS origin. Configure `deployment.cupsy_source` in `config.json` (`base_url`, `auto_configure`, `certificate_email`) and run:

```bash
./deploy/configure-public-source.sh --dry-run   # preview
sudo ./deploy/configure-public-source.sh        # apply (Nginx + Certbot)
./deploy/configure-public-source.sh --check
```

Port 80 must be reachable for HTTP-01 validation and firewall rules are your responsibility. To run behind systemd, `deploy/restart_with_https.py --service nanobanana.service --dry-run` shows what it would change; it needs root to apply. The Nginx and Certbot templates are in [`deploy/nginx/`](deploy/nginx/) and [`deploy/certbot/`](deploy/certbot/).

## 6. Upgrading from 1.x to 2.0

2.0 replaces the per-project libraries, tags and per-canvas copies with one global library and migrates existing data once (see [CHANGELOG](CHANGELOG.md)). Run the steps below from the 2.0 checkout, next to the existing `tasks.db`; `canvas_assets/` and `output/` are expected beside it (otherwise pass `--asset-root` / `--output-dir`).

1. Install ffmpeg and check that `ffprobe -version` works; the migration stops part-way without it.
2. Make sure no generation task or node-group run is active, then stop the API and the Worker.
3. Back up: `python3 scripts/migrate-library-global.py --db tasks.db --make-backup <new-dir>` (SQLite backup, hard-link snapshot of `canvas_assets/` and `output/`, checksums).
4. Dry run: `python3 scripts/migrate-library-global.py --db tasks.db` prints what will be imported, skipped, deduplicated and cleaned up, and anything that blocks the migration. Nothing is written.
5. Apply: `python3 scripts/migrate-library-global.py --db tasks.db --apply --backup-dir <new-dir>`. It refuses while tasks or runs are active, while the Worker is still running, or without a fresh backup of this database. If interrupted, run the same command again; a repeated run changes nothing.
6. Check: `python3 scripts/migrate-library-global.py --db tasks.db --verify`, then start the services and open the library.

Copies held only by already-deleted canvases or projects are removed during the migration (`--include-archived` imports them instead); tags and project folders are deleted and their assets placed in the library root. Keep the backup until you have checked the new library.

To roll back: stop the services, export what changed after the migration with `--new-since <apply finish time> --export-dir <new-empty-dir>` (new files plus a `changes.json` of moves, renames, deletions, folders and groups), restore `tasks.db` from the backup directory and `canvas_assets/` / `output/` from its snapshot (for example `cp -al`), and go back to the 1.x code.

## 7. Run the tests (mock providers, no paid requests)

Backend tests use mocked providers. Run them from a checkout that has **no** `config.json` (the test session refuses to start when one exists):

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r server/requirements-dev.txt
pytest
```

Browser (Playwright) tests depend on an isolated fixture setup that is not part of this distribution. Frontend build check:

```bash
cd client && npm install && npm run build
```

## 8. Maintenance

With services stopped: `python3 server/maintenance.py all --grace-hours 24` removes expired task media (results kept in the library are not touched), compacts legacy data and vacuums SQLite. `./clean.sh` removes regenerable caches.
Back up `tasks.db`, `canvas_assets/` (library files) and `output/` together.
