from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .util import truncate

# Entries at or past these statuses are excluded from retrieval by default:
# an "obsolete"/"superseded" decision or learning is kept in the file for
# history/audit but must never be handed to an agent as current guidance.
_EXCLUDED_STATUSES = {"obsolete", "superseded"}

# Bounds on what a single retrieval call can return, independent of the
# per-file `limit` (character) truncation applied afterwards. These keep
# retrieval "small and relevant" even against a pathologically large
# knowledge file with hundreds of matching entries.
_MAX_ENTRIES = 8
_GENERAL_FALLBACK_MAX = 3

_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_HEADER_RE = re.compile(r"^##\s+(.*)$", re.MULTILINE)
_ID_TITLE_RE = re.compile(r"^([A-Za-z]+-\d+)\s+(.*)$")
_TAGS_RE = re.compile(r"^\s*tags\s*:\s*(.*)$", re.IGNORECASE | re.MULTILINE)
_STATUS_RE = re.compile(r"^\s*status\s*:\s*(.*)$", re.IGNORECASE | re.MULTILINE)


@dataclass
class KnowledgeEntry:
    """One durable knowledge entry parsed from a DECISIONS.md/LEARNINGS.md file.

    `structured` distinguishes an entry that carried real `Tags:`/`Status:`
    metadata (retrieval matches on tags only) from a legacy flat bullet with
    none (retrieval falls back to a body substring match for backward
    compatibility with pre-existing project knowledge files).
    """

    text: str
    id: str | None = None
    title: str = ""
    tags: list[str] = field(default_factory=list)
    status: str = "active"
    structured: bool = False
    # Content used for duplicate detection: the full entry text minus its
    # `## ID Title` header line, so two entries with different IDs/titles
    # but byte-identical bodies still dedupe (matches `text` for flat
    # entries, which have no separate header line).
    body: str = ""


def parse_knowledge_entries(text: str) -> list[KnowledgeEntry]:
    """Parse a knowledge file into entries, degrading safely on malformed input.

    Two conventions are supported: the structured `## ID Title` / `Tags:` /
    `Status:` convention (see `.ai/DECISIONS.md`), and legacy flat `- ` bullet
    lists with no `##` headers at all (see historical `.ai/LEARNINGS.md`
    files). HTML comments are stripped first so template example blocks
    (wrapped in `<!-- ... -->`) never surface as real entries.
    """
    stripped = _COMMENT_RE.sub("", text)
    if _HEADER_RE.search(stripped):
        return _parse_structured(stripped)
    return _parse_flat(stripped)


def _parse_structured(text: str) -> list[KnowledgeEntry]:
    chunks = re.split(r"(?=^##\s+)", text, flags=re.MULTILINE)
    entries = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        header_match = _HEADER_RE.match(chunk)
        if not header_match:
            continue
        header = header_match.group(1).strip()
        id_title_match = _ID_TITLE_RE.match(header)
        entry_id = id_title_match.group(1) if id_title_match else None
        title = id_title_match.group(2).strip() if id_title_match else header
        tags_match = _TAGS_RE.search(chunk)
        status_match = _STATUS_RE.search(chunk)
        tags = (
            [t.strip().lower() for t in tags_match.group(1).split(",") if t.strip()]
            if tags_match
            else []
        )
        status = status_match.group(1).strip().lower() if status_match else "active"
        entries.append(
            KnowledgeEntry(
                text=chunk,
                id=entry_id,
                title=title,
                tags=tags,
                status=status or "active",
                structured=bool(tags_match or status_match),
                body=chunk[header_match.end():].strip(),
            )
        )
    return entries


def _parse_flat(text: str) -> list[KnowledgeEntry]:
    bullets = re.split(r"(?=^- )", text, flags=re.MULTILINE)
    entries = []
    for bullet in bullets:
        bullet = bullet.strip()
        if not bullet.startswith("- "):
            continue
        entries.append(KnowledgeEntry(text=bullet, structured=False, body=bullet))
    return entries


