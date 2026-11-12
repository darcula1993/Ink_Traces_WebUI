#!/usr/bin/env python3
"""Repair the local systemd service user and deploy a public HTTPS workspace.

Run --dry-run first. Requires root to apply; does not modify the service on 443.
"""
import argparse
import grp
import json
import os
from pathlib import Path
import pwd
import re
import sqlite3
import subprocess
import tempfile
import time
from datetime import datetime, timezone

if __package__:
    from . import configure_public_source as public_source
else:
    import configure_public_source as public_source

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / 'deploy/nginx/nanobanana-workspace.conf.template'


def prepare_config(config, origin):
    # Round-trip a copy so dry runs never modify the loaded configuration.
    candidate = json.loads(json.dumps(config))
    if candidate.get('config_version') != 2:
        raise RuntimeError('config.json is not v2; run scripts/migrate-config-v2.py first')
    candidate.setdefault('deployment', {}).setdefault('cupsy_source', {})['base_url'] = origin
    return candidate


def check_idle():
    with sqlite3.connect(f'file:{ROOT / "tasks.db"}?mode=ro', uri=True) as db:
        count = db.execute("SELECT count(*) FROM tasks WHERE status IN "
                           "('submitting','preparing','pending','processing','cancel_requested')").fetchone()[0]
    if count:
        raise RuntimeError(f'{count} active tasks; finish or cancel them before restarting')


def run(*command):
    subprocess.run(command, check=True)


def service_override(user, group):
    return f'''[Service]
User={user}
Group={group}
# systemd terminates only this service's cgroup. Avoid legacy stop.sh's global pkill.
ExecStop=
KillMode=control-group
TimeoutStopSec=90
Environment=NANOBANANA_SKIP_PUBLIC_SOURCE_DEPLOY=1
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin', required=True, help='Public HTTPS origin, for example https://PUBLIC_IP:8443')
    parser.add_argument('--service', default='nanobanana.service')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_.@-]+\.service', args.service):
        parser.error('Invalid systemd service name')
    config_path = ROOT / 'config.json'
    original = config_path.read_bytes()
    config_stat = config_path.stat()
    owner = pwd.getpwuid(config_stat.st_uid)
    group = grp.getgrgid(owner.pw_gid).gr_name
    candidate = prepare_config(json.loads(original), args.origin)
    check_idle()
    with tempfile.TemporaryDirectory(prefix='nanobanana-https-') as temporary:
        staged = Path(temporary) / 'config.json'
        staged.write_text(json.dumps(candidate))
        staged.chmod(0o600)
        spec = public_source.load_spec(staged)
        if spec.scheme != 'https':
            parser.error('--origin must use HTTPS')
        if spec.public_port == 443:
            parser.error('Port 443 is reserved for the existing proxy; use a separate port such as 8443')
        # Ark video reference URLs use the same public HTTPS origin (config v2).
        candidate.setdefault('deployment', {})['public_base_url'] = spec.source_url
        dropin = Path('/etc/systemd/system') / (args.service + '.d') / 'nanobanana-owner.conf'
        print(f'Service: {args.service}; runtime owner: {owner.pw_name}:{group}', flush=True)
        print(f'Workspace and provider source: {spec.source_url}', flush=True)
        print('Public TCP ports 80 and the HTTPS port must be reachable for issuance and use.', flush=True)
        if args.dry_run:
            print(service_override(owner.pw_name, group))
            print(public_source.render_https_proxy(spec, TEMPLATE, Path('/var/www/certbot'), Path('/etc/letsencrypt')))
            return
        if os.geteuid() != 0:
            parser.error('Run with sudo to update systemd, Nginx and certificates')
        runtime = ROOT.parent
        runtime_path = f'{runtime}/.nanobanana-venv/bin:{runtime}/.runtime/node/bin:/usr/local/bin:/usr/bin:/bin'
        # Build as the eventual service owner, without producing root-owned assets.
        run('runuser', '-u', owner.pw_name, '--', 'env', f'PATH={runtime_path}',
            'npm', '--prefix', str(ROOT / 'client'), 'run', 'build')
        check_idle()
        public_source._write_atomic(dropin, service_override(owner.pw_name, group))
        run('systemctl', 'daemon-reload')
        run('systemctl', 'restart', args.service)
        for _ in range(30):
            ready = subprocess.run([
                'curl', '--noproxy', '*', '--fail', '--silent', '--max-time', '3',
                f'http://127.0.0.1:{spec.backend_port}/api/ready',
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError('Service restarted but worker is not ready; inspect worker.log')
        print('Service restarted with the correct owner; configuring HTTPS next.', flush=True)
        deployment_args = public_source.build_parser().parse_args(['--config', str(staged), '--template', str(TEMPLATE)])
        public_source.reconcile(deployment_args, spec)
        check_idle()
        backup_dir = Path('/var/backups/nanobanana')
        backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup = backup_dir / f'config-{stamp}.json'
        public_source._write_atomic(backup, original.decode(), mode=0o600)
        public_source._write_atomic(config_path, json.dumps(candidate, ensure_ascii=False, indent=2) + '\n', mode=0o600)
        os.chown(config_path, config_stat.st_uid, config_stat.st_gid)
        run('systemctl', 'restart', args.service)
        # Verify both worker readiness and certificate identity through the local TLS listener.
        url = f'{spec.source_url}/api/ready'
        for _ in range(30):
            result = subprocess.run([
                'curl', '--noproxy', '*', '--fail', '--silent', '--show-error', '--max-time', '3',
                '--resolve', f'{spec.host}:{spec.public_port}:127.0.0.1', url,
            ], capture_output=True, text=True)
            if result.returncode == 0:
                print(f'HTTPS and worker readiness verified: {spec.source_url}')
                print(f'Original configuration backup: {backup}')
                return
            time.sleep(1)
        raise RuntimeError('HTTPS readiness check failed; inspect the service journal and worker.log')


if __name__ == '__main__':
    main()
