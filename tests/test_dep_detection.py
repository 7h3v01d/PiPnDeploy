# tests/test_dep_detection.py
# Tests for detect_dependencies(), get_package_folder_path(), is_standard_library().

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from PiPnDeploy.core_logic import (
    detect_dependencies,
    find_package_roots,
    get_package_folder_path,
    is_standard_library,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_package(tmp_path: Path, name: str = "mypkg") -> Path:
    """Create a minimal package folder with __init__.py."""
    pkg = tmp_path / name
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    return pkg


def write_module(pkg: Path, filename: str, content: str) -> Path:
    p = pkg / filename
    p.write_text(content, encoding="utf-8")
    return p


# ─── is_standard_library ─────────────────────────────────────────────────────

class TestIsStandardLibrary:
    def test_os_is_stdlib(self):
        assert is_standard_library("os") is True

    def test_sys_is_stdlib(self):
        assert is_standard_library("sys") is True

    def test_json_is_stdlib(self):
        assert is_standard_library("json") is True

    def test_pathlib_is_stdlib(self):
        assert is_standard_library("pathlib") is True

    def test_requests_not_stdlib(self):
        assert is_standard_library("requests") is False

    def test_numpy_not_stdlib(self):
        assert is_standard_library("numpy") is False

    def test_pyqt6_not_stdlib(self):
        assert is_standard_library("PyQt6") is False

    def test_case_insensitive(self):
        assert is_standard_library("OS") is True
        assert is_standard_library("Json") is True


# ─── get_package_folder_path ──────────────────────────────────────────────────

class TestGetPackageFolderPath:
    def test_finds_package_with_init(self, tmp_path):
        make_package(tmp_path, "mypkg")
        result = get_package_folder_path(tmp_path)
        assert result is not None
        assert result.name == "mypkg"

    def test_returns_none_when_no_package(self, tmp_path):
        assert get_package_folder_path(tmp_path) is None

    def test_ignores_dir_without_init(self, tmp_path):
        (tmp_path / "notapkg").mkdir()
        assert get_package_folder_path(tmp_path) is None

    def test_ignores_tests_dir(self, tmp_path):
        # tests/ with __init__.py must never be returned — even if it sorts first
        make_package(tmp_path, "mypkg")
        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "__init__.py").write_text("")
        result = get_package_folder_path(tmp_path)
        assert result is not None
        assert result.name == "mypkg"

    def test_ignores_tests_dir_when_first_alphabetically(self, tmp_path):
        """tests/ sorts before zzz_pkg/ alphabetically — must still be excluded."""
        pkg = tmp_path / "zzz_pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "__init__.py").write_text("")
        result = get_package_folder_path(tmp_path)
        assert result is not None
        assert result.name == "zzz_pkg"


# ─── detect_dependencies ─────────────────────────────────────────────────────

