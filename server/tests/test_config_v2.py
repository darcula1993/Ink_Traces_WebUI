"""config.json v2 loader/validator and scripts/migrate-config-v2.py (synthetic values only)."""
import copy
import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

import app as application
import config_v2

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('migrate_config_v2', ROOT / 'scripts' / 'migrate-config-v2.py')
migrate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migrate)

# Every value below is fake; the assertions check none of them reaches any output.
SECRETS = [
    'byteplus-test-key-111', 'byteplus-video-test-key-222', 'cupsy-test-key-333', 'google-test-key-444',
    'openai-test-key-555', 'fake-pass-666', 'fake-secret-777', 'ep-fake-image-888', 'ep-fake-25-999',
    'fake-user-000', 'ops@example.invalid', '203.0.113.9', 'ark.fake.invalid',
]
V1 = {
    'auth': {'username': 'fake-user-000', 'password': 'fake-pass-666', 'secret_key': 'fake-secret-777'},
    'server': {'port': 5001, 'public_host': '203.0.113.9', 'public_port': '8443', 'public_scheme': 'https'},
    'client': {'port': 4546},
    'deployment': {'cupsy_public_source': {'auto_configure': False, 'certificate_email': 'ops@example.invalid'}},
    'api': {
        'default_provider': 'ark',
        'google': {'api_key': 'google-test-key-444', 'model': 'gemini'},
        'cupsy': {'model': 'seedream-5.0-pro'},
        'ark': {'api_key': 'byteplus-test-key-111', 'model': 'ep-fake-image-888', 'endpoint': 'https://ark.fake.invalid'},
    },
    'video': {
        'ark': {'api_key': 'byteplus-test-key-111', 'endpoint': 'https://ark.fake.invalid', 'seedance_2_5_model': 'ep-fake-25-999'},
        'cupsy': {'api_key': 'cupsy-test-key-333', 'source_base_url': 'https://203.0.113.9:8443'},
    },
    'audio': {'cupsy': {'model': 'seed-audio-1.0'}},
    'openai': {'api_key': 'openai-test-key-555', 'endpoint': 'https://openai.fake.invalid', 'prompt_file': 'p.txt'},
}


def write(tmp_path, data, mode=0o600, name='config.json'):
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding='utf-8')
    os.chmod(path, mode)
    return path


def config_files(directory):
    # conftest's isolated backend shares tmp_path (tasks.db, error_logs); look at config files only.
    return sorted(p.name for p in directory.iterdir() if p.name.startswith(('config', '.config')))


def run(capsys, *args):
    code = migrate.main(list(args))
    captured = capsys.readouterr()
    output = captured.out + captured.err
    for secret in SECRETS:
        assert secret not in output, f'value leaked into migration output: {secret[:8]}…'
    return code, output


# --- migration -------------------------------------------------------------------------

def test_dry_run_lists_paths_only_and_writes_nothing(tmp_path, capsys):
    path = write(tmp_path, V1)
    before = path.read_bytes()
    code, output = run(capsys, '--config', str(path))
    assert code == 0
    assert path.read_bytes() == before
    assert config_files(tmp_path) == ['config.json']
    assert 'api.google.api_key  [将删除]' in output
    assert 'openai.api_key  [将删除]' in output and 'openai.prompt_file  [将删除]' in output
    assert 'api.ark.api_key -> providers.byteplus.api_key  [有值]' in output
    assert 'video.ark.model -> generation.video.byteplus.model  [空]' in output
    assert '试运行' in output


