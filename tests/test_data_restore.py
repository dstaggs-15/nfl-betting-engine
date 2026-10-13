import runpy
import subprocess
from pathlib import Path


def test_restore_keeps_new_frozen_revision(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()

    def git(*args):
        return subprocess.check_output(
            ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", *args], cwd=root
        )

    git("init", "--quiet")
    old = root / "data/model_registry/week-06-r2.json"
    old.parent.mkdir(parents=True)
    old.write_text('{"version":2}')
    current = root / "site/data/status.json"
    current.parent.mkdir(parents=True)
    current.write_text('{"old":true}')
    git("add", ".")
    git("commit", "--quiet", "-m", "published data")
    git("update-ref", "refs/remotes/origin/data", git("rev-parse", "HEAD").decode().strip())
    new = old.with_name("week-06-r3.json")
    new.write_text('{"version":3}')
    current.write_text('{"new":true}')
    binary = old.with_name("week-06-distribution.joblib")
    binary.write_bytes(b"frozen fitted weights")
    report = current.with_name("model_evaluation.json")
    report.write_text('{"generated_at":"2026-10-13","version":"fitted-v2"}')
    git("add", ".")
    git("commit", "--quiet", "-m", "new code model")
    restore = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/restore_data.py"))["restore"]
    assert restore(root)
    assert binary.read_bytes() == b"frozen fitted weights"
    assert "fitted-v2" in report.read_text()
    assert new.read_text() == '{"version":3}'
    assert old.read_text() == '{"version":2}'
    assert current.read_text() == '{"old":true}'
