"""Thin wrapper over git for one project repo: fetch, temporary worktrees, diffs, push, worktree cleanup."""
import shutil
import subprocess
from pathlib import Path

from .rules import Change


class GitError(RuntimeError):
    pass


class Git:
    def __init__(self, repo_dir):
        self.dir = Path(repo_dir)
        self.exe = shutil.which("git") or "git"

    def _git(self, *args, cwd=None, check=True):
        p = subprocess.run([self.exe, *args], cwd=str(cwd or self.dir), capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        if check and p.returncode != 0:
            raise GitError(f"git {' '.join(args[:3])}: {p.stderr.strip()}")
        return p.stdout if check else (p.returncode, p.stdout, p.stderr)

    def fetch(self):
        self._git("fetch", "--quiet", "--prune", "origin")

    def show(self, ref, path):
        code, out, _ = self._git("show", f"{ref}:{path}", check=False)
        return out if code == 0 else None

    def merge_base(self, a, b):
        return self._git("merge-base", a, b).strip()

    def diff(self, base, head):
        return self._git("diff", f"{base}..{head}")

    def diff_stat(self, base, head):
        return self._git("diff", "--stat", f"{base}..{head}")

    def remote_head(self, branch):
        out = self._git("ls-remote", "origin", f"refs/heads/{branch}")
        return out.split()[0] if out.strip() else None

    # ---- temporary worktrees (detached, so they never clash with a builder's branch)
    def add_worktree(self, path, ref):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._git("worktree", "add", "--quiet", "--detach", str(path), ref)

    def remove_worktree(self, path):
        self._git("worktree", "remove", "--force", str(path), check=False)
        self._git("worktree", "prune", check=False)

    def head(self, cwd):
        return self._git("rev-parse", "HEAD", cwd=cwd).strip()

    def commits(self, base, cwd):
        return self._git("log", "--oneline", f"{base}..HEAD", cwd=cwd).strip().splitlines()

    def changes(self, base, cwd):
        out = self._git("diff", "--name-status", "--no-renames", f"{base}..HEAD", cwd=cwd)
        return [Change(line.split("\t")[0][0], line.split("\t")[-1]) for line in out.splitlines() if line.strip()]

    def added_lines(self, base, cwd):
        added, current = {}, None
        for line in self._git("diff", "-U0", "--no-renames", f"{base}..HEAD", cwd=cwd).splitlines():
            if line.startswith("+++ "):
                current = line[6:] if line.startswith("+++ b/") else None
            elif line.startswith("+") and current:
                added.setdefault(current, []).append(line[1:])
        return added

    def push(self, cwd, branch):
        """Normal (never forced) push of the worktree's HEAD to the PR branch."""
        code, _, err = self._git("push", "--quiet", "origin", f"HEAD:refs/heads/{branch}", cwd=cwd, check=False)
        return code == 0, err.strip()

    # ---- builder worktrees (ADR 0016)
    def worktrees(self):
        """[{path, head, branch, locked}] from git worktree list --porcelain."""
        items, cur = [], None
        for line in self._git("worktree", "list", "--porcelain").splitlines():
            if line.startswith("worktree "):
                cur = {"path": Path(line[9:]), "head": "", "branch": None, "locked": False}
                items.append(cur)
            elif cur is not None and line.startswith("HEAD "):
                cur["head"] = line[5:]
            elif cur is not None and line.startswith("branch "):
                cur["branch"] = line[7:].removeprefix("refs/heads/")
            elif cur is not None and line.startswith("locked"):
                cur["locked"] = True
        return items

    def has_tracked_changes(self, path):
        return bool(self._git("status", "--porcelain", "--untracked-files=no", cwd=path).strip())

    def remove_builder_worktree(self, path, branch):
        self.remove_worktree(path)
        self._git("branch", "-D", branch, check=False)
