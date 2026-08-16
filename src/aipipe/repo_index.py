from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .util import run, truncate

# Bounds keep the index cheap to build, cheap to store, and cheap to inline
# into an agent prompt regardless of repository size.
MAX_TRACKED_FILES = 500
MAX_TEST_LOCATIONS = 100
MAX_SYMBOL_FILES = 40
MAX_SYMBOLS_PER_FILE = 20
MAX_SYMBOL_FILE_BYTES = 200_000
RENDER_LIMIT = 6000
GIT_TIMEOUT_SECONDS = 30

# Directories that are generated, vendored, or otherwise not part of the
# reviewable source tree, regardless of what a particular git history has
# tracked. Matched by exact path-component name at any depth.
EXCLUDED_DIR_NAMES = {
    ".git", ".hg", ".svn",
    "node_modules", "bower_components", "vendor",
    ".venv", "venv", "env", "__pycache__", ".mypy_cache", ".pytest_cache",
    ".tox", "site-packages", "egg-info",
    "dist", "build", "out", "target", ".next", ".nuxt", ".output",
    ".cache", "coverage", ".nyc_output",
    ".idea", ".vscode",
}

# Manifest basename -> language label. Order is insertion order, used only
# to keep the rendered "languages" line deterministic.
LANGUAGE_MANIFESTS: dict[str, str] = {
    "pyproject.toml": "python",
    "setup.py": "python",
    "setup.cfg": "python",
    "requirements.txt": "python",
    "Pipfile": "python",
    "package.json": "node",
    "go.mod": "go",
    "Cargo.toml": "rust",
    "pom.xml": "java",
    "build.gradle": "java",
    "build.gradle.kts": "java",
    "Gemfile": "ruby",
    "composer.json": "php",
}

_TEST_DIR_NAMES = {"tests", "test", "__tests__", "spec"}
_TEST_FILE_RE = re.compile(
    r"(^|/)(test_[^/]+\.py|[^/]+_test\.py|[^/]+\.(test|spec)\.[jt]sx?)$"
)

_SYMBOL_PATTERNS: dict[str, re.Pattern] = {
    ".py": re.compile(r"^(?:async\s+)?def\s+(\w+)|^class\s+(\w+)", re.MULTILINE),
    ".js": re.compile(
        r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(\w+)"
        r"|^(?:export\s+)?class\s+(\w+)"
        r"|^export\s+const\s+(\w+)\s*=",
        re.MULTILINE,
    ),
}
_SYMBOL_PATTERNS[".jsx"] = _SYMBOL_PATTERNS[".js"]
_SYMBOL_PATTERNS[".ts"] = _SYMBOL_PATTERNS[".js"]
_SYMBOL_PATTERNS[".tsx"] = _SYMBOL_PATTERNS[".js"]


@dataclass
class RepoIndex:
    commit_sha: str
    tracked_file_count: int
    tracked_files: list[str]
    tracked_files_truncated: bool
    languages: list[str]
    manifests: list[str]
    test_locations: list[str]
    test_locations_truncated: bool
    symbols: dict[str, list[str]] = field(default_factory=dict)
    symbols_truncated: bool = False

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, text: str) -> "RepoIndex":
        return cls(**json.loads(text))


def _excluded(rel_path: str) -> bool:
    return any(part in EXCLUDED_DIR_NAMES for part in Path(rel_path).parts[:-1])


def _is_test_location(rel_path: str) -> bool:
    parts = Path(rel_path).parts[:-1]
    if any(part in _TEST_DIR_NAMES for part in parts):
        return True
    return bool(_TEST_FILE_RE.search(rel_path))


def _extract_symbols(path: Path) -> list[str]:
    pattern = _SYMBOL_PATTERNS.get(path.suffix)
    if pattern is None:
        return []
    try:
        if path.stat().st_size > MAX_SYMBOL_FILE_BYTES:
            return []
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    names: list[str] = []
    for match in pattern.finditer(text):
        name = next((g for g in match.groups() if g), None)
        if name and name not in names:
            names.append(name)
        if len(names) >= MAX_SYMBOLS_PER_FILE:
            break
    return names


