# tests/test_pyproject_generation.py
# Tests for generate_pyproject() — both create (new file) and surgical (existing file) modes.
# Runs without PyQt6 or a real build environment.

import sys
import tomllib
from pathlib import Path

import pytest
import tomlkit

# Make PiPnDeploy importable when running from the project root
sys.path.insert(0, str(Path(__file__).parent.parent))
from PiPnDeploy.core_logic import (
    generate_pyproject,
    make_default_entry_point,
    validate_entry_point,
    _distribution_name,
    _module_name,
    _cli_command_name,
    read_pyproject_toml,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

MINIMAL_ARGS = dict(
    name="my-package",
    version="1.0.0",
    description="A test package.",
    author="Test Author",
    email="test@example.com",
    dependencies=["requests>=2.0"],
    license_text="MIT",
    keywords=["testing"],
    homepage="https://github.com/example/my-package",
    cli_script_value="my_package.main:main",
)


def read_toml(path: Path) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


# ─── CREATE MODE (no existing file) ──────────────────────────────────────────

class TestCreateMode:
    def test_creates_file(self, tmp_path):
        generate_pyproject(**MINIMAL_ARGS, project_root=tmp_path)
        assert (tmp_path / "pyproject.toml").exists()

    def test_valid_toml(self, tmp_path):
        generate_pyproject(**MINIMAL_ARGS, project_root=tmp_path)
        doc = read_toml(tmp_path / "pyproject.toml")
        assert isinstance(doc, dict)

    def test_project_fields(self, tmp_path):
        generate_pyproject(**MINIMAL_ARGS, project_root=tmp_path)
        doc = read_toml(tmp_path / "pyproject.toml")
        proj = doc["project"]
        assert proj["name"]        == "my-package"
        assert proj["version"]     == "1.0.0"
        assert proj["description"] == "A test package."
        assert proj["license"]     == "MIT"

    def test_authors_written(self, tmp_path):
        generate_pyproject(**MINIMAL_ARGS, project_root=tmp_path)
        doc = read_toml(tmp_path / "pyproject.toml")
        authors = doc["project"]["authors"]
        assert any(a.get("name") == "Test Author" for a in authors)
        assert any(a.get("email") == "test@example.com" for a in authors)

    def test_dependencies_written(self, tmp_path):
        generate_pyproject(**MINIMAL_ARGS, project_root=tmp_path)
        doc = read_toml(tmp_path / "pyproject.toml")
        assert "requests>=2.0" in doc["project"]["dependencies"]

    def test_license_classifier_not_injected(self, tmp_path):
        """PEP 639: License classifiers must not appear when using SPDX string."""
        generate_pyproject(**MINIMAL_ARGS, project_root=tmp_path)
        content = (tmp_path / "pyproject.toml").read_text()
        assert "License ::" not in content

    def test_description_with_quotes(self, tmp_path):
        """Special chars in description must produce valid TOML."""
        args = {**MINIMAL_ARGS, "description": 'A "quoted" description with \'apostrophes\''}
        generate_pyproject(**args, project_root=tmp_path)
        doc = read_toml(tmp_path / "pyproject.toml")
        assert "quoted" in doc["project"]["description"]

    def test_homepage_in_urls(self, tmp_path):
        generate_pyproject(**MINIMAL_ARGS, project_root=tmp_path)
        doc = read_toml(tmp_path / "pyproject.toml")
        assert doc["project"]["urls"]["Homepage"] == "https://github.com/example/my-package"

    def test_build_system_present(self, tmp_path):
        generate_pyproject(**MINIMAL_ARGS, project_root=tmp_path)
        doc = read_toml(tmp_path / "pyproject.toml")
        assert "build-system" in doc

    def test_empty_dependencies(self, tmp_path):
        args = {**MINIMAL_ARGS, "dependencies": []}
        generate_pyproject(**args, project_root=tmp_path)
        doc = read_toml(tmp_path / "pyproject.toml")
        assert doc["project"]["dependencies"] == []


# ─── SURGICAL MODE (existing file) ────────────────────────────────────────────

REAL_WORLD_TOML = """\
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

# This comment must survive
[project]
name = "old-name"
version = "1.0.0"
description = "Old description."
license = { text = "MIT" }
requires-python = ">=3.11"
authors = [
  {name = "Old Author", email = "old@example.com"},
]
dependencies = ["old-dep>=1.0"]
keywords = ["old"]

[project.optional-dependencies]
dev = ["pytest>=7.0"]

[project.gui-scripts]
mygui = "mypkg.gui:main"

[project.urls]
Homepage = "https://old.example.com"
Repository = "https://old.example.com"
"Bug Tracker" = "https://old.example.com/issues"

[tool.ruff]
name = "do-not-touch"
line-length = 100

[tool.pytest.ini_options]
testpaths = ["tests"]
"""


class TestSurgicalMode:
    def setup_existing(self, tmp_path: Path, content: str = REAL_WORLD_TOML) -> Path:
        toml_path = tmp_path / "pyproject.toml"
        toml_path.write_text(content, encoding="utf-8")
        return toml_path

    def test_updates_name(self, tmp_path):
        self.setup_existing(tmp_path)
        generate_pyproject(**{**MINIMAL_ARGS, "name": "new-name"}, project_root=tmp_path)
        assert read_toml(tmp_path / "pyproject.toml")["project"]["name"] == "new-name"

    def test_updates_version(self, tmp_path):
        self.setup_existing(tmp_path)
        generate_pyproject(**{**MINIMAL_ARGS, "version": "9.9.9"}, project_root=tmp_path)
        assert read_toml(tmp_path / "pyproject.toml")["project"]["version"] == "9.9.9"

    def test_updates_description(self, tmp_path):
        self.setup_existing(tmp_path)
        args = {**MINIMAL_ARGS, "description": "Brand new description."}
        generate_pyproject(**args, project_root=tmp_path)
        assert read_toml(tmp_path / "pyproject.toml")["project"]["description"] == "Brand new description."

    def test_description_with_quotes_surgical(self, tmp_path):
        self.setup_existing(tmp_path)
        args = {**MINIMAL_ARGS, "description": 'Has "quotes" inside'}
        generate_pyproject(**args, project_root=tmp_path)
        doc = read_toml(tmp_path / "pyproject.toml")
        assert "quotes" in doc["project"]["description"]

    def test_replaces_old_license_dict(self, tmp_path):
        """Old license = { text = "MIT" } must be replaced with plain SPDX string."""
        self.setup_existing(tmp_path)
        generate_pyproject(**MINIMAL_ARGS, project_root=tmp_path)
        content = (tmp_path / "pyproject.toml").read_text()
        assert 'text = "MIT"' not in content
        doc = read_toml(tmp_path / "pyproject.toml")
        assert doc["project"]["license"] == "MIT"

    def test_no_license_classifier_added(self, tmp_path):
        self.setup_existing(tmp_path)
        generate_pyproject(**MINIMAL_ARGS, project_root=tmp_path)
        content = (tmp_path / "pyproject.toml").read_text()
        assert "License ::" not in content

    def test_preserves_hatchling_backend(self, tmp_path):
        self.setup_existing(tmp_path)
        generate_pyproject(**MINIMAL_ARGS, project_root=tmp_path)
        content = (tmp_path / "pyproject.toml").read_text()
        assert "hatchling" in content

    def test_preserves_tool_ruff(self, tmp_path):
        self.setup_existing(tmp_path)
        generate_pyproject(**MINIMAL_ARGS, project_root=tmp_path)
        doc = read_toml(tmp_path / "pyproject.toml")
        assert doc["tool"]["ruff"]["line-length"] == 100

    def test_tool_ruff_name_not_corrupted(self, tmp_path):
        """[tool.ruff].name must not be overwritten when [project].name changes."""
        self.setup_existing(tmp_path)
        generate_pyproject(**{**MINIMAL_ARGS, "name": "changed"}, project_root=tmp_path)
        doc = read_toml(tmp_path / "pyproject.toml")
        assert doc["tool"]["ruff"]["name"] == "do-not-touch"

    def test_preserves_gui_scripts(self, tmp_path):
        self.setup_existing(tmp_path)
        generate_pyproject(**MINIMAL_ARGS, project_root=tmp_path)
        doc = read_toml(tmp_path / "pyproject.toml")
        assert "gui-scripts" in doc["project"]
        assert doc["project"]["gui-scripts"]["mygui"] == "mypkg.gui:main"

    def test_preserves_optional_dependencies(self, tmp_path):
        self.setup_existing(tmp_path)
        generate_pyproject(**MINIMAL_ARGS, project_root=tmp_path)
        doc = read_toml(tmp_path / "pyproject.toml")
        assert "optional-dependencies" in doc["project"]
        assert "pytest>=7.0" in doc["project"]["optional-dependencies"]["dev"]

    def test_preserves_bug_tracker_url(self, tmp_path):
        self.setup_existing(tmp_path)
        generate_pyproject(**MINIMAL_ARGS, project_root=tmp_path)
        doc = read_toml(tmp_path / "pyproject.toml")
        assert "Bug Tracker" in doc["project"]["urls"]

    def test_updates_homepage_only(self, tmp_path):
        self.setup_existing(tmp_path)
        generate_pyproject(**{**MINIMAL_ARGS, "homepage": "https://new.example.com"}, project_root=tmp_path)
        doc = read_toml(tmp_path / "pyproject.toml")
        assert doc["project"]["urls"]["Homepage"] == "https://new.example.com"
        assert doc["project"]["urls"]["Repository"] == "https://old.example.com"

    def test_preserves_comment(self, tmp_path):
        self.setup_existing(tmp_path)
        generate_pyproject(**MINIMAL_ARGS, project_root=tmp_path)
        content = (tmp_path / "pyproject.toml").read_text()
        assert "This comment must survive" in content

    def test_updates_dependencies(self, tmp_path):
        self.setup_existing(tmp_path)
        args = {**MINIMAL_ARGS, "dependencies": ["requests>=2.0", "PyQt6>=6.4"]}
        generate_pyproject(**args, project_root=tmp_path)
        doc = read_toml(tmp_path / "pyproject.toml")
        deps = doc["project"]["dependencies"]
        assert "requests>=2.0" in deps
        assert "PyQt6>=6.4" in deps
        assert "old-dep>=1.0" not in deps

    def test_classifiers_preserved_when_not_passed(self, tmp_path):
        """Classifiers must not change when caller passes classifiers=None."""
        # Classifiers must be inside [project], not appended after [tool.*] sections
        toml_with_cls = """[project]
name = "old-name"
version = "1.0.0"
description = "Old description."
license = { text = "MIT" }
authors = [{name = "Old Author", email = "old@example.com"}]
dependencies = ["old-dep>=1.0"]
keywords = ["old"]
classifiers = [
    "Topic :: Utilities",
    "Development Status :: 5 - Production/Stable",
]

[tool.ruff]
name = "do-not-touch"
line-length = 100
"""
        self.setup_existing(tmp_path, toml_with_cls)
        args = {**MINIMAL_ARGS, "classifiers": None}
        generate_pyproject(**args, project_root=tmp_path)
        doc = read_toml(tmp_path / "pyproject.toml")
        assert "Development Status :: 5 - Production/Stable" in doc["project"]["classifiers"]

    def test_result_is_valid_toml(self, tmp_path):
        self.setup_existing(tmp_path)
        generate_pyproject(**MINIMAL_ARGS, project_root=tmp_path)
        content = (tmp_path / "pyproject.toml").read_text()
        parsed = tomlkit.parse(content)
        assert parsed["project"]["name"] is not None


# ─── Fix 1: surgical mode creates [project.urls] if missing ──────────────────

class TestSurgicalModeUrlCreation:
    """generate_pyproject must not silently drop homepage in surgical mode."""

    TOML_NO_URLS = """[project]
name = "old-name"
version = "1.0.0"
description = "No URLs section."
license = "MIT"
authors = [{name = "Author", email = "a@b.com"}]
dependencies = []

[tool.ruff]
line-length = 100
"""

    def test_creates_urls_when_missing(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(self.TOML_NO_URLS)
        generate_pyproject(**{**MINIMAL_ARGS, "homepage": "https://new.example.com"},
                           project_root=tmp_path)
        doc = read_toml(tmp_path / "pyproject.toml")
        assert "urls" in doc["project"]
        assert doc["project"]["urls"]["Homepage"] == "https://new.example.com"

    def test_creates_only_homepage_not_repository(self, tmp_path):
        """When creating urls from scratch, only Homepage is added — not Repository."""
        (tmp_path / "pyproject.toml").write_text(self.TOML_NO_URLS)
        generate_pyproject(**{**MINIMAL_ARGS, "homepage": "https://new.example.com"},
                           project_root=tmp_path)
        doc = read_toml(tmp_path / "pyproject.toml")
        # Only Homepage is created; Repository is left for the user to add
        assert "Homepage" in doc["project"]["urls"]

    def test_preserves_existing_urls_when_present(self, tmp_path):
        """If [project.urls] already exists, other entries survive the update."""
        extra = (
            "[project.urls]\n"
            'Homepage = "https://old.example.com"\n'
            '"Bug Tracker" = "https://bugs.example.com"\n\n'
        )
        toml = self.TOML_NO_URLS.replace("[tool.ruff]", extra + "[tool.ruff]")
        (tmp_path / "pyproject.toml").write_text(toml)
        generate_pyproject(**{**MINIMAL_ARGS, "homepage": "https://new.example.com"},
                           project_root=tmp_path)
        doc = read_toml(tmp_path / "pyproject.toml")
        assert doc["project"]["urls"]["Homepage"] == "https://new.example.com"
        assert doc["project"]["urls"]["Bug Tracker"] == "https://bugs.example.com"

    def test_tool_sections_untouched_when_creating_urls(self, tmp_path):
        """Creating [project.urls] must not disturb [tool.*] sections."""
        (tmp_path / "pyproject.toml").write_text(self.TOML_NO_URLS)
        generate_pyproject(**MINIMAL_ARGS, project_root=tmp_path)
        doc = read_toml(tmp_path / "pyproject.toml")
        assert doc["tool"]["ruff"]["line-length"] == 100


# ─── Fix 2: name normalisation + entry point validation ──────────────────────

class TestNameNormalisation:
    def test_distribution_name_hyphen(self):
        assert _distribution_name("my_package") == "my-package"

    def test_distribution_name_already_hyphen(self):
        assert _distribution_name("my-package") == "my-package"

    def test_distribution_name_lowercase(self):
        assert _distribution_name("MyPackage") == "mypackage"

    def test_module_name_underscore(self):
        assert _module_name("my-package") == "my_package"

    def test_module_name_already_underscore(self):
        assert _module_name("my_package") == "my_package"

    def test_cli_command_name_hyphen(self):
        assert _cli_command_name("my_package") == "my-package"

    def test_cli_command_name_lowercase(self):
        assert _cli_command_name("MyPkg") == "mypkg"


class TestDefaultEntryPoint:
    def test_hyphenated_name_gets_underscored_module(self):
        ep = make_default_entry_point("my-package")
        assert ep == "my_package.main:main"

    def test_underscored_name_unchanged(self):
        ep = make_default_entry_point("my_package")
        assert ep == "my_package.main:main"

    def test_mixed_case_lowercased(self):
        ep = make_default_entry_point("MyPackage")
        assert ep == "mypackage.main:main"

    def test_result_passes_validation(self):
        for name in ("my-package", "my_package", "MyPkg", "simple"):
            ep = make_default_entry_point(name)
            err = validate_entry_point(ep)
            assert err is None, f"Default EP for {name!r} failed validation: {ep!r} — {err}"


class TestValidateEntryPoint:
    def test_valid_simple(self):
        assert validate_entry_point("mypkg.main:main") is None

    def test_valid_nested(self):
        assert validate_entry_point("mypkg.sub.cli:app") is None

    def test_valid_no_submodule(self):
        assert validate_entry_point("mypkg:main") is None

    def test_invalid_hyphen_in_module(self):
        assert validate_entry_point("my-pkg.main:main") is not None

    def test_invalid_missing_colon(self):
        assert validate_entry_point("mypkg.main") is not None

    def test_invalid_empty_callable(self):
        assert validate_entry_point("mypkg.main:") is not None

    def test_invalid_empty_string(self):
        assert validate_entry_point("") is not None

    def test_invalid_starts_with_digit(self):
        assert validate_entry_point("123pkg.main:main") is not None

    def test_invalid_hyphen_in_callable(self):
        assert validate_entry_point("mypkg.main:my-func") is not None


class TestCreateModeEntryPoint:
    def test_hyphenated_name_generates_valid_entry_point(self, tmp_path):
        """my-package must produce my_package.main:main not my-package.main:main."""
        args = {**MINIMAL_ARGS, "name": "my-package"}
        generate_pyproject(**args, project_root=tmp_path)
        doc = read_toml(tmp_path / "pyproject.toml")
        scripts = doc["project"]["scripts"]
        # CLI command uses hyphens; module path uses underscores
        assert "my-package" in scripts
        assert scripts["my-package"] == "my_package.main:main"

    def test_underscored_name_generates_hyphenated_command(self, tmp_path):
        args = {**MINIMAL_ARGS, "name": "my_package"}
        generate_pyproject(**args, project_root=tmp_path)
        doc = read_toml(tmp_path / "pyproject.toml")
        scripts = doc["project"]["scripts"]
        assert "my-package" in scripts
        assert scripts["my-package"] == "my_package.main:main"

    def test_custom_entry_point_used_when_provided(self, tmp_path):
        args = {**MINIMAL_ARGS, "cli_script_value": "mypkg.cli:app"}
        generate_pyproject(**args, project_root=tmp_path)
        doc = read_toml(tmp_path / "pyproject.toml")
        scripts = doc["project"]["scripts"]
        assert list(scripts.values())[0] == "mypkg.cli:app"
