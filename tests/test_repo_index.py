from pathlib import Path
from unittest.mock import patch

import aipipe.repo_index as repo_index_module
from aipipe.repo_index import (
    MAX_TRACKED_FILES,
    RepoIndexCache,
    build_repo_index,
    render_repo_index,
)
from aipipe.util import run


def git(cwd: Path, *args: str):
    r = run(["git", *args], cwd)
    assert r.ok, r.stderr
    return r


def _init_repo(tmp_path: Path, name: str = "repo") -> Path:
    repo = tmp_path / name
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    return repo


def _commit_all(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return run(["git", "rev-parse", "HEAD"], repo).stdout.strip()


def _write(repo: Path, rel_path: str, content: str) -> None:
    path = repo / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_python_repo_detects_language_manifest_tests_and_symbols(tmp_path: Path):
    repo = _init_repo(tmp_path)
    _write(repo, "pyproject.toml", "[project]\nname='x'\n")
    _write(repo, "src/pkg/core.py", "class Widget:\n    pass\n\n\ndef build():\n    return Widget()\n")
    _write(repo, "tests/test_core.py", "def test_build():\n    assert True\n")
    sha = _commit_all(repo, "initial")

    index = build_repo_index(repo, sha)

    assert index.commit_sha == sha
    assert index.languages == ["python"]
    assert index.manifests == ["pyproject.toml"]
    assert "tests/test_core.py" in index.test_locations
    assert index.symbols["src/pkg/core.py"] == ["build", "Widget"] or set(index.symbols["src/pkg/core.py"]) == {"build", "Widget"}


def test_node_repo_detects_language_manifest_tests_and_symbols(tmp_path: Path):
    repo = _init_repo(tmp_path)
    _write(repo, "package.json", '{"name": "x", "scripts": {"test": "vitest"}}')
    _write(repo, "src/widget.js", "export class Widget {}\n\nexport function build() {\n  return new Widget();\n}\n")
    _write(repo, "src/widget.test.js", "test('builds', () => {});\n")
    sha = _commit_all(repo, "initial")

    index = build_repo_index(repo, sha)

    assert index.languages == ["node"]
    assert index.manifests == ["package.json"]
    assert "src/widget.test.js" in index.test_locations
    assert set(index.symbols["src/widget.js"]) == {"Widget", "build"}


def test_mixed_repo_detects_both_languages(tmp_path: Path):
    repo = _init_repo(tmp_path)
    _write(repo, "pyproject.toml", "[project]\nname='x'\n")
    _write(repo, "package.json", '{"name": "web"}')
    _write(repo, "api/app.py", "def handler():\n    return 'ok'\n")
    _write(repo, "web/index.js", "export function main() {}\n")
    sha = _commit_all(repo, "initial")

    index = build_repo_index(repo, sha)

    assert index.languages == ["node", "python"]
    assert set(index.manifests) == {"package.json", "pyproject.toml"}


def test_bounded_tracked_files_output(tmp_path: Path):
    repo = _init_repo(tmp_path)
    for i in range(MAX_TRACKED_FILES + 50):
        _write(repo, f"src/file_{i:04d}.py", "x = 1\n")
    sha = _commit_all(repo, "many files")

    index = build_repo_index(repo, sha)

    assert index.tracked_file_count == MAX_TRACKED_FILES + 50
    assert len(index.tracked_files) == MAX_TRACKED_FILES
    assert index.tracked_files_truncated is True

    rendered = render_repo_index(index)
    assert len(rendered) <= repo_index_module.RENDER_LIMIT + 100


def test_excludes_generated_vendor_and_build_directories(tmp_path: Path):
    repo = _init_repo(tmp_path)
    _write(repo, "pyproject.toml", "[project]\nname='x'\n")
    _write(repo, "src/app.py", "def real():\n    pass\n")
    _write(repo, "node_modules/pkg/index.js", "module.exports = {};\n")
    _write(repo, "dist/bundle.js", "console.log(1);\n")
    _write(repo, "vendor/lib.py", "def vendored():\n    pass\n")
    _write(repo, ".venv/site.py", "def venv_thing():\n    pass\n")
    _write(repo, "build/out.py", "def built():\n    pass\n")
    sha = _commit_all(repo, "initial")

    index = build_repo_index(repo, sha)

    for f in index.tracked_files:
        assert "node_modules" not in f
        assert not f.startswith("dist/")
        assert not f.startswith("vendor/")
        assert not f.startswith(".venv/")
        assert not f.startswith("build/")
    assert not any(name.startswith("vendor/") or name.startswith("build/") for name in index.symbols)


def test_cache_reuses_result_for_same_commit_sha_and_invalidates_on_new_commit(tmp_path: Path):
    repo = _init_repo(tmp_path)
    _write(repo, "a.py", "def a():\n    pass\n")
    sha1 = _commit_all(repo, "first")

    cache = RepoIndexCache(tmp_path / "cache")

    with patch.object(repo_index_module, "build_repo_index", wraps=repo_index_module.build_repo_index) as spy:
        first = cache.get_or_build(repo)
        second = cache.get_or_build(repo)
        assert spy.call_count == 1
        assert first.commit_sha == sha1
        assert second.commit_sha == sha1
        assert first.tracked_files == second.tracked_files

        _write(repo, "b.py", "def b():\n    pass\n")
        sha2 = _commit_all(repo, "second")
        assert sha2 != sha1

        third = cache.get_or_build(repo)
        assert spy.call_count == 2
        assert third.commit_sha == sha2
        assert "b.py" in third.tracked_files


def test_cache_persists_to_disk_across_instances(tmp_path: Path):
    repo = _init_repo(tmp_path)
    _write(repo, "a.py", "def a():\n    pass\n")
    _commit_all(repo, "first")

    cache_root = tmp_path / "cache"
    first_cache = RepoIndexCache(cache_root)
    built = first_cache.get_or_build(repo)
    assert built is not None

    second_cache = RepoIndexCache(cache_root)
    with patch.object(repo_index_module, "build_repo_index", wraps=repo_index_module.build_repo_index) as spy:
        reloaded = second_cache.get_or_build(repo)
        assert spy.call_count == 0
    assert reloaded.tracked_files == built.tracked_files


def test_get_or_build_returns_none_when_not_a_git_repository(tmp_path: Path):
    not_a_repo = tmp_path / "plain-dir"
    not_a_repo.mkdir()
    cache = RepoIndexCache(tmp_path / "cache")

    assert cache.get_or_build(not_a_repo) is None


def test_get_or_build_returns_none_when_build_fails(tmp_path: Path):
    repo = _init_repo(tmp_path)
    _write(repo, "a.py", "def a():\n    pass\n")
    _commit_all(repo, "first")

    cache = RepoIndexCache(tmp_path / "cache")
    with patch.object(repo_index_module, "build_repo_index", side_effect=RuntimeError("boom")):
        assert cache.get_or_build(repo) is None
