import subprocess
from pathlib import Path
from typing import List, Optional


class GitError(RuntimeError):
    pass


def git_checked(root: Path, *args: str, timeout: int = 30) -> str:
    """Run git as an argv list. Never uses a shell, and never swallows failures."""
    root = Path(root)
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        shell=False,
    )
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "git command failed").strip()
        raise GitError(message)
    return (completed.stdout or "").strip()


def git(root: Path, *args: str, timeout: int = 10) -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return None


def git_at_root(root: Path, *args: str, timeout: int = 10) -> Optional[str]:
    root = Path(root).resolve()
    toplevel = git(root, "rev-parse", "--show-toplevel", timeout=timeout)
    if not toplevel:
        return None
    try:
        if Path(toplevel).resolve() != root:
            return None
    except OSError:
        return None
    return git(root, *args, timeout=timeout)


def recent_commits(root: Path, days: int = 7, limit: int = 100) -> List[str]:
    value = git_at_root(root, "log", "--format=%h %s", "--since={} days ago".format(days), "-n", str(limit))
    return value.splitlines() if value else []
