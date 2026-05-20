# tests/test_version_bump.py
# Tests for bump_version() and get_current_version().

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from PiPnDeploy.core_logic import bump_version, get_current_version


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_toml(tmp_path: Path, version: str, extra: str = "") -> Path:
    content = f'[project]\nname = "test-pkg"\nversion = "{version}"\n{extra}'
    p = tmp_path / "pyproject.toml"
    p.write_text(content, encoding="utf-8")
    return p


# ─── get_current_version ─────────────────────────────────────────────────────

class TestGetCurrentVersion:
    def test_reads_version(self, tmp_path):
        make_toml(tmp_path, "1.2.3")
        assert get_current_version(tmp_path) == "1.2.3"

    def test_returns_none_when_no_file(self, tmp_path):
        assert get_current_version(tmp_path) is None

    def test_returns_none_when_no_version_field(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n')
        assert get_current_version(tmp_path) is None


# ─── bump_version — patch ─────────────────────────────────────────────────────

class TestBumpPatch:
    def test_patch_increments(self, tmp_path):
        make_toml(tmp_path, "1.2.3")
        old, new = bump_version("patch", tmp_path)
        assert old == "1.2.3"
        assert new == "1.2.4"

    def test_patch_written_to_file(self, tmp_path):
        make_toml(tmp_path, "1.2.3")
        bump_version("patch", tmp_path)
        assert get_current_version(tmp_path) == "1.2.4"

    def test_patch_at_zero(self, tmp_path):
        make_toml(tmp_path, "1.2.0")
        _, new = bump_version("patch", tmp_path)
        assert new == "1.2.1"

    def test_patch_large_number(self, tmp_path):
        make_toml(tmp_path, "1.2.99")
        _, new = bump_version("patch", tmp_path)
        assert new == "1.2.100"


# ─── bump_version — minor ─────────────────────────────────────────────────────

class TestBumpMinor:
    def test_minor_increments(self, tmp_path):
        make_toml(tmp_path, "1.2.3")
        old, new = bump_version("minor", tmp_path)
        assert new == "1.3.0"

    def test_minor_resets_patch(self, tmp_path):
        make_toml(tmp_path, "1.2.9")
        _, new = bump_version("minor", tmp_path)
        assert new == "1.3.0"

    def test_minor_large_patch(self, tmp_path):
        make_toml(tmp_path, "0.0.99")
        _, new = bump_version("minor", tmp_path)
        assert new == "0.1.0"


# ─── bump_version — major ─────────────────────────────────────────────────────

class TestBumpMajor:
    def test_major_increments(self, tmp_path):
        make_toml(tmp_path, "1.2.3")
        _, new = bump_version("major", tmp_path)
        assert new == "2.0.0"

    def test_major_resets_minor_and_patch(self, tmp_path):
        make_toml(tmp_path, "3.7.12")
        _, new = bump_version("major", tmp_path)
        assert new == "4.0.0"

    def test_major_from_zero(self, tmp_path):
        make_toml(tmp_path, "0.1.0")
        _, new = bump_version("major", tmp_path)
        assert new == "1.0.0"


# ─── bump_version — set_version ───────────────────────────────────────────────

class TestSetVersion:
    def test_set_exact_version(self, tmp_path):
        make_toml(tmp_path, "1.0.0")
        old, new = bump_version("patch", tmp_path, set_version="3.0.0")
        assert old == "1.0.0"
        assert new == "3.0.0"

    def test_set_version_written(self, tmp_path):
        make_toml(tmp_path, "1.0.0")
        bump_version("patch", tmp_path, set_version="5.1.2")
        assert get_current_version(tmp_path) == "5.1.2"

    def test_set_invalid_version_raises(self, tmp_path):
        make_toml(tmp_path, "1.0.0")
        with pytest.raises(ValueError, match="not a valid semver"):
            bump_version("patch", tmp_path, set_version="not-a-version")

    def test_set_version_with_prefix_raises(self, tmp_path):
        make_toml(tmp_path, "1.0.0")
        with pytest.raises(ValueError):
            bump_version("patch", tmp_path, set_version="v2.0.0")


# ─── bump_version — error cases ──────────────────────────────────────────────

class TestBumpErrors:
    def test_no_pyproject_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            bump_version("patch", tmp_path)

    def test_unknown_part_raises(self, tmp_path):
        make_toml(tmp_path, "1.2.3")
        with pytest.raises(ValueError, match="Unknown part"):
            bump_version("build", tmp_path)

    def test_non_semver_version_raises(self, tmp_path):
        make_toml(tmp_path, "not-a-version")
        with pytest.raises(ValueError, match="not semver"):
            bump_version("patch", tmp_path)

    def test_missing_version_field_raises(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n')
        with pytest.raises(ValueError):
            bump_version("patch", tmp_path)


# ─── bump_version — file preservation ────────────────────────────────────────

class TestBumpPreservesFile:
    def test_other_fields_untouched(self, tmp_path):
        make_toml(tmp_path, "1.0.0", extra='description = "Stays the same."\n')
        bump_version("patch", tmp_path)
        content = (tmp_path / "pyproject.toml").read_text()
        assert "Stays the same." in content

    def test_tool_section_untouched(self, tmp_path):
        extra = '\n[tool.ruff]\nversion = "do-not-touch"\nline-length = 100\n'
        make_toml(tmp_path, "1.0.0", extra=extra)
        bump_version("patch", tmp_path)
        import tomllib
        with open(tmp_path / "pyproject.toml", "rb") as f:
            doc = tomllib.load(f)
        assert doc["tool"]["ruff"]["version"] == "do-not-touch"
        assert doc["project"]["version"] == "1.0.1"

    def test_bump_is_idempotent_in_isolation(self, tmp_path):
        make_toml(tmp_path, "2.0.0")
        bump_version("patch", tmp_path)
        bump_version("patch", tmp_path)
        assert get_current_version(tmp_path) == "2.0.2"