def test_apply_writes_valid_v2_with_backup_and_preserves_600(tmp_path, capsys):
    path = write(tmp_path, V1)
    original = path.read_bytes()
    code, output = run(capsys, '--config', str(path), '--apply')
    assert code == 0, output
    backup = tmp_path / 'config.json.pre-v2'
    assert backup.read_bytes() == original
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert config_files(tmp_path) == ['config.json', 'config.json.pre-v2']  # no temp left
    config, _warnings = config_v2.load(path)
    raw = json.loads(path.read_text(encoding='utf-8'))
    assert 'api' not in raw and 'video' not in raw and 'audio' not in raw and 'openai' not in raw
    assert 'google' not in path.read_text(encoding='utf-8')
    assert config['providers']['byteplus'] == {
        'api_key': 'byteplus-test-key-111', 'endpoint': 'https://ark.fake.invalid',
        'endpoint_ids': {'seedance_2_5': 'ep-fake-25-999'},
        'request_timeout_seconds': 600, 'upload_timeout_seconds': 120,
    }
    assert config['providers']['cupsy']['api_key'] == 'cupsy-test-key-333'
    assert config['providers']['cupsy']['endpoint'] == 'https://cupsy.io'
    assert config['generation']['image'] == {'default': 'byteplus', 'byteplus': {'model': 'ep-fake-image-888'}, 'cupsy': {'poll_max_attempts': 1800}}
    assert config['generation']['layer']['byteplus']['model'] == ''
    assert config['server']['port'] == 5001 and config['client']['port'] == 4546
    assert config['auth']['password'] == 'fake-pass-666'
    assert config['deployment'] == {
        'public_base_url': 'https://203.0.113.9:8443',
        'cupsy_source': {'base_url': 'https://203.0.113.9:8443', 'asset_token_ttl_seconds': 7200,
                         'auto_configure': False, 'certificate_email': 'ops@example.invalid'},
    }
    # Running again on the migrated file is a no-op.
    assert run(capsys, '--config', str(path), '--apply')[0] == 0
    assert backup.read_bytes() == original


def test_apply_preserves_non_600_mode(tmp_path, capsys):
    path = write(tmp_path, V1, mode=0o640)
    code, output = run(capsys, '--config', str(path), '--apply')
    assert code == 0 and '建议改为 600' in output
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert stat.S_IMODE((tmp_path / 'config.json.pre-v2').stat().st_mode) == 0o600


def test_existing_backup_refuses_without_touching_files(tmp_path, capsys):
    path = write(tmp_path, V1)
    backup = tmp_path / 'config.json.pre-v2'
    backup.write_text('first backup', encoding='utf-8')
    before = path.read_bytes()
    code, output = run(capsys, '--config', str(path), '--apply')
    assert code == 2 and '已存在' in output
    assert path.read_bytes() == before and backup.read_text(encoding='utf-8') == 'first backup'


def test_inconsistent_byteplus_credentials_stop_until_user_chooses(tmp_path, capsys):
    data = copy.deepcopy(V1)
    data['video']['ark']['api_key'] = 'byteplus-video-test-key-222'
    path = write(tmp_path, data)
    before = path.read_bytes()
    for extra in ([], ['--apply']):
        code, output = run(capsys, '--config', str(path), *extra)
        assert code == 3
        assert 'api.ark.api_key ≠ video.ark.api_key  [冲突]' in output and '--byteplus-from' in output
        assert path.read_bytes() == before and not (tmp_path / 'config.json.pre-v2').exists()

    code, _output = run(capsys, '--config', str(path), '--byteplus-from', 'video', '--apply')
    assert code == 0
    assert config_v2.load(path)[0]['providers']['byteplus']['api_key'] == 'byteplus-video-test-key-222'


def test_byteplus_endpoint_or_one_sided_key_is_a_conflict(tmp_path, capsys):
    data = copy.deepcopy(V1)
    del data['video']['ark']['endpoint']  # falls back to the v1 default, which differs
    data['video']['ark']['api_key'] = ''
    code, output = run(capsys, '--config', str(write(tmp_path, data)))
    assert code == 3
    assert 'api.ark.endpoint ≠ video.ark.endpoint' in output and 'api.ark.api_key ≠ video.ark.api_key' in output
    code, _ = run(capsys, '--config', str(tmp_path / 'config.json'), '--byteplus-from', 'image', '--apply')
    assert code == 0
    assert config_v2.load(tmp_path / 'config.json')[0]['providers']['byteplus']['endpoint'] == 'https://ark.fake.invalid'


def test_cupsy_endpoint_conflict_and_unknown_keys_block(tmp_path, capsys):
    data = copy.deepcopy(V1)
    data['audio']['cupsy']['endpoint'] = 'https://cupsy-audio.fake.invalid'
    data['server']['legacy_flag'] = 'fake-secret-777'
    path = write(tmp_path, data)
    code, output = run(capsys, '--config', str(path))
    assert code == 3 and '--cupsy-from' in output and 'server.legacy_flag  [未识别]' in output
    code, output = run(capsys, '--config', str(path), '--cupsy-from', 'audio', '--drop-unknown', '--apply')
    assert code == 0, output
    config = config_v2.load(path)[0]
    assert config['providers']['cupsy']['endpoint'] == 'https://cupsy-audio.fake.invalid'
    assert 'legacy_flag' not in config['server']