class TestDetectDependencies:
    def test_detects_third_party_import(self, tmp_path):
        pkg = make_package(tmp_path)
        write_module(pkg, "main.py", "import requests\n")
        deps = detect_dependencies(tmp_path)
        assert "requests" in deps

    def test_excludes_stdlib(self, tmp_path):
        pkg = make_package(tmp_path)
        write_module(pkg, "main.py", "import os\nimport sys\nimport json\n")
        deps = detect_dependencies(tmp_path)
        assert "os" not in deps
        assert "sys" not in deps
        assert "json" not in deps

    def test_detects_from_import(self, tmp_path):
        pkg = make_package(tmp_path)
        write_module(pkg, "main.py", "from requests import get\n")
        deps = detect_dependencies(tmp_path)
        assert "requests" in deps

    def test_applies_import_alias_map(self, tmp_path):
        pkg = make_package(tmp_path)
        write_module(pkg, "main.py", "import PIL\nfrom bs4 import BeautifulSoup\n")
        deps = detect_dependencies(tmp_path)
        assert "Pillow" in deps
        assert "beautifulsoup4" in deps

    def test_returns_sorted_list(self, tmp_path):
        pkg = make_package(tmp_path)
        write_module(pkg, "main.py", "import requests\nimport numpy\n")
        deps = detect_dependencies(tmp_path)
        assert deps == sorted(deps)

    def test_no_duplicates(self, tmp_path):
        pkg = make_package(tmp_path)
        write_module(pkg, "a.py", "import requests\n")
        write_module(pkg, "b.py", "import requests\n")
        deps = detect_dependencies(tmp_path)
        assert deps.count("requests") == 1

    def test_returns_empty_when_no_package(self, tmp_path):
        deps = detect_dependencies(tmp_path)
        assert deps == []

    def test_skips_dummy_py(self, tmp_path):
        """dummy.py must be excluded from dep scanning."""
        pkg = make_package(tmp_path)
        write_module(pkg, "dummy.py", "import flask\nimport django\n")
        write_module(pkg, "main.py", "import requests\n")
        deps = detect_dependencies(tmp_path)
        assert "flask" not in deps
        assert "django" not in deps
        assert "requests" in deps

    def test_skips_conftest_py(self, tmp_path):
        pkg = make_package(tmp_path)
        write_module(pkg, "conftest.py", "import pytest_mock\n")
        write_module(pkg, "main.py", "import requests\n")
        deps = detect_dependencies(tmp_path)
        assert "pytest_mock" not in deps

    def test_scans_subdirectories(self, tmp_path):
        pkg = make_package(tmp_path)
        sub = pkg / "utils"
        sub.mkdir()
        (sub / "__init__.py").write_text("")
        write_module(sub, "helper.py", "import httpx\n")
        deps = detect_dependencies(tmp_path)
        assert "httpx" in deps

    def test_handles_parse_error_gracefully(self, tmp_path):
        """Files with syntax errors should be skipped, not crash the scan."""
        pkg = make_package(tmp_path)
        write_module(pkg, "broken.py", "this is not valid python !!!")
        write_module(pkg, "main.py", "import requests\n")
        deps = detect_dependencies(tmp_path)
        assert "requests" in deps

    def test_ignores_relative_imports(self, tmp_path):
        pkg = make_package(tmp_path)
        write_module(pkg, "main.py", "from . import utils\nfrom .utils import helper\n")
        deps = detect_dependencies(tmp_path)
        assert deps == []

    def test_ignores_future_imports(self, tmp_path):
        pkg = make_package(tmp_path)
        write_module(pkg, "main.py", "from __future__ import annotations\n")
        deps = detect_dependencies(tmp_path)
        assert deps == []

    def test_mixed_stdlib_and_third_party(self, tmp_path):
        pkg = make_package(tmp_path)
        write_module(
            pkg, "main.py",
            "import os\nimport sys\nimport requests\nfrom pathlib import Path\nimport numpy\n"
        )
        deps = detect_dependencies(tmp_path)
        assert "requests" in deps
        assert "numpy" in deps
        assert "os" not in deps
        assert "sys" not in deps
        assert "pathlib" not in deps

    def test_real_world_style_module(self, tmp_path):
        pkg = make_package(tmp_path)
        write_module(pkg, "app.py", """\
import os
import sys
import json
from pathlib import Path
from typing import Optional

import typer
import tomlkit
from PyQt6.QtWidgets import QApplication

app = typer.Typer()
""")
        deps = detect_dependencies(tmp_path)
        assert "typer" in deps
        assert "tomlkit" in deps
        assert "PyQt6" in deps
        assert "os" not in deps
        assert "json" not in deps
        assert "typing" not in deps


# ─── find_package_roots ───────────────────────────────────────────────────────

class TestFindPackageRoots:
    def test_flat_layout(self, tmp_path):
        make_package(tmp_path, "mypkg")
        roots = find_package_roots(tmp_path)
        assert len(roots) == 1
        assert roots[0].name == "mypkg"

    def test_src_layout(self, tmp_path):
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        pkg = src_dir / "mypkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        roots = find_package_roots(tmp_path)
        assert len(roots) == 1
        assert roots[0].name == "mypkg"

    def test_multi_package(self, tmp_path):
        make_package(tmp_path, "pkg_a")
        make_package(tmp_path, "pkg_b")
        roots = find_package_roots(tmp_path)
        names = {r.name for r in roots}
        assert "pkg_a" in names
        assert "pkg_b" in names

    def test_excludes_tests(self, tmp_path):
        make_package(tmp_path, "mypkg")
        t = tmp_path / "tests"; t.mkdir(); (t / "__init__.py").write_text("")
        roots = find_package_roots(tmp_path)
        assert all(r.name != "tests" for r in roots)

    def test_excludes_docs(self, tmp_path):
        make_package(tmp_path, "mypkg")
        d = tmp_path / "docs"; d.mkdir(); (d / "__init__.py").write_text("")
        roots = find_package_roots(tmp_path)
        assert all(r.name != "docs" for r in roots)

    def test_excludes_venv(self, tmp_path):
        make_package(tmp_path, "mypkg")
        v = tmp_path / ".venv"; v.mkdir(); (v / "__init__.py").write_text("")
        roots = find_package_roots(tmp_path)
        assert all(r.name != ".venv" for r in roots)

    def test_excludes_build_and_dist(self, tmp_path):
        make_package(tmp_path, "mypkg")
        for d in ("build", "dist"):
            p = tmp_path / d; p.mkdir(); (p / "__init__.py").write_text("")
        roots = find_package_roots(tmp_path)
        names = {r.name for r in roots}
        assert "build" not in names
        assert "dist" not in names

    def test_returns_empty_when_nothing(self, tmp_path):
        assert find_package_roots(tmp_path) == []

    def test_deterministic_ordering(self, tmp_path):
        """Results must be sorted, not OS-dependent."""
        for name in ("zzz_pkg", "aaa_pkg", "mmm_pkg"):
            make_package(tmp_path, name)
        roots = find_package_roots(tmp_path)
        names = [r.name for r in roots]
        assert names == sorted(names)


