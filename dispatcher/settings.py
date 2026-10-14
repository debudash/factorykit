"""The two settings sources: ~/factory/projects.toml (dispatcher only) and docs/agents/factory.md (per repo)."""
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

AUTO_FIX = ("off", "ci", "ci_and_review")
MERGE_MODES = ("auto-low-risk", "manual")
DEFAULT_REGISTRY = Path.home() / "factory" / "projects.toml"


@dataclass(frozen=True)
class Project:
    name: str
    path: Path
    auto_fix: str = "ci_and_review"
    merge_mode: str = "auto-low-risk"


def load_registry(path):
    """Return (projects, errors). A bad table is skipped with an error, the others still load."""
    path = Path(path)
    if not path.exists():
        return [], [f"{path} not found: run scripts/setup-project first"]
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        return [], [f"{path}: {e}"]
    projects, errors = [], []
    for name, table in raw.items():
        if not isinstance(table, dict) or "path" not in table:
            errors.append(f"[{name}]: missing path")
            continue
        auto_fix = table.get("auto_fix", "ci_and_review")
        merge_mode = table.get("merge_mode", "auto-low-risk")
        if auto_fix not in AUTO_FIX:
            errors.append(f"[{name}]: auto_fix must be one of {', '.join(AUTO_FIX)}")
            continue
        if merge_mode not in MERGE_MODES:
            errors.append(f"[{name}]: merge_mode must be one of {', '.join(MERGE_MODES)}")
            continue
        projects.append(Project(name, Path(table["path"]).expanduser(), auto_fix, merge_mode))
    return projects, errors


@dataclass
class RepoSettings:
    """The settings block of docs/agents/factory.md."""
    risky_paths: list = field(default_factory=lambda: ["**/auth/**", "**/migrations/**", ".github/workflows/**",
                                                       "infra/**", "infrastructure/**", "terraform/**", "**/*.tf"])
    max_parallel: int = 2
    reviewer_model: str = "sonnet"
    verify: dict = field(default_factory=dict)


SETTINGS_BLOCK = re.compile(r"```toml\s*\n(.*?)```", re.S)


def parse_factory_md(text):
    """Settings from factory.md. Missing file or block means defaults; a broken block raises ValueError."""
    if not text:
        return RepoSettings()
    m = SETTINGS_BLOCK.search(text)
    if not m:
        return RepoSettings()
    try:
        raw = tomllib.loads(m.group(1))
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"docs/agents/factory.md settings block: {e}") from e
    s = RepoSettings()
    s.risky_paths = list(raw.get("risky_paths", s.risky_paths))
    s.max_parallel = int(raw.get("max_parallel", s.max_parallel))
    s.reviewer_model = str(raw.get("reviewer_model") or s.reviewer_model)
    s.verify = {k: v for k, v in dict(raw.get("verify", {})).items() if v}
    return s
