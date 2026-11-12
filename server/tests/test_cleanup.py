"""Ensure the cleanup command cannot erase runtime assets or follow cache symlinks."""
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def test_cleanup_is_rooted_and_preserves_runtime_data(tmp_path):
    project = tmp_path / 'project'
    project.mkdir()
    shutil.copy2(ROOT / 'clean.sh', project / 'clean.sh')
    caches = ['.pytest_cache', 'client/test-results', 'client/playwright-report',
              'server/__pycache__', 'server/tests/__pycache__', 'deploy/__pycache__']
    kept = ['config.json', 'config.pre-deploy.json', 'tasks.db', 'tasks.db-wal',
            'tasks.db-shm', 'server.log', '.flask_secret_key', 'server/prompts.json',
            'output/result.png', 'workspace_assets/reference.png', 'upload_video/ref.mp4',
            'error_logs/error.json', 'client/dist/index.html',
            'node_modules/dep/index.js', 'server/uploads/__pycache__/keep',
            'server/node_modules/dep/__pycache__/keep']
    for relative in kept + [name + '/cache' for name in caches]:
        target = project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('sentinel')
    subprocess.run(['bash', str(project / 'clean.sh'), '--dry-run'], cwd=tmp_path, check=True)
    assert all((project / name / 'cache').exists() for name in caches)
    subprocess.run(['bash', str(project / 'clean.sh')], cwd=tmp_path, check=True)
    assert all(not (project / name).exists() for name in caches)
    assert all((project / name).read_text() == 'sentinel' for name in kept)


def test_cleanup_skips_symlinks_and_rejects_unknown_flags(tmp_path):
    project = tmp_path / 'project'
    outside = tmp_path / 'outside'
    project.mkdir()
    outside.mkdir()
    (outside / 'test-results').mkdir()
    (outside / 'test-results' / 'keep').write_text('sentinel')
    shutil.copy2(ROOT / 'clean.sh', project / 'clean.sh')
    (project / 'client').symlink_to(outside, target_is_directory=True)
    (project / '.pytest_cache').symlink_to(outside, target_is_directory=True)
    (project / 'server').symlink_to(outside, target_is_directory=True)
    subprocess.run(['bash', str(project / 'clean.sh')], cwd=tmp_path, check=True)
    assert (outside / 'test-results' / 'keep').read_text() == 'sentinel'
    assert (project / '.pytest_cache').is_symlink()
    assert subprocess.run(['bash', str(project / 'clean.sh'), '--all'], cwd=tmp_path).returncode == 2