# ─── src layout detection ─────────────────────────────────────────────────────

class TestSrcLayoutDetection:
    def test_detects_deps_in_src_layout(self, tmp_path):
        src_dir = tmp_path / "src"; src_dir.mkdir()
        pkg = src_dir / "mypkg"; pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        write_module(pkg, "main.py", "import requests\n")
        deps = detect_dependencies(tmp_path)
        assert "requests" in deps

    def test_src_layout_excludes_stdlib(self, tmp_path):
        src_dir = tmp_path / "src"; src_dir.mkdir()
        pkg = src_dir / "mypkg"; pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        write_module(pkg, "main.py", "import os\nimport requests\n")
        deps = detect_dependencies(tmp_path)
        assert "os" not in deps
        assert "requests" in deps

    def test_src_layout_excludes_self_imports(self, tmp_path):
        src_dir = tmp_path / "src"; src_dir.mkdir()
        pkg = src_dir / "mypkg"; pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        write_module(pkg, "main.py", "from mypkg.utils import helper\nimport requests\n")
        deps = detect_dependencies(tmp_path)
        assert "mypkg" not in deps
        assert "requests" in deps


# ─── self-import exclusion ────────────────────────────────────────────────────

class TestSelfImportExclusion:
    def test_excludes_own_package_name(self, tmp_path):
        pkg = make_package(tmp_path, "mypkg")
        write_module(pkg, "main.py", "from mypkg.utils import helper\nimport requests\n")
        deps = detect_dependencies(tmp_path)
        assert "mypkg" not in deps
        assert "requests" in deps

    def test_excludes_own_package_import_statement(self, tmp_path):
        pkg = make_package(tmp_path, "mypkg")
        write_module(pkg, "main.py", "import mypkg\nimport requests\n")
        deps = detect_dependencies(tmp_path)
        assert "mypkg" not in deps

    def test_excludes_hyphen_underscore_variant(self, tmp_path):
        """my-pkg and my_pkg both refer to the same local package."""
        pkg = make_package(tmp_path, "my_pkg")
        write_module(pkg, "main.py", "import my_pkg\nfrom my_pkg.utils import x\nimport requests\n")
        deps = detect_dependencies(tmp_path)
        assert "my_pkg" not in deps
        assert "my-pkg" not in deps
        assert "requests" in deps

    def test_submodule_import_excluded(self, tmp_path):
        pkg = make_package(tmp_path, "mypkg")
        write_module(pkg, "main.py", "from mypkg.api.v2 import route\nimport httpx\n")
        deps = detect_dependencies(tmp_path)
        assert "mypkg" not in deps
        assert "httpx" in deps


# ─── tests/ ordering robustness ──────────────────────────────────────────────

class TestNoiseDirectoryExclusion:
    def test_tests_before_package_alphabetically(self, tmp_path):
        """tests/ sorts before the real package — must still be excluded."""
        pkg = tmp_path / "zzz_app"; pkg.mkdir(); (pkg / "__init__.py").write_text("")
        write_module(pkg, "main.py", "import requests\n")
        tests = tmp_path / "tests"; tests.mkdir(); (tests / "__init__.py").write_text("")
        write_module(tests, "test_something.py", "import pytest\n")
        deps = detect_dependencies(tmp_path)
        assert "requests" in deps
        assert "pytest" not in deps

    def test_docs_with_init_ignored(self, tmp_path):
        pkg = make_package(tmp_path, "mypkg")
        write_module(pkg, "main.py", "import requests\n")
        docs = tmp_path / "docs"; docs.mkdir(); (docs / "__init__.py").write_text("")
        write_module(docs, "conf.py", "import sphinx\n")
        deps = detect_dependencies(tmp_path)
        assert "sphinx" not in deps
        assert "requests" in deps

    def test_examples_with_init_ignored(self, tmp_path):
        pkg = make_package(tmp_path, "mypkg")
        write_module(pkg, "main.py", "import requests\n")
        ex = tmp_path / "examples"; ex.mkdir(); (ex / "__init__.py").write_text("")
        write_module(ex, "demo.py", "import matplotlib\n")
        deps = detect_dependencies(tmp_path)
        assert "matplotlib" not in deps
        assert "requests" in deps

    def test_multi_package_scans_all(self, tmp_path):
        """Both packages in a multi-package project must be scanned."""
        pkg_a = make_package(tmp_path, "pkg_a")
        pkg_b = make_package(tmp_path, "pkg_b")
        write_module(pkg_a, "main.py", "import requests\n")
        write_module(pkg_b, "main.py", "import httpx\n")
        deps = detect_dependencies(tmp_path)
        assert "requests" in deps
        assert "httpx" in deps
