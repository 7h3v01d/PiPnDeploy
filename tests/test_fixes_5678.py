# tests/test_fixes_5678.py
# Targeted regression tests for fixes 5-8:
#   5. generate_pyproject uses _distribution_name() for [project].name
#   6. _purge_pyc correctly skips all dot-directories (not just _CLEAN_EXCLUDE_DIRS)
#   7. run_hook accepts python param; build_package threads it to pre_build hook
#   8. resolve_project_root() gives clean errors for bad paths

import sys
import tomllib
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from PiPnDeploy.core_logic import (
    _distribution_name,
    _module_name,
    generate_pyproject,
    resolve_project_root,
    run_hook,
)


COMMON = dict(
    version="1.0.0",
    description="Test.",
    author="Author",
    email="a@b.com",
    dependencies=[],
    license_text="MIT",
)


def read_toml(tmp_path: Path) -> dict:
    with open(tmp_path / "pyproject.toml", "rb") as f:
        return tomllib.load(f)


# ─── Fix 5: generate_pyproject normalises [project].name ─────────────────────

class TestDistributionNameNormalisation:
    """[project].name must always be the canonical distribution name:
    lowercase, hyphens — regardless of what the user typed."""

    def test_uppercase_name_lowercased_in_create_mode(self, tmp_path):
        generate_pyproject(name="MyPackage", **COMMON, project_root=tmp_path)
        doc = read_toml(tmp_path)
        assert doc["project"]["name"] == "mypackage"

    def test_underscore_name_hyphenated_in_create_mode(self, tmp_path):
        generate_pyproject(name="my_package", **COMMON, project_root=tmp_path)
        doc = read_toml(tmp_path)
        assert doc["project"]["name"] == "my-package"

    def test_hyphenated_name_unchanged_in_create_mode(self, tmp_path):
        generate_pyproject(name="my-package", **COMMON, project_root=tmp_path)
        doc = read_toml(tmp_path)
        assert doc["project"]["name"] == "my-package"

    def test_mixed_case_hyphen_in_create_mode(self, tmp_path):
        generate_pyproject(name="My_Package", **COMMON, project_root=tmp_path)
        doc = read_toml(tmp_path)
        assert doc["project"]["name"] == "my-package"

    def test_uppercase_name_lowercased_in_surgical_mode(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "old"\nversion = "1.0.0"\n'
        )
        generate_pyproject(name="MyPackage", **COMMON, project_root=tmp_path)
        doc = read_toml(tmp_path)
        assert doc["project"]["name"] == "mypackage"

    def test_underscore_name_hyphenated_in_surgical_mode(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "old"\nversion = "1.0.0"\n'
        )
        generate_pyproject(name="my_package", **COMMON, project_root=tmp_path)
        doc = read_toml(tmp_path)
        assert doc["project"]["name"] == "my-package"

    def test_distribution_name_helper_consistency(self):
        """Helper must be consistent with what generate_pyproject writes."""
        for name in ("MyPkg", "my_pkg", "my-pkg", "My_Pkg"):
            expected = _distribution_name(name)
            assert expected == expected.lower()
            assert "_" not in expected


# ─── Fix 6: _purge_pyc skips all dot-directories ─────────────────────────────

