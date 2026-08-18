import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from deploy import configure_public_source as deployment


def write_config(tmp_path, source_url, server_port=5000, email='', client_port=4545):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps({
        'server': {'port': server_port},
        'client': {'port': client_port},
        'video': {'cupsy': {'source_base_url': source_url}},
        'deployment': {'cupsy_public_source': {'certificate_email': email}},
    }), encoding='utf-8')
    return path


def test_load_spec_for_public_ip_https(tmp_path):
    path = write_config(tmp_path, 'https://203.0.113.20')
    with pytest.raises(deployment.DeploymentError, match='globally routable'):
        deployment.load_spec(path)

    path = write_config(tmp_path, 'https://8.8.8.8', email='ops@example.com')
    spec = deployment.load_spec(path)
    assert spec.host == '8.8.8.8'
    assert spec.public_port == 443
    assert spec.backend_port == 5000
    assert spec.frontend_port == 4545
    assert spec.is_ip is True
    assert spec.certificate_email == 'ops@example.com'


def test_load_spec_rejects_paths_and_credentials(tmp_path):
    with pytest.raises(deployment.DeploymentError, match='must not include a path'):
        deployment.load_spec(write_config(tmp_path, 'https://studio.example/source'))
    with pytest.raises(deployment.DeploymentError, match='cannot contain credentials'):
        deployment.load_spec(write_config(tmp_path, 'https://user:pass@studio.example'))


def test_load_spec_rejects_proxy_port_conflicts(tmp_path):
    with pytest.raises(deployment.DeploymentError, match='must not conflict'):
        deployment.load_spec(write_config(tmp_path, 'https://8.8.8.8:5000'))
    with pytest.raises(deployment.DeploymentError, match='client.port'):
        deployment.load_spec(write_config(tmp_path, 'http://8.8.8.8:4545'))


def test_direct_http_does_not_require_proxy(tmp_path):
    spec = deployment.load_spec(write_config(tmp_path, 'http://8.8.8.8:5000'))
    assert spec.direct_http is True


def test_https_render_uses_config_and_contains_no_deployment_ip(tmp_path):
    spec = deployment.load_spec(write_config(tmp_path, 'https://8.8.4.4:8443', 5100))
    rendered = deployment.render_https_proxy(
        spec,
        ROOT / 'deploy/nginx/nanobanana-cupsy.conf.template',
        Path('/var/www/certbot'),
        Path('/etc/letsencrypt'),
    )
    assert 'listen 8443 ssl;' in rendered
    assert 'server_name 8.8.4.4;' in rendered
    assert 'proxy_pass http://127.0.0.1:5100;' in rendered
    assert '/etc/letsencrypt/live/8.8.4.4/fullchain.pem' in rendered
    assert '154.36.185.182' not in rendered
    assert '/api/cupsy/source/' in rendered
    assert 'access_log off;' in rendered


def test_domain_uses_standard_https_certificate(tmp_path):
    spec = deployment.load_spec(write_config(tmp_path, 'https://media.example.com'))
    assert spec.is_ip is False
    assert spec.certificate_name == 'media.example.com'


def test_ip_certificate_request_uses_shortlived_webroot(tmp_path, monkeypatch):
    spec = deployment.load_spec(write_config(tmp_path, 'https://8.8.8.8'))
    observed = []
    monkeypatch.setattr(deployment, '_run', lambda command, **_kwargs: observed.append(command))

    deployment._request_certificate(
        spec,
        '/snap/bin/certbot',
        tmp_path / 'webroot',
        tmp_path / 'reload-nginx.sh',
    )

    command = observed[0]
    assert command[:2] == ['/snap/bin/certbot', 'certonly']
    assert command[command.index('--preferred-profile') + 1] == 'shortlived'
    assert command[command.index('--ip-address') + 1] == '8.8.8.8'
    assert '--webroot' in command
    assert '--domain' not in command


def test_nginx_activation_restores_previous_config_on_failure(tmp_path, monkeypatch):
    available = tmp_path / 'sites-available/nanobanana-cupsy'
    enabled = tmp_path / 'sites-enabled/nanobanana-cupsy'
    available.parent.mkdir()
    enabled.parent.mkdir()
    available.write_text('previous config\n', encoding='utf-8')
    enabled.symlink_to(available)
    attempts = 0

    def reload_nginx():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError('invalid config')

    monkeypatch.setattr(deployment, '_reload_nginx', reload_nginx)
    with pytest.raises(RuntimeError, match='invalid config'):
        deployment._activate_nginx_config(available, enabled, 'replacement config\n')

    assert available.read_text(encoding='utf-8') == 'previous config\n'
    assert enabled.resolve() == available.resolve()
    assert attempts == 2
