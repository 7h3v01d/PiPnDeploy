# tests/test_clean_safety.py
# Regression tests for clean_project() — verifies that the purge operation
# never crawls into virtual environments or VCS internals.

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from PiPnDeploy.core_logic import clean_project


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_pyproject(tmp_path: Path, name: str = "mypkg") -> None:
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "{name}"\nversion = "1.0.0"\n'
    )


def plant_pyc(directory: Path, filename: str = "cached.pyc") -> Path:
    """Create a .pyc file inside directory, creating parents as needed."""
    directory.mkdir(parents=True, exist_ok=True)
    f = directory / filename
    f.write_bytes(b"\x00" * 16)   # minimal fake pyc content
    return f


def plant_pycache(directory: Path) -> Path:
    """Create a __pycache__ directory with a fake .pyc file inside."""
    pc = directory / "__pycache__"
    pc.mkdir(parents=True, exist_ok=True)
    (pc / "mod.cpython-311.pyc").write_bytes(b"\x00" * 16)
    return pc


# ─── Basic purge behaviour ─────────────────────────────────────────────────────

class TestPurgePycBasic:
    def test_removes_pycache_in_package(self, tmp_path):
        make_pyproject(tmp_path)
        pkg = tmp_path / "mypkg"; pkg.mkdir()
        pc = plant_pycache(pkg)
        clean_project(purge_pyc=True, project_root=tmp_path)
        assert not pc.exists()

    def test_removes_pyc_file_in_package(self, tmp_path):
        make_pyproject(tmp_path)
        pkg = tmp_path / "mypkg"; pkg.mkdir()
        pyc = plant_pyc(pkg)
        clean_project(purge_pyc=True, project_root=tmp_path)
        assert not pyc.exists()

    def test_removes_pycache_in_tests(self, tmp_path):
        make_pyproject(tmp_path)
        tests = tmp_path / "tests"; tests.mkdir()
        pc = plant_pycache(tests)
        clean_project(purge_pyc=True, project_root=tmp_path)
        assert not pc.exists()

    def test_removes_nested_pycache(self, tmp_path):
        make_pyproject(tmp_path)
        deep = tmp_path / "mypkg" / "sub" / "deeper"
        pc = plant_pycache(deep)
        clean_project(purge_pyc=True, project_root=tmp_path)
        assert not pc.exists()

    def test_purge_false_leaves_pycache(self, tmp_path):
        make_pyproject(tmp_path)
        pkg = tmp_path / "mypkg"; pkg.mkdir()
        pc = plant_pycache(pkg)
        clean_project(purge_pyc=False, project_root=tmp_path)
        assert pc.exists()


# ─── Exclusion of virtual environments ────────────────────────────────────────

class TestVenvExclusion:
    def test_dot_venv_pycache_not_removed(self, tmp_path):
        make_pyproject(tmp_path)
        venv_pc = plant_pycache(tmp_path / ".venv" / "lib" / "python3.11")
        clean_project(purge_pyc=True, project_root=tmp_path)
        assert venv_pc.exists(), ".venv/__pycache__ must not be touched"

    def test_venv_pycache_not_removed(self, tmp_path):
        make_pyproject(tmp_path)
        venv_pc = plant_pycache(tmp_path / "venv" / "lib" / "python3.11")
        clean_project(purge_pyc=True, project_root=tmp_path)
        assert venv_pc.exists(), "venv/__pycache__ must not be touched"

    def test_env_pycache_not_removed(self, tmp_path):
        make_pyproject(tmp_path)
        env_pc = plant_pycache(tmp_path / "env" / "lib")
        clean_project(purge_pyc=True, project_root=tmp_path)
        assert env_pc.exists(), "env/__pycache__ must not be touched"

    def test_dot_venv_pyc_not_removed(self, tmp_path):
        make_pyproject(tmp_path)
        pyc = plant_pyc(tmp_path / ".venv" / "lib" / "python3.11")
        clean_project(purge_pyc=True, project_root=tmp_path)
        assert pyc.exists(), ".venv .pyc files must not be touched"

    def test_project_pycache_removed_when_venv_excluded(self, tmp_path):
        """Excluding .venv must not prevent project-owned caches from being cleaned."""
        make_pyproject(tmp_path)
        pkg = tmp_path / "mypkg"; pkg.mkdir()
        proj_pc = plant_pycache(pkg)
        venv_pc = plant_pycache(tmp_path / ".venv" / "lib")
        clean_project(purge_pyc=True, project_root=tmp_path)
        assert not proj_pc.exists(), "project __pycache__ must be removed"
        assert venv_pc.exists(),     ".venv __pycache__ must be preserved"


# ─── Exclusion of VCS internals ───────────────────────────────────────────────

class TestVCSExclusion:
    def test_git_pycache_not_removed(self, tmp_path):
        make_pyproject(tmp_path)
        git_pc = plant_pycache(tmp_path / ".git" / "hooks")
        clean_project(purge_pyc=True, project_root=tmp_path)
        assert git_pc.exists(), ".git internals must not be touched"

    def test_hg_pycache_not_removed(self, tmp_path):
        make_pyproject(tmp_path)
        hg_pc = plant_pycache(tmp_path / ".hg")
        clean_project(purge_pyc=True, project_root=tmp_path)
        assert hg_pc.exists(), ".hg internals must not be touched"


# ─── Build artefact removal ───────────────────────────────────────────────────

class TestBuildArtefacts:
    def test_removes_build_dir(self, tmp_path):
        make_pyproject(tmp_path)
        build = tmp_path / "build"; build.mkdir()
        (build / "lib").mkdir()
        clean_project(purge_pyc=False, project_root=tmp_path)
        assert not build.exists()

    def test_removes_dist_dir(self, tmp_path):
        make_pyproject(tmp_path)
        dist = tmp_path / "dist"; dist.mkdir()
        (dist / "mypkg-1.0.0.whl").write_bytes(b"fake wheel")
        clean_project(purge_pyc=False, project_root=tmp_path)
        assert not dist.exists()

    def test_removes_egg_info(self, tmp_path):
        make_pyproject(tmp_path)
        egg = tmp_path / "mypkg.egg-info"; egg.mkdir()
        (egg / "PKG-INFO").write_text("Name: mypkg\n")
        clean_project(purge_pyc=False, project_root=tmp_path)
        assert not egg.exists()

    def test_leaves_source_when_only_cleaning_artefacts(self, tmp_path):
        make_pyproject(tmp_path)
        pkg = tmp_path / "mypkg"; pkg.mkdir()
        src = pkg / "main.py"; src.write_text("# source\n")
        dist = tmp_path / "dist"; dist.mkdir()
        clean_project(purge_pyc=False, project_root=tmp_path)
        assert src.exists(),   "source file must survive clean"
        assert not dist.exists()
