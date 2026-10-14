"""Pure decision rules: fix guards, merge verdict, trace check, review result. No I/O here."""
import re
from dataclasses import dataclass
from pathlib import PurePosixPath

LOW_RISK_MAX_LINES = 400  # "fewer than about 400 changed lines" (design section 12)

TEST_FILE = re.compile(
    r"(^|/)(tests?|__tests__|specs?)/"      # a tests folder
    r"|(^|/)test_[^/]+$"                     # test_x.py
    r"|_test\.[^/]+$"                        # x_test.go
    r"|\.(test|spec)\.[^/]+$"                # x.test.ts, x.spec.js
    r"|(^|/)[^/]*Tests?\.cs$"                # XTests.cs
)
SKIP_MARKER = re.compile(
    r"\.skip\s*\("                           # it.skip(, describe.skip(, test.skip(
    r"|\bx(it|describe|test)\s*\("           # xit(, xdescribe(, xtest(
    r"|@pytest\.mark\.(skip|skipif|xfail)\b"
    r"|@unittest\.skip"
    r"|\bpytest\.skip\s*\("
    r"|\bskipTest\s*\("
    r"|\bt\.Skip(Now|f)?\s*\("               # Go
    r"|@Disabled\b|@Ignore\b"                # JUnit
    r"|\[Ignore\]|\[Fact\s*\(\s*Skip\s*="    # NUnit, xUnit
)
CI_CONFIG = re.compile(
    r"^(\.github/workflows/|\.github/actions/|\.circleci/|\.buildkite/|\.gitlab/ci/)"
    r"|^(\.gitlab-ci\.yml|azure-pipelines\.ya?ml|Jenkinsfile|\.travis\.yml|bitbucket-pipelines\.yml|cloudbuild\.ya?ml)$"
)
MANIFESTS = {
    "package.json", "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb",
    "requirements.txt", "pyproject.toml", "Pipfile", "Pipfile.lock", "poetry.lock", "uv.lock", "setup.py", "setup.cfg",
    "go.mod", "go.sum", "Cargo.toml", "Cargo.lock", "Gemfile", "Gemfile.lock",
    "pom.xml", "build.gradle", "build.gradle.kts", "composer.json", "composer.lock",
    "packages.config", "Directory.Packages.props", "mix.exs", "mix.lock", "pubspec.yaml", "pubspec.lock",
}
MANIFEST_PATTERN = re.compile(r"(^|/)requirements[^/]*\.txt$|\.(csproj|fsproj|vbproj)$")


# ---------------------------------------------------------------- paths

def glob_to_regex(pattern):
    """gitignore-style glob: ** spans folders, * and ? stay inside one folder."""
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            out, i = out + ".*", i + 2
        elif pattern[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif pattern[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return re.compile(out + "$")


def matches(path, pattern):
    """A pattern without a slash also matches the file name anywhere, like .gitignore."""
    if "/" not in pattern.rstrip("/"):
        return bool(glob_to_regex(pattern).match(PurePosixPath(path).name)) or bool(glob_to_regex(pattern).match(path))
    return bool(glob_to_regex(pattern.lstrip("/")).match(path))


def risky_hits(paths, risky_paths):
    return sorted({p for p in paths for pat in risky_paths if matches(p, pat)})


def is_manifest(path):
    return PurePosixPath(path).name in MANIFESTS or bool(MANIFEST_PATTERN.search(path))


# ---------------------------------------------------------------- fix guards (design section 11)

@dataclass
class Change:
    status: str  # A, M, D, R (renames are reported as D of the old path plus A of the new)
    path: str


@dataclass
class GuardResult:
    name: str
    ok: bool
    detail: str = ""


def check_fix(changes, added_lines, risky_paths):
    """Guards a fix diff must pass before the dispatcher pushes it.

    changes: list of Change; added_lines: {path: [added line, ...]}.
    """
    paths = [c.path for c in changes]
    deleted_tests = [c.path for c in changes if c.status == "D" and TEST_FILE.search(c.path)]
    skips = [f"{p}: {line.strip()[:80]}" for p, lines in sorted(added_lines.items())
             for line in lines if SKIP_MARKER.search(line)]
    ci = [p for p in paths if CI_CONFIG.search(p)]
    risky = risky_hits(paths, risky_paths)
    manifests = [p for p in paths if is_manifest(p)]
    return [
        GuardResult("no deleted tests", not deleted_tests, ", ".join(deleted_tests)),
        GuardResult("no skip markers", not skips, "; ".join(skips)),
        GuardResult("no CI config changes", not ci, ", ".join(ci)),
        GuardResult("no risky paths", not risky, ", ".join(risky)),
        GuardResult("no dependency manifest changes", not manifests, ", ".join(manifests)),
    ]


def guards_passed(results):
    return all(r.ok for r in results)


def guard_table(results):
    rows = ["| Guard | Result |", "|---|---|"]
    rows += [f"| {r.name} | {'pass' if r.ok else 'FAIL: ' + r.detail} |" for r in results]
    return "\n".join(rows)


# ---------------------------------------------------------------- merge verdict (design section 12)

@dataclass
class Verdict:
    auto_merge: bool
    message: str


def merge_verdict(changed_lines, paths, risky_paths, merge_mode):
    """Called only when CI is green, the review passed and there is no needs-decision label."""
    risky = risky_hits(paths, risky_paths)
    manifests = [p for p in paths if is_manifest(p)]
    reasons = []
    if merge_mode != "auto-low-risk":
        reasons.append("merge_mode is manual")
    if changed_lines >= LOW_RISK_MAX_LINES:
        reasons.append(f"{changed_lines} changed lines ({LOW_RISK_MAX_LINES} or more)")
    if manifests:
        reasons.append("changes dependency manifest " + ", ".join(manifests))
    if risky:
        reasons.append("touches " + ", ".join(risky))
    if reasons:
        return Verdict(False, "Held for you: " + "; ".join(reasons))
    return Verdict(True, f"Auto-merge: low risk ({changed_lines} lines, no risky paths)")


# ---------------------------------------------------------------- PR record checks

CLOSES = re.compile(r"(?im)^\s*(closes|fixes|resolves)\s+#(\d+)\b")
TRACE = re.compile(r"(?m)^\s*Trace:\s*\S")
SPEC_REF = re.compile(r"(?i)spec\s+#(\d+)")
DOCS_PR_REF = re.compile(r"(?i)docs PR\s+#(\d+)")


def trace_problems(body):
    body = body or ""
    problems = []
    if not CLOSES.search(body):
        problems.append("`Closes #N`")
    if not TRACE.search(body):
        problems.append("the `Trace:` line")
    return problems


def linked_numbers(body):
    """Ticket, spec and docs PR numbers from the PR description (None when absent)."""
    body = body or ""
    first = lambda rx: int(m.group(m.lastindex)) if (m := rx.search(body)) else None
    return {"ticket": first(CLOSES), "spec": first(SPEC_REF), "docs_pr": first(DOCS_PR_REF)}


REVIEW_RESULT = re.compile(r"(?m)^\s*REVIEW_RESULT:\s*blocking\s*=\s*(\d+)\s*$")


def parse_review_result(text):
    """Number of blocking findings from the reviewer's last REVIEW_RESULT line, or None."""
    found = REVIEW_RESULT.findall(text or "")
    return int(found[-1]) if found else None


def needs_decision_questions(text):
    return [line.split("NEEDS_DECISION:", 1)[1].strip() for line in (text or "").splitlines()
            if "NEEDS_DECISION:" in line]