def build_repo_index(repo: Path, commit_sha: str, timeout: int = GIT_TIMEOUT_SECONDS) -> RepoIndex:
    """Deterministically summarize tracked repository structure.

    No LLM calls and no network access: git plumbing, filesystem metadata,
    and bounded regex-based symbol extraction only. Callers that need safe
    degradation on failure should use ``RepoIndexCache.get_or_build``
    instead of calling this directly.
    """

    result = run(["git", "ls-files"], repo, timeout)
    if not result.ok:
        raise RuntimeError(result.stderr or "git ls-files failed")

    all_files = [line for line in result.stdout.splitlines() if line.strip()]
    all_files.sort()

    included = [f for f in all_files if not _excluded(f)]

    tracked_files = included[:MAX_TRACKED_FILES]
    tracked_files_truncated = len(included) > MAX_TRACKED_FILES

    manifests = sorted({f for f in included if Path(f).name in LANGUAGE_MANIFESTS})
    languages = sorted({LANGUAGE_MANIFESTS[Path(f).name] for f in manifests})

    test_candidates = [f for f in included if _is_test_location(f)]
    test_locations = test_candidates[:MAX_TEST_LOCATIONS]
    test_locations_truncated = len(test_candidates) > MAX_TEST_LOCATIONS

    symbol_candidates = [f for f in included if Path(f).suffix in _SYMBOL_PATTERNS]
    symbols_truncated = len(symbol_candidates) > MAX_SYMBOL_FILES
    symbols: dict[str, list[str]] = {}
    for rel_path in symbol_candidates[:MAX_SYMBOL_FILES]:
        names = _extract_symbols(repo / rel_path)
        if names:
            symbols[rel_path] = names

    return RepoIndex(
        commit_sha=commit_sha,
        tracked_file_count=len(included),
        tracked_files=tracked_files,
        tracked_files_truncated=tracked_files_truncated,
        languages=languages,
        manifests=manifests,
        test_locations=test_locations,
        test_locations_truncated=test_locations_truncated,
        symbols=symbols,
        symbols_truncated=symbols_truncated,
    )


def render_repo_index(index: RepoIndex, limit: int = RENDER_LIMIT) -> str:
    lines = [f"Commit: {index.commit_sha}"]
    lines.append(f"Tracked files: {index.tracked_file_count}" + (" (truncated)" if index.tracked_files_truncated else ""))
    if index.languages:
        lines.append("Languages: " + ", ".join(index.languages))
    if index.manifests:
        lines.append("Manifests: " + ", ".join(index.manifests))
    if index.test_locations:
        suffix = " (truncated)" if index.test_locations_truncated else ""
        lines.append(f"Test locations{suffix}:")
        lines.extend(f"  - {t}" for t in index.test_locations)
    if index.symbols:
        suffix = " (truncated)" if index.symbols_truncated else ""
        lines.append(f"Key symbols{suffix}:")
        for path, names in index.symbols.items():
            lines.append(f"  - {path}: " + ", ".join(names))
    return truncate("\n".join(lines), limit)


class RepoIndexCache:
    """Bounded, disk-backed cache of ``RepoIndex`` keyed by repo identity + base commit SHA.

    Any failure (missing git binary, unreadable files, a non-worktree path,
    a full disk, ...) is swallowed and reported as a cache miss so that a
    repository index is always an optional convenience, never something a
    task can be blocked on.
    """

    def __init__(self, cache_root: Path, timeout: int = GIT_TIMEOUT_SECONDS):
        self.cache_root = cache_root
        self.timeout = timeout
        self._memory: dict[tuple[str, str], RepoIndex] = {}

    def _repo_identity(self, repo: Path) -> str:
        result = run(["git", "rev-parse", "--git-common-dir"], repo, self.timeout)
        if not result.ok:
            raise RuntimeError(result.stderr or "git rev-parse --git-common-dir failed")
        raw = result.stdout.strip()
        common_dir = Path(raw)
        if not common_dir.is_absolute():
            common_dir = (repo / common_dir).resolve()
        return str(common_dir)

    def _commit_sha(self, repo: Path) -> str:
        result = run(["git", "rev-parse", "HEAD"], repo, self.timeout)
        if not result.ok:
            raise RuntimeError(result.stderr or "git rev-parse HEAD failed")
        return result.stdout.strip()

    def _cache_file(self, identity: str, commit_sha: str) -> Path:
        repo_key = hashlib.sha256(identity.encode()).hexdigest()[:16]
        return self.cache_root / repo_key / f"{commit_sha}.json"

    def get_or_build(self, repo: Path) -> RepoIndex | None:
        try:
            identity = self._repo_identity(repo)
            commit_sha = self._commit_sha(repo)
            key = (identity, commit_sha)
            cached = self._memory.get(key)
            if cached is not None:
                return cached

            cache_file = self._cache_file(identity, commit_sha)
            if cache_file.is_file():
                try:
                    index = RepoIndex.from_json(cache_file.read_text(encoding="utf-8"))
                    self._memory[key] = index
                    return index
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    pass  # fall through and rebuild

            index = build_repo_index(repo, commit_sha, self.timeout)
            self._memory[key] = index
            try:
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(index.to_json(), encoding="utf-8")
            except OSError:
                pass  # in-memory cache still succeeded; disk persistence is best-effort
            return index
        except Exception:
            return None
