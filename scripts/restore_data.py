"""Restore published data while retaining new frozen model revisions from main."""

import json
import subprocess
from pathlib import Path


def restore(root):
    if subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", "refs/remotes/origin/data"], cwd=root
    ).returncode:
        return False
    models = {
        p.relative_to(root): p.read_bytes() for p in (root / "data/model_registry").rglob("*") if p.is_file()
    }
    report_path = root / "site/data/model_evaluation.json"
    current_report = report_path.read_bytes() if report_path.exists() else None
    subprocess.run(
        ["git", "restore", "--source=origin/data", "--worktree", "--", "data", "site/data"],
        cwd=root,
        check=True,
    )
    for relative, payload in models.items():
        path = root / relative
        if path.exists() and path.read_bytes() != payload:
            raise ValueError(f"Conflicting immutable model artifact: {relative}")
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
    if current_report:
        restored = json.loads(report_path.read_text()) if report_path.exists() else {}
        current = json.loads(current_report)
        if current.get("generated_at", "") > restored.get("generated_at", ""):
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_bytes(current_report)
    return True


if __name__ == "__main__":
    restore(Path.cwd())