def select_relevant_entries(
    text: str,
    scopes: list[str],
    *,
    limit: int = 7000,
    max_entries: int = _MAX_ENTRIES,
    general_fallback_max: int = _GENERAL_FALLBACK_MAX,
) -> str:
    """Select bounded, relevant knowledge entries for the given task scopes.

    Structured entries match by tag/scope intersection only (no body
    substring matching once metadata exists); unstructured legacy entries
    fall back to a body substring match against the scopes. Obsolete/
    superseded entries are always excluded. If nothing matches and
    "general" is one of the scopes, a bounded set of the first active
    entries is returned instead of nothing.
    """
    entries = parse_knowledge_entries(text)
    needles = [s.lower() for s in scopes]

    seen_ids: set[str] = set()
    seen_bodies: set[str] = set()
    active: list[KnowledgeEntry] = []
    for entry in entries:
        if entry.status in _EXCLUDED_STATUSES:
            continue
        if entry.id and entry.id.lower() in seen_ids:
            continue
        if entry.body in seen_bodies:
            continue
        if entry.id:
            seen_ids.add(entry.id.lower())
        seen_bodies.add(entry.body)
        active.append(entry)

    matched = []
    for entry in active:
        if entry.structured:
            if set(entry.tags) & set(needles):
                matched.append(entry)
        else:
            if any(n in entry.text.lower() for n in needles):
                matched.append(entry)

    if not matched and "general" in needles:
        matched = active[:general_fallback_max]

    matched = matched[:max_entries]
    return truncate("\n\n".join(e.text for e in matched), limit)


def infer_project_summary(repo: Path) -> str:
    stack: list[str] = []
    build: list[str] = []
    if (repo / "package.json").exists():
        stack.append("Node.js / JavaScript or TypeScript")
        try:
            pkg = json.loads((repo / "package.json").read_text(encoding="utf-8"))
            scripts = pkg.get("scripts", {})
            if scripts:
                build.append("package.json scripts: " + ", ".join(sorted(scripts)[:12]))
        except Exception:
            pass
    if (repo / "pyproject.toml").exists():
        stack.append("Python (pyproject.toml)")
    if (repo / "Cargo.toml").exists():
        stack.append("Rust / Cargo")
    if (repo / "go.mod").exists():
        stack.append("Go modules")
    if (repo / "pom.xml").exists():
        stack.append("Java / Maven")
    if (repo / "gradlew").exists() or (repo / "build.gradle").exists() or (repo / "build.gradle.kts").exists():
        stack.append("Gradle")
    top_dirs = sorted(p.name for p in repo.iterdir() if p.is_dir() and not p.name.startswith(".") and p.name not in {"node_modules", "vendor", "venv", ".venv"})[:16]
    ci = "GitHub Actions present" if (repo / ".github" / "workflows").exists() else "No GitHub Actions directory detected at initialization"
    return (
        "# Project\n\n"
        "## Purpose\n"
        "To be refined from repository evidence when durable project context is learned.\n\n"
        "## Stack\n"
        + ("\n".join(f"- {x}" for x in stack) if stack else "- Not inferred from top-level manifests")
        + "\n\n## Architecture\n"
        + ("Top-level directories: " + ", ".join(top_dirs) if top_dirs else "No non-hidden top-level directories detected")
        + "\n\n## Testing and Build\n"
        + ("\n".join(f"- {x}" for x in build) if build else "- Use project configuration/autodetection until refined")
        + f"\n- {ci}\n\n## Constraints\n- Add only durable, non-obvious constraints here.\n"
    )


def init_project_knowledge(repo: Path, *, main_branch: str = "main", agent: str = "codex",
                           auto_merge: bool = True, merge_method: str = "squash") -> None:
    ai = repo / ".ai"
    ai.mkdir(exist_ok=True)
    defaults = {
        "PROJECT.md": infer_project_summary(repo),
        "DECISIONS.md": "# Decisions\n\n<!-- Active decisions only are retrieved by default. -->\n",
        "LEARNINGS.md": "# Project Learnings\n\n<!-- Store only reusable future-facing knowledge. -->\n",
        "config.yml": (
            f"main_branch: {main_branch}\nagent: {agent}\n\n"
            f"git:\n  auto_merge: {'true' if auto_merge else 'false'}\n  merge_method: {merge_method}\n\n"
            "quality:\n  commands: {}\n\nsecurity:\n  commands: {}\n"
        ),
    }
    for name, content in defaults.items():
        p = ai / name
        if not p.exists():
            p.write_text(content, encoding="utf-8")
