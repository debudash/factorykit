"""The one adapter between the dispatcher and an agent CLI (design section 16), plus process handles.

Only build_agent_command knows Claude Code's flags. Adding Cursor or Codex later means another
branch here, nothing else.
"""
import json
import shlex
import shutil
import subprocess
import time
from pathlib import Path

PROMPTS = Path(__file__).resolve().parent / "prompts"
STDIN_PROMPT = "Your full instructions are on standard input. Follow them."

READ_ONLY_GIT = ["Bash(git diff *)", "Bash(git log *)", "Bash(git show *)", "Bash(git merge-base *)",
                 "Bash(git status *)", "Bash(git rev-parse *)"]
COMMIT_GIT = ["Bash(git add *)", "Bash(git commit *)"]
NEVER = ["Bash(git push *)", "Bash(gh *)", "Bash(git reset *)", "Bash(git checkout *)", "Bash(git switch *)",
         "Bash(git rebase *)", "Bash(git worktree *)"]


def verify_rules(verify):
    """Allow the project's verify commands, by their first word (e.g. 'python -m unittest' -> Bash(python *))."""
    words = sorted({shlex.split(cmd)[0] for cmd in verify.values() if cmd.strip()})
    return [f"Bash({w} *)" for w in words]


def build_agent_command(role, *, model="", verify=None, harness="claude"):
    """Command for a headless agent run. The prompt itself is sent on stdin.

    role "reviewer": the reviewer agent definition, read-only tools.
    role "fixer": edits and commits only; the dispatcher inspects and pushes.
    """
    if harness != "claude":
        raise ValueError(f"no adapter for {harness}")
    exe = shutil.which("claude") or "claude"
    cmd = [exe, "-p", STDIN_PROMPT, "--output-format", "json", "--permission-mode", "dontAsk"]
    if model:
        cmd += ["--model", model]
    allowed_verify = verify_rules(verify or {})
    if role == "reviewer":
        cmd += ["--agent", "reviewer",
                "--allowedTools", " ".join(["Read", "Grep", "Glob", "Skill", "Agent", *READ_ONLY_GIT, *allowed_verify]),
                "--disallowedTools", " ".join(["Edit", "Write", "NotebookEdit", *COMMIT_GIT, *NEVER])]
    elif role == "fixer":
        # A file, not inline text: on Windows claude is a .cmd shim, and cmd.exe would cut the
        # command line at characters like | and & inside the rules.
        cmd += ["--append-system-prompt-file", str(PROMPTS / "fix-rules.md"),
                "--allowedTools", " ".join(["Read", "Edit", "Write", "Grep", "Glob", "Skill",
                                            *READ_ONLY_GIT, *COMMIT_GIT, *allowed_verify]),
                "--disallowedTools", " ".join(NEVER)]
    else:
        raise ValueError(f"unknown role {role}")
    return cmd


def parse_agent_output(text):
    """(result text, cost in USD or None, failed?) from Claude Code's --output-format json."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return "", None, True
    cost = data.get("total_cost_usd")
    return str(data.get("result") or ""), cost if isinstance(cost, (int, float)) else None, bool(data.get("is_error"))


class ProcessHandle:
    def __init__(self, proc, files):
        self.proc, self.files = proc, files

    def poll(self):
        rc = self.proc.poll()
        if rc is not None:
            for f in self.files:
                f.close()
        return rc

    def terminate(self):
        self.proc.terminate()


class DetachedHandle:
    """A run started by an earlier dispatcher process: done when its JSON output is complete."""

    def __init__(self, out_path, started, max_seconds, clock=time.time):
        self.out_path, self.started, self.max_seconds, self.clock = Path(out_path), started, max_seconds, clock

    def poll(self):
        try:
            json.loads(self.out_path.read_text(encoding="utf-8"))
            return 0
        except (OSError, ValueError):
            return -1 if self.clock() - self.started > self.max_seconds else None

    def terminate(self):
        pass  # not our child process; the timeout escalates instead


class ProcessSpawner:
    def spawn(self, cmd, cwd, prompt_path, out_path, err_path):
        stdin = open(prompt_path, encoding="utf-8")
        out = open(out_path, "w", encoding="utf-8")
        err = open(err_path, "w", encoding="utf-8")
        proc = subprocess.Popen(cmd, cwd=cwd, stdin=stdin, stdout=out, stderr=err, text=True, encoding="utf-8")
        return ProcessHandle(proc, [stdin, out, err])
