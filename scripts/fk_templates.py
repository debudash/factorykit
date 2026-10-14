"""Render FactoryKit templates: replace {{name}} placeholders, refuse to leave any unfilled."""
import re
from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")

DEFAULT_RISKY_PATHS = [
    "**/auth/**",
    "**/migrations/**",
    ".github/workflows/**",
    ".gitlab-ci.yml",
    "infra/**",
    "infrastructure/**",
    "terraform/**",
    "**/*.tf",
]

# Placeholder values used by tests and dry runs.
SAMPLE_VALUES = {
    "project_name": "notify-service",
    "project_summary": "Sends email and SMS notifications for the shop.",
    "owner": "debudash",
    "test_cmd": "python -m unittest discover -s tests",
    "typecheck_cmd": "",
    "lint_cmd": "ruff check .",
    "build_cmd": "",
    "max_parallel": "2",
    "reviewer_model": "sonnet",
    "ticket_number": "42",
    "ticket_title": "Add retry to SMS sender",
    "spec_number": "30",
    "spec_title": "Reliable notifications",
    "docs_pr_number": "31",
    "date": "2026-10-14",
    "what_changed": "- Retries failed SMS sends up to 3 times.",
    "verification": "- `python -m unittest discover -s tests`: 14 passed",
    "review_notes": "- None.",
}


def placeholders(text):
    return set(PLACEHOLDER.findall(text))


def render(text, values):
    missing = placeholders(text) - values.keys()
    if missing:
        raise KeyError(f"missing values for placeholders: {', '.join(sorted(missing))}")
    return PLACEHOLDER.sub(lambda m: str(values[m.group(1)]), text)


def render_file(name, values):
    return render((TEMPLATES_DIR / name).read_text(encoding="utf-8"), values)


def toml_escape(value):
    """Escape a value for use inside a double-quoted TOML string."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def toml_array(items):
    return "[" + ", ".join(f'"{toml_escape(i)}"' for i in items) + "]"


def factory_values(values):
    """Values for templates/factory.md: TOML-escape strings, format risky_paths as an array."""
    out = dict(values)
    for key in ("test_cmd", "typecheck_cmd", "lint_cmd", "build_cmd", "reviewer_model"):
        out[key] = toml_escape(values[key])
    out["risky_paths"] = toml_array(values.get("risky_paths_list", DEFAULT_RISKY_PATHS))
    return out
