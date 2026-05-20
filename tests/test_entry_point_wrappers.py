# tests/test_entry_point_wrappers.py
# Regression tests for the entry-point wrapper bug.
#
# The bug: cli_main.py and gui_main.py used to fall back to
#   f"{name}.main:main"
# which produces an invalid Python import path for hyphenated names like
# "my-package" → "my-package.main:main".
#
# The fix: wrappers now pass cli_script_value="" and let
# init_project_command() call make_default_entry_point(name) which
# correctly produces "my_package.main:main".
#
# These tests verify the fix end-to-end through init_project_command()
# — the same path the CLI and GUI call — not just the helper functions.

import sys
import tomllib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from PiPnDeploy.core_logic import (
    init_project_command,
    make_default_entry_point,
    validate_entry_point,
)


COMMON = dict(
    version="1.0.0",
    description="Test package.",
    author="Test Author",
    email="test@example.com",
    dependencies=[],
    license_text="MIT",
)


def read_scripts(tmp_path: Path) -> dict:
    with open(tmp_path / "pyproject.toml", "rb") as f:
        doc = tomllib.load(f)
    return doc.get("project", {}).get("scripts", {})


# ─── The core regression: hyphenated name via empty cli_script_value ──────────

class TestEntryPointWrapperRegression:
    """Prove that passing cli_script_value='' (what the fixed wrappers do)
    produces a valid entry point — not my-package.main:main."""

    def test_hyphenated_name_empty_cli_script(self, tmp_path):
        """The regression case: name='my-package', cli_script_value=''."""
        init_project_command(
            name="my-package",
            cli_script_value="",   # ← what the fixed CLI/GUI pass
            project_root=tmp_path,
            **COMMON,
        )
        scripts = read_scripts(tmp_path)
        # CLI command uses hyphens
        assert "my-package" in scripts, f"Expected 'my-package' in scripts, got: {scripts}"
        ep = scripts["my-package"]
        # Module path MUST use underscores — this is the regression assertion
        assert ep == "my_package.main:main", (
            f"Got {ep!r} — hyphens in entry point module path are invalid Python"
        )

    def test_hyphenated_name_entry_point_is_valid(self, tmp_path):
        """The generated entry point must pass validate_entry_point."""
        init_project_command(
            name="my-package",
            cli_script_value="",
            project_root=tmp_path,
            **COMMON,
        )
        scripts = read_scripts(tmp_path)
        ep = scripts.get("my-package", "")
        err = validate_entry_point(ep)
        assert err is None, f"Entry point {ep!r} failed validation: {err}"

    def test_underscored_name_empty_cli_script(self, tmp_path):
        """Underscored names work correctly too."""
        init_project_command(
            name="my_package",
            cli_script_value="",
            project_root=tmp_path,
            **COMMON,
        )
        scripts = read_scripts(tmp_path)
        assert "my-package" in scripts
        assert scripts["my-package"] == "my_package.main:main"

    def test_simple_name_empty_cli_script(self, tmp_path):
        """Simple single-word names are unaffected."""
        init_project_command(
            name="mypkg",
            cli_script_value="",
            project_root=tmp_path,
            **COMMON,
        )
        scripts = read_scripts(tmp_path)
        assert "mypkg" in scripts
        assert scripts["mypkg"] == "mypkg.main:main"

    def test_mixed_case_name_lowercased(self, tmp_path):
        init_project_command(
            name="MyPackage",
            cli_script_value="",
            project_root=tmp_path,
            **COMMON,
        )
        scripts = read_scripts(tmp_path)
        assert scripts.get("mypackage") == "mypackage.main:main"

    def test_custom_cli_script_respected(self, tmp_path):
        """Explicit cli_script_value must be used as-is (after validation)."""
        init_project_command(
            name="my-package",
            cli_script_value="mypkg.cli:app",
            project_root=tmp_path,
            **COMMON,
        )
        scripts = read_scripts(tmp_path)
        ep = list(scripts.values())[0]
        assert ep == "mypkg.cli:app"

    def test_invalid_custom_cli_script_raises(self, tmp_path):
        """A hyphenated module path in cli_script_value must be rejected."""
        with pytest.raises(ValueError, match="Invalid entry point"):
            init_project_command(
                name="my-package",
                cli_script_value="my-package.main:main",  # ← the old bug
                project_root=tmp_path,
                **COMMON,
            )


# ─── make_default_entry_point correctness ────────────────────────────────────

class TestMakeDefaultEntryPoint:
    """Belt-and-braces: verify the helper itself for every name shape."""

    @pytest.mark.parametrize("name, expected", [
        ("my-package",   "my_package.main:main"),
        ("my_package",   "my_package.main:main"),
        ("MyPackage",    "mypackage.main:main"),
        ("simple",       "simple.main:main"),
        ("a-b-c",        "a_b_c.main:main"),
        ("pkg_with_many_parts", "pkg_with_many_parts.main:main"),
    ])
    def test_produces_valid_entry_point(self, name, expected):
        ep = make_default_entry_point(name)
        assert ep == expected
        assert validate_entry_point(ep) is None, f"{ep!r} failed validation"


# ─── Simulate exactly what the fixed wrappers do ─────────────────────────────

class TestWrapperBehaviour:
    """Simulate the exact call pattern from the fixed CLI and GUI."""

    def test_cli_init_pattern(self, tmp_path):
        """Simulate: cli_script = "" (user left field blank in CLI)."""
        cli_script = ""   # typer.Option default after our fix
        init_project_command(
            name="my-package",
            cli_script_value=cli_script,   # passes "" not f"{name}.main:main"
            project_root=tmp_path,
            **COMMON,
        )
        scripts = read_scripts(tmp_path)
        assert scripts.get("my-package") == "my_package.main:main"

    def test_cli_full_pipeline_pattern(self, tmp_path):
        """Simulate: cli_script_value="" hardcoded in full pipeline."""
        init_project_command(
            name="another-pkg",
            cli_script_value="",   # fixed full pipeline passes ""
            project_root=tmp_path,
            **COMMON,
        )
        scripts = read_scripts(tmp_path)
        assert scripts.get("another-pkg") == "another_pkg.main:main"

    def test_gui_init_pattern_blank_field(self, tmp_path):
        """Simulate: user left CLI Script field blank in GUI Init tab."""
        gui_field_value = ""   # QLineEdit().text().strip() when blank
        init_project_command(
            name="my-package",
            cli_script_value=gui_field_value,
            project_root=tmp_path,
            **COMMON,
        )
        scripts = read_scripts(tmp_path)
        assert scripts.get("my-package") == "my_package.main:main"

    def test_gui_init_pattern_user_typed_entry_point(self, tmp_path):
        """Simulate: user typed a valid entry point in the GUI CLI Script field."""
        gui_field_value = "mypkg.cli:app"
        init_project_command(
            name="my-package",
            cli_script_value=gui_field_value,
            project_root=tmp_path,
            **COMMON,
        )
        scripts = read_scripts(tmp_path)
        ep = list(scripts.values())[0]
        assert ep == "mypkg.cli:app"
