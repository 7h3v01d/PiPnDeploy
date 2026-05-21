# tests/test_init_scaffold.py
# Tests for:
#   - create_package_skeleton() — creates correct files, skips if exists
#   - generate_pyproject() omits [project.urls] when homepage is empty
#   - generate_pyproject() skips Homepage update in surgical mode when empty
#   - create_readme() omits Development section when homepage is empty

import sys
import tomllib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from PiPnDeploy.core_logic import (
    create_package_skeleton,
    generate_pyproject,
    init_project_command,
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


# ─── create_package_skeleton ──────────────────────────────────────────────────

class TestCreatePackageSkeleton:
    def test_creates_init_py(self, tmp_path):
        create_package_skeleton("my-package", tmp_path)
        assert (tmp_path / "my_package" / "__init__.py").exists()

    def test_creates_main_py(self, tmp_path):
        create_package_skeleton("my-package", tmp_path)
        assert (tmp_path / "my_package" / "main.py").exists()

    def test_init_py_contains_docstring(self, tmp_path):
        create_package_skeleton("my-package", tmp_path)
        content = (tmp_path / "my_package" / "__init__.py").read_text()
        assert "my-package" in content

    def test_main_py_contains_main_function(self, tmp_path):
        create_package_skeleton("my-package", tmp_path)
        content = (tmp_path / "my_package" / "main.py").read_text()
        assert "def main()" in content
        assert 'if __name__ == "__main__"' in content

    def test_uses_module_name_not_distribution_name(self, tmp_path):
        """Package folder must use underscores, not hyphens."""
        create_package_skeleton("my-package", tmp_path)
        assert (tmp_path / "my_package").is_dir()
        assert not (tmp_path / "my-package").exists()

    def test_handles_underscored_name(self, tmp_path):
        create_package_skeleton("my_package", tmp_path)
        assert (tmp_path / "my_package" / "__init__.py").exists()

    def test_handles_uppercase_name(self, tmp_path):
        create_package_skeleton("MyPackage", tmp_path)
        assert (tmp_path / "mypackage" / "__init__.py").exists()

    def test_returns_true_when_created(self, tmp_path):
        result = create_package_skeleton("mypkg", tmp_path)
        assert result is True

    def test_returns_false_when_already_exists(self, tmp_path):
        """Complete folder (both files present) → returns False."""
        pkg = tmp_path / "mypkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "main.py").write_text("def main(): pass\n")
        result = create_package_skeleton("mypkg", tmp_path)
        assert result is False

    def test_does_not_overwrite_existing_package(self, tmp_path):
        """Existing package content must survive."""
        pkg = tmp_path / "mypkg"
        pkg.mkdir()
        init = pkg / "__init__.py"
        init.write_text("# existing content\n")
        create_package_skeleton("mypkg", tmp_path)
        assert init.read_text() == "# existing content\n"

    def test_main_py_is_importable_python(self, tmp_path):
        """Generated main.py must be parseable Python."""
        import ast
        create_package_skeleton("my-package", tmp_path)
        content = (tmp_path / "my_package" / "main.py").read_text()
        ast.parse(content)   # raises SyntaxError if invalid


# ─── init_project_command with gen_package=True ───────────────────────────────

class TestInitProjectCommandGenPackage:
    def test_creates_skeleton_when_gen_package_true(self, tmp_path):
        init_project_command(
            name="my-tool", gen_package=True, project_root=tmp_path, **COMMON
        )
        assert (tmp_path / "my_tool" / "__init__.py").exists()
        assert (tmp_path / "my_tool" / "main.py").exists()

    def test_does_not_create_skeleton_when_gen_package_false(self, tmp_path):
        init_project_command(
            name="my-tool", gen_package=False, project_root=tmp_path, **COMMON
        )
        assert not (tmp_path / "my_tool").exists()

    def test_gen_package_default_is_false(self, tmp_path):
        """Default must be False — safe for existing projects."""
        init_project_command(name="my-tool", project_root=tmp_path, **COMMON)
        assert not (tmp_path / "my_tool").exists()

    def test_pyproject_created_regardless_of_gen_package(self, tmp_path):
        init_project_command(
            name="my-tool", gen_package=True, project_root=tmp_path, **COMMON
        )
        assert (tmp_path / "pyproject.toml").exists()


# ─── homepage omission ────────────────────────────────────────────────────────

class TestHomepageOmission:
    def test_create_mode_no_urls_when_homepage_empty(self, tmp_path):
        generate_pyproject(name="mypkg", homepage="", project_root=tmp_path, **COMMON)
        doc = read_toml(tmp_path)
        assert "urls" not in doc.get("project", {}), \
            "[project.urls] must not be written when homepage is empty"

    def test_create_mode_urls_written_when_homepage_given(self, tmp_path):
        generate_pyproject(
            name="mypkg", homepage="https://example.com", project_root=tmp_path, **COMMON
        )
        doc = read_toml(tmp_path)
        assert "urls" in doc["project"]
        assert doc["project"]["urls"]["Homepage"] == "https://example.com"

    def test_surgical_mode_no_url_creation_when_homepage_empty(self, tmp_path):
        """Surgical mode must not create [project.urls] when homepage is empty."""
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "old"\nversion = "1.0.0"\n'
        )
        generate_pyproject(name="mypkg", homepage="", project_root=tmp_path, **COMMON)
        doc = read_toml(tmp_path)
        assert "urls" not in doc.get("project", {})

    def test_surgical_mode_preserves_existing_urls_when_homepage_empty(self, tmp_path):
        """Existing URLs must not be removed when homepage="" is passed."""
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "old"\nversion = "1.0.0"\n\n'
            '[project.urls]\nHomepage = "https://existing.com"\n'
            '"Bug Tracker" = "https://bugs.existing.com"\n'
        )
        generate_pyproject(name="mypkg", homepage="", project_root=tmp_path, **COMMON)
        doc = read_toml(tmp_path)
        # Existing URLs must survive untouched
        assert doc["project"]["urls"]["Homepage"] == "https://existing.com"
        assert doc["project"]["urls"]["Bug Tracker"] == "https://bugs.existing.com"

    def test_no_yourusername_in_generated_toml(self, tmp_path):
        generate_pyproject(name="mypkg", homepage="", project_root=tmp_path, **COMMON)
        content = (tmp_path / "pyproject.toml").read_text()
        assert "yourusername" not in content

    def test_no_yourusername_in_generated_readme(self, tmp_path):
        from PiPnDeploy.core_logic import create_readme
        create_readme(tmp_path, name="mypkg", description="A pkg.", homepage="")
        content = (tmp_path / "README.md").read_text()
        assert "yourusername" not in content

    def test_readme_omits_dev_section_when_no_homepage(self, tmp_path):
        from PiPnDeploy.core_logic import create_readme
        create_readme(tmp_path, name="mypkg", description="A pkg.", homepage="")
        content = (tmp_path / "README.md").read_text()
        assert "git clone" not in content
        assert "## Development" not in content

    def test_readme_includes_dev_section_when_homepage_given(self, tmp_path):
        from PiPnDeploy.core_logic import create_readme
        create_readme(tmp_path, name="mypkg", description="A pkg.",
                      homepage="https://github.com/user/mypkg")
        content = (tmp_path / "README.md").read_text()
        assert "git clone https://github.com/user/mypkg" in content
        assert "## Development" in content