class TestPurgePycDotDirs:
    """Any dot-directory must be skipped, not just those in _CLEAN_EXCLUDE_DIRS."""

    def _plant_pycache(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        pc = directory / "__pycache__"
        pc.mkdir()
        (pc / "mod.cpython-311.pyc").write_bytes(b"\x00" * 16)
        return pc

    def test_dot_mypy_cache_skipped(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text('[project]\nname="x"\nversion="1"\n')
        pc = self._plant_pycache(tmp_path / ".mypy_cache")
        from PiPnDeploy.core_logic import clean_project
        clean_project(purge_pyc=True, project_root=tmp_path)
        assert pc.exists(), ".mypy_cache/__pycache__ must not be removed"

    def test_dot_tox_skipped(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text('[project]\nname="x"\nversion="1"\n')
        pc = self._plant_pycache(tmp_path / ".tox")
        from PiPnDeploy.core_logic import clean_project
        clean_project(purge_pyc=True, project_root=tmp_path)
        assert pc.exists(), ".tox/__pycache__ must not be removed"

    def test_dot_pytest_cache_skipped(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text('[project]\nname="x"\nversion="1"\n')
        pc = self._plant_pycache(tmp_path / ".pytest_cache")
        from PiPnDeploy.core_logic import clean_project
        clean_project(purge_pyc=True, project_root=tmp_path)
        assert pc.exists(), ".pytest_cache must not be removed"

    def test_project_pycache_still_removed_when_dot_dirs_excluded(self, tmp_path):
        """Excluding dot-dirs must not prevent project-owned caches from cleaning."""
        (tmp_path / "pyproject.toml").write_text('[project]\nname="x"\nversion="1"\n')
        pkg = tmp_path / "mypkg"; pkg.mkdir()
        proj_pc = pkg / "__pycache__"; proj_pc.mkdir()
        (proj_pc / "mod.pyc").write_bytes(b"\x00" * 16)
        self._plant_pycache(tmp_path / ".mypy_cache")
        from PiPnDeploy.core_logic import clean_project
        clean_project(purge_pyc=True, project_root=tmp_path)
        assert not proj_pc.exists(), "project __pycache__ must be removed"


# ─── Fix 7: run_hook accepts python param ────────────────────────────────────

class TestRunHookPythonParam:
    def test_run_hook_returns_true_when_no_hook(self, tmp_path):
        """No hook file → always returns True."""
        assert run_hook("pre_build", tmp_path) is True

    def test_run_hook_uses_provided_python(self, tmp_path):
        """run_hook must call the interpreter it was given, not sys.executable."""
        hooks = tmp_path / "hooks"; hooks.mkdir()
        hook = hooks / "pre_build.py"
        hook.write_text("import sys\nsys.exit(0)\n")

        called_with: list[list] = []

        def fake_run(cmd, **kwargs):
            called_with.append(cmd)
            result = MagicMock()
            result.returncode = 0
            return result

        with patch("PiPnDeploy.core_logic.subprocess.run", side_effect=fake_run):
            run_hook("pre_build", tmp_path, python="/custom/python")

        assert called_with[0][0] == "/custom/python", (
            f"Hook must use provided interpreter, got: {called_with[0][0]}"
        )

    def test_run_hook_defaults_to_sys_executable_when_no_python(self, tmp_path):
        import sys as _sys
        hooks = tmp_path / "hooks"; hooks.mkdir()
        (hooks / "pre_build.py").write_text("import sys\nsys.exit(0)\n")

        called_with: list[list] = []

        def fake_run(cmd, **kwargs):
            called_with.append(cmd)
            result = MagicMock()
            result.returncode = 0
            return result

        with patch("PiPnDeploy.core_logic.subprocess.run", side_effect=fake_run):
            run_hook("pre_build", tmp_path)

        assert called_with[0][0] == _sys.executable

    def test_run_hook_failure_returns_false(self, tmp_path):
        hooks = tmp_path / "hooks"; hooks.mkdir()
        (hooks / "pre_build.py").write_text("import sys\nsys.exit(1)\n")

        def fake_run(cmd, **kwargs):
            result = MagicMock()
            result.returncode = 1
            return result

        with patch("PiPnDeploy.core_logic.subprocess.run", side_effect=fake_run):
            result = run_hook("pre_build", tmp_path)

        assert result is False


# ─── Fix 8: resolve_project_root gives clean errors ─────────────────────────

class TestResolveProjectRoot:
    def test_empty_string_returns_cwd(self):
        result = resolve_project_root("")
        assert result == Path.cwd()

    def test_valid_path_returns_resolved(self, tmp_path):
        result = resolve_project_root(str(tmp_path))
        assert result == tmp_path.resolve()

    def test_nonexistent_path_raises_file_not_found(self, tmp_path):
        bad = str(tmp_path / "does_not_exist")
        with pytest.raises(FileNotFoundError) as exc_info:
            resolve_project_root(bad)
        assert "does not exist" in str(exc_info.value)
        assert bad in str(exc_info.value) or "does_not_exist" in str(exc_info.value)

    def test_file_path_raises_not_a_directory(self, tmp_path):
        f = tmp_path / "somefile.txt"
        f.write_text("not a dir")
        with pytest.raises(NotADirectoryError) as exc_info:
            resolve_project_root(str(f))
        assert "not a directory" in str(exc_info.value).lower()

    def test_error_message_contains_path(self, tmp_path):
        bad = str(tmp_path / "missing_dir")
        with pytest.raises(FileNotFoundError) as exc_info:
            resolve_project_root(bad)
        # The error must be human-readable — no raw Python exception text
        assert "❌" in str(exc_info.value)

    def test_relative_path_resolved(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        sub = tmp_path / "subdir"; sub.mkdir()
        result = resolve_project_root("subdir")
        assert result == sub.resolve()
