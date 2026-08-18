#!/usr/bin/env python3
"""Reconcile the Cupsy public source proxy with config.json."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from string import Template
from urllib.parse import urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / 'config.json'
DEFAULT_TEMPLATE = PROJECT_ROOT / 'deploy/nginx/nanobanana-cupsy.conf.template'
DEFAULT_NGINX_AVAILABLE = Path('/etc/nginx/sites-available/nanobanana-cupsy')
DEFAULT_NGINX_ENABLED = Path('/etc/nginx/sites-enabled/nanobanana-cupsy')
DEFAULT_WEBROOT = Path('/var/www/certbot')
DEFAULT_CERT_ROOT = Path('/etc/letsencrypt')
DEFAULT_DEPLOY_HOOK = Path('/etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh')
MANAGED_MARKER = '# Managed by Nanobanana public source deployment.'


class DeploymentError(RuntimeError):
    pass


@dataclass(frozen=True)
class PublicSourceSpec:
    source_url: str
    scheme: str
    host: str
    public_port: int
    backend_port: int
    frontend_port: int
    is_ip: bool
    certificate_email: str = ''

    @property
    def server_name(self) -> str:
        return '_' if ':' in self.host else self.host

    @property
    def certificate_name(self) -> str:
        return self.host

    @property
    def direct_http(self) -> bool:
        return self.scheme == 'http' and self.public_port == self.backend_port


def _valid_hostname(host: str) -> bool:
    if len(host) > 253:
        return False
    labels = host.rstrip('.').split('.')
    return bool(labels) and all(
        label and len(label) <= 63
        and re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?', label)
        for label in labels
    )


def load_spec(config_path: Path) -> PublicSourceSpec | None:
    try:
        config = json.loads(config_path.read_text(encoding='utf-8'))
    except FileNotFoundError as error:
        raise DeploymentError(f'Config file not found: {config_path}') from error
    except json.JSONDecodeError as error:
        raise DeploymentError(f'Invalid JSON in {config_path}: {error}') from error

    source_url = str(
        config.get('video', {}).get('cupsy', {}).get('source_base_url', '')
    ).strip().rstrip('/')
    if not source_url:
        return None

    parsed = urlsplit(source_url)
    try:
        host = parsed.hostname
    except ValueError as error:
        raise DeploymentError(f'Invalid public source host: {error}') from error
    if parsed.scheme not in {'http', 'https'} or not host:
        raise DeploymentError('video.cupsy.source_base_url must be an HTTP(S) origin')
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise DeploymentError('Cupsy source URL cannot contain credentials, query, or fragment')
    if parsed.path not in {'', '/'}:
        raise DeploymentError('Cupsy source URL must not include a path')
    try:
        public_port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    except ValueError as error:
        raise DeploymentError(f'Invalid public source port: {error}') from error
    if not 1 <= public_port <= 65535:
        raise DeploymentError('Public source port must be between 1 and 65535')

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if not _valid_hostname(host):
            raise DeploymentError(f'Invalid public source hostname: {host}')
        is_ip = False
    else:
        if not address.is_global:
            raise DeploymentError('Cupsy source IP must be globally routable')
        is_ip = True

    try:
        backend_port = int(config.get('server', {}).get('port', 5000))
    except (TypeError, ValueError) as error:
        raise DeploymentError('server.port must be an integer') from error
    if not 1 <= backend_port <= 65535:
        raise DeploymentError('server.port must be between 1 and 65535')
    try:
        frontend_port = int(config.get('client', {}).get('port', 4545))
    except (TypeError, ValueError) as error:
        raise DeploymentError('client.port must be an integer') from error
    if not 1 <= frontend_port <= 65535:
        raise DeploymentError('client.port must be between 1 and 65535')
    if parsed.scheme == 'https' and (
        backend_port in {80, public_port} or frontend_port in {80, public_port}
    ):
        raise DeploymentError(
            'HTTPS public source ports 80 and the TLS port must not conflict '
            'with server.port or client.port'
        )
    if parsed.scheme == 'http' and public_port != backend_port and public_port == frontend_port:
        raise DeploymentError('HTTP public source proxy port must not conflict with client.port')

    deploy_config = config.get('deployment', {}).get('cupsy_public_source', {})
    email = str(deploy_config.get('certificate_email', '')).strip()
    return PublicSourceSpec(
        source_url=source_url,
        scheme=parsed.scheme,
        host=host,
        public_port=public_port,
        backend_port=backend_port,
        frontend_port=frontend_port,
        is_ip=is_ip,
        certificate_email=email,
    )


def render_bootstrap(spec: PublicSourceSpec, webroot: Path) -> str:
    return f'''{MANAGED_MARKER}
# Temporary ACME bootstrap configuration for {spec.host}.
server {{
    listen 80;
    listen [::]:80;
    server_name {spec.server_name};
    access_log off;

    location ^~ /.well-known/acme-challenge/ {{
        root {webroot};
        default_type text/plain;
        try_files $uri =404;
    }}

    location / {{ return 404; }}
}}
'''


def render_http_proxy(spec: PublicSourceSpec) -> str:
    return f'''{MANAGED_MARKER}
# Public HTTP source endpoint for Cupsy Assets.
server {{
    listen {spec.public_port};
    listen [::]:{spec.public_port};
    server_name {spec.server_name};
    access_log off;

    location ^~ /api/cupsy/source/ {{
        proxy_pass http://127.0.0.1:{spec.backend_port};
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto http;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_buffering off;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
    }}

    location / {{ return 404; }}
}}
'''


def render_https_proxy(
    spec: PublicSourceSpec,
    template_path: Path,
    webroot: Path,
    cert_root: Path,
) -> str:
    try:
        template = Template(template_path.read_text(encoding='utf-8'))
    except FileNotFoundError as error:
        raise DeploymentError(f'Nginx template not found: {template_path}') from error
    certificate_path = cert_root / 'live' / spec.certificate_name
    rendered = template.substitute(
        SERVER_NAME=spec.server_name,
        ACME_WEBROOT=str(webroot),
        PUBLIC_PORT=str(spec.public_port),
        CERTIFICATE_PATH=str(certificate_path),
        BACKEND_PORT=str(spec.backend_port),
    )
    digest = hashlib.sha256(rendered.encode('utf-8')).hexdigest()[:16]
    return f'{MANAGED_MARKER}\n# Configuration fingerprint: {digest}\n{rendered}'


def _run(command: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    printable = ' '.join(command)
    print(f'+ {printable}')
    return subprocess.run(
        command,
        check=True,
        text=True,
        capture_output=capture,
    )


def _write_atomic(path: Path, content: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f'.{path.name}.', dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _reload_nginx() -> None:
    _run(['nginx', '-t'])
    if shutil.which('systemctl'):
        active = subprocess.run(
            ['systemctl', 'is-active', '--quiet', 'nginx'],
            check=False,
        ).returncode == 0
        if active:
            _run(['systemctl', 'reload', 'nginx'])
        else:
            _run(['systemctl', 'enable', '--now', 'nginx'])
    else:
        _run(['nginx', '-s', 'reload'])


def _activate_nginx_config(available: Path, enabled: Path, content: str) -> None:
    if (
        available.exists()
        and available.read_text(encoding='utf-8') == content
        and enabled.is_symlink()
        and Path(os.path.realpath(enabled)) == available.resolve()
    ):
        _run(['nginx', '-t'])
        return
    previous = available.read_bytes() if available.exists() else None
    enabled_existed = enabled.exists() or enabled.is_symlink()
    previous_target = os.readlink(enabled) if enabled.is_symlink() else None
    if enabled_existed and not enabled.is_symlink():
        raise DeploymentError(f'Refusing to replace non-symlink Nginx site: {enabled}')
    try:
        _write_atomic(available, content)
        enabled.parent.mkdir(parents=True, exist_ok=True)
        if enabled.is_symlink() and Path(os.path.realpath(enabled)) != available.resolve():
            enabled.unlink()
        if not (enabled.exists() or enabled.is_symlink()):
            enabled.symlink_to(available)
        _reload_nginx()
    except Exception:
        if previous is None:
            if available.exists():
                available.unlink()
        else:
            _write_atomic(available, previous.decode('utf-8'))
        if not enabled_existed and enabled.is_symlink():
            enabled.unlink()
        elif previous_target and (
            not enabled.is_symlink() or os.readlink(enabled) != previous_target
        ):
            if enabled.exists() or enabled.is_symlink():
                enabled.unlink()
            enabled.symlink_to(previous_target)
        try:
            _reload_nginx()
        except Exception as rollback_error:
            print(f'WARNING: Nginx rollback reload failed: {rollback_error}', file=sys.stderr)
        raise


def _remove_nginx_config(available: Path, enabled: Path) -> None:
    if enabled.is_symlink() and Path(os.path.realpath(enabled)) == available.resolve():
        enabled.unlink()
    if available.exists():
        available.unlink()
    _reload_nginx()


def _version_tuple(output: str) -> tuple[int, ...]:
    match = re.search(r'(\d+)\.(\d+)(?:\.(\d+))?', output)
    return tuple(int(part or 0) for part in match.groups()) if match else ()


def _certbot_path() -> str | None:
    snap_certbot = Path('/snap/bin/certbot')
    if snap_certbot.exists():
        return str(snap_certbot)
    return shutil.which('certbot')


def _install_dependencies(needs_ip_certificate: bool) -> None:
    if not shutil.which('nginx'):
        if not shutil.which('apt-get'):
            raise DeploymentError('Nginx is missing and automatic installation requires apt-get')
        _run(['apt-get', 'update'])
        _run(['apt-get', 'install', '-y', 'nginx'])

    certbot = _certbot_path()
    version = ()
    if certbot:
        result = _run([certbot, '--version'], capture=True)
        version = _version_tuple((result.stdout or '') + (result.stderr or ''))
    if certbot and (not needs_ip_certificate or version >= (5, 4, 0)):
        return

    if not shutil.which('snap'):
        if not shutil.which('apt-get'):
            raise DeploymentError('Certbot 5.4+ is required and snap/apt-get are unavailable')
        _run(['apt-get', 'update'])
        _run(['apt-get', 'install', '-y', 'snapd'])
    if Path('/snap/bin/certbot').exists():
        _run(['snap', 'refresh', 'certbot'])
    else:
        _run(['snap', 'install', '--classic', 'certbot'])
    certbot = _certbot_path()
    if not certbot:
        raise DeploymentError('Certbot installation completed but the executable was not found')
    result = _run([certbot, '--version'], capture=True)
    if needs_ip_certificate and _version_tuple(result.stdout + result.stderr) < (5, 4, 0):
        raise DeploymentError('Certbot 5.4 or newer is required for IP webroot certificates')


def _install_deploy_hook(path: Path) -> None:
    source = PROJECT_ROOT / 'deploy/certbot/reload-nginx.sh'
    content = source.read_text(encoding='utf-8')
    _write_atomic(path, content, mode=0o755)


def _timer_enabled(name: str) -> bool:
    if not shutil.which('systemctl'):
        return False
    return subprocess.run(
        ['systemctl', 'is-enabled', '--quiet', name],
        check=False,
    ).returncode == 0


def _ensure_renewal_timer(certbot: str) -> None:
    known_timers = ('snap.certbot.renew.timer', 'certbot.timer', 'nanobanana-certbot-renew.timer')
    for timer in known_timers:
        if _timer_enabled(timer):
            _run(['systemctl', 'start', timer])
            return
    if not shutil.which('systemctl'):
        raise DeploymentError('No Certbot renewal timer is active and systemd is unavailable')

    service = Path('/etc/systemd/system/nanobanana-certbot-renew.service')
    timer = Path('/etc/systemd/system/nanobanana-certbot-renew.timer')
    _write_atomic(service, f'''[Unit]
Description=Renew Nanobanana public source certificates

[Service]
Type=oneshot
ExecStart={certbot} renew --quiet
''')
    _write_atomic(timer, '''[Unit]
Description=Twice-daily Nanobanana certificate renewal

[Timer]
OnCalendar=*-*-* 00,12:00:00
RandomizedDelaySec=1h
Persistent=true

[Install]
WantedBy=timers.target
''')
    _run(['systemctl', 'daemon-reload'])
    _run(['systemctl', 'enable', '--now', timer.name])


def _request_certificate(
    spec: PublicSourceSpec,
    certbot: str,
    webroot: Path,
    deploy_hook: Path,
) -> None:
    command = [
        certbot,
        'certonly',
        '--non-interactive',
        '--agree-tos',
        '--webroot',
        '--webroot-path', str(webroot),
        '--cert-name', spec.certificate_name,
        '--deploy-hook', str(deploy_hook),
    ]
    if spec.certificate_email:
        command.extend(['--email', spec.certificate_email])
    else:
        command.append('--register-unsafely-without-email')
    if spec.is_ip:
        command.extend(['--preferred-profile', 'shortlived', '--ip-address', spec.host])
    else:
        command.extend(['--domain', spec.host])
    _run(command)


def _certificate_valid(cert_path: Path) -> bool:
    if not cert_path.exists() or not shutil.which('openssl'):
        return cert_path.exists()
    return subprocess.run(
        ['openssl', 'x509', '-checkend', '0', '-noout', '-in', str(cert_path)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0


def reconcile(args: argparse.Namespace, spec: PublicSourceSpec) -> None:
    if spec.direct_http:
        print(
            f'Cupsy source uses direct HTTP on backend port {spec.backend_port}; '
            'no certificate or reverse proxy is required.'
        )
        return
    if os.geteuid() != 0:
        raise DeploymentError('Deployment requires root privileges')

    _install_dependencies(needs_ip_certificate=spec.scheme == 'https' and spec.is_ip)
    available = Path(args.nginx_available)
    enabled = Path(args.nginx_enabled)
    webroot = Path(args.webroot)
    cert_root = Path(args.cert_root)
    deploy_hook = Path(args.deploy_hook)
    webroot.mkdir(parents=True, exist_ok=True)

    if spec.scheme == 'http':
        _activate_nginx_config(available, enabled, render_http_proxy(spec))
        print(f'Configured Cupsy HTTP source proxy at {spec.source_url}')
        return

    certbot = _certbot_path()
    if not certbot:
        raise DeploymentError('Certbot is not installed')
    _install_deploy_hook(deploy_hook)
    certificate_path = cert_root / 'live' / spec.certificate_name / 'fullchain.pem'
    final_config = render_https_proxy(spec, Path(args.template), webroot, cert_root)

    if not certificate_path.exists():
        previous = available.read_text(encoding='utf-8') if available.exists() else None
        _activate_nginx_config(available, enabled, render_bootstrap(spec, webroot))
        try:
            _request_certificate(spec, certbot, webroot, deploy_hook)
        except Exception:
            if previous is not None:
                _activate_nginx_config(available, enabled, previous)
            else:
                _remove_nginx_config(available, enabled)
            raise

    _activate_nginx_config(available, enabled, final_config)
    _ensure_renewal_timer(certbot)
    if not _certificate_valid(certificate_path):
        raise DeploymentError(f'Certificate is missing or expired: {certificate_path}')
    print(f'Configured Cupsy HTTPS source proxy at {spec.source_url}')


def check_deployment(args: argparse.Namespace, spec: PublicSourceSpec) -> None:
    if spec.direct_http:
        print('OK: direct HTTP source configuration does not require Nginx')
        return
    available = Path(args.nginx_available)
    enabled = Path(args.nginx_enabled)
    if not available.exists() or not enabled.exists():
        raise DeploymentError('Managed Nginx public source site is not installed')
    expected = (
        render_https_proxy(spec, Path(args.template), Path(args.webroot), Path(args.cert_root))
        if spec.scheme == 'https'
        else render_http_proxy(spec)
    )
    if available.read_text(encoding='utf-8') != expected:
        raise DeploymentError('Installed Nginx public source config does not match config.json')
    if Path(os.path.realpath(enabled)) != available.resolve():
        raise DeploymentError('Nginx public source site is not enabled correctly')
    if spec.scheme == 'https':
        certificate = Path(args.cert_root) / 'live' / spec.certificate_name / 'fullchain.pem'
        if not _certificate_valid(certificate):
            raise DeploymentError(f'Certificate is missing or expired: {certificate}')
        if not Path(args.deploy_hook).exists():
            raise DeploymentError('Certbot Nginx deploy hook is missing')
    _run(['nginx', '-t'])
    print(f'OK: public source deployment matches {spec.source_url}')


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=str(DEFAULT_CONFIG))
    parser.add_argument('--template', default=str(DEFAULT_TEMPLATE))
    parser.add_argument('--nginx-available', default=str(DEFAULT_NGINX_AVAILABLE))
    parser.add_argument('--nginx-enabled', default=str(DEFAULT_NGINX_ENABLED))
    parser.add_argument('--webroot', default=str(DEFAULT_WEBROOT))
    parser.add_argument('--cert-root', default=str(DEFAULT_CERT_ROOT))
    parser.add_argument('--deploy-hook', default=str(DEFAULT_DEPLOY_HOOK))
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        spec = load_spec(Path(args.config))
        if spec is None:
            print('Cupsy source_base_url is empty; public source deployment skipped.')
            return 0
        if args.dry_run:
            if spec.direct_http:
                print('Direct HTTP mode: no Nginx configuration required.')
            elif spec.scheme == 'https':
                print(render_https_proxy(spec, Path(args.template), Path(args.webroot), Path(args.cert_root)))
            else:
                print(render_http_proxy(spec))
            return 0
        if args.check:
            check_deployment(args, spec)
        else:
            reconcile(args, spec)
        return 0
    except (DeploymentError, subprocess.CalledProcessError, OSError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