def test_non_endpoint_seedance_25_mapping_blocks(tmp_path, capsys):
    data = copy.deepcopy(V1)
    data['video']['ark']['seedance_2_5_model'] = 'dreamina-seedance-2-5-public'
    code, output = run(capsys, '--config', str(write(tmp_path, data)), '--apply')
    assert code == 3 and 'video.ark.seedance_2_5_model' in output
    assert not (tmp_path / 'config.json.pre-v2').exists()


def test_minimal_v1_uses_effective_v1_defaults(tmp_path, capsys):
    path = write(tmp_path, {'api': {'ark': {'api_key': 'byteplus-test-key-111'}}})
    code, output = run(capsys, '--config', str(path))
    # video.ark.api_key was empty in v1 (video unusable); merging enables it, so ask the user.
    assert code == 3 and 'api.ark.api_key ≠ video.ark.api_key' in output
    assert run(capsys, '--config', str(path), '--byteplus-from', 'image', '--apply')[0] == 0
    config = config_v2.load(path)[0]
    assert config['generation']['image']['byteplus']['model'] == 'dola-seedream-5-5-261028'
    assert config['providers']['byteplus']['endpoint_ids']['seedance_2_5'] == 'ep-your-endpoint-id'
    assert config['deployment']['public_base_url'] == ''


def test_public_base_url_keeps_v1_port_semantics():
    def url(**server):
        return migrate._public_base_url(migrate._merge(migrate.V1_DEFAULTS, {'server': server}))
    assert url() == ''
    assert url(public_host='media.fake.invalid') == 'http://media.fake.invalid:5000'
    assert url(public_host='media.fake.invalid', public_port=443, public_scheme='https') == 'https://media.fake.invalid'
    assert url(public_host='media.fake.invalid', public_port=80) == 'http://media.fake.invalid'


def test_invalid_json_reports_position_not_content(tmp_path, capsys):
    path = tmp_path / 'config.json'
    path.write_text('{"api": {"ark": {"api_key": "byteplus-test-key-111",}}}', encoding='utf-8')
    code, output = run(capsys, '--config', str(path))
    assert code == 2 and '不是有效的 JSON' in output


# --- v2 validation and startup ---------------------------------------------------------

def example():
    return json.loads((ROOT / 'config.json.example').read_text(encoding='utf-8'))


def test_example_is_valid_v2_and_matches_defaults():
    config, warnings = config_v2.validate(example())
    expected = copy.deepcopy(config_v2.DEFAULTS)
    expected['providers']['byteplus']['endpoint_ids']['seedance_2_5'] = 'ep-your-endpoint-id'
    assert config == expected  # the example documents exactly the built-in defaults
    assert any('seedance_2_5' in item for item in warnings)


@pytest.mark.parametrize('mutate, expected', [
    (lambda c: c.pop('config_version'), '旧格式 v1'),
    (lambda c: c.update(config_version=1), 'config_version'),
    (lambda c: c.update(api={'ark': {}}), '旧段 api'),
    (lambda c: c.update(openai={}), '旧段 openai'),
    (lambda c: c['providers'].update(google={}), 'providers.google: 未知键'),
    (lambda c: c['server'].update(port='5000'), 'server.port: 必须为整数'),
    (lambda c: c['server'].update(port=70000), 'server.port: 必须在'),
    (lambda c: c['providers']['byteplus'].update(endpoint='ftp://x.invalid'), 'providers.byteplus.endpoint'),
    (lambda c: c['providers']['byteplus']['endpoint_ids'].update(seedance_2_5='public-model'), 'endpoint_ids.seedance_2_5'),
    (lambda c: c['generation']['image'].update(default='google'), 'generation.image.default'),
    (lambda c: c['deployment'].update(public_base_url='https://203.0.113.9/path'), 'deployment.public_base_url'),
    (lambda c: c['deployment']['cupsy_source'].update(auto_configure='true'), 'auto_configure'),
    (lambda c: c['deployment']['cupsy_source'].update(asset_token_ttl_seconds=60), 'asset_token_ttl_seconds'),
])
def test_validation_rejects_with_path_only(mutate, expected):
    data = example()
    data['providers']['byteplus']['api_key'] = 'byteplus-test-key-111'
    mutate(data)
    with pytest.raises(config_v2.ConfigError) as error:
        config_v2.validate(data)
    assert expected in error.value.report()
    assert 'byteplus-test-key-111' not in error.value.report()