# ─── create_package_skeleton: incomplete existing folder ─────────────────────

class TestCreatePackageSkeletonIncomplete:
    """Folder exists but is missing files — scaffold the missing pieces."""

    def test_creates_missing_init_py(self, tmp_path):
        pkg = tmp_path / "mypkg"; pkg.mkdir()
        # main.py exists but __init__.py is missing
        (pkg / "main.py").write_text("def main(): pass\n")
        create_package_skeleton("mypkg", tmp_path)
        assert (pkg / "__init__.py").exists()

    def test_creates_missing_main_py(self, tmp_path):
        pkg = tmp_path / "mypkg"; pkg.mkdir()
        # __init__.py exists but main.py is missing
        (pkg / "__init__.py").write_text("")
        create_package_skeleton("mypkg", tmp_path)
        assert (pkg / "main.py").exists()

    def test_does_not_overwrite_existing_init_py(self, tmp_path):
        pkg = tmp_path / "mypkg"; pkg.mkdir()
        (pkg / "__init__.py").write_text("# my existing init\n")
        create_package_skeleton("mypkg", tmp_path)
        assert (pkg / "__init__.py").read_text() == "# my existing init\n"

    def test_does_not_overwrite_existing_main_py(self, tmp_path):
        pkg = tmp_path / "mypkg"; pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "main.py").write_text("# my existing main\n")
        create_package_skeleton("mypkg", tmp_path)
        assert (pkg / "main.py").read_text() == "# my existing main\n"

    def test_returns_true_when_missing_files_created(self, tmp_path):
        pkg = tmp_path / "mypkg"; pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        # main.py missing — should be created → returns True
        result = create_package_skeleton("mypkg", tmp_path)
        assert result is True

    def test_returns_false_when_already_complete(self, tmp_path):
        pkg = tmp_path / "mypkg"; pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "main.py").write_text("def main(): pass\n")
        result = create_package_skeleton("mypkg", tmp_path)
        assert result is False
