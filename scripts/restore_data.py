"""Restore published data while retaining new frozen model revisions from main."""

import subprocess
from pathlib import Path


def restore(root):
    if subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", "refs/remotes/origin/data"], cwd=root
    ).returncode:
        return False
    models = {p.relative_to(root): p.read_bytes() for p in (root / "data/model_registry").rglob("*.json")}
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
    return True


if __name__ == "__main__":
    restore(Path.cwd())