def test_load_missing_and_broken_files(tmp_path):
    with pytest.raises(config_v2.ConfigError, match='文件不存在'):
        config_v2.load(tmp_path / 'absent.json')
    broken = tmp_path / 'broken.json'
    broken.write_text('{"providers": {"byteplus": {"api_key": "byteplus-test-key-111"', encoding='utf-8')
    with pytest.raises(config_v2.ConfigError) as error:
        config_v2.load(broken)
    assert 'JSON 解析失败' in error.value.report() and 'byteplus-test-key' not in error.value.report()


def test_app_load_config_exits_on_v1(tmp_path, capsys):
    path = write(tmp_path, V1)
    with pytest.raises(SystemExit) as stopped:
        application.load_config(str(path))
    assert stopped.value.code == 4  # Gunicorn APP_LOAD_ERROR: halt, do not respawn
    err = capsys.readouterr().err
    assert '旧格式 v1' in err and 'migrate-config-v2.py' in err
    assert all(secret not in err for secret in SECRETS)


@pytest.mark.parametrize('content', [None, 'v1', 'invalid'])
def test_server_import_stops_with_clear_error(tmp_path, content):
    if content == 'v1':
        write(tmp_path, V1)
    elif content == 'invalid':
        data = example()
        data['server']['port'] = 'fake-pass-666'
        write(tmp_path, data)
    env = {**os.environ, 'NANOBANANA_CONFIG_FILE': str(tmp_path / 'config.json'),
           'NANOBANANA_DB_PATH': str(tmp_path / 'tasks.db')}
    result = subprocess.run([sys.executable, '-c', 'import app'], cwd=ROOT / 'server', env=env,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 4
    assert 'config.json 无法使用' in result.stderr
    assert all(secret not in result.stdout + result.stderr for secret in SECRETS)


def test_cli_check_and_get(tmp_path):
    tool = [sys.executable, str(ROOT / 'server' / 'config_v2.py')]
    ok = subprocess.run(tool + ['check', str(ROOT / 'config.json.example')], capture_output=True, text=True)
    assert ok.returncode == 0 and 'OK' in ok.stdout
    legacy = subprocess.run(tool + ['check', str(write(tmp_path, V1))], capture_output=True, text=True)
    assert legacy.returncode == 2 and '旧格式 v1' in legacy.stderr
    assert all(secret not in legacy.stdout + legacy.stderr for secret in SECRETS)
    get = subprocess.run(tool + ['get', 'deployment.cupsy_source.auto_configure', str(ROOT / 'config.json.example')],
                         capture_output=True, text=True)
    assert get.stdout.strip() == 'true'
    secret = subprocess.run(tool + ['get', 'providers.byteplus.api_key', str(ROOT / 'config.json.example')],
                            capture_output=True, text=True)
    assert secret.returncode == 2 and secret.stdout == ''


def test_runtime_views_share_one_account_per_provider():
    config, _ = config_v2.validate(example())
    config['providers']['byteplus']['api_key'] = 'byteplus-test-key-111'
    config['providers']['cupsy']['api_key'] = 'cupsy-test-key-333'
    assert config_v2.image_byteplus(config)['api_key'] == config_v2.video_byteplus(config)['api_key'] == 'byteplus-test-key-111'
    assert config_v2.image_cupsy(config)['api_key'] == config_v2.video_cupsy(config)['api_key'] == config_v2.audio_cupsy(config)['api_key']
    assert config_v2.video_byteplus(config)['seedance_2_5_model'] == 'ep-your-endpoint-id'
    assert config_v2.audio_cupsy(config)['source_base_url'] == config_v2.video_cupsy(config)['source_base_url']


def test_layer_model_override_and_inheritance(monkeypatch):
    monkeypatch.setitem(application.API_PROVIDERS, 'ark', {'api_key': 'test', 'model': 'image-model'})
    monkeypatch.setitem(application.config['generation']['layer']['byteplus'], 'model', '')
    assert application.get_layer_provider_config()[1]['model'] == 'image-model'
    monkeypatch.setitem(application.config['generation']['layer']['byteplus'], 'model', 'layer-model')
    assert application.get_layer_provider_config()[1]['model'] == 'layer-model'
