# Installation Guide

This guide covers installing, configuring, starting and testing Ink Traces WebUI on a single Linux or macOS host.

## 1. Requirements

- Python 3.10+
- Node.js 18+ and npm
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
- Image: `generation.image.default` (`byteplus` or `cupsy`) and `generation.image.byteplus.model`. Video: `generation.video.byteplus.model` / `fast_model` and `generation.video.cupsy.model`. Audio: `generation.audio.cupsy.model`. Layer decomposition uses the BytePlus image model (`generation.image.byteplus.model`); there is no separate layer setting. If an older v2 file still has `generation.layer`, remove it with `python3 scripts/config-drop-layer.py` (dry run) / `--apply`.
- Ark reference video uploads: set `deployment.public_base_url` to the public origin of this application.
- Cupsy references: `deployment.cupsy_source.base_url`, a public HTTP(S) origin that routes back to this application.
- Sessions: set `auth.secret_key` (or env `INK_TRACES_SECRET_KEY`); otherwise an ignored `.flask_secret_key` file is generated.

Validate the file with `python3 server/config_v2.py check`; `start.sh` runs the same check and does not start anything when it fails. The server only reads v2. A configuration file from a pre-release version (no `config_version`) must be converted first: stop the services and run `python3 scripts/migrate-config-v2.py` (dry run, prints key paths only), then add `--apply` (writes a `config.json.pre-v2` backup). Details are in [doc/development.md](doc/development.md#配置configjson-v2).

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

## 6. Run the tests (mock providers, no paid requests)

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

## 7. Maintenance

With services stopped: `python3 server/maintenance.py all --grace-hours 24` removes expired media, compacts legacy data and vacuums SQLite. `./clean.sh` removes regenerable caches.
